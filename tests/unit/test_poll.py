"""輪詢新票單 ＋ demo 餵票（輪詢新票單.feature 唯一 Rule）。"""

from __future__ import annotations

import json

from app.ingest import poll
from tests.unit._phase2_fixtures import add_ticket, make_db, seed_domain

SCRIPT = [
    {
        "content": "i need help cancelling puchase {{Order Number}}",
        "category": "ORDER",
        "intent": "cancel_order",
        "feature_name": "Cancel Order",
        "customer_ref": "alice@example.com",
        "created_at": "2026-09-01T15:00:00Z",
    },
    {
        "content": "I need to cancel purchase {{Order Number}}",
        "category": "ORDER",
        "intent": "cancel_order",
        "feature_name": "Cancel Order",
        "customer_ref": "bob@example.com",
        "created_at": "2026-09-01T16:00:00Z",
    },
    {
        "content": "Something is wrong with my thing",
        "category": "",
        "intent": None,
        "feature_name": None,
        "customer_ref": "alice@example.com",
        "created_at": "2026-09-01T17:00:00Z",
    },
]


def _script_files(tmp_path, monkeypatch, rows=SCRIPT):
    script = tmp_path / "demo_tickets.json"
    script.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(poll, "DEMO_SCRIPT_PATH", script)
    monkeypatch.setattr(poll, "DEMO_CURSOR_PATH", tmp_path / "demo_cursor.json")


def test_poll_respects_cursor_and_status(tmp_path):
    """Example：09:00 open 不動、10:00（＝cursor）不動、10:30 open 要處理、10:30 resolved 不動。"""
    db = make_db(tmp_path)
    seed_domain(db, ids=(1, 2))
    add_ticket(db, created_at="2026-09-11T09:00:00Z")
    add_ticket(db, created_at="2026-09-11T10:00:00Z", customer_ref="bob@example.com")
    third = add_ticket(db, created_at="2026-09-11T10:30:00Z")
    add_ticket(db, created_at="2026-09-11T10:30:00Z", status="resolved", user_problem_id=2)

    rows = poll.poll_new_tickets(db, "2026-09-11T10:00:00Z")

    assert [r["id"] for r in rows] == [third]


def test_poll_returns_empty_when_nothing_new(tmp_path):
    db = make_db(tmp_path)
    seed_domain(db)
    add_ticket(db, created_at="2026-09-11T09:00:00Z")

    assert poll.poll_new_tickets(db, "2026-09-11T10:00:00Z") == []


def test_feed_next_ticket_in_order_and_maps_user_problem(tmp_path, monkeypatch):
    """餵票依劇本順序，並用 intent 填好 user_problem_id / feature_id。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _script_files(tmp_path, monkeypatch)

    first = poll.feed_next_ticket(db)
    assert first["content"] == SCRIPT[0]["content"]
    row = db.run_sql("SELECT * FROM Ticket WHERE id = :id", {"id": first["ticket_id"]})[0]
    assert row["status"] == "open"
    assert row["user_problem_id"] == 1
    assert row["feature_id"] == 1
    assert row["customer_ref"] == "alice@example.com"

    second = poll.feed_next_ticket(db)
    assert second["content"] == SCRIPT[1]["content"]
    assert second["ticket_id"] != first["ticket_id"]


def test_feed_next_ticket_without_intent_leaves_user_problem_null(tmp_path, monkeypatch):
    """intent 為 null 的票：user_problem_id 留空（自動回覆顧客 Rule 3 的素材）。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _script_files(tmp_path, monkeypatch, rows=[SCRIPT[2]])

    fed = poll.feed_next_ticket(db)

    row = db.run_sql("SELECT * FROM Ticket WHERE id = :id", {"id": fed["ticket_id"]})[0]
    assert row["user_problem_id"] is None
    assert row["feature_id"] is None
    assert row["status"] == "open"


def test_feed_next_ticket_exhausted(tmp_path, monkeypatch):
    """劇本餵完後回 None，不 crash。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _script_files(tmp_path, monkeypatch, rows=[SCRIPT[0]])

    assert poll.feed_next_ticket(db) is not None
    assert poll.feed_next_ticket(db) is None


def test_fed_ticket_created_at_is_after_poll_cursor(tmp_path, monkeypatch):
    """餵進來的票 created_at 用現在時間，才會被輪詢（嚴格大於 cursor）看見。"""
    db = make_db(tmp_path)
    seed_domain(db)
    _script_files(tmp_path, monkeypatch)

    fed = poll.feed_next_ticket(db)
    rows = poll.poll_new_tickets(db, "2026-09-01T00:00:00Z")

    assert fed["ticket_id"] in [r["id"] for r in rows]
