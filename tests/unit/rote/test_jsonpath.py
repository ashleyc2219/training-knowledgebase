"""Phase 36 Task 1：可重放 JSONPath 只接受「欄位名」與「非負陣列 index」。

安全子集合的反例一律以 `PermanentError` 結束，**不得**靜默回 `None`：回 `None` 會讓
「欄位不存在」與「欄位的值就是 null」變成同一件事，重放時會悄悄換掉語意（設計 §7.2）。
本檔是純函式測試，不連 AWS、不呼叫模型，所以不標 `aws` marker。
"""

import pytest

from training_kb.adapters import resolve_jsonpath
from training_kb.errors import PermanentError

ROOT = {"event": {"payload": {"issue": {"labels": [{"name": "bug"}], "body": "Button not found"}}},
        "steps": [{"ticket": {"id": "t_gh-acme-app-12"}}]}


def test_resolve_fields_and_array_index() -> None:
    assert resolve_jsonpath(ROOT, "$event.payload.issue.labels[0].name") == "bug"
    assert resolve_jsonpath(ROOT, "$steps[0].ticket.id") == "t_gh-acme-app-12"
    assert resolve_jsonpath(ROOT, "$steps[0]") == {"ticket": {"id": "t_gh-acme-app-12"}}


@pytest.mark.parametrize("path", [
    "$..password", "$event[*]", "$event[?(@.x)]", "$event['payload']",
    "$event.payload.issue.labels[-1]", "$event.payload.issue.labels[0:1]",
    "$event", "$steps", "", "$event.payload.missing", "$steps[9].ticket", "$event.payload[0]",
])
def test_rejects_unsafe_or_missing_paths(path: str) -> None:
    with pytest.raises(PermanentError):
        resolve_jsonpath(ROOT, path)
