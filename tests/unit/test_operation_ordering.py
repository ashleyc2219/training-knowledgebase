"""接受順序（`accept_seq`）與租約（lease）的程式邏輯：用記憶體假 `Repository`。

這支是**單元測試**：它證明 compare-and-swap 的分支走對了，**證明不了 O2**。
O2 只認 `tests/integration/test_o2_cases.py` 對真實 DynamoDB 隔離表跑出來的觀察值。

兩句必須一直成立（Phase 11 §6）：
- **鎖不等於接受順序。** 誰先搶到 lease 只代表誰先送達 DynamoDB，順序一律讀 `accept_seq`。
- **TTL 不是準時解鎖。** 到期判斷自己比 `expires_at`，`ttl` 只給 DynamoDB 長期清理。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from training_kb.errors import CoordinationError
from training_kb.keys import META, parse_pk
from training_kb.operations import SEQUENCE_ATTEMPTS, AcceptOperation, OperationCoordinator
from training_kb.repository import DynamoItem, DynamoValue, Repository

BASE = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


class _MemoryRepository(Repository):
    """只實作 `put_meta_item`／`get_meta_item`／`update_meta` 三個原語的記憶體替身。

    語意逐條對齊 `repository.py`：`put_meta_item` 回「本次是否由我建立」、
    `get_meta_item` 回含 `_revision` 的整筆 item、`update_meta` 的 `expected_revision`
    對不上就丟 `CoordinationError`。沒有 boto3、沒有網路。
    """

    def __init__(self) -> None:
        super().__init__(None)
        self.items: dict[str, dict[str, object]] = {}

    def put_meta_item(self, pk: str, attributes: Mapping[str, DynamoValue], *,
                      create_only: bool = True) -> bool:
        existing = self.items.get(pk)
        if existing is not None:
            if create_only:
                return False
            existing.update(attributes)
            existing["_revision"] = int(str(existing["_revision"])) + 1
            return False
        self.items[pk] = {**attributes, "PK": pk, "SK": META,
                          "entity": parse_pk(pk)[0], "_revision": 1}
        return True

    def get_meta_item(self, pk: str) -> DynamoItem | None:
        item = self.items.get(pk)
        return None if item is None else dict(item)  # type: ignore[arg-type]

    def update_meta(self, pk: str, changes: Mapping[str, DynamoValue], *,
                    expected_revision: int) -> int:
        item = self.items.get(pk)
        if item is None or item["_revision"] != expected_revision:
            raise CoordinationError(f"stale revision for {pk}: expected {expected_revision}")
        item.update(changes)
        item["_revision"] = expected_revision + 1
        return expected_revision + 1


@dataclass(frozen=True)
class _Clock:
    """可注入的時鐘：`at(29)` 就是起點後 29 秒。深層程式一律把 `now` 當參數收（00A §3.5）。"""

    base: datetime

    def at(self, offset: int) -> datetime:
        return self.base + timedelta(seconds=offset)


@pytest.fixture
def repository() -> _MemoryRepository:
    return _MemoryRepository()


@pytest.fixture
def coordinator(repository: _MemoryRepository) -> OperationCoordinator:
    return OperationCoordinator(repository)


@pytest.fixture
def clock() -> _Clock:
    return _Clock(BASE)


def test_next_sequence_is_monotonic_per_scope(coordinator: OperationCoordinator) -> None:
    first = coordinator.next_sequence("PROJECT#demo")
    second = coordinator.next_sequence("PROJECT#demo")
    other = coordinator.next_sequence("PROJECT#other")
    assert (first, second, other) == (1, 2, 1)


def test_a_resend_reuses_the_number_and_burns_a_new_one(
    coordinator: OperationCoordinator, repository: _MemoryRepository
) -> None:
    """號碼在條件寫入之前取，所以重送燒掉一個號碼；`OPS#` item 的號碼不變。

    接受順序只要求單調遞增、可比較，不要求連號（同 D26 對版號缺口的取捨）。
    """
    request = AcceptOperation("op-release-r_42", "release", "r_42", "demo", BASE)
    first = coordinator.accept(request)
    second = coordinator.accept(request)
    assert (first.status, first.record.accept_seq) == ("accepted", 1)
    assert (second.status, second.record.accept_seq) == ("duplicate", 1)
    assert repository.items["SEQ#PROJECT#demo"]["counter"] == 2
    assert repository.items["OPS#op-release-r_42"]["accept_seq"] == 1


def test_two_events_of_the_same_project_share_one_counter(
    coordinator: OperationCoordinator,
) -> None:
    """取號是**專案層級**：`accept` 當下還不知道最後會動到哪一篇教學，所以不能用 slug。"""
    release = coordinator.accept(
        AcceptOperation("op-release-r_42", "release", "r_42", "demo", BASE)
    )
    feedback = coordinator.accept(
        AcceptOperation("op-feedback-" + "f" * 64, "feedback", "f" * 64, "demo", BASE)
    )
    other = coordinator.accept(
        AcceptOperation("op-release-r_43", "release", "r_43", "other", BASE)
    )
    assert (release.record.accept_seq, feedback.record.accept_seq) == (1, 2)
    assert other.record.accept_seq == 1


def test_sequence_contention_fails_loudly_instead_of_spinning(
    coordinator: OperationCoordinator, repository: _MemoryRepository
) -> None:
    """一直搶輸就丟 `CoordinationError`，不無限重試（`SEQUENCE_ATTEMPTS` 是上限）。"""
    attempts = 0

    def _always_stale(pk: str, changes: Mapping[str, DynamoValue], *,
                      expected_revision: int) -> int:
        nonlocal attempts
        attempts += 1
        raise CoordinationError(f"stale revision for {pk}: expected {expected_revision}")

    repository.update_meta = _always_stale  # type: ignore[method-assign]
    with pytest.raises(CoordinationError, match=str(SEQUENCE_ATTEMPTS)):
        coordinator.next_sequence("PROJECT#demo")
    assert attempts == SEQUENCE_ATTEMPTS
