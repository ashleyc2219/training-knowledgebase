"""HydraDB Cloud backend（write-through 鏡射）：用 httpx.MockTransport，不打網路。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.memory.hydradb_client import HydraDBClient


def _settings():
    return Settings(HYDRADB_URI="https://hydra.test", HYDRADB_APIKEY="sk.test",
                    HYDRADB_DATABASE="support_tutorials", HYDRADB_COLLECTION="graph")


@pytest.fixture
def captured():
    return []


def _client(tmp_path, captured, status=202, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = body if body is not None else {"success": True, "data": {"results": [{"id": "abc"}]}}
        return httpx.Response(status, json=payload)

    return HydraDBClient(path=str(tmp_path / "graph.json"), settings=_settings(),
                         transport=httpx.MockTransport(handler))


def _form(request: httpx.Request) -> dict:
    """httpx 對 data= 送 application/x-www-form-urlencoded（HydraDB 實測接受）。"""
    from urllib.parse import parse_qs

    qs = parse_qs(request.content.decode("utf-8"))
    out = {k: v[0] for k, v in qs.items()}
    if "memories" in out:
        out["memories"] = json.loads(out["memories"])
    return out


def test_upsert_node_本機永遠寫且鏡射成_memory_ingest(tmp_path, captured):
    g = _client(tmp_path, captured)
    g.upsert_node("Feature", {"name": "Cancel Order"}, {"id": 1, "status": "active"})

    assert len(g.nodes("Feature")) == 1  # 本機索引
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST" and req.url.path == "/context/ingest"
    assert req.headers["Authorization"] == "Bearer sk.test"
    assert req.headers["API-Version"] == "2"
    form = _form(req)
    assert form["type"] == "memory" and form["database"] == "support_tutorials" and form["collection"] == "graph"
    assert form["upsert"] == "true"
    assert "Feature" in form["memories"][0]["text"] and "Cancel Order" in form["memories"][0]["text"]
    assert form["memories"][0]["metadata"]["kind"] == "node"
    assert g.mirrored == 1


def test_upsert_edge_鏡射文字含關係名(tmp_path, captured):
    g = _client(tmp_path, captured)
    g.upsert_node("Tutorial", {"tutorial_id": 1}, {})
    g.upsert_node("Feature", {"name": "Cancel Order"}, {})
    captured.clear()
    g.upsert_edge("Tutorial", {"tutorial_id": 1}, "explains", "Feature", {"name": "Cancel Order"})

    form = _form(captured[0])
    text = form["memories"][0]["text"]
    assert "Tutorial" in text and "explains" in text and "Cancel Order" in text
    assert form["memories"][0]["metadata"] == {"kind": "edge", "rel": "explains", "from": "Tutorial", "to": "Feature"}
    assert len(g.edges("explains")) == 1


def test_hydradb_失敗不外拋且本機仍寫入(tmp_path, captured):
    g = _client(tmp_path, captured, status=500, body={"success": False, "error": "boom"})
    g.upsert_node("Ticket", {"id": 1}, {"status": "resolved"})

    assert len(g.nodes("Ticket")) == 1
    assert g.mirrored == 0
    assert g.last_error and "500" in g.last_error


def test_recall_走_query_端點(tmp_path, captured):
    body = {"success": True, "data": {"chunks": [{"chunk_content": "Tutorial explains Cancel Order"}], "graph": {"paths": []}}}
    g = _client(tmp_path, captured, status=200, body=body)
    out = g.recall("which tutorial explains Cancel Order", top_k=3)

    req = captured[-1]
    assert req.method == "POST" and req.url.path == "/query"
    sent = json.loads(req.content)
    assert sent["database"] == "support_tutorials" and sent["type"] == "memory" and sent["max_results"] == 3
    assert sent["graph_context"] is True
    assert out["chunks"][0]["chunk_content"].startswith("Tutorial")
    assert out["error"] is None


def test_relations_走_context_relations(tmp_path, captured):
    body = {"success": True, "data": {"relations": [{"source": "Tutorial", "target": "Cancel Order"}]}}
    g = _client(tmp_path, captured, status=200, body=body)
    rels = g.relations(limit=10)

    req = captured[-1]
    assert req.method == "GET" and req.url.path == "/context/relations"
    assert req.url.params["database"] == "support_tutorials" and req.url.params["type"] == "memory"
    assert rels and rels[0]["target"] == "Cancel Order"


def test_沒有_uri_時完全不打_http(tmp_path, captured):
    g = HydraDBClient(path=str(tmp_path / "graph.json"), settings=Settings(HYDRADB_URI=None),
                      transport=httpx.MockTransport(lambda r: captured.append(r) or httpx.Response(200)))
    g.upsert_node("Ticket", {"id": 1}, {})
    assert captured == []
    assert g.recall("x")["chunks"] == [] and g.relations() == []
