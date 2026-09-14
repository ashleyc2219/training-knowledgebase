"""Bedrock 呼叫的唯一邊界：窄介面、逐次 attempt 追蹤與錯誤分類。

`CallTrace` 只保存 metadata（哪個操作、哪個節點、哪個模型、第幾次、結果），
不保存 prompt 原文、request body 或使用者全文（設計 §14.3、§17.2）。
"""

import json
from collections.abc import Mapping
from typing import Any

from training_kb.errors import PermanentError

# 一筆 trace 的欄位 allowlist：多一個或少一個都是 PermanentError。
TRACE_FIELDS = ("operation_id", "node", "model", "attempt", "kind", "started_at", "outcome")
TRACE_KINDS = frozenset({"embedding", "generation", "tool_use"})
TRACE_OUTCOMES = frozenset({"success", "transient_error", "permanent_error"})


class CallTrace:
    """一次流程裡所有真實 request attempt 的清單；記憶體重用不進來。"""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def add(self, record: Mapping[str, Any]) -> None:
        if set(record) != set(TRACE_FIELDS):
            raise PermanentError(f"call trace fields must be exactly {TRACE_FIELDS}")
        if record["kind"] not in TRACE_KINDS or record["outcome"] not in TRACE_OUTCOMES:
            raise PermanentError(f"unknown kind/outcome: {record['kind']!r} {record['outcome']!r}")
        self._records.append({name: record[name] for name in TRACE_FIELDS})

    def count(self, *, operation_id: str | None = None) -> int:
        return sum(1 for row in self._records
                   if operation_id is None or row["operation_id"] == operation_id)

    def next_attempt(self, *, operation_id: str, node: str) -> int:
        """attempt 依 `(operation_id, node)` 重新起算：換節點就回到 1（Phase 58 靠這個判重試）。"""
        return 1 + sum(1 for row in self._records
                       if row["operation_id"] == operation_id and row["node"] == node)

    def to_json(self) -> str:
        return json.dumps(self._records, ensure_ascii=False, sort_keys=True)
