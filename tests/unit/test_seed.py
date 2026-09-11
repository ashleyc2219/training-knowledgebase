"""種子匯入：對齊 docs/spec/features/建構知識圖譜.feature 的 5 條 Rule。

每個測試只餵對應 Example 的那幾列，Then 表逐欄比對。
Cognee / HydraDB 用 fake 物件，不打真服務。
"""

import pytest

from app.analytics.local_db import LocalDB
from app.ingest.seed import seed

# --- .feature Example 的匯入列（欄名逐字對齊規格） ---

CANCEL_ALICE = {
    "content": "I want to cancel order {{Order Number}}",
    "category": "ORDER",
    "intent": "cancel_order",
    "response": "Go to Orders, select the order, and click Cancel Order.",
    "customer_ref": "alice@example.com",
    "feature_name": "Cancel Order",
    "created_at": "2026-09-01T10:00:00Z",
}

CANCEL_BOB = {
    "content": "How can I cancel my order?",
    "category": "ORDER",
    "intent": "cancel_order",
    "response": "Go to Orders, select the order, and click Cancel Order.",
    "customer_ref": "bob@example.com",
    "feature_name": "Cancel Order",
    "created_at": "2026-09-01T11:00:00Z",
}

REFUND_BOB = {
    "content": "I want to track my refund",
    "category": "REFUND",
    "intent": "track_refund",
    "response": "Go to Refunds and open the refund to see its status.",
    "customer_ref": "bob@example.com",
    "feature_name": "Track Refund",
    "created_at": "2026-09-01T11:00:00Z",
}


class FakeCognee:
    def __init__(self):
        self.calls = []

    def remember(self, text, kind, meta):
        self.calls.append({"text": text, "kind": kind, "meta": meta})


class FakeHydra:
    def __init__(self):
        self.nodes = []
        self.edges = []

    def upsert_node(self, label, key, props):
        self.nodes.append((label, key, props))

    def upsert_edge(self, from_label, from_key, rel, to_label, to_key):
        self.edges.append((from_label, from_key, rel, to_label, to_key))


@pytest.fixture
def db(tmp_path):
    d = LocalDB(path=str(tmp_path / "seed.db"))
    d.init_schema()
    return d


# --- Rule 1 ---

def test_匯入後票單為_resolved_且有解法與時間(db):
    seed(db, rows=[CANCEL_ALICE])
    rows = db.run_sql("SELECT * FROM Ticket ORDER BY id")
    assert len(rows) == 1
    t = rows[0]
    assert t["id"] == 1
    assert t["content"] == "I want to cancel order {{Order Number}}"
    assert t["category"] == "ORDER"
    assert t["customer_ref"] == "alice@example.com"
    assert t["feature_id"] == 1
    assert t["user_problem_id"] == 1
    assert t["status"] == "resolved"
    assert t["resolution_steps"] == "Go to Orders, select the order, and click Cancel Order."
    assert t["created_at"] == "2026-09-01T10:00:00Z"


# --- Rule 2 ---

def test_user_problem_topic_等於_intent(db):
    seed(db, rows=[CANCEL_ALICE])
    rows = db.run_sql("SELECT id, topic, feature_id FROM UserProblem ORDER BY id")
    assert rows == [{"id": 1, "topic": "cancel_order", "feature_id": 1}]


# --- Rule 3 ---

def test_同一_topic_重用同一列_user_problem(db):
    seed(db, rows=[CANCEL_ALICE, CANCEL_BOB])
    ups = db.run_sql("SELECT id, topic, feature_id FROM UserProblem ORDER BY id")
    assert ups == [{"id": 1, "topic": "cancel_order", "feature_id": 1}]
    tickets = db.run_sql("SELECT id, user_problem_id, status FROM Ticket ORDER BY id")
    assert tickets == [
        {"id": 1, "user_problem_id": 1, "status": "resolved"},
        {"id": 2, "user_problem_id": 1, "status": "resolved"},
    ]


# --- Rule 4 ---

def test_同名_feature_重用同一列(db):
    seed(db, rows=[CANCEL_ALICE, CANCEL_BOB])
    rows = db.run_sql("SELECT id, name, status FROM Feature ORDER BY id")
    assert rows == [{"id": 1, "name": "Cancel Order", "status": "active"}]


# --- Rule 5 ---

def test_不同_intent_建立不同_user_problem_與_feature(db):
    seed(db, rows=[CANCEL_ALICE, REFUND_BOB])
    ups = db.run_sql("SELECT id, topic, feature_id FROM UserProblem ORDER BY id")
    assert ups == [
        {"id": 1, "topic": "cancel_order", "feature_id": 1},
        {"id": 2, "topic": "track_refund", "feature_id": 2},
    ]
    feats = db.run_sql("SELECT id, name, status FROM Feature ORDER BY id")
    assert feats == [
        {"id": 1, "name": "Cancel Order", "status": "active"},
        {"id": 2, "name": "Track Refund", "status": "active"},
    ]


# --- 冪等（工程需求，非規格 Rule） ---

def test_重跑不產生重複列(db):
    first = seed(db, rows=[CANCEL_ALICE, CANCEL_BOB, REFUND_BOB])
    second = seed(db, rows=[CANCEL_ALICE, CANCEL_BOB, REFUND_BOB])
    assert first["tickets"] == second["tickets"] == 3
    assert first["user_problems"] == second["user_problems"] == 2
    assert first["features"] == second["features"] == 2
    assert second["inserted_tickets"] == 0
    assert len(db.run_sql("SELECT * FROM Ticket")) == 3


# --- 圖譜層契約 ---

def test_每張票呼叫一次_cognee_remember(db):
    cognee = FakeCognee()
    seed(db, cognee=cognee, rows=[CANCEL_ALICE, CANCEL_BOB, REFUND_BOB])
    assert len(cognee.calls) == 3
    assert {c["kind"] for c in cognee.calls} == {"ticket"}
    assert cognee.calls[0]["meta"]["intent"] == "cancel_order"
    assert cognee.calls[0]["meta"]["ticket_id"] == 1
    assert "Go to Orders" in cognee.calls[0]["text"]


def test_只寫_asks_about_邊(db):
    hydra = FakeHydra()
    seed(db, hydra=hydra, rows=[CANCEL_ALICE, CANCEL_BOB, REFUND_BOB])
    assert {e[2] for e in hydra.edges} == {"asks_about"}
    # 3 Ticket + 2 UserProblem + 2 Feature = 7 個 upsert_node 目標（同一列重複 upsert 也算）
    assert {n[0] for n in hydra.nodes} == {"Ticket", "UserProblem", "Feature"}
    assert len(hydra.edges) == 3
    assert hydra.edges[0] == ("Ticket", {"id": 1}, "asks_about", "Feature", {"name": "Cancel Order"})


def test_圖譜層失敗不擋資料層(db):
    class Broken:
        def remember(self, text, kind, meta):
            raise RuntimeError("cognee down")

        def upsert_node(self, *a, **k):
            raise RuntimeError("hydra down")

        def upsert_edge(self, *a, **k):
            raise RuntimeError("hydra down")

    broken = Broken()
    result = seed(db, cognee=broken, hydra=broken, rows=[CANCEL_ALICE])
    assert result["tickets"] == 1
    assert result["cognee_ok"] is False
    assert result["hydra_ok"] is False
