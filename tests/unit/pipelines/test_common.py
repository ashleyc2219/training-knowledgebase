"""Phase 29 Task 1：共用序列執行契約的成功、失敗與邊界。"""

from datetime import UTC, datetime

import pytest

from training_kb.errors import PermanentError, TransientError
from training_kb.pipelines.common import Deps, run_sequence

INPUT = {"operation_id": "op-ticket-t_881", "project_id": "demo",
         "input_ref": "operations/op-ticket-t_881/input.json"}


class FakeOperations:
    """只記錄呼叫的假 OperationCoordinator，不碰 DynamoDB。"""

    def __init__(self) -> None:
        self.failures: list[tuple[str, str, bool]] = []

    def fail(self, operation_id: str, error: str, retryable: bool, *, now: datetime) -> None:
        self.failures.append((operation_id, error, retryable))


def make_deps() -> tuple[Deps, FakeOperations]:
    operations = FakeOperations()
    return Deps(operations=operations, now=lambda: datetime(2026, 9, 13, tzinfo=UTC)), operations


def test_run_sequence_stops_at_first_failure() -> None:
    calls: list[str] = []

    def ok(value, deps):
        calls.append("ok")
        return {**value, "ticket_id": "t_881"}

    def broken(value, deps):
        calls.append("broken")
        raise PermanentError("invalid business result")

    deps, operations = make_deps()
    with pytest.raises(PermanentError):
        run_sequence("ticket-analysis", INPUT, [ok, broken], deps)
    assert calls == ["ok", "broken"]
    assert operations.failures == [("op-ticket-t_881", "invalid business result", False)]


def test_run_sequence_merges_task_output_onto_input() -> None:
    def ok(value, deps):
        return {**value, "ticket_id": "t_881"}

    def ok2(value, deps):
        return {**value, "cluster_id": "c1"}

    deps, operations = make_deps()
    result = run_sequence("ticket-analysis", INPUT, [ok, ok2], deps)
    assert result == {**INPUT, "ticket_id": "t_881", "cluster_id": "c1"}
    assert operations.failures == []


def test_task_after_the_failure_is_never_called() -> None:
    published: list[str] = []

    def broken(value, deps):
        raise PermanentError("invalid business result")

    def publish(value, deps):   # publish spy：失敗之後絕對不能被呼叫
        published.append("publish")
        return value

    deps, operations = make_deps()
    with pytest.raises(PermanentError):
        run_sequence("ticket-analysis", INPUT, [broken, publish], deps)
    assert published == []
    assert operations.failures == [("op-ticket-t_881", "invalid business result", False)]


def test_unknown_pipeline_name_is_rejected() -> None:
    """沒有第四條 pipeline：Analytics 是獨立 Lambda，不是 pipeline。"""
    deps, operations = make_deps()
    with pytest.raises(PermanentError) as error:
        run_sequence("analytics", INPUT, [], deps)
    assert "analytics" in str(error.value)
    assert operations.failures == []


def test_payload_without_operation_id_is_rejected() -> None:
    deps, operations = make_deps()
    with pytest.raises(PermanentError):
        run_sequence("ticket-analysis", {"project_id": "demo"}, [], deps)
    assert operations.failures == []


def test_empty_tasks_returns_a_copy_of_the_payload() -> None:
    deps, operations = make_deps()
    result = run_sequence("ticket-analysis", INPUT, [], deps)
    assert result == INPUT
    assert result is not INPUT
    assert operations.failures == []


def test_transient_failure_is_recorded_as_retryable_without_local_retry() -> None:
    calls: list[str] = []

    def flaky(value, deps):
        calls.append("flaky")
        raise TransientError("bedrock timeout")

    deps, operations = make_deps()
    with pytest.raises(TransientError):
        run_sequence("ticket-analysis", INPUT, [flaky], deps)
    assert calls == ["flaky"]   # run_sequence 自己不重試，重試由 ASL 的 Retry 管
    assert operations.failures == [("op-ticket-t_881", "bedrock timeout", True)]
