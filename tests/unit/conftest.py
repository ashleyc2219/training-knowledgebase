"""單元測試共用設定：一個不連 Bedrock 的假 Writer。"""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from training_kb.errors import PermanentError

FIXED_EMBEDDING = [0.001] * 1024


class RecordingWriter:
    """實作 Phase 15 的 Writer：回應由測試先排好，呼叫全部記下來。"""

    def __init__(self, *, replies: Sequence[Mapping[str, Any]] = (),
                 tool_plans: Sequence[Mapping[str, Any]] = (),
                 embedding: Sequence[float] = FIXED_EMBEDDING) -> None:
        self.replies = [dict(reply) for reply in replies]
        self.tool_plans = [dict(plan) for plan in tool_plans]
        self.embedding = list(embedding)
        self.calls: list[dict[str, Any]] = []
        self.request_attempts = 0

    def _record(self, kind: str, *, operation_id: str, node: str, **extra: Any) -> None:
        self.request_attempts += 1
        self.calls.append({"kind": kind, "operation_id": operation_id, "node": node, **extra})

    def _next(self, queue: list[dict[str, Any]], name: str) -> dict[str, Any]:
        if not queue:
            raise PermanentError(f"RecordingWriter 沒有排好下一個 {name} 回應")
        return queue.pop(0)

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        self._record("embedding", operation_id=operation_id, node=node, text=text)
        return list(self.embedding)

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self._record("generation", operation_id=operation_id, node=node,
                     system=system, user=user, schema=dict(schema))
        return self._next(self.replies, "generate_json")

    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        self._record("tool_use", operation_id=operation_id, node=node,
                     messages=[dict(message) for message in messages],
                     tools=[dict(tool) for tool in tools])
        return self._next(self.tool_plans, "converse_with_tools")


@pytest.fixture
def fake_writer() -> RecordingWriter:
    return RecordingWriter()
