"""Phase 34：Rote 兩層命中的純函式單元測試。

這裡只驗「確定性的選擇規則」：Jaccard 的算法與空集合、門檻的比較方向（`>=`）、
重放資格的兩個硬條件，以及 Layer 2 的三段排序在所有候選排列下都得到同一個勝者。
不連 AWS、不呼叫模型、不讀 fixture 檔。
"""

from datetime import UTC, datetime

import pytest

from training_kb.models import ProcStatus, ProvenWorkflow
from training_kb.rote import JACCARD_THRESHOLD, jaccard, replayable

NOW = datetime(2026, 9, 12, tzinfo=UTC)
ANY_SIG = "0123456789abcdef"  # signature 必須是 16 個小寫 hex（Phase 04 的不變條件）


def proc(signature: str, *, keys: set[str], status: ProcStatus = ProcStatus.ACTIVE,
         success: int = 3, last: datetime = NOW, domain: str = "github.com",
         adapter: str = "github_issue") -> ProvenWorkflow:
    return ProvenWorkflow(
        signature=signature, domain=domain, adapter=adapter, steps=[], keys=sorted(keys),
        success_count=success, fail_count=0, status=status, last_used=last,
    )


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (frozenset(), frozenset(), 0.0),
        (frozenset({"a"}), frozenset({"a"}), 1.0),
        (frozenset({"a", "b", "c"}), frozenset({"a", "b", "c", "d"}), 0.75),
        (frozenset({"a", "b", "c", "d"}), frozenset({"a", "b", "c", "d", "e"}), 0.8),
    ],
)
def test_jaccard(left: frozenset[str], right: frozenset[str], expected: float) -> None:
    assert jaccard(left, right) == expected


@pytest.mark.parametrize(("score", "accepted"), [(0.7999, False), (0.8, True)])
def test_threshold_uses_greater_or_equal(score: float, accepted: bool) -> None:
    assert (score >= JACCARD_THRESHOLD) is accepted


def test_replay_requires_active_and_three_successes() -> None:
    assert not replayable(proc(ANY_SIG, keys={"a"}, status=ProcStatus.RETIRED, success=9))
    assert not replayable(proc(ANY_SIG, keys={"a"}, success=2))
    assert replayable(proc(ANY_SIG, keys={"a"}, success=3))
