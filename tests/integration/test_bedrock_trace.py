import json
import os

import pytest

from training_kb.writing.client import TRACE_FIELDS, BedrockWriter, CallTrace, build_bedrock_client

pytestmark = pytest.mark.aws      # Phase 01 conftest：TKB_RUN_AWS_INTEGRATION != "1" 時自動 skip


def test_real_request_creates_exactly_one_attempt() -> None:
    trace = CallTrace()
    writer = BedrockWriter(build_bedrock_client(os.environ["TKB_BEDROCK_REGION"]), trace,
                           generation_model_id=os.environ["TKB_GENERATION_MODEL_ID"],
                           embedding_model_id=os.environ["TKB_EMBEDDING_MODEL_ID"])
    result = writer.generate_json("只輸出一個 JSON 物件，不要其他文字。", '請輸出 {"ok": true}',
                                  {"type": "object"}, operation_id="smoke-writer", node="smoke")
    rows = json.loads(trace.to_json())
    assert isinstance(result, dict) and len(rows) == 1
    assert rows[0]["attempt"] == 1 and rows[0]["outcome"] == "success"
    assert set(rows[0]) == set(TRACE_FIELDS)
