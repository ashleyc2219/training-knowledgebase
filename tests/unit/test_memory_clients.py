"""Memory 層兩個 client 的單元測試（不打真服務）。

- HydraDBClient：本機 `.state/graph.json` backend、五種邊白名單、兩個固定查詢模板。
- CogneeClient：httpx MockTransport 驗證 remember 的 URL / header / multipart payload。
"""

import httpx
import pytest

from app.errors import OperationFailed
from app.memory.cognee_client import CogneeClient
from app.memory.hydradb_client import ALLOWED_LABELS, ALLOWED_RELS, HydraDBClient


@pytest.fixture
def graph(tmp_path):
    return HydraDBClient(path=str(tmp_path / "graph.json"))


# --- HydraDB 本機 backend ---

def test_upsert_node_冪等(graph):
    graph.upsert_node("Ticket", {"id": 1}, {"status": "resolved"})
    graph.upsert_node("Ticket", {"id": 1}, {"status": "deflected"})
    nodes = graph.nodes("Ticket")
    assert len(nodes) == 1
    assert nodes[0]["props"]["status"] == "deflected"


def test_upsert_edge_冪等且只收五種邊(graph):
    graph.upsert_node("Ticket", {"id": 1}, {})
    graph.upsert_node("Feature", {"name": "Cancel Order"}, {})
    for _ in range(2):
        graph.upsert_edge("Ticket", {"id": 1}, "asks_about", "Feature", {"name": "Cancel Order"})
    assert len(graph.edges("asks_about")) == 1
    assert ALLOWED_RELS == {"asks_about", "explains", "refers_to", "changes", "supersedes"}
    with pytest.raises(OperationFailed):
        graph.upsert_edge("Ticket", {"id": 1}, "mentions", "Feature", {"name": "Cancel Order"})


def test_label_白名單(graph):
    assert "Ticket" in ALLOWED_LABELS
    with pytest.raises(OperationFailed):
        graph.upsert_node("Customer", {"id": 1}, {})


def test_has_published_tutorial(graph):
    assert graph.has_published_tutorial(1) is False
    graph.upsert_node(
        "Tutorial", {"tutorial_id": 1}, {"user_problem_id": 1, "status": "published"}
    )
    assert graph.has_published_tutorial(1) is True
    graph.upsert_node(
        "Tutorial", {"tutorial_id": 2}, {"user_problem_id": 2, "status": "retired"}
    )
    assert graph.has_published_tutorial(2) is False


def test_affected_tutorials_by_release_多跳(graph):
    graph.upsert_node("Release", {"id": 7}, {})
    graph.upsert_node("Feature", {"name": "Cancel Order"}, {})
    graph.upsert_node("Tutorial", {"tutorial_id": 1}, {"path": "tutorials/cancel-order.md"})
    graph.upsert_node("Tutorial", {"tutorial_id": 2}, {"path": "tutorials/track-refund.md"})
    graph.upsert_node("Feature", {"name": "Track Refund"}, {})
    graph.upsert_edge("Release", {"id": 7}, "changes", "Feature", {"name": "Cancel Order"})
    graph.upsert_edge("Tutorial", {"tutorial_id": 1}, "explains", "Feature", {"name": "Cancel Order"})
    graph.upsert_edge("Tutorial", {"tutorial_id": 2}, "explains", "Feature", {"name": "Track Refund"})

    hits = graph.affected_tutorials_by_release(7)
    assert [h["tutorial_id"] for h in hits] == [1]
    assert hits == graph.cypher("affected_by_release", {"release_id": 7})


def test_cypher_只吃具名模板(graph):
    graph.upsert_node("Ticket", {"id": 1}, {})
    graph.upsert_node("Ticket", {"id": 2}, {})
    graph.upsert_node("Feature", {"name": "Cancel Order"}, {})
    graph.upsert_edge("Ticket", {"id": 1}, "asks_about", "Feature", {"name": "Cancel Order"})
    graph.upsert_edge("Ticket", {"id": 2}, "asks_about", "Feature", {"name": "Cancel Order"})

    assert graph.cypher("ping") == [{"ok": 1}]
    assert graph.cypher("tickets_by_feature", {"name": "Cancel Order"}) == [{"c": 2}]
    with pytest.raises(OperationFailed):
        graph.cypher("MATCH (t:Ticket) RETURN t")


def test_graph_檔案跨實例保存(tmp_path):
    path = str(tmp_path / "graph.json")
    a = HydraDBClient(path=path)
    a.upsert_node("Feature", {"name": "Cancel Order"}, {"status": "active"})
    b = HydraDBClient(path=path)
    assert len(b.nodes("Feature")) == 1


# --- Cognee REST ---

def _client(handler, **kw):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return CogneeClient(
        base_url="https://cognee.example",
        api_key="test-key",
        dataset="support_tutorials",
        client=http,
        **kw,
    )


def test_remember_打對端點與_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["api_key"] = request.headers.get("X-Api-Key")
        seen["content_type"] = request.headers.get("Content-Type", "")
        seen["body"] = request.content.decode("utf-8", "replace")
        return httpx.Response(200, json={"status": "ok"})

    cognee = _client(handler)
    cognee.remember("cancel order steps", kind="ticket", meta={"ticket_id": 1})

    assert seen["method"] == "POST"
    assert seen["url"] == "https://cognee.example/api/v1/remember"
    assert seen["api_key"] == "test-key"
    assert seen["content_type"].startswith("multipart/form-data")
    assert "support_tutorials" in seen["body"]
    assert "cancel order steps" in seen["body"]
    assert "ticket_id" in seen["body"]


def test_recall_打_recall_端點():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json=[{"text": "Go to Orders"}])

    cognee = _client(handler)
    out = cognee.recall("how to cancel order")
    assert seen["url"] == "https://cognee.example/api/v1/recall"
    assert "support_tutorials" in seen["body"]
    assert out == [{"text": "Go to Orders"}]


def test_非_2xx_丟_OperationFailed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    cognee = _client(handler)
    with pytest.raises(OperationFailed):
        cognee.remember("x", kind="ticket", meta={})


def test_沒設定_base_url_就丟_OperationFailed():
    from app.config import Settings

    cognee = CogneeClient(settings=Settings())  # 全空的設定＝env 沒填
    with pytest.raises(OperationFailed):
        cognee.remember("x", kind="ticket", meta={})
