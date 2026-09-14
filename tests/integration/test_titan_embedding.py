import math
import os

import pytest

from training_kb.vectors import cosine
from training_kb.writing.client import BedrockWriter, CallTrace, build_bedrock_client

pytestmark = pytest.mark.aws      # Phase 01 conftest：TKB_RUN_AWS_INTEGRATION != "1" 時自動 skip


def test_real_titan_returns_1024_finite_values() -> None:
    trace = CallTrace()
    writer = BedrockWriter(build_bedrock_client(os.environ["TKB_BEDROCK_REGION"]), trace,
                           generation_model_id=None,
                           embedding_model_id=os.environ["TKB_EMBEDDING_MODEL_ID"])
    first = writer.embed("會前摘要在哪裡開啟？", operation_id="smoke-titan", node="embed")
    second = writer.embed("如何看到開會前整理的重點？", operation_id="smoke-titan", node="embed")
    assert len(first) == len(second) == 1024
    assert all(math.isfinite(value) for value in first)
    assert -1.0 <= cosine(first, second) <= 1.0
    assert trace.count(operation_id="smoke-titan") == 2
