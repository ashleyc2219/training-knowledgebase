"""Phase 35：PROC 成功、失敗與退役生命週期的純函式單元測試。

這裡只驗「狀態怎麼從一個 `ProvenWorkflow` 算到下一個」：不同事件才累積 `success_count`、
連敗歸零與退役、以及 retired 之後三個函式都拒絕自動復活。三個轉移函式不碰 AWS，
所以整支檔案不需要 moto，`record_proc_sample` 用 `FakeOperations` 替身（落地行為在
`tests/integration/test_proc_concurrency.py`）。
"""

from datetime import UTC, datetime

import pytest

from training_kb.errors import PermanentError
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.rote import on_new_success

NOW = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 13, 1, 0, tzinfo=UTC)
BASE = ProvenWorkflow(
    signature="a1b2c3d4e5f60718", domain="github.com", adapter="github_issue",
    steps=[ProcStep(tool="parse_github_issue", args={"body": "$event.payload.issue.body"})],
    keys=["action", "issue", "repository", "sender"],
    success_count=1, fail_count=0, status=ProcStatus.ACTIVE, last_used=NOW,
)


def proc(**changes: object) -> ProvenWorkflow:
    return BASE.model_copy(update=changes)


class FakeOperations:                 # Phase 10 record_proc_sample 的替身
    def __init__(self) -> None:
        self.samples: dict[str, str] = {}

    def record_proc_sample(self, operation_id: str, signature: str) -> bool:
        if operation_id in self.samples:
            return False
        self.samples[operation_id] = signature
        return True


def test_three_distinct_operations_reach_replayable_count() -> None:
    operations, current = FakeOperations(), proc(success_count=0)
    for index in (1, 2, 3):
        current = on_new_success(current, f"op-ticket-t_88{index}", operations, LATER)
        assert current.success_count == index
        assert current.status == ProcStatus.ACTIVE
    assert current.last_used == LATER


def test_duplicate_operation_does_not_add_sample() -> None:
    operations = FakeOperations()
    first = on_new_success(proc(success_count=0), "op-ticket-t_881", operations, NOW)
    duplicate = on_new_success(first, "op-ticket-t_881", operations, LATER)
    assert duplicate.success_count == 1
    assert duplicate.last_used == NOW


def test_retired_proc_needs_manual_reset() -> None:
    with pytest.raises(PermanentError, match="人工"):
        on_new_success(proc(status=ProcStatus.RETIRED), "op-ticket-t_999", FakeOperations(), NOW)
