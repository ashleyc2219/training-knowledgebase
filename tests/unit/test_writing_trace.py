import json
from typing import Any

import pytest
from botocore.exceptions import ClientError

from training_kb.errors import PermanentError, TransientError
from training_kb.writing.client import TRACE_FIELDS, BedrockWriter, CallTrace, bedrock_config

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


class FakeConverseClient:
    def __init__(self, *answers: object) -> None:
        self.answers, self.requests = list(answers), []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"output": {"message": {"content": [{"text": json.dumps(answer)}]}}}


def make_writer(client: object) -> BedrockWriter:
    return BedrockWriter(client, CallTrace(), generation_model_id="verified-model",
                         embedding_model_id="amazon.titan-embed-text-v2:0")


def test_one_sdk_request_creates_one_attempt_per_node() -> None:
    client = FakeConverseClient({"answer": "ok"}, {"answer": "next"})
    writer = make_writer(client)
    first = writer.generate_json("system", "user", {"type": "object"},
                                 operation_id="op-1", node="name_gap")
    writer.generate_json("system", "user", {"type": "object"}, operation_id="op-1", node="draft")
    assert first == {"answer": "ok"}
    assert len(client.requests) == writer.trace.count(operation_id="op-1") == 2
    assert client.requests[0]["inferenceConfig"] == {"maxTokens": 512, "temperature": 0.1}
    assert [row["attempt"] for row in json.loads(writer.trace.to_json())] == [1, 1]


@pytest.mark.parametrize(("code", "raised", "outcome"), [
    ("ThrottlingException", TransientError, "transient_error"),
    ("ValidationException", PermanentError, "permanent_error"),
])
def test_sdk_failure_is_traced_and_classified(code, raised, outcome) -> None:
    error = ClientError({"Error": {"Code": code, "Message": "回聲了使用者輸入"}}, "Converse")
    writer = make_writer(FakeConverseClient(error))
    with pytest.raises(raised):
        writer.generate_json("s", "u", {}, operation_id="op-1", node="draft")
    rows = json.loads(writer.trace.to_json())
    assert len(rows) == 1 and rows[0]["outcome"] == outcome and rows[0]["attempt"] == 1
    assert "回聲" not in writer.trace.to_json()


def test_config_has_one_retry_layer_and_saved_output_adds_no_attempt() -> None:
    config = bedrock_config()
    assert config.retries == {"total_max_attempts": 1}
    assert config.connect_timeout == 2 and config.read_timeout == 30
    client = FakeConverseClient({"gap": "找不到 Prepare 按鈕"})
    writer = make_writer(client)
    first = writer.generate_json("s", "u", {}, operation_id="op-retry", node="name_gap")
    saved = json.dumps(first)            # Phase 10 會寫到 operations/op-retry/gap-naming.json
    assert json.loads(saved) == first    # 儲存重送只讀檔，不再進 Writer
    assert writer.trace.count(operation_id="op-retry") == 1 and len(client.requests) == 1
