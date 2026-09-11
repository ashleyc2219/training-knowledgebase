"""學習指標快照與曲線歷史：對齊 展示學習指標.feature 的 3 條 Rule（皆為 0.5）。"""

import json

import pytest

from app.analytics import metrics
from app.analytics.local_db import LocalDB


@pytest.fixture
def db(tmp_path):
    d = LocalDB(path=str(tmp_path / "t.db"))
    d.init_schema()
    return d


def _ticket(db, status):
    db.execute(
        "INSERT INTO Ticket (content, status, created_at)"
        " VALUES ('x', :status, '2026-09-11T10:00:00Z')",
        {"status": status},
    )


def _demo_rows(db):
    """展示學習指標.feature 三個 Example 合成一份資料：三條指標都是 0.5。"""
    for status in ("deflected", "deflected", "escalated", "escalated", "open"):
        _ticket(db, status)
    db.execute(
        "INSERT INTO Workflow (user_problem_id, steps, captured_at, replay_count)"
        " VALUES (1, 's', '2026-09-11T10:00:00Z', 1)"
    )
    db.execute("INSERT INTO UserProblem (id, topic) VALUES (1, 'cancel_order')")
    db.execute("INSERT INTO UserProblem (id, topic) VALUES (2, 'track_refund')")
    db.execute(
        "INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status,"
        " current_version, is_possibly_outdated, is_obsolete, last_action)"
        " VALUES (1, 1, 1, 'tutorials/cancel-order.md', 'published', 'v1', 0, 0, 'CREATE')"
    )


def test_三條指標對齊Example皆為零點五(db):
    _demo_rows(db)
    assert metrics.deflection_rate(db) == 0.5  # 2 / 4
    assert metrics.replay_rate(db) == 0.5  # 1 / 2
    assert metrics.coverage(db) == 0.5  # 1 / 2


def test_snapshot鍵齊全(db):
    _demo_rows(db)
    point = metrics.snapshot(db)
    assert set(point) == {"ts", "deflection_rate", "avg_rating", "replay_rate", "coverage"}
    assert point["deflection_rate"] == 0.5
    assert point["replay_rate"] == 0.5
    assert point["coverage"] == 0.5
    assert point["avg_rating"] == 0.0  # 還沒有 Feedback
    assert point["ts"].endswith("Z")


def test_history可追加與讀回(db, tmp_path):
    _demo_rows(db)
    path = tmp_path / "metrics_history.json"

    assert metrics.load_history(path) == []
    first = metrics.append_history(metrics.snapshot(db), path)
    second = metrics.append_history(metrics.snapshot(db), path)

    assert len(first) == 1
    assert len(second) == 2
    assert metrics.load_history(path) == second
    assert json.loads(path.read_text(encoding="utf-8")) == second


def test_history檔壞掉時當作空的(db, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{不是 JSON", encoding="utf-8")
    assert metrics.load_history(path) == []
