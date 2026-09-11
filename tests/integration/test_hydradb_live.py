"""HydraDB Cloud live 測試：沒有 HYDRADB_URI 就 skip。ingest 是非同步，只驗到 indexing 進入終態。"""

from __future__ import annotations

import os
import time

import httpx
import pytest
from dotenv import load_dotenv

from app.config import Settings
from app.memory.hydradb_client import HydraDBClient

pytestmark = pytest.mark.integration

load_dotenv(".env")


@pytest.fixture
def live(tmp_path):
    if not os.getenv("HYDRADB_URI") or not os.getenv("HYDRADB_APIKEY"):
        pytest.skip("HYDRADB_URI / HYDRADB_APIKEY 未設定")
    s = Settings.from_env()
    s.HYDRADB_COLLECTION = "smoke"
    return HydraDBClient(path=str(tmp_path / "graph.json"), settings=s)


def test_hydradb_database_已就緒(live):
    st = live.remote_status()
    assert st["backend"] == "hydradb"
    assert st.get("ready_for_ingestion") is True


def test_hydradb_節點與邊_ingest_進入終態(live):
    live.upsert_node("Tutorial", {"tutorial_id": 999}, {"status": "published", "topic": "cancel_order"})
    live.upsert_node("Feature", {"name": "Cancel Order"}, {"id": 999, "status": "active"})
    live.upsert_edge("Tutorial", {"tutorial_id": 999}, "explains", "Feature", {"name": "Cancel Order"})
    assert live.mirrored == 3, live.last_error

    # 等 HydraDB 索引（最多 90 秒）；只驗「不是 errored」，relations 抽取內容不在規格內
    client = live._client()
    deadline = time.time() + 90
    states = set()
    while time.time() < deadline:
        r = client.get("/context/status", params={"database": live.database, "collection": "smoke"})
        statuses = (r.json().get("data") or {}).get("statuses") or []
        states = {s.get("indexing_status") for s in statuses}
        if states and states <= {"completed", "errored"}:
            break
        time.sleep(5)
    assert "errored" not in states, statuses
