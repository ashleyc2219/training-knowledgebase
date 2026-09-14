"""Phase 35：PROC 計數在 moto DynamoDB 上的條件更新與寫入 owner。

單元測試只證明「純函式算得對」，這裡證明「算完之後存得住」：兩個 worker 讀到同一個
`_revision` 時第二次必須被擋下（`CoordinationError`），重讀重算後兩次失敗都留在資料裡；
連敗歸零與退役的最終值也要落地。「併發」用兩個先後讀取、交錯寫入的視角模擬，不開執行緒，
所以不需要真實帳號、不標 `aws`；moto 的 PASS 只證明資料形狀，O2 仍未 PASS。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from training_kb.errors import CoordinationError
from training_kb.keys import proc_pk
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.repository import Repository
from training_kb.rote import on_replay_failure, on_replay_success, proc_changes, replayable

SIG, LATER = "a1b2c3d4e5f60718", datetime(2026, 9, 13, 1, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]
PROC_OWNERS = {"keys.py", "repository.py", "rote.py"}
BASE = ProvenWorkflow(
    signature=SIG, domain="github.com", adapter="github_issue",
    steps=[ProcStep(tool="validate", args={"candidate": "$steps[0]"})],
    keys=["action", "issue", "repository", "sender"],
    success_count=3, fail_count=0, status=ProcStatus.ACTIVE, last_used=LATER,
)


def save(repository: Repository, updated: ProvenWorkflow) -> None:
    # 呼叫端的固定順序：讀 -> 純函式算 -> 條件寫；CoordinationError 由上層重讀重算
    pk = proc_pk(SIG)
    repository.update_meta(pk, proc_changes(updated),
                           expected_revision=repository.revision_of(pk))


def reload(repository: Repository) -> ProvenWorkflow:
    """重讀那筆 PROC；`get_proc` 回 `None` 代表 item 不見了，直接在這裡斷言比較好讀。"""
    stored = repository.get_proc(SIG)
    assert stored is not None
    return stored


def test_interleaved_failures_do_not_lose_a_count(repository: Repository) -> None:
    repository.put_meta(BASE)
    pk, stale = proc_pk(SIG), repository.revision_of(proc_pk(SIG))
    worker_a, worker_b = reload(repository), reload(repository)
    save(repository, on_replay_failure(worker_a, LATER))
    with pytest.raises(CoordinationError, match="revision"):
        repository.update_meta(pk, proc_changes(on_replay_failure(worker_b, LATER)),
                               expected_revision=stale)
    save(repository, on_replay_failure(reload(repository), LATER))
    assert reload(repository).fail_count == 2


def test_persisted_failures_reset_then_retire(repository: Repository) -> None:
    repository.put_meta(BASE)
    save(repository, on_replay_failure(reload(repository), LATER))
    save(repository, on_replay_success(reload(repository), LATER))
    assert reload(repository).fail_count == 0
    for _ in range(3):
        save(repository, on_replay_failure(reload(repository), LATER))
    stored = reload(repository)
    assert (stored.fail_count, stored.status) == (3, ProcStatus.RETIRED)
    assert replayable(stored) is False


def test_only_rote_touches_proc_items() -> None:
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "src" / "training_kb").rglob("*.py")
        if path.name not in PROC_OWNERS
        and any(t in path.read_text(encoding="utf-8") for t in ("proc_pk(", "PROC#"))
    )
    assert offenders == [], f"只有 Rote 可以讀寫 PROC，違規檔案：{offenders}"
