"""Phase 34：Rote 兩層命中的純函式單元測試。

這裡只驗「確定性的選擇規則」：Jaccard 的算法與空集合、門檻的比較方向（`>=`）、
重放資格的兩個硬條件，以及 Layer 2 的三段排序在所有候選排列下都得到同一個勝者。
不連 AWS、不呼叫模型、不讀 fixture 檔。
"""

from datetime import UTC, datetime
from itertools import permutations

import pytest

from training_kb.models import ProcStatus, ProvenWorkflow
from training_kb.rote import (
    JACCARD_THRESHOLD,
    RawEvent,
    jaccard,
    pick_layer2,
    replayable,
)

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


# --- Layer 2：同範圍候選的三段排序 --------------------------------------------

FOUR = {"action", "issue", "repository", "sender"}
EVENT = RawEvent("github.com", "github_issue", "issues", {},
                 {"action": "opened", "issue": {}, "repository": {}, "sender": {}})
EMPTY_EVENT = RawEvent("github.com", "github_issue", "issues", {}, {})

LOOSE = "aaaa000000000000"      # 多一個 installation，分數 0.8
OLDEST = "bbbb000000000002"     # 分數 1.0，last_used 最舊
TIE_HIGH = "bbbb000000000009"   # 分數 1.0、last_used 最新，字典序較大
TIE_LOW = "bbbb000000000001"    # 分數 1.0、last_used 最新，字典序最小 -> 應該勝出


def test_layer2_picks_highest_score_then_last_used_then_signature() -> None:
    loose = proc(LOOSE, keys=FOUR | {"installation"}, last=datetime(2026, 9, 9, tzinfo=UTC))
    older = proc(OLDEST, keys=FOUR, last=datetime(2026, 9, 1, tzinfo=UTC))
    newer_b = proc(TIE_HIGH, keys=FOUR, last=datetime(2026, 9, 2, tzinfo=UTC))
    newer_a = proc(TIE_LOW, keys=FOUR, last=datetime(2026, 9, 2, tzinfo=UTC))
    for order in permutations([loose, older, newer_b, newer_a]):
        picked = pick_layer2(EVENT, list(order))
        assert picked is not None
        assert picked.signature == TIE_LOW


@pytest.mark.parametrize(
    "candidate",
    [
        proc("c0de000000000001", keys=FOUR, status=ProcStatus.RETIRED),
        proc("c0de000000000002", keys=FOUR, success=2),
        proc("c0de000000000003", keys=FOUR, domain="discord.com"),
        proc("c0de000000000004", keys=FOUR, adapter="github_pr"),
        proc("c0de000000000005", keys={"action", "issue", "repository", "x", "y"}),
    ],
    ids=["retired", "success-2", "other-domain", "other-adapter", "score-0.5"],
)
def test_layer2_rejects_unqualified_candidates(candidate: ProvenWorkflow) -> None:
    assert pick_layer2(EVENT, [candidate]) is None


def test_empty_key_sets_and_empty_candidate_list_never_match() -> None:
    assert pick_layer2(EMPTY_EVENT, [proc("0000000000000000", keys=set())]) is None
    assert pick_layer2(EVENT, []) is None
