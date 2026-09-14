"""Phase 34：兩層重放查詢在 moto DynamoDB 上的整合測試。

證明 `find_replayable` 的順序是「先以 `PROC#<signature>` 精確比對，不成才進 Layer 2」
（00B 的 ING Rule 5／6／7／11），而且整段查詢碰不到任何 Writer。moto 的 PASS 只證明
資料形狀，不是實表行為的證據；不需要真實帳號，所以不標 `aws`。
"""

import inspect
from collections.abc import Callable
from datetime import UTC, datetime

from training_kb.models import ProcStatus, ProvenWorkflow
from training_kb.repository import Repository
from training_kb.rote import RawEvent, find_replayable, pick_layer2, structure_signature

FOUR = {"action", "issue", "repository", "sender"}
EVENT = RawEvent("github.com", "github_issue", "issues", {},
                 {"action": "opened", "issue": {}, "repository": {}, "sender": {}})
NEIGHBOUR = "beef000000000001"   # 同範圍的 Layer 2 候選，keys 多一個 installation
STALE = "dead000000000002"       # 同範圍但只成功兩次


def proc(signature: str, *, keys: set[str], status: ProcStatus = ProcStatus.ACTIVE,
         success: int = 3) -> ProvenWorkflow:
    return ProvenWorkflow(
        signature=signature, domain="github.com", adapter="github_issue", steps=[],
        keys=sorted(keys), success_count=success, fail_count=0, status=status,
        last_used=datetime(2026, 9, 12, tzinfo=UTC),
    )


class SpyWriter:
    """任何 Writer 方法被呼叫都會記下來；查詢路徑拿不到它，清單必須維持空的。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: self.calls.append(name)


def test_layer1_exact_hit_returns_that_proc(repository: Repository) -> None:
    signature = structure_signature(EVENT)
    repository.put_meta(proc(signature, keys=FOUR, success=4))
    picked = find_replayable(EVENT, signature, repository=repository)
    assert picked is not None
    assert picked.signature == signature


def test_retired_exact_falls_through_to_layer2(repository: Repository) -> None:
    signature = structure_signature(EVENT)
    repository.put_meta(proc(signature, keys=FOUR, status=ProcStatus.RETIRED, success=9))
    repository.put_meta(proc(NEIGHBOUR, keys=FOUR | {"installation"}))
    picked = find_replayable(EVENT, signature, repository=repository)
    assert picked is not None
    assert picked.signature == NEIGHBOUR


def test_no_qualified_proc_returns_none(repository: Repository) -> None:
    repository.put_meta(proc(STALE, keys=FOUR, success=2))
    assert find_replayable(EVENT, structure_signature(EVENT), repository=repository) is None


def test_lookup_never_reaches_a_writer(repository: Repository) -> None:
    writer = SpyWriter()
    signature = structure_signature(EVENT)
    repository.put_meta(proc(signature, keys=FOUR, success=4))
    assert find_replayable(EVENT, signature, repository=repository) is not None
    assert writer.calls == []
    assert "writer" not in inspect.signature(find_replayable).parameters
    assert "writer" not in inspect.signature(pick_layer2).parameters
