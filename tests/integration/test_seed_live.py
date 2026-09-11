"""真的打外部服務的煙測。沒設定 env 就 skip。

跑法：`uv run pytest -m integration -v`
（預設 `uv run pytest -q` 也會跑，但沒 env 時全部 skip。）
"""

import pytest

from app.config import Settings
from app.ingest.bitext import SEED_PATH
from app.ingest.seed import load_seed, seed
from app.memory.cognee_client import CogneeClient

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings():
    return Settings.from_env()


def test_hotdata_種子六張票(settings):
    if not settings.HOTDATA_DATABASE:
        pytest.skip("沒有 HOTDATA_DATABASE，跳過 hotdata 煙測")
    from app.analytics.hotdata_client import HotdataClient

    db = HotdataClient(settings)
    summary = seed(db, rows=load_seed(SEED_PATH))
    assert summary["tickets"] == 6
    assert summary["user_problems"] == 3
    assert summary["features"] == 3

    rows = db.run_sql("SELECT COUNT(*) AS c FROM Ticket WHERE status = 'resolved'")
    assert rows[0]["c"] == 6


def test_cognee_remember_與_recall(settings):
    if not settings.COGNEE_URL:
        pytest.skip("沒有 COGNEE_URL，跳過 Cognee 煙測")
    cognee = CogneeClient(settings=settings)
    cognee.remember(
        "How do I cancel an order? Go to Orders, select the order, and click Cancel Order.",
        kind="ticket",
        meta={"ticket_id": 1, "intent": "cancel_order"},
    )
    out = cognee.recall("how to cancel order")
    assert isinstance(out, list)
