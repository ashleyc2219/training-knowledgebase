"""Phase 40 Task 1：CREATE／KEEP／NO_FEATURE 三種結果與工單側的兩項寫入（D-52）。

本檔同時是 Phase 40 三支測試檔的**共用器材**所在地：`FakeRepository`、`FakeOperations`、
`FakeWriter` 與 `GAP`／`dt` 都定義在這裡，另外兩支測試檔直接 import 類別再各自宣告 fixture
（fixture 靠 import 傳遞會被 ruff 判成未使用的 import）。00A §3.2 的
`tests/unit/pipelines/conftest.py` owner 是 Phase 38，本 Phase 不得修改它，所以模組層級的
`fake_repo` fixture 會**刻意遮蔽** conftest 那個只有三個方法的同名 fixture——那是 pytest 的
標準行為，作用範圍只有本檔（Phase 39 的 `test_ticket_name_gap.py` 也是這樣做）。
"""

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.analytics.status_writer import VALIDATED_AT_KEY
from training_kb.clock import parse_iso
from training_kb.errors import ContentError, CoordinationError, ObjectAlreadyExists
from training_kb.keys import (
    META,
    edge_sk,
    feature_pk,
    parse_pk,
    parse_step_pk,
    ticket_pk,
    tutorial_pk,
    version_pk,
)
from training_kb.models import (
    AuthoringRule,
    Feature,
    StrictModel,
    Ticket,
    Tutorial,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.operations import OperationRecord
from training_kb.pipelines.ticket import TicketGap, decide_ticket_action, record_decision
from training_kb.repository import _entity_pk, item_to_model

FIXED_TS = datetime(2026, 9, 13, 2, 0, 0, tzinfo=UTC)
"""種子資料的時間；UTC 整秒（`models.py` 會拒絕帶微秒的 datetime）。"""

GAP = TicketGap(cluster_id="c12", gap="找不到會前摘要入口", feature_id="Prepare",
                ticket_ids=("t_881",))


def dt(value: str) -> datetime:
    """Phase 02 `parse_iso` 的薄包裝，讓測試用字面 ISO 字串寫時間。"""
    return parse_iso(value)


class FakeRepository:
    """用兩個 dict 當 DynamoDB 表與 S3 bucket 的假 `Repository`。

    只實作 Phase 06／07／08／27 這四批被 Phase 40 走到的原語，語意與真實版本對齊：
    `put_meta(create_only=True)` 撞鍵丟 `CoordinationError`、`put_object(if_none_match=True)`
    撞鍵丟 `ObjectAlreadyExists`、`scan_entity` 預設只回 `SK == META`、`list_edges` 濾掉
    `META`。`writes` 記下**每一次寫入**的 PK 或 S3 key（種子鉤子不記），KEEP 路徑才能直接
    斷言「0 筆新 `TUTORIAL#`／`VERSION#`／`STEP#`」。
    """

    def __init__(self) -> None:
        self.table: dict[tuple[str, str], dict[str, Any]] = {}
        self.objects: dict[str, bytes] = {}
        self.writes: list[str] = []

    # --- Phase 06：metadata ---

    def put_meta(self, entity: StrictModel, *, create_only: bool = True) -> None:
        pk = _entity_pk(entity)
        if create_only and (pk, META) in self.table:
            raise CoordinationError(f"metadata already exists or changed since read: {pk}")
        self._store(pk, META, entity.model_dump(mode="json"))
        self.writes.append(pk)

    def get_meta[T: StrictModel](self, pk: str, model: type[T], *,
                                 consistent: bool = True) -> T | None:
        item = self.table.get((pk, META))
        return None if item is None else item_to_model(item, model)

    def get_tutorial(self, slug: str) -> Tutorial | None:
        return self.get_meta(tutorial_pk(slug), Tutorial)

    def get_version(self, version_id: str) -> TutorialVersion | None:
        return self.get_meta(version_pk(version_id), TutorialVersion)

    def get_feature(self, feature_id: str) -> Feature | None:
        return self.get_meta(feature_pk(feature_id), Feature)

    # --- Phase 07：S3 物件與關係邊 ---

    def put_object(self, key: str, body: bytes, content_type: str, *,
                   if_none_match: bool) -> None:
        if if_none_match and key in self.objects:
            raise ObjectAlreadyExists(f"object already exists: {key}")
        self.objects[key] = body
        self.writes.append(key)

    def get_object(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def put_edge(self, pk: str, relation: str, target_pk: str,
                 attrs: dict[str, Any] | None = None) -> None:
        sort_key = edge_sk(relation, target_pk)
        self.table[(pk, sort_key)] = {"PK": pk, "SK": sort_key, "target": target_pk,
                                      "entity": parse_pk(pk)[0], **dict(attrs or {})}
        self.writes.append(pk)

    # --- Phase 08：查詢 ---

    def query_pk(self, pk: str, *, sk_prefix: str | None = None,
                 consistent: bool = True) -> list[dict[str, Any]]:
        return [item for (item_pk, sort_key), item in sorted(self.table.items())
                if item_pk == pk and (sk_prefix is None or sort_key.startswith(sk_prefix))]

    def list_edges(self, pk: str, relation: str | None = None) -> list[dict[str, Any]]:
        prefix = None if relation is None else f"{relation}#"
        return [item for item in self.query_pk(pk, sk_prefix=prefix)
                if str(item["SK"]) != META]

    def scan_entity(self, entity: str, *, consistent: bool = True,
                    meta_only: bool = True) -> list[dict[str, Any]]:
        rows = [item for _, item in sorted(self.table.items()) if item.get("entity") == entity]
        return [row for row in rows if str(row["SK"]) == META] if meta_only else rows

    def get_steps(self, version_id: str) -> list[TutorialStep]:
        steps: list[TutorialStep] = []
        for item in self.scan_entity("STEP", meta_only=False):
            owner, number = parse_step_pk(str(item["PK"]))
            if owner != version_id:
                continue
            payload = {**item, "tutorial_version": owner, "number": number,
                       "feature_id": parse_pk(str(item["target"]))[1]}
            steps.append(item_to_model(payload, TutorialStep))
        return sorted(steps, key=lambda step: step.number)

    def list_rules(self, status: object = None) -> list[AuthoringRule]:
        rules = sorted((item_to_model(row, AuthoringRule) for row in self.scan_entity("RULE")),
                       key=lambda rule: rule.rule_id)
        return rules if status is None else [rule for rule in rules if rule.status == status]

    # --- Phase 27：固定圖譜查詢（P27 尚未落地，這裡先提供同一份判準） ---

    def find_active_tutorial_for_feature(self, feature_id: str) -> Tutorial | None:
        found = sorted((item_to_model(row, Tutorial) for row in self.scan_entity("TUTORIAL")),
                       key=lambda one: one.slug)
        return next((one for one in found if one.status == TutorialStatus.ACTIVE
                     and feature_id in one.feature_ids), None)

    # --- 種子鉤子：不記進 `writes` ---

    def _store(self, pk: str, sort_key: str, payload: dict[str, Any]) -> None:
        self.table[(pk, sort_key)] = {"PK": pk, "SK": sort_key,
                                      "entity": parse_pk(pk)[0], **payload}

    def _seed(self, entity: StrictModel) -> None:
        self._store(_entity_pk(entity), META, entity.model_dump(mode="json"))

    def save_feature(self, feature_id: str) -> None:
        self._seed(Feature(feature_id=feature_id, name=feature_id, aliases=[],
                           first_seen=FIXED_TS))

    def save_tutorial(self, slug: str, *, feature_id: str = "Prepare", status: str = "active",
                      current_version: str | None = None, cluster_id: str = "c12") -> None:
        self._seed(Tutorial(slug=slug, topic=slug, feature_ids=[feature_id],
                            status=TutorialStatus(status), current_version=current_version,
                            successor=None, cluster_id=cluster_id))

    def save_ticket(self, ticket_id: str, *, cluster: str = "c12") -> None:
        self._seed(Ticket(id=ticket_id, source="github_issue", text=f"{ticket_id} 的原始提問",
                          author="reporter", ts=FIXED_TS, project_id="demo", cluster_id=cluster))

    def save_rule(self, rule_id: str, *, status: str = "active",
                  applies_when: str = "click_ui") -> None:
        self._seed(AuthoringRule(rule_id=rule_id, rule="每一步都要寫出按鈕文字",
                                 applies_when=applies_when, status=status,
                                 evidence=[f"fb_{index}" for index in range(5)],
                                 applied_to=[], derived_from="prepare-meeting@v1"))

    def save_validated_at_file(self, mapping: dict[str, str]) -> None:
        """Phase 55 才會寫的 `operations/rules/validated_at.json`（00A D-28）。"""
        self.objects[VALIDATED_AT_KEY] = json.dumps(mapping).encode("utf-8")

    # --- 斷言輔助 ---

    def edges(self, pk: str, relation: str) -> list[str]:
        return [str(item["target"]) for item in self.list_edges(pk, relation)]

    def written(self, prefix: str) -> list[str]:
        return [key for key in self.writes if key.startswith(prefix)]


class FakeOperations:
    """只實作 Phase 40 走到的三個 `OperationCoordinator` 方法。

    `allocate_version` 在 `load` 回 `None` 時會丟 `CoordinationError`，所以建構時就放一筆
    accepted 紀錄；`record_version` 照真實版本 write-once（同值 no-op、換值丟
    `CoordinationError`），`record_model_output` 同 ref 不重複附加。
    """

    def __init__(self, operation_id: str = "op-1") -> None:
        self.operation_id = operation_id
        self.version_id: str | None = None
        self.model_output_refs: list[str] = []

    def load(self, operation_id: str) -> OperationRecord | None:
        if operation_id != self.operation_id:
            return None
        return OperationRecord(
            operation_id=operation_id, kind="ticket-analysis", canonical_id="t_881",
            project_id="demo", status="accepted", input_ref=None, execution_arn=None,
            version_id=self.version_id, model_output_refs=tuple(self.model_output_refs),
            proc_sample_signature=None, error=None, retryable=None, accept_seq=1,
            accepted_at=FIXED_TS, updated_at=FIXED_TS)

    def record_version(self, operation_id: str, version_id: str) -> None:
        if self.version_id == version_id:
            return
        if self.version_id is not None:
            raise CoordinationError(
                f"operation {operation_id} already has version {self.version_id}")
        self.version_id = version_id

    def record_model_output(self, operation_id: str, output_ref: str) -> None:
        if output_ref not in self.model_output_refs:
            self.model_output_refs.append(output_ref)


class FakeWriter:
    """記下每次 `generate_json` 的 `(system, user, schema, node)`，固定回 `self.reply`。

    形狀與 `tests/unit/conftest.py` 的 `RecordingWriter` 相容（00A §6.5），但回應不是佇列：
    `generate_validated_json` 的修正路徑會呼叫第二次，佇列版會因為空佇列而炸掉，看不出
    「同一個壞回應被修正一次後確定失敗」。
    """

    def __init__(self) -> None:
        self.reply: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, system: str, user: str, schema: dict[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "schema": schema, "node": node,
                           "operation_id": operation_id})
        return json.loads(json.dumps(self.reply))


@pytest.fixture
def fake_repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def fake_ops() -> FakeOperations:
    return FakeOperations()


@pytest.fixture
def fake_writer() -> FakeWriter:
    return FakeWriter()


# --- Task 1 Step 1 ----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "current", "expected"),
    [("active", None, "KEEP"), ("active", "prepare-meeting@v1", "KEEP"),
     ("retired", "prepare-meeting@v1", "CREATE")],
)
def test_only_active_status_blocks_create(fake_repo: FakeRepository, status: str,
                                          current: str | None, expected: str) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_tutorial("prepare-meeting", feature_id="Prepare", status=status,
                            current_version=current)
    assert decide_ticket_action(GAP, repository=fake_repo) == expected


def test_active_lookup_has_no_silent_fallback(
        fake_repo: FakeRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    """P27 落地後「有沒有 active 教學」只有一條路，**沒有**掃全表的備援。

    備援會在查詢缺席時安靜地回「沒有 active 教學」，把 KEEP 判成 CREATE，同一個功能因此被
    建第二篇，直接違反 F12。缺方法要大聲失敗，不是靜靜換一套判準（Phase 40 review A3）。
    """
    fake_repo.save_feature("Prepare")
    fake_repo.save_tutorial("prepare-meeting", feature_id="Prepare", status="active")
    monkeypatch.delattr(FakeRepository, "find_active_tutorial_for_feature")
    with pytest.raises(AttributeError, match="find_active_tutorial_for_feature"):
        decide_ticket_action(GAP, repository=fake_repo)


def test_missing_feature_returns_no_feature(fake_repo: FakeRepository) -> None:
    assert decide_ticket_action(replace(GAP, feature_id=None), repository=fake_repo) \
        == "NO_FEATURE"
    assert fake_repo.writes == []


def test_unknown_feature_id_is_a_data_inconsistency(fake_repo: FakeRepository) -> None:
    with pytest.raises(ContentError):
        decide_ticket_action(GAP, repository=fake_repo)
    assert fake_repo.writes == []


@pytest.mark.parametrize(("action", "linked"), [("KEEP", ["Prepare"]), ("NO_FEATURE", [])])
def test_record_decision_links_tickets_only_when_feature_is_valid(
        fake_repo: FakeRepository, action: str, linked: list[str]) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    gap = GAP if action == "KEEP" else replace(GAP, feature_id=None)

    ref = record_decision(action, gap, repository=fake_repo,
                          operation_id="op-1", now=dt("2026-09-13T02:05:00Z"))

    assert ref == "operations/op-1/ticket-decision.json"
    stored = fake_repo.get_meta(ticket_pk("t_881"), Ticket)
    assert stored is not None and stored.feature_ids == linked
    assert fake_repo.edges(ticket_pk("t_881"), "ASKS_ABOUT") == (
        [feature_pk("Prepare")] if linked else [])


# --- Task 1 Step 4 ----------------------------------------------------------


@pytest.mark.parametrize("action", ["KEEP", "NO_FEATURE"])
def test_keep_and_no_feature_write_no_tutorial_content(fake_repo: FakeRepository,
                                                       action: str) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    fake_repo.save_tutorial("prepare-meeting", feature_id="Prepare",
                            current_version="prepare-meeting@v1")
    before = fake_repo.get_tutorial("prepare-meeting")
    gap = GAP if action == "KEEP" else replace(GAP, feature_id=None)

    ref = record_decision(action, gap, repository=fake_repo,
                          operation_id="op-1", now=dt("2026-09-13T02:05:00Z"))

    for prefix in ("TUTORIAL#", "VERSION#", "STEP#"):
        assert fake_repo.written(prefix) == []
    assert fake_repo.get_tutorial("prepare-meeting") == before
    record = json.loads(fake_repo.objects[ref])
    assert record["action"] == action
    assert record["gap"] == GAP.gap
    assert record["cluster_id"] == "c12"
    assert record["decided_at"] == "2026-09-13T02:05:00Z"
    assert record["ticket_ids"] == ["t_881"]


def test_record_decision_is_idempotent_on_rerun(fake_repo: FakeRepository) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")

    first = record_decision("KEEP", GAP, repository=fake_repo, operation_id="op-1",
                            now=dt("2026-09-13T02:05:00Z"))
    second = record_decision("KEEP", GAP, repository=fake_repo, operation_id="op-1",
                             now=dt("2026-09-13T02:06:00Z"))

    assert first == second
    assert fake_repo.edges(ticket_pk("t_881"), "ASKS_ABOUT") == [feature_pk("Prepare")]
    stored = fake_repo.get_meta(ticket_pk("t_881"), Ticket)
    assert stored is not None and stored.feature_ids == ["Prepare"]
    assert len(fake_repo.list_edges(ticket_pk("t_881"))) == 1


def test_record_decision_refuses_missing_ticket(fake_repo: FakeRepository) -> None:
    fake_repo.save_feature("Prepare")
    with pytest.raises(ContentError):
        record_decision("KEEP", GAP, repository=fake_repo, operation_id="op-1",
                        now=dt("2026-09-13T02:05:00Z"))
