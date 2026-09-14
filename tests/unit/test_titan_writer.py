import io
import json
from typing import Any

import pytest

from training_kb.errors import PermanentError
from training_kb.writing.client import TITAN_DIMENSIONS, BedrockWriter, CallTrace, Writer


class FakeTitanClient:          # 回應形狀與真實 invoke_model 一致：body 只能讀一次
    def __init__(self, embedding: object) -> None:
        self.embedding: object = embedding
        self.json_body: dict[str, Any] | None = None
        self.calls = 0

    def invoke_model(self, *, modelId: str, body: str) -> dict[str, Any]:
        self.calls += 1
        self.json_body = json.loads(body)
        payload = {"embedding": self.embedding, "inputTextTokenCount": 3}
        return {"body": io.BytesIO(json.dumps(payload).encode())}


def make_writer(client: object) -> BedrockWriter:
    return BedrockWriter(client, CallTrace(), generation_model_id=None,
                         embedding_model_id="amazon.titan-embed-text-v2:0")


def test_titan_request_has_only_embedding_fields_and_one_attempt() -> None:
    client = FakeTitanClient([0.0] * 1023 + [1.0])
    writer = make_writer(client)
    vector = writer.embed("prepare meeting", operation_id="op-e", node="embed")
    assert client.json_body == {"inputText": "prepare meeting", "dimensions": 1024,
                                "normalize": True}
    assert {"maxTokens", "temperature", "topP"}.isdisjoint(client.json_body)
    assert len(vector) == 1024 and vector[1023] == 1.0
    assert writer.trace.count(operation_id="op-e") == 1
    assert json.loads(writer.trace.to_json())[0]["kind"] == "embedding"


@pytest.mark.parametrize("embedding", [
    [0.0] * 1023,
    [0.0] * 1025,
    [0.0] * 1023 + [float("nan")],
    [0.0] * 1023 + [float("inf")],
    [0.0] * 1023 + [True],
    [0.0] * 1023 + ["1.0"],
    {"not": "a list"},
])
def test_embed_rejects_wrong_dimension_or_non_finite(embedding: object) -> None:
    writer = make_writer(FakeTitanClient(embedding))
    with pytest.raises(PermanentError):
        writer.embed("meeting summary", operation_id="op-e", node="embed")


def test_embed_refuses_blank_text_without_calling_titan() -> None:
    client = FakeTitanClient([0.0] * 1024)
    writer = make_writer(client)
    with pytest.raises(PermanentError):
        writer.embed("   ", operation_id="op-e", node="embed")
    assert client.calls == 0 and writer.trace.count() == 0


def test_bedrock_writer_satisfies_the_writer_protocol() -> None:
    """補上 embed 之後 BedrockWriter 才完整實作 Writer；這一行由 mypy 檢查形狀。"""
    client = FakeTitanClient([0.0] * TITAN_DIMENSIONS)
    writer: Writer = BedrockWriter(client, CallTrace(), generation_model_id=None,
                                   embedding_model_id="amazon.titan-embed-text-v2:0")
    assert len(writer.embed("protocol", operation_id="op-p", node="embed")) == TITAN_DIMENSIONS
