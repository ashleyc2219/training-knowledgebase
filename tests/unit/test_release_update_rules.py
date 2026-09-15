"""Phase 51 Task 2：UPDATE 只注入本次選中的 active 規則（APL Rule 8、F29；不連 AWS）。

`test_release_update.py` 管的是改寫範圍、reason、diff 與 lease；本檔只管**規則**這一件事：
哪幾條進得了 prompt、哪幾條進得了 `VersionPlan.rules_applied`、以及沿用原文為什麼不算套用。

器材沿用同一套形狀但**各自定義**（tests 目錄沒有 `__init__.py`，測試檔之間不互相 import；
`tests/unit/conftest.py` 依 COMMON.md R3.6 只有 P55 能改）：一個真的 `Repository` 架在記憶體
表與 bucket 上，一個只會回固定改寫的假 Writer。驗證時間一律寫進
`operations/rules/validated_at.json`，由 `analytics/status_writer.load_validated_at` 讀（D-28）。
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from training_kb.clock import to_iso
from training_kb.content import TutorialContent, markdown_key, render_markdown
from training_kb.errors import PermanentError
from training_kb.keys import META
from training_kb.models import (
    AuthoringRule,
    Feature,
    Release,
    StepDraft,
    StepType,
    Tutorial,
    TutorialVersion,
)
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.pipelines.release import StepHit, prepare_update
from training_kb.repository import Repository

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
PROJECT = "demo"
OPERATION = "op-rules"
FEATURE = "Prepare"
A = "prepare-meeting"
A_V2 = f"{A}@v2"
VALIDATED_AT_KEY = "operations/rules/validated_at.json"

HITS_STEP3 = (StepHit(A, A_V2, 3),)
OLD_STEP3 = "在右上角選擇 Meeting Summary，查看會前摘要。"
NEW_STEP3 = "在會議頁面右上角選擇 Prepare，查看會前摘要。"

RELEASE_R42 = Release(id="r_42", source="github_pr", feature=FEATURE, kind="renamed",
                      old_name="Meeting Summary", new_name=FEATURE,
                      evidence="PR #42 rename Meeting Summary -> Prepare", ts=NOW)


def rule(rule_id: str, applies_when: str, *, status: str = "active") -> AuthoringRule:
    """一條規則；`rule` 文字帶 `rule_id`，斷言「這一條有沒有進 prompt」才驗得動。"""
    return AuthoringRule(rule_id=rule_id, rule=f"{rule_id} 要求動作寫清楚在哪一頁按哪個按鈕",
                         applies_when=applies_when,
                         evidence=[f"fb-{rule_id}-{index}" for index in range(5)],
                         status=status, applied_to=[], derived_from=A_V2)


def content_a() -> TutorialContent:
    """四步；**第 1 步與第 3 步同樣是 `click_ui`**，但只有第 3 步會被命中（F29 的邊界）。"""
    return TutorialContent(
        title="會前準備教學",
        problem="不知道怎麼在會議前拿到摘要。",
        prerequisites=["已登入"],
        steps=[
            StepDraft(number=1, type=StepType.CLICK_UI, text="在側欄點選會議。",
                      feature_id=FEATURE),
            StepDraft(number=2, type=StepType.INPUT, text="輸入會議名稱。", feature_id=FEATURE),
            StepDraft(number=3, type=StepType.CLICK_UI, text=OLD_STEP3, feature_id=FEATURE),
            StepDraft(number=4, type=StepType.READ, text="回到會議列表確認摘要已更新。",
                      feature_id=FEATURE),
        ],
        expected_outcome="會前摘要已經可以在會議頁面看到。",
    )


# --- 假的 Writer 與儲存層 ----------------------------------------------------


@dataclass
class JsonCall:
    system: str
    user: str
    node: str


@dataclass
class FakeWriter:
    """只會把第 3 步改成 `NEW_STEP3` 的假 Writer（O5 BLOCKED，沒有真實 Bedrock 呼叫）。"""

    json_calls: list[JsonCall] = field(default_factory=list)

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        raise AssertionError("prepare_update 不呼叫 embedding")

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self.json_calls.append(JsonCall(system=system, user=user, node=node))
        return {"steps": [{"number": 3, "text": NEW_STEP3, "feature_id": FEATURE,
                           "type": "click_ui"}]}

    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError("prepare_update 不呼叫 tool use")


def _conditional_check_failed(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, operation)


def _matches(item: Mapping[str, Any], condition: Any) -> bool:
    expression = condition.get_expression()
    operator = expression["operator"]
    values = expression["values"]
    if operator == "AND":
        return all(_matches(item, value) for value in values)
    actual = item.get(values[0].name)
    if operator == "=":
        return actual == values[1]
    if operator == "begins_with":
        return isinstance(actual, str) and actual.startswith(values[1])
    raise AssertionError(f"假表不支援的條件：{operator}")


class FakeTable:
    """記憶體表：只實作 `Repository` 真的會送出的四個 boto3 操作與兩種條件式。"""

    name = "fake_training_kb"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def put_item(self, **arguments: Any) -> dict[str, Any]:
        item = dict(arguments["Item"])
        key = (str(item["PK"]), str(item["SK"]))
        condition = arguments.get("ConditionExpression")
        if condition == "attribute_not_exists(PK)" and key in self.items:
            raise _conditional_check_failed("PutItem")
        if condition == "#revision = :current":
            values = arguments["ExpressionAttributeValues"]
            if self.items.get(key, {}).get("_revision") != values[":current"]:
                raise _conditional_check_failed("PutItem")
        self.items[key] = item
        return {}

    def get_item(self, **arguments: Any) -> dict[str, Any]:
        key = arguments["Key"]
        item = self.items.get((str(key["PK"]), str(key["SK"])))
        return {} if item is None else {"Item": dict(item)}

    def update_item(self, **arguments: Any) -> dict[str, Any]:
        key = arguments["Key"]
        item = self.items.get((str(key["PK"]), str(key["SK"])))
        names: Mapping[str, str] = arguments["ExpressionAttributeNames"]
        values: Mapping[str, Any] = arguments["ExpressionAttributeValues"]
        field_name, operator, placeholder = str(arguments["ConditionExpression"]).split(" ")
        assert operator == "=", f"假表不支援的條件：{operator}"
        if item is None or item.get(names[field_name]) != values[placeholder]:
            raise _conditional_check_failed("UpdateItem")
        expression = str(arguments["UpdateExpression"])
        assert expression.startswith("SET "), f"假表不支援的更新式：{expression}"
        for assignment in expression.removeprefix("SET ").split(", "):
            name, separator, value = assignment.partition(" = ")
            assert separator, f"假表不支援的更新式：{expression}"
            item[names[name]] = values[value]
        return {}

    def query(self, **arguments: Any) -> dict[str, Any]:
        rows = [dict(item) for item in self.items.values()]
        found = [row for row in rows if _matches(row, arguments["KeyConditionExpression"])]
        return {"Items": sorted(found, key=lambda row: (str(row["PK"]), str(row["SK"])))}

    def scan(self, **arguments: Any) -> dict[str, Any]:
        condition = arguments.get("FilterExpression")
        return {"Items": [dict(item) for item in self.items.values()
                          if condition is None or _matches(item, condition)]}


class _MissingKey(ClientError):
    def __init__(self, key: str) -> None:
        super().__init__({"Error": {"Code": "NoSuchKey"}}, f"GetObject {key}")


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _FakeObject:
    def __init__(self, bucket: "FakeBucket", key: str) -> None:
        self._bucket = bucket
        self._key = key

    def get(self) -> dict[str, Any]:
        body = self._bucket.objects.get(self._key)
        if body is None:
            raise _MissingKey(self._key)
        return {"Body": _Body(body)}

    def load(self) -> None:
        if self._key not in self._bucket.objects:
            raise _MissingKey(self._key)


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **arguments: Any) -> None:
        key = str(arguments["Key"])
        if arguments.get("IfNoneMatch") == "*" and key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[key] = bytes(arguments["Body"])

    def Object(self, key: str) -> _FakeObject:  # noqa: N802 - 照 boto3 resource 的名字
        return _FakeObject(self, key)


class RuleRepository(Repository):
    """真的 `Repository` ＋ 種規則資料的方法；`list_rules` 與 `scan_entity` 沒有被覆寫。"""

    def __init__(self) -> None:
        self.table = FakeTable()
        self.bucket = FakeBucket()
        super().__init__(self.table, self.bucket)
        self.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
        self.put_meta(Tutorial(slug=A, current_version=A_V2, topic=A, feature_ids=[FEATURE],
                               status="active", successor=None, cluster_id=None))
        self.put_meta(TutorialVersion(version_id=A_V2, slug=A, supersedes=None,
                                      reason="create:seed", rules_applied=[],
                                      s3_key=markdown_key(A, 2), published_at=NOW))
        self.bucket.objects[markdown_key(A, 2)] = render_markdown(content_a()).encode("utf-8")

    def add_rules(self, rules: Sequence[AuthoringRule], *,
                  validated_at: Mapping[str, datetime] | None = None,
                  record_validation: bool = True) -> None:
        """寫規則 item；`record_validation=False` 時故意不寫驗證時間（Phase 19 會拒絕）。"""
        for item in rules:
            self.put_meta(item)
        if not record_validation:
            return
        times = dict(validated_at or {})
        payload = {item.rule_id: to_iso(times.get(item.rule_id, NOW)) for item in rules}
        existing = self.bucket.objects.get(VALIDATED_AT_KEY)
        merged = json.loads(existing.decode("utf-8")) if existing else {}
        merged.update(payload)
        self.bucket.objects[VALIDATED_AT_KEY] = json.dumps(
            merged, ensure_ascii=False).encode("utf-8")

    @property
    def applied_to_edges(self) -> list[str]:
        """指向 `prepare-meeting@v3` 的 `APPLIED_TO` 邊，依起點規則 ID 升序。"""
        return sorted(str(pk).removeprefix("RULE#")
                      for (pk, sk) in self.table.items
                      if pk.startswith("RULE#") and sk.startswith("APPLIED_TO#")
                      and str(self.table.items[(pk, sk)].get("target", "")).endswith("@v3"))


@pytest.fixture
def repo() -> RuleRepository:
    return RuleRepository()


@pytest.fixture
def ops(repo: RuleRepository) -> OperationCoordinator:
    coordinator = OperationCoordinator(repo)
    coordinator.accept(AcceptOperation(operation_id=OPERATION, kind="release-update",
                                       canonical_id="r_42", project_id=PROJECT, now=NOW))
    return coordinator


@pytest.fixture
def fake_writer() -> FakeWriter:
    return FakeWriter()


# --- APL Rule 8：後續 Release 重寫仍注入 active 規則 -------------------------


def test_only_injected_active_rules_enter_prompt_and_record(
        repo: RuleRepository, ops: OperationCoordinator, fake_writer: FakeWriter) -> None:
    """Given R-007（active、click_ui）、R-012（active、read）與 R-099（candidate、click_ui），
    When 改寫 click_ui 的第 3 步，Then prompt 只看得到 `[R-007]`，
    `rules_applied` 也只有 R-007（APL Rule 8、F27）。"""
    repo.add_rules([rule("R-007", "click_ui"), rule("R-012", "read"),
                    rule("R-099", "click_ui", status="candidate")])
    plans = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id=OPERATION)
    injected = fake_writer.json_calls[0].user
    assert "[R-007]" in injected
    assert "R-012" not in injected
    assert "R-099" not in injected
    assert plans[0].rules_applied == ("R-007",)


def test_copied_steps_do_not_add_rules(
        repo: RuleRepository, ops: OperationCoordinator, fake_writer: FakeWriter) -> None:
    """Given 第 1 步同樣是 `click_ui`、第 2 步是 `input`、第 4 步是 `read`，但都沒被改寫，
    When 只命中第 3 步，Then 只有管 click_ui 的 R-007 入選——沿用原文不算本次套用（F29）。"""
    repo.add_rules([rule("R-007", "click_ui"), rule("R-020", "input"), rule("R-012", "read")])
    plans = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id=OPERATION)
    assert plans[0].rules_applied == ("R-007",)
    injected = fake_writer.json_calls[0].user
    assert "R-020" not in injected and "R-012" not in injected


def test_rules_applied_matches_the_applied_to_edges(
        repo: RuleRepository, ops: OperationCoordinator, fake_writer: FakeWriter) -> None:
    """Given 一條入選規則，When 版本寫完，
    Then `APPLIED_TO` 邊恰好等於 `rules_applied`（D17：權威欄位與邊不可分岔）。"""
    repo.add_rules([rule("R-007", "click_ui"), rule("R-012", "read")])
    plans = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id=OPERATION)
    assert repo.applied_to_edges == list(plans[0].rules_applied) == ["R-007"]


def test_most_recently_validated_rule_wins_within_a_step_type(
        repo: RuleRepository, ops: OperationCoordinator, fake_writer: FakeWriter) -> None:
    """Given 同一個 `click_ui` 有兩條 active 規則，When 選規則，
    Then 只留最近驗證通過的那一條（F28；每個 step_type 最多一條）。"""
    repo.add_rules([rule("R-007", "click_ui"), rule("R-050", "click_ui")],
                   validated_at={"R-007": NOW - timedelta(days=3), "R-050": NOW})
    plans = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id=OPERATION)
    assert plans[0].rules_applied == ("R-050",)
    assert "R-007" not in fake_writer.json_calls[0].user


def test_active_rule_without_validation_time_stops_the_update(
        repo: RuleRepository, ops: OperationCoordinator, fake_writer: FakeWriter) -> None:
    """Given active 規則沒有寫進 `operations/rules/validated_at.json`，When 選規則，
    Then `PermanentError`：缺值不可自己補時間（00A D-28），而且模型一次都沒被呼叫。"""
    repo.add_rules([rule("R-007", "click_ui")], record_validation=False)
    with pytest.raises(PermanentError, match="最近驗證時間"):
        prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                       operations=ops, operation_id=OPERATION)
    assert fake_writer.json_calls == []


def test_no_active_rule_leaves_an_empty_rules_block(
        repo: RuleRepository, ops: OperationCoordinator, fake_writer: FakeWriter) -> None:
    """Given 一條 active 規則都沒有（Phase 55 之前的正常狀態），When 改寫，
    Then `rules_applied` 是空的、`<active_rules>` 分區是空的，改版照樣完成。"""
    plans = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id=OPERATION)
    assert plans[0].rules_applied == ()
    assert "<active_rules></active_rules>" in fake_writer.json_calls[0].user
    assert repo.applied_to_edges == []


def test_lease_and_version_items_are_the_only_coordination_writes(
        repo: RuleRepository, ops: OperationCoordinator, fake_writer: FakeWriter) -> None:
    """Given 一次成功的 UPDATE，When 看 `RULE#` 本體，
    Then 規則 item 的 `applied_to` 欄位沒有被本 Phase 改過（那是 Phase 55 的事）。"""
    repo.add_rules([rule("R-007", "click_ui")])
    prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                   operations=ops, operation_id=OPERATION)
    assert repo.table.items[("RULE#R-007", META)]["applied_to"] == []
