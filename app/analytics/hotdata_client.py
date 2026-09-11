"""hotdata.dev backend（Live 分析層）。

以本機 `hotdata` CLI（v0.33.0）subprocess 呼叫，讀寫分兩條路（實測 `--help` 與真跑得到）：

- **讀** `hotdata query "<SQL>" -d <db-id> -o json --no-input`
  回 `{"columns": [...], "rows": [[...]], "row_count": n, ...}`，本模組轉成 `list[dict]`。
  `-d` 只吃 **database id**（`dbid…`），給 name 會回 "Database 'support' not found"。
- **寫** `hotdata databases load --catalog <c> --schema <s> --table <t> --file <json>
  --mode upsert --key <k> --format json --no-input`
  （`hotdata query` 是唯讀入口，不能用 INSERT 灌資料。）

instant database 是 **schema-on-load**：欄位由第一次 load 的內容定型，所以寫入前會照
`app.analytics.sql.DDL` 補齊每一列的所有欄位（沒值填 None）。

查詢時表名要寫三段式 `catalog.schema.table`，`_qualify()` 會把 `sql.py` 裡的裸表名
（`Ticket`、`UserProblem`…）補成 `support.public.Ticket`。hotdata 把表名摺成小寫
（`support.public.ticket`），未加引號的識別字大小寫不敏感，所以直接沿用 `sql.py` 的寫法。
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.analytics.sql import DDL, TABLES
from app.config import Settings
from app.errors import OperationFailed


def _columns_of(table: str) -> list[str]:
    """從 `sql.DDL` 取欄位順序（用 sqlite 解析，不自己寫 parser）。"""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(DDL[table])
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


COLUMNS: dict[str, list[str]] = {t: _columns_of(t) for t in TABLES}

# 宣告過但還沒載入資料的表，`hotdata query` 回這句錯誤而不是空集合。
EMPTY_TABLE_HINT = "is declared but has no data"


def _literal(value: Any) -> str:
    """把 Python 值轉成 SQL 字面值（demo 用；CLI 沒有 bind 參數）。"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _bind(sql: str, params: Optional[dict[str, Any]]) -> str:
    """把 `:name` 具名參數換成字面值。"""
    if not params:
        return sql
    # 長 key 先換，避免 :tutorial 誤吃 :tutorial_id
    for key in sorted(params, key=len, reverse=True):
        sql = sql.replace(f":{key}", _literal(params[key]))
    return sql


class HotdataClient:
    """呼叫 `hotdata` CLI 的 backend。介面與 `LocalDB` 一致，另加 `load_rows`。"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings.from_env()
        self.database = self.settings.HOTDATA_DATABASE
        self.catalog = self.settings.HOTDATA_CATALOG
        self.schema = self.settings.HOTDATA_SCHEMA

    # --- 表名三段式 ---

    def qualify(self, table: str) -> str:
        return f"{self.catalog}.{self.schema}.{table}"

    def _qualify(self, sql: str) -> str:
        """把裸表名補成 `catalog.schema.table`（已經有前綴的不動）。"""
        for table in TABLES:
            sql = re.sub(
                rf"(?<![.\w]){re.escape(table)}\b",
                self.qualify(table),
                sql,
            )
        return sql

    # --- 讀 ---

    def _run_cli(self, cmd: list[str], what: str, empty_ok: bool = False) -> str:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 or out.startswith("error"):
            message = (proc.stderr or out)[:300]
            # 已宣告但還沒 load 過的表，hotdata 會報錯而不是回空集合；對呼叫端而言就是「沒有列」。
            if empty_ok and EMPTY_TABLE_HINT in message:
                return ""
            raise OperationFailed(f"{what} 失敗（exit {proc.returncode}）：{message}")
        return out

    def run_sql(self, sql: str, params: Optional[dict[str, Any]] = None) -> list[dict]:
        """跑查詢，回傳 list[dict]。"""
        if not self.database:
            raise OperationFailed("沒有設定 HOTDATA_DATABASE（instant database id）")
        statement = self._qualify(_bind(sql, params))
        cmd = ["hotdata", "query", statement, "-d", self.database, "-o", "json", "--no-input"]
        if self.settings.HOTDATA_API_KEY:
            cmd += ["--api-key", self.settings.HOTDATA_API_KEY]
        out = self._run_cli(cmd, "hotdata query", empty_ok=True)
        if not out:
            return []
        try:
            data = json.loads(out)
        except ValueError as exc:
            # CLI 用彩色文字回報錯誤（例如 Database not found），不是 JSON
            raise OperationFailed(f"hotdata query 回傳不是 JSON：{out[:300]}") from exc
        columns = data.get("columns") or []
        return [dict(zip(columns, row)) for row in data.get("rows") or []]

    # --- 寫 ---

    def load_rows(
        self,
        table: str,
        rows: list[dict],
        key: Optional[list[str]] = None,
        mode: str = "upsert",
    ) -> None:
        """upsert 一批列（schema-on-load，所以先照 DDL 補齊欄位）。"""
        if not rows:
            return
        cols = COLUMNS.get(table)
        if cols is None:
            raise OperationFailed(f"未知的表：{table}")
        payload = [{c: row.get(c) for c in cols} for row in rows]
        keys = key or ["id"]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{table}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            cmd = [
                "hotdata", "databases", "load",
                "--catalog", self.catalog,
                "--schema", self.schema,
                "--table", table,
                "--file", str(path),
                "--mode", mode,
                "--format", "json",
                "--no-input",
            ]
            for k in keys:
                cmd += ["--key", k]
            if self.settings.HOTDATA_API_KEY:
                cmd += ["--api-key", self.settings.HOTDATA_API_KEY]
            self._run_cli(cmd, f"hotdata databases load {table}")

    def execute(self, sql: str, params: Optional[dict[str, Any]] = None) -> int:
        """hotdata 的 query 入口唯讀，寫入請用 `load_rows`。"""
        raise OperationFailed(
            "hotdata backend 不支援 execute（`hotdata query` 是唯讀入口）；請改用 load_rows()"
        )

    def init_schema(self) -> None:
        """no-op：instant database 的 9 表用 `hotdata databases tables add` 宣告過了，

        欄位在第一次 `load_rows` 時由內容定型（schema-on-load）。
        """

    def reset(self) -> None:
        raise NotImplementedError("hotdata backend 不提供 reset；請在 hotdata console 重建 database")
