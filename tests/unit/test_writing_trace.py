import json

import pytest

from training_kb.errors import PermanentError
from training_kb.writing.client import TRACE_FIELDS, CallTrace

ROW = {"operation_id": "op-17", "node": "name_gap", "model": "verified-model", "attempt": 1,
       "kind": "generation", "started_at": "2026-09-13T00:00:00Z", "outcome": "transient_error"}


def test_trace_counts_attempts_and_keeps_only_fixed_fields() -> None:
    trace = CallTrace()
    trace.add(ROW)
    trace.add({**ROW, "attempt": 2, "outcome": "success"})
    assert trace.count(operation_id="op-17") == 2 and trace.count() == 2
    assert trace.count(operation_id="op-other") == 0
    assert [set(row) for row in json.loads(trace.to_json())] == [set(TRACE_FIELDS)] * 2
    assert trace.next_attempt(operation_id="op-17", node="name_gap") == 3
    assert trace.next_attempt(operation_id="op-17", node="draft") == 1


@pytest.mark.parametrize("bad", [
    {**ROW, "prompt": "secret prompt"},
    {key: value for key, value in ROW.items() if key != "outcome"},
    {**ROW, "outcome": "maybe"},
    {**ROW, "kind": "chat"},
])
def test_trace_rejects_extra_missing_or_unknown_values(bad: dict) -> None:
    trace = CallTrace()
    with pytest.raises(PermanentError):
        trace.add(bad)
    assert trace.count() == 0
