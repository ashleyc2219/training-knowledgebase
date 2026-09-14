"""部署前的一次性 Bedrock probe：確認 Region、模型可呼叫性與參數支援（O5 gate）。

這支腳本不進 Lambda runtime。它用 `bedrock` control plane 列候選、用 `bedrock-runtime`
各送一個最小 request，再把結果寫成 O5 報告與 `.env` 片段（片段只印到 stdout）。
"""

from dataclasses import dataclass
from typing import Any, Literal, cast

from botocore.config import Config

ProbeStatus = Literal[
    "ok", "blocked", "unavailable", "param_unsupported", "quota", "retry_later", "unknown",
]

# 設計 §14.3：連線 2 秒、讀取 30 秒；total_max_attempts=1 代表 SDK 完全不重試（只讓一層管理重試）。
SDK_CONFIG = Config(connect_timeout=2, read_timeout=30, retries={"total_max_attempts": 1})

ERROR_STATUS: dict[str, ProbeStatus] = {
    "AccessDeniedException": "blocked",
    "ResourceNotFoundException": "unavailable",
    "ValidationException": "param_unsupported",
    "ThrottlingException": "quota",
    "ServiceQuotaExceededException": "quota",
    "ModelNotReadyException": "retry_later",
    "ModelTimeoutException": "retry_later",
    "ServiceUnavailableException": "retry_later",
}


@dataclass(frozen=True)
class ModelProbe:
    purpose: Literal["embedding", "generation"]
    model_id: str
    region: str
    status: ProbeStatus
    detail: str
    tokens: int | None


def classify_error(error: Exception) -> ProbeStatus:
    """把 botocore 的 Error.Code 對到固定狀態；未知代碼一律 unknown，gate 不通過。"""
    response = getattr(error, "response", None)
    code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
    return ERROR_STATUS.get(code, "unknown")


def list_candidates(bedrock: object, *, output_modality: str) -> tuple[str, ...]:
    """列出這個 Region 可直接 on-demand 呼叫的 ACTIVE 模型 ID。

    `ListFoundationModels` 不會列出跨區推論 profile，所以候選為空時改查
    `list_inference_profiles()`；兩邊都空就回空 tuple，呼叫端據此標 unavailable。
    """
    client = cast(Any, bedrock)
    rows = client.list_foundation_models(byOutputModality=output_modality)["modelSummaries"]
    on_demand = tuple(
        row["modelId"]
        for row in rows
        if "ON_DEMAND" in row.get("inferenceTypesSupported", ())
        and row.get("modelLifecycle", {}).get("status") == "ACTIVE"
    )
    if on_demand:
        return on_demand
    return list_profile_candidates(bedrock)


def list_profile_candidates(bedrock: object) -> tuple[str, ...]:
    """跨區推論 profile 的 ID 清單；`ListFoundationModels` 不會列出它們。"""
    client = cast(Any, bedrock)
    rows = client.list_inference_profiles()["inferenceProfileSummaries"]
    return tuple(row["inferenceProfileId"] for row in rows)
