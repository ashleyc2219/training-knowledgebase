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
            return None

    operations = OperationCoordinator(_AmnesiacRepository(table, bucket))
    operations.accept(REQUEST)
    with pytest.raises(CoordinationError):
        operations.accept(REQUEST)
