"""三條學習指標（features/展示學習指標.feature、showme.md §12）。

分母為 0 一律回 0.0，不抛例外（demo 開場時表是空的）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.analytics.sql import (
    AVG_RATING_CURRENT_VERSION,
    COVERAGE,
    DEFLECTION_RATE,
    REPLAY_RATE,
)


def _div(numerator, denominator) -> float:
    n = float(numerator or 0)
    d = float(denominator or 0)
    return n / d if d else 0.0


def deflection_rate(db) -> float:
    """deflected / (deflected + escalated)。open / resolved 不進分母。"""
    rows = db.run_sql(DEFLECTION_RATE)
    if not rows:
        return 0.0
    return _div(rows[0].get("deflected"), rows[0].get("denominator"))


def replay_rate(db) -> float:
    """SUM(Workflow.replay_count) / COUNT(Ticket.status = 'deflected')。"""
    rows = db.run_sql(REPLAY_RATE)
    if not rows:
        return 0.0
    return _div(rows[0].get("replays"), rows[0].get("deflected"))


def coverage(db) -> float:
    """有 published Tutorial 的 UserProblem 數 / UserProblem 總數。"""
    rows = db.run_sql(COVERAGE)
    if not rows:
        return 0.0
    return _div(rows[0].get("covered"), rows[0].get("total"))


def avg_rating(db, tutorial_id: int) -> float:
    """某 Tutorial 的平均 rating，只算 current_version 那一版。"""
    rows = db.run_sql(AVG_RATING_CURRENT_VERSION, {"tutorial_id": tutorial_id})
    if not rows or rows[0].get("avg_rating") is None:
        return 0.0
    return float(rows[0]["avg_rating"])


# --- 曲線用快照（Phase 4）：append-only 檔案，不落第 10 張業務表 ---

HISTORY_PATH = Path(".state/metrics_history.json")


def snapshot(db, tutorial_id: int = 1) -> dict:
    """取四個數字＋時間戳，給下欄曲線累積一個點。"""
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "deflection_rate": deflection_rate(db),
        "avg_rating": avg_rating(db, tutorial_id),
        "replay_rate": replay_rate(db),
        "coverage": coverage(db),
    }


def load_history(path=HISTORY_PATH) -> list[dict]:
    """讀曲線歷史；檔案不存在或壞掉都回空 list（demo 不因此中斷）。"""
    path = Path(path)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def append_history(point: dict, path=HISTORY_PATH) -> list[dict]:
    """把一個 snapshot 追加進歷史檔，回傳追加後的全部點。"""
    path = Path(path)
    history = load_history(path)
    history.append(point)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return history
