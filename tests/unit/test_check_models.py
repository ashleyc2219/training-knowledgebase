"""infra/scripts/check_models.py 的單元測試：用假的 boto3 回應形狀驗證候選、body 純度與報告。"""

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

# check_models.py 是部署前的一次性腳本，不在 src/ 的安裝套件裡，所以直接把它的目錄加進路徑。
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_models import (  # noqa: E402
    PREFERRED_GENERATION,
    classify_error,
    list_candidates,
    main,
    probe_embedding,
    probe_generation,
    rank_candidates,
    render_env,
    render_o5_report,
)


class FakeBedrock:
    """只回傳預設好的 modelSummaries／inferenceProfileSummaries。"""

    def __init__(self) -> None:
        self.summaries: list[dict[str, Any]] = []
        self.profiles: list[dict[str, Any]] = []
        self.profile_calls = 0

    def list_foundation_models(self, **kwargs: Any) -> dict[str, Any]:
        return {"modelSummaries": self.summaries}

    def list_inference_profiles(self, **kwargs: Any) -> dict[str, Any]:
        self.profile_calls += 1
        return {"inferenceProfileSummaries": self.profiles}


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": f"{code} happened"}}, "Probe")


def test_candidates_keep_on_demand_active_models_only() -> None:
    fake_bedrock = FakeBedrock()
    live = {"inferenceTypesSupported": ["ON_DEMAND"], "modelLifecycle": {"status": "ACTIVE"}}
    other = {"inferenceTypesSupported": ["PROVISIONED"], "modelLifecycle": {"status": "ACTIVE"}}
    fake_bedrock.summaries = [
        {"modelId": "amazon.titan-embed-text-v2:0", **live},
        {"modelId": "vendor.legacy", **other},
    ]
    assert list_candidates(fake_bedrock, output_modality="EMBEDDING") == (
        "amazon.titan-embed-text-v2:0",
    )
    assert classify_error(client_error("AccessDeniedException")) == "blocked"
    assert classify_error(client_error("SomethingNew")) == "unknown"


def test_candidates_fall_back_to_inference_profiles_when_empty() -> None:
    fake_bedrock = FakeBedrock()
    fake_bedrock.summaries = [
        {
            "modelId": "anthropic.claude-haiku-4-5-20251001-v1:0",
            "inferenceTypesSupported": ["INFERENCE_PROFILE"],
            "modelLifecycle": {"status": "ACTIVE"},
        }
    ]
    fake_bedrock.profiles = [
        {"inferenceProfileId": "us.anthropic.claude-haiku-4-5-20251001-v1:0"},
        {"inferenceProfileId": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
    ]
    assert list_candidates(fake_bedrock, output_modality="TEXT") == (
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
    assert fake_bedrock.profile_calls == 1


def test_candidates_stay_empty_when_both_sources_are_empty() -> None:
    fake_bedrock = FakeBedrock()
    assert list_candidates(fake_bedrock, output_modality="TEXT") == ()


TITAN, REGION = "amazon.titan-embed-text-v2:0", "us-east-1"


class FakeRuntime:
    """模擬 bedrock-runtime：記下最後一次 kwargs，回傳預設好的回應或丟出預設錯誤。"""

    def __init__(self) -> None:
        self.invoke_response: dict[str, Any] = {}
        self.converse_response: dict[str, Any] = {}
        self.error: Exception | None = None
        self.last_kwargs: dict[str, Any] = {}
        self.calls = 0

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        self.last_kwargs, self.calls = kwargs, self.calls + 1
        if self.error is not None:
            raise self.error
        return self.invoke_response

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.last_kwargs, self.calls = kwargs, self.calls + 1
        if self.error is not None:
            raise self.error
        return self.converse_response


def titan_reply(size: int, *, values: list[float] | None = None) -> dict[str, Any]:
    """模擬 boto3 的回應形狀：body 是可 read() 的串流，不是已解析的 dict。"""
    payload = {"embedding": values if values is not None else [0.1] * size,
               "inputTextTokenCount": 8}
    return {"body": io.BytesIO(json.dumps(payload).encode("utf-8"))}


def test_titan_body_is_pure_and_dimension_is_checked() -> None:
    fake_runtime = FakeRuntime()
    fake_runtime.invoke_response = titan_reply(1024)
    good = probe_embedding(fake_runtime, TITAN, region=REGION)
    body = json.loads(fake_runtime.last_kwargs["body"])
    assert set(body) == {"inputText", "dimensions", "normalize"}
    assert (body["dimensions"], good.status, good.tokens) == (1024, "ok", 8)

    fake_runtime.invoke_response = titan_reply(512)
    wrong = probe_embedding(fake_runtime, TITAN, region=REGION)
    assert (wrong.status, "512" in wrong.detail) == ("param_unsupported", True)


def test_titan_rejects_non_finite_values_and_maps_access_denied() -> None:
    fake_runtime = FakeRuntime()
    fake_runtime.invoke_response = titan_reply(1024, values=[float("nan")] + [0.1] * 1023)
    broken = probe_embedding(fake_runtime, TITAN, region=REGION)
    assert broken.status == "param_unsupported"
    assert "有限" in broken.detail

    fake_runtime.error = client_error("AccessDeniedException")
    blocked = probe_embedding(fake_runtime, TITAN, region=REGION)
    assert blocked.status == "blocked"
    assert "AccessDeniedException" in blocked.detail
    assert blocked.tokens is None


def test_generation_config_is_fixed_and_blocked_never_emits_env() -> None:
    fake_runtime = FakeRuntime()
    fake_runtime.converse_response = {
        "output": {"message": {"content": [{"text": "ok"}], "role": "assistant"}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 2},
    }
    good = probe_generation(fake_runtime, "candidate-id", region=REGION)
    assert set(fake_runtime.last_kwargs["inferenceConfig"]) == {"maxTokens", "temperature"}
    assert fake_runtime.last_kwargs["inferenceConfig"]["temperature"] == 0.1
    assert good.status == "ok"
    assert good.detail == "stopReason=end_turn、12 tokens"

    fake_runtime.error = client_error("AccessDeniedException")
    blocked = probe_generation(fake_runtime, "candidate-id", region=REGION)
    assert blocked.status == "blocked"
    assert "TKB_GENERATION_MODEL_ID" not in render_env([blocked])
    assert "BLOCKED" in render_o5_report([blocked], run_id="r1")


def test_rank_candidates_keeps_only_preferred_models_in_preference_order() -> None:
    pool = (
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        "amazon.nova-lite-v1:0",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    )
    assert rank_candidates(pool, preferred=PREFERRED_GENERATION) == (
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
    assert rank_candidates((), preferred=PREFERRED_GENERATION) == ()


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch, bedrock: FakeBedrock, runtime: FakeRuntime
) -> None:
    import check_models

    def fake_client(service: str, **kwargs: Any) -> Any:
        return bedrock if service == "bedrock" else runtime

    monkeypatch.setattr(check_models.boto3, "client", fake_client)
    monkeypatch.setattr(check_models, "account_alias", lambda region: "fake-alias")


def _wire_catalogue(bedrock: FakeBedrock) -> None:
    bedrock.summaries = [
        {
            "modelId": TITAN,
            "inferenceTypesSupported": ["ON_DEMAND"],
            "modelLifecycle": {"status": "ACTIVE"},
        }
    ]
    bedrock.profiles = [{"inferenceProfileId": "us.anthropic.claude-haiku-4-5-20251001-v1:0"}]


def test_main_prints_env_and_returns_zero_when_both_probes_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bedrock, runtime = FakeBedrock(), FakeRuntime()
    _wire_catalogue(bedrock)
    runtime.invoke_response = titan_reply(1024)
    runtime.converse_response = {
        "output": {"message": {"content": [{"text": "ok"}], "role": "assistant"}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 2},
    }
    _install_fakes(monkeypatch, bedrock, runtime)

    code = main(["--region", REGION, "--report-dir", str(tmp_path), "--run-id", "r1"])
    out = capsys.readouterr().out

    assert code == 0
    assert "purpose    | model_id" in out
    assert f"TKB_BEDROCK_REGION={REGION}" in out
    assert f"TKB_EMBEDDING_MODEL_ID={TITAN}" in out
    assert "TKB_GENERATION_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0" in out
    report = (tmp_path / "o5-r1.md").read_text(encoding="utf-8")
    assert report.startswith("# O5 模型可用性報告 r1：PASS")
    assert "fake-alias" in report


def test_main_returns_two_and_hides_generation_id_when_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bedrock, runtime = FakeBedrock(), FakeRuntime()
    _wire_catalogue(bedrock)
    runtime.error = client_error("AccessDeniedException")
    _install_fakes(monkeypatch, bedrock, runtime)

    code = main(["--region", REGION, "--report-dir", str(tmp_path), "--run-id", "r2"])
    out = capsys.readouterr().out

    assert code == 2
    assert "TKB_GENERATION_MODEL_ID" not in out
    assert "TKB_EMBEDDING_MODEL_ID" not in out
    report = (tmp_path / "o5-r2.md").read_text(encoding="utf-8")
    assert "BLOCKED" in report
    assert "AccessDeniedException" in report
    assert "不填猜測值" in report
