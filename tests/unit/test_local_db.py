"""LocalDB schema 與 round-trip。"""

from app.analytics.local_db import LocalDB
from app.analytics.sql import TABLES


def test_init_schema_建出9張表(tmp_path):
    db = LocalDB(path=str(tmp_path / "t.db"))
    db.init_schema()
    rows = db.run_sql("SELECT name FROM sqlite_master WHERE type = 'table'")
    names = {r["name"] for r in rows}
    assert len(TABLES) == 9
    assert set(TABLES) <= names


def test_execute_run_sql_round_trip(tmp_path):
    db = LocalDB(path=str(tmp_path / "t.db"))
    db.init_schema()
    rowid = db.execute(
        """
        INSERT INTO Ticket (content, category, customer_ref, status, created_at)
        VALUES (:content, :category, :customer_ref, 'open', :created_at)
        """,
        {
            "content": "I want to cancel order {{Order Number}}",
            "category": "ORDER",
            "customer_ref": "alice@example.com",
            "created_at": "2026-09-11T10:00:00Z",
        },
    )
    assert rowid == 1
    rows = db.run_sql("SELECT * FROM Ticket WHERE id = :id", {"id": rowid})
    assert len(rows) == 1
    assert rows[0]["status"] == "open"
    assert rows[0]["customer_ref"] == "alice@example.com"


def test_reset_清空資料(tmp_path):
    db = LocalDB(path=str(tmp_path / "t.db"))
    db.init_schema()
    db.execute("INSERT INTO UserProblem (topic) VALUES (:topic)", {"topic": "cancel_order"})
    assert db.run_sql("SELECT * FROM UserProblem")
    db.reset()
    assert db.run_sql("SELECT * FROM UserProblem") == []
