"""本機 sqlite backend：黑客松沒網路／hotdata 沒接通時的 fallback。

介面與 `HotdataClient` 一致：`init_schema` / `run_sql` / `execute` / `reset`。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from app.analytics.sql import DDL, TABLES

DEFAULT_PATH = ".state/local.db"


class LocalDB:
    """sqlite3 薄封裝，回傳 dict 列。"""

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """建立 9 張表（已存在則略過）。"""
        with self._connect() as conn:
            for ddl in DDL.values():
                conn.execute(ddl)

    def run_sql(self, sql: str, params: Optional[dict[str, Any]] = None) -> list[dict]:
        """跑查詢，回傳 list[dict]。"""
        with self._connect() as conn:
            cur = conn.execute(sql, params or {})
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def execute(self, sql: str, params: Optional[dict[str, Any]] = None) -> int:
        """跑寫入，回傳 lastrowid。"""
        with self._connect() as conn:
            cur = conn.execute(sql, params or {})
            conn.commit()
            return cur.lastrowid or 0

    def reset(self) -> None:
        """刪掉全部表再重建（demo 重置用）。"""
        with self._connect() as conn:
            for table in TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()
        self.init_schema()
