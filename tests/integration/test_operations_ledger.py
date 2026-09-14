"""操作紀錄（`OPS#`）在 moto 表上的行為：永久去重、進度欄位與重新載入。

`repository` fixture 是 `tests/integration/conftest.py` 的 moto 表＋bucket；moto 的 PASS
只證明資料形狀，**不是** O2 的證據。真正的程序重啟、交錯事件與 lease 過期由 Phase 11 驗。
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.errors import CoordinationError
from training_kb.keys import META, operation_ref, ops_pk
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.repository import DynamoItem, Repository

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 13, 12, 5, tzinfo=UTC)
REQUEST = AcceptOperation("op-ticket-t_881", "ticket", "t_881", "demo", NOW)


def test_second_accept_returns_the_same_record(repository: Repository) -> None:
    operations = OperationCoordinator(repository)
    first = operations.accept(REQUEST)
    second = operations.accept(REQUEST)
    assert first.status == "accepted"
    assert second.status == "duplicate"
    assert second.record == first.record
    assert len(repository.scan_entity("OPS")) == 1


def test_the_same_canonical_id_under_another_kind_is_another_operation(
    repository: Repository,
) -> None:
    """`operation_id` 已經把 kind 編進去，所以同一張工單被兩條 pipeline 接受不會互相去重。"""
    operations = OperationCoordinator(repository)
    operations.accept(REQUEST)
    other = AcceptOperation("op-release-t_881", "release", "t_881", "demo", NOW)
    assert operations.accept(other).status == "accepted"
    assert len(repository.scan_entity("OPS")) == 2


def test_a_record_deleted_from_the_table_is_gone_not_reborn(
    repository: Repository, table: Any,
) -> None:
    """item 被刪掉之後 `load` 回 `None`、`record_*` 明確失敗，不會默默重建一筆。"""
    operations = OperationCoordinator(repository)
    operations.accept(REQUEST)
    table.delete_item(Key={"PK": ops_pk(REQUEST.operation_id), "SK": META})
    assert operations.load(REQUEST.operation_id) is None
    with pytest.raises(CoordinationError):
        operations.record_normalized(REQUEST.operation_id, operation_ref("op-1", "input"))


def test_a_write_conflict_without_a_readable_record_fails_loudly(
    table: object, bucket: object,
) -> None:
    """條件寫入說「已存在」卻讀不到既有 item：資料不一致，不得當成新事件重做一次。

    真實的表刪掉 item 之後條件寫入就會成功，製造不出這個分支，所以這裡用一個永遠
    讀不回 `OPS#` 的 `Repository` 子類把「條件失敗」與「讀不到」湊在同一次呼叫。
    """
    class _AmnesiacRepository(Repository):
        def get_meta_item(self, pk: str) -> DynamoItem | None:
            """只對 `OPS#` 失憶。`SEQ#` 要照常讀得回，`accept` 的取號（Phase 11）才走得完。"""
            return None if pk.startswith("OPS#") else super().get_meta_item(pk)

    operations = OperationCoordinator(_AmnesiacRepository(table, bucket))
    operations.accept(REQUEST)
    with pytest.raises(CoordinationError):
        operations.accept(REQUEST)


def test_progress_fields_and_single_proc_sample(repository: Repository) -> None:
    """ref 只記路徑、同 ref 不重複附加、第二次樣本回 `False`，而且都不動 `updated_at`。"""
    operations = OperationCoordinator(repository)
    operations.accept(REQUEST)
    output = operation_ref("op-ticket-t_881", "model-gap")
    operations.record_normalized("op-ticket-t_881", operation_ref("op-ticket-t_881", "input"))
    operations.record_model_output("op-ticket-t_881", output)
    operations.record_model_output("op-ticket-t_881", output)
    assert operations.record_proc_sample("op-ticket-t_881", "abc123") is True
    assert operations.record_proc_sample("op-ticket-t_881", "abc123") is False
    record = operations.load("op-ticket-t_881")
    assert record is not None
    assert record.input_ref == "operations/op-ticket-t_881/input.json"
    assert (record.model_output_refs, record.updated_at) == ((output,), NOW)


def test_the_raw_item_carries_no_target_and_no_progress_payload(repository: Repository) -> None:
    """人工驗收自動化：操作紀錄是執行資訊，不進 `by_target` GSI，也不存大內容。"""
    operations = OperationCoordinator(repository)
    operations.accept(REQUEST)
    operations.record_execution("op-ticket-t_881", "arn:aws:states:us-east-1:1:execution:x:y")
    operations.record_version("op-ticket-t_881", "prepare-meeting@v2")
    item = repository.get_meta_item(ops_pk("op-ticket-t_881"))
    assert item is not None
    assert "target" not in item
    assert (item["entity"], item["SK"]) == ("OPS", META)
    assert repository.query_by_target(ops_pk("op-ticket-t_881")) == []
    assert item["version_id"] == "prepare-meeting@v2"


def test_ledger_survives_a_new_coordinator(repository: Repository) -> None:
    """換一個 `OperationCoordinator` 物件仍讀得回同一筆紀錄。

    資料還在同一個 moto 表，所以這裡**只證明持久紀錄可以被重新載入**；真正的程序重啟、
    交錯事件、lease 過期與 closed execution 都是 Phase 11 的整合證據。
    """
    first = OperationCoordinator(repository)
    accepted = first.accept(REQUEST)
    first.record_normalized("op-ticket-t_881", operation_ref("op-ticket-t_881", "input"))
    again = OperationCoordinator(repository).accept(REQUEST)
    assert again.status == "duplicate"
    assert again.record.input_ref == "operations/op-ticket-t_881/input.json"
    assert again.record.accepted_at == accepted.record.accepted_at


def test_a_completed_operation_is_still_a_duplicate(repository: Repository) -> None:
    operations = OperationCoordinator(repository)
    operations.accept(REQUEST)
    operations.complete("op-ticket-t_881", now=LATER)
    again = operations.accept(REQUEST)
    assert (again.status, again.record.status) == ("duplicate", "done")
    assert (again.record.accepted_at, again.record.updated_at) == (NOW, LATER)
    assert len(repository.scan_entity("OPS")) == 1


def test_a_retryable_failure_never_creates_a_second_record(repository: Repository) -> None:
    """要不要重試由呼叫端依 `retryable` 決定；重送仍是同一筆邏輯操作。"""
    operations = OperationCoordinator(repository)
    operations.accept(REQUEST)
    operations.fail("op-ticket-t_881", "bedrock timeout", True, now=LATER)
    again = operations.accept(REQUEST)
    assert (again.status, again.record.status) == ("duplicate", "failed")
    assert (again.record.error, again.record.retryable) == ("bedrock timeout", True)
    assert len(repository.scan_entity("OPS")) == 1
