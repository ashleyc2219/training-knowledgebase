"""O5 probe 的真實帳號整合測試：每個測試各送一個最小的計費 request。

整支標 `aws`；未設 `TKB_RUN_AWS_INTEGRATION=1` 時由 tests/conftest.py 自動跳過。
無權限時不改用預填值頂替，而是明確失敗並在訊息寫 BLOCKED。
"""

import os
import sys
from pathlib import Path

import boto3
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_models import (  # noqa: E402
    EMBEDDING_MODEL_ID,
    PREFERRED_GENERATION,
    SDK_CONFIG,
    ModelProbe,
    probe_candidates,
    probe_embedding,
    resolve_candidates,
)

pytestmark = pytest.mark.aws

REGION = os.environ.get("TKB_BEDROCK_REGION", "us-east-1")


@pytest.fixture(scope="module")
def runtime() -> object:
    return boto3.client("bedrock-runtime", region_name=REGION, config=SDK_CONFIG)


@pytest.fixture(scope="module")
def bedrock() -> object:
    return boto3.client("bedrock", region_name=REGION, config=SDK_CONFIG)


def test_embedding_probe_returns_1024_finite_values(runtime: object) -> None:
    probe = probe_embedding(runtime, EMBEDDING_MODEL_ID, region=REGION)
    assert probe.status == "ok", f"O5 BLOCKED：embedding probe {probe.status}／{probe.detail}"
    assert probe.tokens is not None and probe.tokens > 0
    assert "1024 維" in probe.detail


def test_generation_probe_accepts_fixed_inference_config(
    bedrock: object, runtime: object
) -> None:
    candidates = resolve_candidates(
        bedrock, output_modality="TEXT", preferred=PREFERRED_GENERATION
    )
    assert candidates, "O5 BLOCKED：這個 Region 沒有偏好的生成模型候選（含跨區推論 profile）"
    attempts: list[ModelProbe] = []
    probe = probe_candidates(
        runtime, candidates, purpose="generation", region=REGION, attempts=attempts
    )
    detail = "；".join(f"{a.model_id}={a.status}／{a.detail}" for a in attempts)
    assert probe.status == "ok", f"O5 BLOCKED：generation probe 全數未通過──{detail}"
    assert probe.tokens is not None and probe.tokens > 0
    assert "stopReason=" in probe.detail
