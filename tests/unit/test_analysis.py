"""分析 Ticket（分析SupportTickets.feature 九條 Rule 的 Example）。"""

from __future__ import annotations

from app.agent import analysis
from tests.unit._phase2_fixtures import add_ticket, add_tutorial, make_db, seed_domain


def _resolved(db, upid, n, status="resolved"):
    for _ in range(n):
        add_ticket(db, user_problem_id=upid, feature_id=upid, status=status)


def _actions(rows):
    return {r["user_problem_id"]: r["action"] for r in rows}


def test_three_tickets_is_recurring(tmp_path):
    """Rule 1 Example：剛好 3 張 cancel_order 票識別為 recurring topic。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _resolved(db, 1, 3)

    assert _actions(analysis.analyze_tickets(db)) == {1: "CREATE"}


def test_two_tickets_not_recurring(tmp_path):
    """Rule 1 Example：只有 2 張時 recurring topic 為空。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _resolved(db, 1, 2)

    assert analysis.analyze_tickets(db) == []


def test_empty_when_no_tickets(tmp_path):
    """Rule 2 Example：沒有 Ticket 時結果為空。"""
    db = make_db(tmp_path)
    seed_domain(db)

    assert analysis.analyze_tickets(db) == []
    assert analysis.knowledge_gaps(db) == []


def test_empty_when_tickets_do_not_cluster(tmp_path):
    """Rule 3 Example：三張票各屬不同 user_problem_id。"""
    db = make_db(tmp_path)
    seed_domain(db, ids=(1, 2, 3))
    for upid in (1, 2, 3):
        _resolved(db, upid, 1)

    assert analysis.analyze_tickets(db) == []


def test_open_and_deflected_excluded(tmp_path):
    """Rule 4 Example 1：open ×2 ＋ deflected ×1 → 空。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _resolved(db, 1, 2, status="open")
    _resolved(db, 1, 1, status="deflected")

    assert analysis.analyze_tickets(db) == []


def test_two_resolved_plus_one_escalated_is_recurring(tmp_path):
    """Rule 4 Example 2：2 resolved ＋ 1 escalated → recurring。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _resolved(db, 1, 2)
    _resolved(db, 1, 1, status="escalated")

    assert _actions(analysis.analyze_tickets(db)) == {1: "CREATE"}


def test_knowledge_gap_only_without_published(tmp_path):
    """Rule 5 兩個 Example：無 Tutorial → gap；已 published → gap 為空。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _resolved(db, 1, 3)

    gaps = analysis.knowledge_gaps(db)
    assert [g["user_problem_id"] for g in gaps] == [1]
    assert gaps[0]["topic"] == "cancel_order"

    add_tutorial(db)
    assert analysis.knowledge_gaps(db) == []


def test_action_keep_when_published(tmp_path):
    """Rule 7 Example：已有 published Tutorial → KEEP。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _resolved(db, 1, 3)
    add_tutorial(db)

    assert _actions(analysis.analyze_tickets(db)) == {1: "KEEP"}


def test_retired_tutorial_still_creates(tmp_path):
    """retired 不是 published → 仍是 Knowledge Gap（對齊 Rule 5 的「published」字面）。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _resolved(db, 1, 3)
    add_tutorial(db, status="retired", is_obsolete=1, last_action="RETIRE")

    assert _actions(analysis.analyze_tickets(db)) == {1: "CREATE"}


def test_multiple_gaps_all_create(tmp_path):
    """Rule 8 Example：cancel_order 與 track_refund 兩個 gap 皆 CREATE。"""
    db = make_db(tmp_path)
    seed_domain(db, ids=(1, 2))
    _resolved(db, 1, 3)
    _resolved(db, 2, 3)

    assert _actions(analysis.analyze_tickets(db)) == {1: "CREATE", 2: "CREATE"}


def test_other_topic_tutorial_does_not_block_create(tmp_path):
    """Rule 9 Example：track_refund 已有 Tutorial 不影響 cancel_order 仍 CREATE。"""
    db = make_db(tmp_path)
    seed_domain(db, ids=(1, 2))
    _resolved(db, 1, 3)
    add_tutorial(db, tutorial_id=1, feature_id=2, user_problem_id=2, path="tutorials/track-refund.md")

    assert _actions(analysis.analyze_tickets(db)) == {1: "CREATE"}
