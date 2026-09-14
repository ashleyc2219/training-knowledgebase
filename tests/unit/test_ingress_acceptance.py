"""接受端（Phase 32）：名稱決定性、永久去重、有限 input 與期限。

用的是記憶體版 `Repository` 加**真正的** `OperationCoordinator`：去重語意由 Phase 10 的
程式決定，不在測試裡另寫一份。moto 的整合證據在
`tests/integration/test_start_execution_idempotency.py`，真實表的 O2 證據在 Phase 11。
"""

import json
import re
from collections.abc import Mapping
from time import monotonic
from typing import cast

import pytest

from training_kb import ingress
from training_kb.clock import now_utc
from training_kb.config import DEFAULT_PROJECT_ID, load_settings
from training_kb.errors import (
    CoordinationError,
    ObjectAlreadyExists,
    PermanentError,
    TransientError,
)
from training_kb.handlers.github_webhook import WEBHOOK_DEADLINE_SECONDS
from training_kb.ingress import (
    MAX_EXECUTION_NAME,
    Wiring,
    accept_normalized,
    accept_release,
    accept_ticket,
    execution_name,
    normalize_then_accept,
    operation_id_for,
    validate_release,
    validate_ticket,
)
from training_kb.keys import ops_pk
from training_kb.models import Release, Ticket
from training_kb.operations import (
    Acceptance,
    AcceptOperation,
    OperationCoordinator,
    OperationKind,
)
from training_kb.repository import Repository


def test_names_are_deterministic_and_safe() -> None:
    op = operation_id_for("ticket", "t_881")
    assert op == "op-ticket-t_881" == operation_id_for("ticket", "t_881")
    assert op != operation_id_for("release", "t_881")
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", execution_name(op))


@pytest.mark.parametrize("canonical_id", ["t_881", "t_" + "9" * 200, "t_會前摘要"])
def test_execution_name_always_obeys_the_step_functions_rule(canonical_id: str) -> None:
    name = execution_name(operation_id_for("ticket", canonical_id))
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name)
    assert name.startswith("op-ticket-")
    assert name == execution_name(operation_id_for("ticket", canonical_id))


# --- Task 2 的共用夾具 --------------------------------------------------------

TICKET_PAYLOAD: dict[str, object] = {
    "id": "t_881", "source": "github_issue", "text": "找不到「開始會議」按鈕在哪裡",
    "author": "u_gh-90210", "ts": "2026-09-01T08:12:30Z", "project_id": "demo",
}
RELEASE_PAYLOAD: dict[str, object] = {
    "id": "r_gh-acme-app-pr42-1", "source_event_id": "gh-acme-app-pr42",
    "source": "github_pr", "feature": "Prepare", "kind": "renamed",
    "old_name": "準備會議", "new_name": "會前準備",
    "evidence": "把「準備會議」改名為「會前準備」", "ts": "2026-09-02T09:00:00Z",
}
TICKET = validate_ticket(TICKET_PAYLOAD)
RELEASE = validate_release(RELEASE_PAYLOAD)
SEEDED_INPUT = b'{"seeded": true}'
"""續跑測試預先放進私有 S3 的輸入 bytes；重送不得覆寫它。"""


def arn_for(pipeline: str, name: str) -> str:
    return f"arn:aws:states:us-east-1:111122223333:execution:training-kb-{pipeline}:{name}"


class FakeRepository:
    """記憶體版 `Repository`：只實作 P32 會用到的四個原語，語意逐條照 P06／P07。

    `put_meta_item` 的 `create_only` 回「本次是否由我建立」、`update_meta` 做 revision
    compare-and-swap、`put_object(..., if_none_match=True)` 撞 key 丟 `ObjectAlreadyExists`。
    真表與真 bucket 的行為由整合測試與 Phase 11 的 O2 證據負責。
    """

    def __init__(self) -> None:
        self.items: dict[str, dict[str, object]] = {}
        self.objects: dict[str, bytes] = {}
        self.put_object_calls = 0

    def put_meta_item(self, pk: str, attributes: Mapping[str, object], *,
                      create_only: bool = True) -> bool:
        if create_only and pk in self.items:
            return False
        revision = int(str(self.items.get(pk, {}).get("_revision", 0))) + 1
        self.items[pk] = {**dict(attributes), "_revision": revision}
        return True

    def get_meta_item(self, pk: str) -> dict[str, object] | None:
        item = self.items.get(pk)
        return None if item is None else dict(item)

    def update_meta(self, pk: str, changes: Mapping[str, object], *,
                    expected_revision: int) -> int:
        item = self.items.get(pk)
        if item is None or item["_revision"] != expected_revision:
            raise CoordinationError(f"revision conflict: {pk}")
        item.update(changes)
        item["_revision"] = expected_revision + 1
        return expected_revision + 1

    def put_object(self, key: str, body: bytes, content_type: str, *,
                   if_none_match: bool) -> None:
        self.put_object_calls += 1
        if if_none_match and key in self.objects:
            raise ObjectAlreadyExists(key)
        assert content_type == "application/json"
        self.objects[key] = body


class FakeStarter:
    """記下每次 StartExecution 的 fake `PipelineStarter`；ARN 由 pipeline 與名稱組出。"""

    def __init__(self) -> None:
        self.calls = 0
        self.pipelines: list[str] = []
        self.names: list[str] = []
        self.inputs: list[dict[str, object]] = []
        self.error: Exception | None = None

    @property
    def last_input(self) -> dict[str, object]:
        return self.inputs[-1]

    def start(self, pipeline: str, execution_name: str, input: dict[str, object]) -> str:
        self.calls += 1
        self.pipelines.append(pipeline)
        self.names.append(execution_name)
        self.inputs.append(dict(input))
        if self.error is not None:
            raise self.error
        return arn_for(pipeline, execution_name)


class Harness:
    """一次接受路徑需要的四個相依，外加「還有剩」與「已過期」兩個期限值。"""

    def __init__(self, *, project_id: str = DEFAULT_PROJECT_ID) -> None:
        self.repository = FakeRepository()
        self.operations = OperationCoordinator(cast(Repository, self.repository))
        self.starter = FakeStarter()
        self.settings = load_settings({"TKB_PROJECT_ID": project_id})
        self.deadline = monotonic() + WEBHOOK_DEADLINE_SECONDS
        self.expired_deadline = monotonic() - 1.0

    @property
    def objects(self) -> dict[str, bytes]:
        return self.repository.objects

    @property
    def operation_ids(self) -> list[str]:
        return sorted(pk for pk in self.repository.items if pk.startswith("OPS#"))

    def accept_ticket(self, ticket: Ticket) -> Acceptance:
        return accept_ticket(ticket, deadline=self.deadline)

    def accept_release(self, release: Release) -> Acceptance:
        return accept_release(release, deadline=self.deadline)

    def seed(self, kind: OperationKind, canonical_id: str, *, status: str,
             input_ref: str | None = None, execution_arn: str | None = None) -> str:
        """把 ledger 預設成某一個狀態；回 `operation_id`。

        欄位一律走 Phase 10 的公開方法寫，只有 `status` 直接改屬性：`normalized`／`started`
        是 00A §6.4 的保留值，沒有任何公開方法會寫入它們（本 Phase 的裁決見報告），
        所以要測「ledger 已經是這個狀態」只能由測試自己擺出來。
        """
        operation_id = operation_id_for(kind, canonical_id)
        self.operations.accept(AcceptOperation(
            operation_id=operation_id, kind=kind, canonical_id=canonical_id,
            project_id=self.settings.project_id, now=now_utc()))
        if input_ref is not None:
            self.operations.record_normalized(operation_id, input_ref)
            self.repository.objects[input_ref] = SEEDED_INPUT
        if execution_arn is not None:
            self.operations.record_execution(operation_id, execution_arn)
        self.repository.items[ops_pk(operation_id)]["status"] = status
        return operation_id


def build_harness(monkeypatch: pytest.MonkeyPatch, *,
                  project_id: str = DEFAULT_PROJECT_ID) -> Harness:
    built = Harness(project_id=project_id)
    wiring = Wiring(operations=built.operations, starter=built.starter,
                    repository=cast(Repository, built.repository), settings=built.settings)
    monkeypatch.setattr(ingress, "_wiring", lambda: wiring)
    return built


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return build_harness(monkeypatch)


def test_duplicate_ticket_starts_once(harness: Harness) -> None:
    first = harness.accept_ticket(TICKET)
    second = harness.accept_ticket(TICKET)
    assert first.status == "accepted"
    assert second.status == "duplicate"
    assert second.operation_id == first.operation_id == "op-ticket-t_881"
    assert second.record.input_ref == first.record.input_ref
    assert second.record.execution_arn == first.record.execution_arn
    assert harness.starter.calls == 1
    assert set(harness.objects) == {first.record.input_ref}
    assert set(harness.starter.last_input) == {"operation_id", "project_id", "input_ref"}
    assert TICKET.text not in json.dumps(harness.starter.last_input, ensure_ascii=False)


def test_duplicate_release_starts_once(harness: Harness) -> None:
    """Release 走的是另一條 pipeline，但去重與有限 input 的規則完全一樣（ING Rule 27）。"""
    first = harness.accept_release(RELEASE)
    second = harness.accept_release(RELEASE)
    assert (first.status, second.status) == ("accepted", "duplicate")
    assert second.operation_id == "op-release-r_gh-acme-app-pr42-1"
    assert second.record.execution_arn == first.record.execution_arn
    assert harness.starter.pipelines == ["release-update"]
    assert set(harness.objects) == {first.record.input_ref}
    assert RELEASE.evidence not in json.dumps(harness.starter.last_input, ensure_ascii=False)


def test_a_fresh_ticket_starts_ticket_analysis_exactly_once(harness: Harness) -> None:
    """ING Rule 26：正規化成功的 Ticket 觸發 Ticket Analysis，而且只有這一條。"""
    accepted = harness.accept_ticket(TICKET)
    assert harness.starter.pipelines == ["ticket-analysis"]
    assert harness.starter.names == [execution_name("op-ticket-t_881")]
    assert harness.starter.last_input == {
        "operation_id": "op-ticket-t_881", "project_id": "demo",
        "input_ref": "operations/op-ticket-t_881/input.json",
    }
    assert accepted.record.input_ref == "operations/op-ticket-t_881/input.json"


def test_the_release_project_id_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Release` 模型沒有 `project_id`，所以它只能從 `Settings` 來（00A §6.8）。"""
    other = build_harness(monkeypatch, project_id="acme")
    accepted = other.accept_release(RELEASE)
    assert accepted.record.project_id == "acme"
    assert other.starter.last_input["project_id"] == "acme"


# ledger 既有狀態 -> (是否已有 input_ref, 是否已有 execution_arn, 重送時預期的 starter 次數)
RESEND_CASES = [
    ("accepted", False, False, 1),
    ("normalized", True, False, 1),
    ("started", True, True, 0),
    ("done", True, True, 0),
    ("failed", True, True, 0),
]


@pytest.mark.parametrize(("status", "has_input", "has_arn", "starts"), RESEND_CASES)
@pytest.mark.parametrize("kind", ["ticket", "release"])
def test_resending_any_ledger_state_keeps_one_operation(
    harness: Harness, kind: str, status: str, has_input: bool, has_arn: bool, starts: int,
) -> None:
    """五種 ledger 狀態 x Ticket／Release：永遠只有一筆 operation、一個 input 物件。"""
    obj: Ticket | Release = TICKET if kind == "ticket" else RELEASE
    operation_id = operation_id_for(cast(OperationKind, kind), obj.id)
    input_ref = f"operations/{operation_id}/input.json"
    pipeline = "ticket-analysis" if kind == "ticket" else "release-update"
    seeded_arn = arn_for(pipeline, operation_id) if has_arn else None
    harness.seed(cast(OperationKind, kind), obj.id, status=status,
                 input_ref=input_ref if has_input else None, execution_arn=seeded_arn)

    resent = accept_normalized(obj, deadline=harness.deadline)

    assert resent.status == "duplicate"
    assert resent.operation_id == operation_id
    assert harness.operation_ids == [ops_pk(operation_id)]   # 沒有第二筆 operation
    assert set(harness.objects) == {input_ref}               # 沒有第二個 input 物件
    assert harness.starter.calls == starts
    assert harness.starter.names == ([execution_name(operation_id)] if starts else [])
    assert resent.record.input_ref == input_ref
    if has_arn:
        assert resent.record.execution_arn == seeded_arn     # 沿用原執行，不換名重跑
    if has_input:
        assert harness.objects[input_ref] == SEEDED_INPUT    # 既有輸入不被覆寫


def test_the_same_canonical_id_under_another_kind_does_not_collide(harness: Harness) -> None:
    """`op-ticket-t_881` 與 `op-release-t_881` 是兩筆 operation，兩條 pipeline。"""
    same_id = validate_release({**RELEASE_PAYLOAD, "id": "t_881"})
    harness.accept_ticket(TICKET)
    harness.accept_release(same_id)
    assert harness.operation_ids == [ops_pk("op-release-t_881"), ops_pk("op-ticket-t_881")]
    assert harness.starter.pipelines == ["ticket-analysis", "release-update"]


def test_accept_normalized_dispatches_by_model(harness: Harness) -> None:
    assert accept_normalized(TICKET, deadline=harness.deadline).operation_id == "op-ticket-t_881"
    assert accept_normalized(
        RELEASE, deadline=harness.deadline).operation_id.startswith("op-release-")
    assert harness.starter.pipelines == ["ticket-analysis", "release-update"]


def test_normalize_then_accept_stops_when_the_deadline_is_gone(harness: Harness) -> None:
    with pytest.raises(TimeoutError):
        normalize_then_accept(
            domain="github.com", adapter="github_issue", event_type="issues",
            headers={"x-github-event": "issues"}, payload={"action": "opened"},
            deadline=harness.expired_deadline,
        )
    assert harness.starter.calls == 0
    assert harness.operation_ids == []


def test_normalize_is_still_the_phase_37_seam(harness: Harness) -> None:
    """期限還有剩時走到 `_normalize`，它必須明確失敗，不得先回一個假的成功。"""
    with pytest.raises(PermanentError, match="Phase 37"):
        normalize_then_accept(
            domain="github.com", adapter="github_issue", event_type="issues",
            headers={"x-github-event": "issues"}, payload={"action": "opened"},
            deadline=harness.deadline,
        )
    assert harness.starter.calls == 0


def test_a_transient_start_failure_keeps_the_input_and_the_execution_name(
    harness: Harness,
) -> None:
    """StartExecution 暫時失敗：紀錄 `retryable=True`、保留 `input_ref`，重試沿用同一個名字。"""
    harness.starter.error = TransientError("Step Functions 暫時不可用")
    with pytest.raises(TransientError):
        harness.accept_ticket(TICKET)
    failed = harness.operations.load("op-ticket-t_881")
    assert failed is not None
    assert (failed.status, failed.retryable) == ("failed", True)
    assert failed.input_ref == "operations/op-ticket-t_881/input.json"

    harness.starter.error = None
    retried = harness.accept_ticket(TICKET)
    assert retried.status == "duplicate"
    assert harness.starter.names == [execution_name("op-ticket-t_881")] * 2
    assert harness.operation_ids == [ops_pk("op-ticket-t_881")]
    assert set(harness.objects) == {"operations/op-ticket-t_881/input.json"}


def test_the_deadline_stops_before_touching_s3(harness: Harness) -> None:
    """期限用完時丟的是 `TimeoutError`（不是 `TransientError`，也不是靜靜回成功）。"""
    with pytest.raises(TimeoutError):
        accept_ticket(TICKET, deadline=harness.expired_deadline)
    assert harness.repository.put_object_calls == 0
    assert harness.starter.calls == 0


@pytest.mark.parametrize("kind", ["ticket", "release", "feedback-review", "ticket-analysis"])
def test_execution_name_keeps_the_whole_kind_prefix(kind: str) -> None:
    """最長的 `op-feedback-review-` 是 19 字；雜湊要跟著縮，前綴不能被切掉。"""
    long_id = "會前摘要-" + "9" * 200
    name = execution_name(operation_id_for(cast(OperationKind, kind), long_id))
    assert name.startswith(f"op-{kind}-")
    assert len(name) <= MAX_EXECUTION_NAME
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name)


def test_long_names_under_the_same_kind_stay_distinct() -> None:
    """截取後前綴一樣，靠雜湊分辨；同輸入仍然同輸出。"""
    first = execution_name(operation_id_for("feedback-review", "demo-會前摘要-" + "1" * 90))
    second = execution_name(operation_id_for("feedback-review", "demo-會前摘要-" + "2" * 90))
    assert first != second
    assert first == execution_name(operation_id_for("feedback-review", "demo-會前摘要-" + "1" * 90))
