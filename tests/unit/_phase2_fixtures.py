"""Phase 2 測試共用種子（只給 tests/unit/test_{realtime,analysis,create,poll}.py 用）。"""

from __future__ import annotations

from app.analytics.local_db import LocalDB

FEATURES = {
    1: ("Cancel Order", "active"),
    2: ("Track Refund", "active"),
    3: ("Change Shipping Address", "active"),
}
TOPICS = {1: "cancel_order", 2: "track_refund", 3: "change_shipping_address"}


def make_db(tmp_path) -> LocalDB:
    db = LocalDB(str(tmp_path / "t.db"))
    db.init_schema()
    return db


def seed_domain(db: LocalDB, ids=(1,)) -> None:
    """建 Feature 與 UserProblem（id 與 topic 對齊規格 Example）。"""
    for i in ids:
        name, status = FEATURES[i]
        db.execute(
            "INSERT INTO Feature (id, name, status) VALUES (:id, :name, :status)",
            {"id": i, "name": name, "status": status},
        )
        db.execute(
            "INSERT INTO UserProblem (id, topic, feature_id) VALUES (:id, :topic, :fid)",
            {"id": i, "topic": TOPICS[i], "fid": i},
        )


def add_ticket(db: LocalDB, **kw) -> int:
    row = {
        "content": "I want to cancel order {{Order Number}}",
        "resolution_steps": "",
        "category": "ORDER",
        "customer_ref": "alice@example.com",
        "feature_id": None,
        "user_problem_id": 1,
        "status": "open",
        "deflected_tutorial_id": None,
        "deflected_tutorial_version": None,
        "reopened_from_ticket_id": None,
        "created_at": "2026-09-11T10:30:00Z",
    }
    row.update(kw)
    return db.execute(
        """
        INSERT INTO Ticket (content, resolution_steps, category, customer_ref, feature_id,
                            user_problem_id, status, deflected_tutorial_id,
                            deflected_tutorial_version, reopened_from_ticket_id, created_at)
        VALUES (:content, :resolution_steps, :category, :customer_ref, :feature_id,
                :user_problem_id, :status, :deflected_tutorial_id,
                :deflected_tutorial_version, :reopened_from_ticket_id, :created_at)
        """,
        row,
    )


def add_tutorial(db: LocalDB, **kw) -> int:
    row = {
        "tutorial_id": 1,
        "feature_id": 1,
        "user_problem_id": 1,
        "path": "tutorials/cancel-order.md",
        "status": "published",
        "current_version": "v1",
        "is_possibly_outdated": 0,
        "is_obsolete": 0,
        "last_action": "CREATE",
    }
    row.update(kw)
    db.execute(
        """
        INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status,
                              current_version, is_possibly_outdated, is_obsolete, last_action)
        VALUES (:tutorial_id, :feature_id, :user_problem_id, :path, :status,
                :current_version, :is_possibly_outdated, :is_obsolete, :last_action)
        """,
        row,
    )
    return row["tutorial_id"]


def ticket(db: LocalDB, ticket_id: int) -> dict:
    return db.run_sql("SELECT * FROM Ticket WHERE id = :id", {"id": ticket_id})[0]
