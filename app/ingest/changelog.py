"""輪詢 changelog 來源，把新列寫進 Release（入庫 ≠ 處理）。

契約見 docs/spec/features/輪詢ReleaseNote.feature 三條 Rule：
1. 只把 created_at **大於**上次檢查時間的列寫入（剛好相等的不寫）。
2. 寫入的 Release `processed_at` 為空。
3. 相同 content + created_at 已存在時不新增列。

cursor 沿用 `app/ingest/poll.py` 的 `.state/last_checked.json`（不落第 10 張表）。
UPDATE / RETIRE 由 `app/agent/release_update.py` 另外處理。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.agent.rules import is_duplicate_release
from app.ingest.poll import load_cursor, save_cursor

SCRIPT_PATH = Path("data/script/changelog.json")

INSERT_RELEASE = """
INSERT INTO Release (content, created_at, processed_at)
VALUES (:content, :created_at, NULL)
"""

EXISTING_RELEASES = "SELECT content, created_at FROM Release"


def now_iso() -> str:
    """UTC ISO 8601（秒級），與規格 Example 的時間字串同形。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_script(path: Path = SCRIPT_PATH) -> list[dict[str, Any]]:
    """讀 demo 用的 changelog 腳本；檔案不存在時回空清單。"""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def poll_changelog(
    db,
    rows: Optional[list[dict[str, Any]]] = None,
    last_checked: Optional[str] = None,
) -> int:
    """輪詢一次 changelog，回傳這次新入庫的 Release 列數。

    `rows` 為 None 時讀 `data/script/changelog.json`；Streamlit 貼上的文字由
    `ingest_release_text` 包成一列傳進來。輪詢後 cursor 前進到這批列的最大 created_at。
    """
    cursor = last_checked if last_checked is not None else load_cursor()
    rows = rows if rows is not None else load_script()

    existing = [(r["content"], r["created_at"]) for r in db.run_sql(EXISTING_RELEASES)]
    inserted = 0
    newest = cursor

    for row in rows:
        content = row["content"]
        created_at = row["created_at"]
        if not created_at > cursor:  # Rule 1：嚴格大於，相等的不寫
            continue
        if is_duplicate_release(content, created_at, existing):  # Rule 3
            continue
        db.execute(INSERT_RELEASE, {"content": content, "created_at": created_at})  # Rule 2
        existing.append((content, created_at))
        inserted += 1
        newest = max(newest, created_at)

    save_cursor(newest)
    return inserted


def ingest_release_text(db, content: str, created_at: Optional[str] = None) -> int:
    """Streamlit 左欄貼一則 Release Note。回傳新列 id；重複則回 0。

    不動 cursor：手貼的時間未必落在輪詢時間軸上，推進 cursor 會誤殺腳本裡的後續列。
    """
    content = content.strip()
    created_at = created_at or now_iso()

    existing = [(r["content"], r["created_at"]) for r in db.run_sql(EXISTING_RELEASES)]
    if is_duplicate_release(content, created_at, existing):  # Rule 3
        return 0

    return db.execute(INSERT_RELEASE, {"content": content, "created_at": created_at})
