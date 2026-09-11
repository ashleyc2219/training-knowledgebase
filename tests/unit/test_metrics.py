"""三條指標對齊 展示學習指標.feature 的 Example（皆為 0.5）。"""

import pytest

from app.analytics.local_db import LocalDB
from app.analytics.metrics import avg_rating, coverage, deflection_rate, replay_rate


@pytest.fixture
def db(tmp_path):
    d = LocalDB(path=str(tmp_path / "m.db"))
    d.init_schema()
    return d


def _ticket(db, status):
    db.execute(
        "INSERT INTO Ticket (content, status, created_at) VALUES ('x', :status, '2026-09-11T10:00:00Z')",
        {"status": status},
    )


def test_deflection_rate為二分之一(db):
    for status in ("deflected", "deflected", "escalated", "escalated", "open"):
        _ticket(db, status)
    assert deflection_rate(db) == 0.5


def test_replay_rate為二分之一(db):
    # 展示學習指標.feature Example：replay_count 總和 2、deflected 4 張 → 0.5
    for status in ("deflected", "deflected", "deflected", "deflected"):
        _ticket(db, status)
    db.execute(
        "INSERT INTO Workflow (user_problem_id, steps, captured_at, replay_count)"
        " VALUES (1, 's', '2026-09-11T10:00:00Z', 2)"
    )
    assert replay_rate(db) == 0.5


def test_coverage為二分之一(db):
    db.execute("INSERT INTO UserProblem (id, topic) VALUES (1, 'cancel_order')")
    db.execute("INSERT INTO UserProblem (id, topic) VALUES (2, 'track_refund')")
    db.execute(
        "INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status,"
        " current_version, is_possibly_outdated, is_obsolete, last_action)"
        " VALUES (1, 1, 1, 'tutorials/cancel-order.md', 'published', 'v1', 0, 0, 'CREATE')"
    )
    assert coverage(db) == 0.5


def test_分母為零回零(db):
    assert deflection_rate(db) == 0.0
    assert replay_rate(db) == 0.0
    assert coverage(db) == 0.0
    assert avg_rating(db, 1) == 0.0


def test_avg_rating只算current_version(db):
    db.execute(
        "INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status,"
        " current_version, is_possibly_outdated, is_obsolete, last_action)"
        " VALUES (1, 1, 1, 'tutorials/cancel-order.md', 'published', 'v2', 0, 0, 'REFINE')"
    )
    for version, rating in [("v1", 2), ("v1", 3), ("v2", 4), ("v2", 5)]:
        db.execute(
            "INSERT INTO Feedback (tutorial_id, tutorial_version, rating, feedback_category,"
            " comment, submitter_id, timestamp)"
            " VALUES (1, :version, :rating, '', '', 'alice@example.com', '2026-09-11T10:00:00Z')",
            {"version": version, "rating": rating},
        )
    assert avg_rating(db, 1) == 4.5
