"""輪詢 cursor（「上次檢查時間」）。

docs/design/showme.md §9 design decision：cursor 存本機檔，不是業務表。
新票輪詢與 changelog 輪詢共用同一支 cursor。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

CURSOR_PATH = Path(".state/last_checked.json")
EPOCH = "1970-01-01T00:00:00Z"


def load_cursor() -> str:
    """回傳上次檢查時間（ISO 8601）；沒有檔案時回 epoch。"""
    if not CURSOR_PATH.exists():
        return EPOCH
    try:
        return json.loads(CURSOR_PATH.read_text(encoding="utf-8")).get("last_checked", EPOCH)
    except (json.JSONDecodeError, OSError):
        return EPOCH


def save_cursor(ts: str) -> None:
    """寫入新的上次檢查時間。"""
    CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    CURSOR_PATH.write_text(json.dumps({"last_checked": ts}, ensure_ascii=False), encoding="utf-8")


# --- Demo 餵票（左欄「餵下一張票」；劇本順序＝陣列順序） ---

DEMO_SCRIPT_PATH = Path("data/script/demo_tickets.json")
DEMO_CURSOR_PATH = Path(".state/demo_cursor.json")
BITEXT_SEED_PATH = Path("data/seed/bitext_seed.json")

# 輪詢新票單.feature：只處理 created_at 嚴格大於上次檢查時間且 status 為 open 的票
SELECT_NEW_OPEN_TICKETS = """
SELECT * FROM Ticket
WHERE status = 'open' AND created_at > :last_checked
ORDER BY created_at, id
"""

INSERT_TICKET = """
INSERT INTO Ticket (content, resolution_steps, category, customer_ref, feature_id,
                    user_problem_id, status, created_at)
VALUES (:content, '', :category, :customer_ref, :feature_id,
        :user_problem_id, 'open', :created_at)
"""


def poll_new_tickets(db, last_checked: Optional[str] = None) -> list[dict]:
    """回傳待處理的票（created_at > cursor 且 status = open）。

    嚴格大於：Example 裡 created_at 剛好等於上次檢查時間的票不處理。
    """
    ts = last_checked if last_checked is not None else load_cursor()
    return db.run_sql(SELECT_NEW_OPEN_TICKETS, {"last_checked": ts})


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def load_demo_cursor() -> int:
    """已餵過幾張劇本票。"""
    data = _read_json(DEMO_CURSOR_PATH, {})
    try:
        return int(data.get("fed", 0))
    except (TypeError, ValueError):
        return 0


def save_demo_cursor(fed: int) -> None:
    DEMO_CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEMO_CURSOR_PATH.write_text(
        json.dumps({"fed": fed}, ensure_ascii=False), encoding="utf-8"
    )


def reset_demo_cursor() -> None:
    """demo 重置：從第一張票重新餵。"""
    DEMO_CURSOR_PATH.unlink(missing_ok=True)


def load_demo_script() -> list[dict]:
    return _read_json(DEMO_SCRIPT_PATH, [])


def peek_next_ticket() -> Optional[dict]:
    """看下一張要餵的劇本票（不推進游標）。"""
    script = load_demo_script()
    fed = load_demo_cursor()
    return script[fed] if fed < len(script) else None


def bitext_response(row: dict) -> str:
    """解法框的預填字串：劇本自帶 bitext_response，否則用同 intent 的種子 resolution_steps。"""
    if row.get("bitext_response"):
        return str(row["bitext_response"])
    intent = row.get("intent")
    if not intent:
        return ""
    for seed in _read_json(BITEXT_SEED_PATH, []):
        if seed.get("intent") == intent and seed.get("resolution_steps"):
            return str(seed["resolution_steps"])
    return ""


def feed_next_ticket(db) -> Optional[dict]:
    """把劇本的下一張票以 status = open 寫進 Ticket；餵完回 None。

    demo 沒有語意分群：劇本的 intent 就是 UserProblem.topic，餵票時直接對好
    user_problem_id / feature_id；intent 為 null（或查無此 topic）時留空，
    交給即時路徑走「自動回覆顧客 Rule 3 → escalated」。
    created_at 用現在時間，確保嚴格大於輪詢 cursor。
    """
    script = load_demo_script()
    fed = load_demo_cursor()
    if fed >= len(script):
        return None
    row = script[fed]

    user_problem_id = None
    feature_id = None
    intent = row.get("intent")
    if intent:
        found = db.run_sql(
            "SELECT id, feature_id FROM UserProblem WHERE topic = :topic",
            {"topic": intent},
        )
        if found:
            user_problem_id = found[0]["id"]
            feature_id = found[0]["feature_id"]
    if feature_id is None and row.get("feature_name"):
        found = db.run_sql(
            "SELECT id FROM Feature WHERE name = :name", {"name": row["feature_name"]}
        )
        if found:
            feature_id = found[0]["id"]

    created_at = _now()
    ticket_id = db.execute(
        INSERT_TICKET,
        {
            "content": row.get("content", ""),
            "category": row.get("category", ""),
            "customer_ref": row.get("customer_ref", ""),
            "feature_id": feature_id,
            "user_problem_id": user_problem_id,
            "created_at": created_at,
        },
    )
    if not ticket_id:  # hotdata backend 不回 lastrowid
        ticket_id = db.run_sql("SELECT MAX(id) AS id FROM Ticket")[0]["id"]
    save_demo_cursor(fed + 1)

    return {
        "ticket_id": ticket_id,
        "seq": fed + 1,
        "total": len(script),
        "content": row.get("content", ""),
        "category": row.get("category", ""),
        "customer_ref": row.get("customer_ref", ""),
        "intent": intent,
        "user_problem_id": user_problem_id,
        "feature_id": feature_id,
        "created_at": created_at,
        "bitext_response": bitext_response(row),
    }


# TODO(Phase 5)：poll_changelog(db) 用 sql.POLL_CHANGELOG 去重後寫 Release（processed_at 空）。
