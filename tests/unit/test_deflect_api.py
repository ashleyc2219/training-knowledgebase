"""Phase 3 — 本機 deflect API（Rote Play 打的 endpoint）。

對應規格 docs/spec/features/自動回覆顧客.feature（deflected Rule）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.analytics.local_db import LocalDB
from app.api.deflect_api import app


@pytest.fixture()
def db(tmp_path):
    d = LocalDB(str(tmp_path / "t.db"))
    d.init_schema()
    d.execute("INSERT INTO Feature (id, name, status) VALUES (1, 'Cancel Order', 'active')")
    d.execute("INSERT INTO UserProblem (id, topic, feature_id) VALUES (1, 'cancel_order', 1)")
    d.execute(
        "INSERT INTO Ticket (id, content, category, customer_ref, user_problem_id, status) "
        "VALUES (4, 'I want to cancel my order', 'ORDER', 'alice@example.com', 1, 'open')"
    )
    app.state.db = d
    yield d
    app.state.db = None


@pytest.fixture()
def client(db):
    return TestClient(app)


def _given_published_tutorial(db) -> None:
    db.execute(
        "INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status, "
        "current_version, last_action) "
        "VALUES (1, 1, 1, 'tutorials/cancel-order.md', 'published', 'v1', 'CREATE')"
    )


def test_有_published_tutorial_時票單變成_deflected(client, db):
    _given_published_tutorial(db)

    resp = client.post("/deflect", json={"ticket_id": 4})

    assert resp.status_code == 200
    assert resp.json() == {
        "ticket_id": 4,
        "tutorial_path": "tutorials/cancel-order.md",
        "version": "v1",
    }
    row = db.run_sql("SELECT * FROM Ticket WHERE id = 4")[0]
    assert row["status"] == "deflected"
    assert row["deflected_tutorial_id"] == 1
    assert row["deflected_tutorial_version"] == "v1"


def test_重複呼叫是冪等的(client, db):
    _given_published_tutorial(db)

    first = client.post("/deflect", json={"ticket_id": 4})
    second = client.post("/deflect", json={"ticket_id": 4})

    assert first.json() == second.json()
    assert db.run_sql("SELECT status FROM Ticket WHERE id = 4")[0]["status"] == "deflected"


def test_沒有_published_tutorial_回_404_且票單不變(client, db):
    resp = client.post("/deflect", json={"ticket_id": 4})

    assert resp.status_code == 404
    assert db.run_sql("SELECT status FROM Ticket WHERE id = 4")[0]["status"] == "open"


def test_tutorial_未_published_也回_404(client, db):
    db.execute(
        "INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status, "
        "current_version) VALUES (1, 1, 1, 'tutorials/cancel-order.md', 'retired', 'v1')"
    )

    assert client.post("/deflect", json={"ticket_id": 4}).status_code == 404


def test_票單不存在回_404(client, db):
    _given_published_tutorial(db)

    assert client.post("/deflect", json={"ticket_id": 999}).status_code == 404


def test_health_與_openapi(client):
    assert client.get("/health").json() == {"status": "ok"}

    spec = client.get("/openapi.json").json()
    assert spec["openapi"].startswith("3.")
    assert spec["paths"]["/deflect"]["post"]["operationId"] == "deflect_ticket"
