"""即時路徑（自動回覆顧客.feature 五條 Rule ＋ 失敗語意）。"""

from __future__ import annotations

import pytest

from app.agent import realtime, rules
from app.errors import OperationFailed
from tests.unit._phase2_fixtures import (
    add_ticket,
    add_tutorial,
    make_db,
    seed_domain,
    ticket,
)


def test_reopen_wins_over_published():
    """自動回覆顧客.feature Rule 5：有 published Tutorial 但屬再開票 → 仍 escalated。"""
    assert rules.classify_ticket(True, True, True) == "escalated"


def test_deflected_when_published_tutorial_exists(tmp_path):
    """Rule 1：cancel_order 已有 published Tutorial → deflected ＋ 兩個 deflected_* 欄有值。"""
    db = make_db(tmp_path)
    seed_domain(db)
    add_tutorial(db)
    tid = add_ticket(db)

    result = realtime.handle_open_ticket(db, tid)

    row = ticket(db, tid)
    assert row["status"] == "deflected"
    assert row["deflected_tutorial_id"] == 1
    assert row["deflected_tutorial_version"] == "v1"
    assert result["status"] == "deflected"
    # 第一次成功攔截 → Workflow 由 rote_client.on_deflected 處理
    workflows = db.run_sql("SELECT * FROM Workflow WHERE user_problem_id = 1")
    assert len(workflows) == 1
    assert workflows[0]["replay_count"] == 0
    assert "replay_count" in result


def test_escalated_when_no_tutorial(tmp_path):
    """Rule 2：UserProblem 尚無 Tutorial → escalated，deflected_* 留空。"""
    db = make_db(tmp_path)
    seed_domain(db)
    tid = add_ticket(db)

    result = realtime.handle_open_ticket(db, tid)

    row = ticket(db, tid)
    assert row["status"] == "escalated"
    assert row["deflected_tutorial_id"] is None
    assert row["deflected_tutorial_version"] is None
    assert result["status"] == "escalated"


def test_escalated_when_user_problem_id_empty(tmp_path):
    """Rule 3：user_problem_id 為空的票 → escalated，且不 crash。"""
    db = make_db(tmp_path)
    tid = add_ticket(
        db,
        content="Something is wrong with my thing",
        category="",
        user_problem_id=None,
    )

    result = realtime.handle_open_ticket(db, tid)

    row = ticket(db, tid)
    assert row["status"] == "escalated"
    assert row["deflected_tutorial_id"] is None
    assert row["reopened_from_ticket_id"] is None
    assert result["status"] == "escalated"


def test_retired_tutorial_treated_as_absent(tmp_path):
    """Rule 4：retired 的 Tutorial 視同沒有 → escalated。"""
    db = make_db(tmp_path)
    seed_domain(db)
    add_tutorial(db, status="retired", is_obsolete=1, last_action="RETIRE")
    tid = add_ticket(db)

    realtime.handle_open_ticket(db, tid)

    row = ticket(db, tid)
    assert row["status"] == "escalated"
    assert row["deflected_tutorial_id"] is None


def test_reopen_sets_reopened_from_ticket_id(tmp_path):
    """Rule 5：alice 被攔截後再開同類票 → escalated ＋ reopened_from_ticket_id 指向舊票。"""
    db = make_db(tmp_path)
    seed_domain(db)
    add_tutorial(db)
    old = add_ticket(
        db,
        status="deflected",
        deflected_tutorial_id=1,
        deflected_tutorial_version="v1",
        created_at="2026-09-11T09:00:00Z",
    )
    new = add_ticket(db, created_at="2026-09-11T11:00:00Z")

    realtime.handle_open_ticket(db, new)

    row = ticket(db, new)
    assert row["status"] == "escalated"
    assert row["reopened_from_ticket_id"] == old
    assert row["deflected_tutorial_id"] is None
    # 舊票不動
    assert ticket(db, old)["status"] == "deflected"


def test_other_customer_still_deflected(tmp_path):
    """Rule 5 只針對同一 customer_ref：bob 的新票仍 deflected。"""
    db = make_db(tmp_path)
    seed_domain(db)
    add_tutorial(db)
    add_ticket(db, status="deflected", deflected_tutorial_id=1, deflected_tutorial_version="v1")
    new = add_ticket(db, customer_ref="bob@example.com")

    realtime.handle_open_ticket(db, new)

    assert ticket(db, new)["status"] == "deflected"


def test_non_open_ticket_fails(tmp_path):
    """票不是 open → 操作失敗（不重複處理已結案的票）。"""
    db = make_db(tmp_path)
    seed_domain(db)
    tid = add_ticket(db, status="resolved")

    with pytest.raises(OperationFailed):
        realtime.handle_open_ticket(db, tid)

    assert ticket(db, tid)["status"] == "resolved"


def test_read_failure_keeps_ticket_open(tmp_path, monkeypatch):
    """showme §7.1 失敗列：讀取失敗 → OperationFailed，票維持 open。"""
    db = make_db(tmp_path)
    seed_domain(db)
    tid = add_ticket(db)

    real_run_sql = db.run_sql

    def boom(sql, params=None):
        if "FROM Tutorial" in sql:
            raise RuntimeError("hotdata 掛了")
        return real_run_sql(sql, params)

    monkeypatch.setattr(db, "run_sql", boom)

    with pytest.raises(OperationFailed):
        realtime.handle_open_ticket(db, tid)

    monkeypatch.undo()
    assert ticket(db, tid)["status"] == "open"


def test_resolve_ticket(tmp_path):
    """轉真人結案：escalated → resolved 並寫入 resolution_steps。"""
    db = make_db(tmp_path)
    seed_domain(db)
    tid = add_ticket(db, status="escalated")

    realtime.resolve_ticket(db, tid, "1. Open Orders. 2. Click \"Cancel Order\".")

    row = ticket(db, tid)
    assert row["status"] == "resolved"
    assert "Cancel Order" in row["resolution_steps"]


def test_resolve_ticket_requires_escalated(tmp_path):
    db = make_db(tmp_path)
    seed_domain(db)
    tid = add_ticket(db, status="open")

    with pytest.raises(OperationFailed):
        realtime.resolve_ticket(db, tid, "whatever")
