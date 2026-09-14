"""infra/scripts/check_models.py 的單元測試：用假的 boto3 回應形狀驗證候選、body 純度與報告。"""

import sys
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

# check_models.py 是部署前的一次性腳本，不在 src/ 的安裝套件裡，所以直接把它的目錄加進路徑。
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_models import classify_error, list_candidates  # noqa: E402


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
