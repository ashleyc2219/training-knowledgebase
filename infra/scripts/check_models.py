"""部署前的一次性 Bedrock probe：確認 Region、模型可呼叫性與參數支援（O5 gate）。

這支腳本不進 Lambda runtime。它用 `bedrock` control plane 列候選、用 `bedrock-runtime`
各送一個最小 request，再把結果寫成 O5 報告與 `.env` 片段（片段只印到 stdout）。
"""

import argparse
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import boto3
from botocore.config import Config

EMBEDDING_DIMENSIONS = 1024
# 設計 §17.1：Titan Text Embeddings V2 固定這一個 ID，輸出 1024 維。
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
# probe 是最小計費請求，maxTokens 只要夠回一個詞；temperature 用設計 §14.3 的判斷類低溫。
PROBE_MAX_TOKENS = 16
JUDGEMENT_TEMPERATURE = 0.1

ENV_KEY = {"embedding": "TKB_EMBEDDING_MODEL_ID", "generation": "TKB_GENERATION_MODEL_ID"}
REGION_ENV_KEY = "TKB_BEDROCK_REGION"

# 候選只挑這幾個前綴，依序探測到第一個通過為止：最便宜的 Haiku 4.5 在前，直接 ID 優先於跨區
# 推論 profile。刻意不收 global. 前綴，也刻意不探測目錄裡其他廠牌的模型（每個 probe 都計費）。
PREFERRED_EMBEDDING: tuple[str, ...] = (EMBEDDING_MODEL_ID,)
PREFERRED_GENERATION: tuple[str, ...] = (
    "anthropic.claude-haiku-4-5",
    "us.anthropic.claude-haiku-4-5",
    "anthropic.claude-sonnet-4-5",
    "us.anthropic.claude-sonnet-4-5",
)

REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "plan" / "report"
O5_STOP_SENTENCE = (
    "O5 未通過，本階段標 BLOCKED；`TKB_GENERATION_MODEL_ID` 保持 `<實測通過的 ID>` 佔位，"
    "不填猜測值。"
)

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


_ARN_PATTERN = re.compile(r"arn:[A-Za-z0-9\-:*/_.]+")


def error_detail(error: Exception) -> str:
    """只留錯誤代碼與 SDK 訊息（§6.3）：不貼完整 request／response、憑證或 ARN。"""
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        info = response.get("Error", {})
        code, message = info.get("Code", ""), info.get("Message", "")
        if code:
            return _ARN_PATTERN.sub("<arn>", f"{code}: {message}".strip())
    return _ARN_PATTERN.sub("<arn>", repr(error))


def probe_embedding(runtime: object, model_id: str, *, region: str) -> ModelProbe:
    """送一個最小的 Titan embedding request；body 只放 embedding 參數，不帶生成參數。"""
    client = cast(Any, runtime)
    body = json.dumps(
        {"inputText": "ping", "dimensions": EMBEDDING_DIMENSIONS, "normalize": True}
    )
    try:
        raw = client.invoke_model(modelId=model_id, body=body, contentType="application/json")
        # invoke_model 的回應 body 是 StreamingBody，一定要先 read() 再 json.loads。
        payload = json.loads(raw["body"].read())
    except Exception as error:  # noqa: BLE001 - 任何例外都要分類成 ProbeStatus，不讓腳本中斷
        status = classify_error(error)
        return ModelProbe("embedding", model_id, region, status, error_detail(error), None)
    vector = payload.get("embedding") or []
    tokens = payload.get("inputTextTokenCount")
    size = len(vector)
    if size != EMBEDDING_DIMENSIONS:
        detail = f"回應維度為 {size}，不是 {EMBEDDING_DIMENSIONS}"
        return ModelProbe("embedding", model_id, region, "param_unsupported", detail, tokens)
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
        detail = "回應含非有限數值（NaN／Infinity）"
        return ModelProbe("embedding", model_id, region, "param_unsupported", detail, tokens)
    detail = f"{EMBEDDING_DIMENSIONS} 維、{tokens} tokens"
    return ModelProbe("embedding", model_id, region, "ok", detail, tokens)


def probe_generation(runtime: object, model_id: str, *, region: str) -> ModelProbe:
    """送一個最小的 converse request；生成參數只放 inferenceConfig，且不同時調 topP。"""
    client = cast(Any, runtime)
    try:
        reply = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "ping"}]}],
            system=[{"text": "reply with ok"}],
            inferenceConfig={
                "maxTokens": PROBE_MAX_TOKENS,
                "temperature": JUDGEMENT_TEMPERATURE,
            },
        )
    except Exception as error:  # noqa: BLE001 - 任何例外都要分類成 ProbeStatus，不讓腳本中斷
        status = classify_error(error)
        return ModelProbe("generation", model_id, region, status, error_detail(error), None)
    tokens = reply.get("usage", {}).get("inputTokens")
    detail = f"stopReason={reply.get('stopReason')}、{tokens} tokens"
    return ModelProbe("generation", model_id, region, "ok", detail, tokens)


def render_env(probes: Sequence[ModelProbe]) -> str:
    """`.env` 片段：只輸出實測通過的鍵；沒通過就不印那一行，不填猜測值。"""
    lines = [f"{REGION_ENV_KEY}={probes[0].region}"] if probes else []
    lines += [f"{ENV_KEY[p.purpose]}={p.model_id}" for p in probes if p.status == "ok"]
    return "\n".join(lines) + "\n"


def render_o5_report(probes: Sequence[ModelProbe], *, run_id: str) -> str:
    verdict = "PASS" if probes and all(p.status == "ok" for p in probes) else "BLOCKED"
    rows = [
        f"| {p.purpose} | {p.model_id} | {p.region} | {p.status} | {p.detail} |" for p in probes
    ]
    head = [
        f"# O5 模型可用性報告 {run_id}：{verdict}",
        "",
        "| purpose | model | region | status | detail |",
        "|---|---|---|---|---|",
    ]
    return "\n".join(head + rows) + "\n"


def rank_candidates(candidates: Sequence[str], *, preferred: Sequence[str]) -> tuple[str, ...]:
    """只留下命中 `preferred` 前綴的候選，並依 `preferred` 的順序排列。"""
    ranked: list[tuple[int, int, str]] = []
    for position, candidate in enumerate(candidates):
        for rank, prefix in enumerate(preferred):
            if candidate.startswith(prefix):
                ranked.append((rank, position, candidate))
                break
    return tuple(candidate for _, _, candidate in sorted(ranked))


def resolve_candidates(
    bedrock: object, *, output_modality: str, preferred: Sequence[str]
) -> tuple[str, ...]:
    """先看 on-demand 目錄；挑不到偏好的模型才去查跨區推論 profile。"""
    on_demand = list_candidates(bedrock, output_modality=output_modality)
    ranked = rank_candidates(on_demand, preferred=preferred)
    if ranked:
        return ranked
    return rank_candidates(list_profile_candidates(bedrock), preferred=preferred)


def probe_candidates(
    runtime: object,
    candidates: Sequence[str],
    *,
    purpose: Literal["embedding", "generation"],
    region: str,
    attempts: list[ModelProbe],
) -> ModelProbe:
    """依序探測候選，第一個 ok 就停手；全部失敗時回最後一筆，候選為空回 unavailable。"""
    if not candidates:
        detail = "候選清單為空（含跨區推論 profile），不填猜測 ID"
        return ModelProbe(purpose, "-", region, "unavailable", detail, None)
    prober = probe_embedding if purpose == "embedding" else probe_generation
    last = ModelProbe(purpose, candidates[0], region, "unknown", "尚未執行", None)
    for model_id in candidates:
        last = prober(runtime, model_id, region=region)
        attempts.append(last)
        if last.status == "ok":
            break
    return last


def render_table(probes: Sequence[ModelProbe]) -> str:
    """設計文件 §2 規定的 stdout 表格。"""
    lines = [
        f"{'purpose':<10} | {'model_id':<29} | {'status':<6} | detail",
        "-" * 11 + "+" + "-" * 31 + "+" + "-" * 8 + "+" + "-" * 27,
    ]
    lines += [
        f"{p.purpose:<10} | {p.model_id:<29} | {p.status:<6} | {p.detail}" for p in probes
    ]
    return "\n".join(lines) + "\n"


def account_alias(region: str) -> str:
    """帳號別名；沒有設別名就退回 STS 的帳號號碼。兩者都拿不到就寫「未知」。"""
    try:
        aliases = boto3.client("iam", region_name=region, config=SDK_CONFIG)
        names = aliases.list_account_aliases()["AccountAliases"]
        if names:
            return str(names[0])
    except Exception:  # noqa: BLE001 - 別名只是報告欄位，拿不到不該讓 probe 失敗
        pass
    try:
        sts = boto3.client("sts", region_name=region, config=SDK_CONFIG)
        return f"（無別名；帳號 {sts.get_caller_identity()['Account']}）"
    except Exception:  # noqa: BLE001
        return "未知"


def render_run_context(
    *, region: str, alias: str, run_at: str, attempts: Sequence[ModelProbe], blocked: bool
) -> str:
    """報告固定要記的執行證據：Region、帳號別名、參數、token 數與時間。"""
    lines = [
        "",
        "## 執行環境",
        "",
        f"- Region：`{region}`",
        f"- 帳號別名：{alias}",
        f"- 執行時間（UTC）：{run_at}",
        "- SDK 逾時：connect_timeout=2 秒、read_timeout=30 秒、"
        "retries={'total_max_attempts': 1}（SDK 不重試）",
        "- embedding 參數：`invoke_model` body 只有 "
        f"`inputText`／`dimensions={EMBEDDING_DIMENSIONS}`／`normalize=true`，"
        "不帶 maxTokens／temperature／topP",
        "- generation 參數：`converse` 的 `inferenceConfig` 只有 "
        f"`maxTokens={PROBE_MAX_TOKENS}`／`temperature={JUDGEMENT_TEMPERATURE}`，未設 topP",
        "",
        "## 候選嘗試（每一列都是一次實際計費請求）",
        "",
        "| # | model | status | tokens | detail |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {index} | {p.model_id} | {p.status} | {p.tokens} | {p.detail} |"
        for index, p in enumerate(attempts, start=1)
    ]
    if blocked:
        lines += ["", "## 停止語句", "", O5_STOP_SENTENCE]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bedrock 模型可用性與參數驗證（O5 gate）")
    parser.add_argument("--region", required=True, help="要驗證的 Bedrock Region")
    parser.add_argument("--run-id", default=None, help="報告檔名的 run id，預設為 UTC 時間戳")
    parser.add_argument(
        "--report-dir", default=None, help=f"報告輸出目錄，預設 {REPORT_DIR}"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    region = str(args.region)
    run_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = str(args.run_id) if args.run_id else run_at.replace(":", "").replace("-", "")
    report_dir = Path(args.report_dir) if args.report_dir else REPORT_DIR

    bedrock = boto3.client("bedrock", region_name=region, config=SDK_CONFIG)
    runtime = boto3.client("bedrock-runtime", region_name=region, config=SDK_CONFIG)

    attempts: list[ModelProbe] = []
    probes = [
        probe_candidates(
            runtime,
            resolve_candidates(
                bedrock, output_modality="EMBEDDING", preferred=PREFERRED_EMBEDDING
            ),
            purpose="embedding",
            region=region,
            attempts=attempts,
        ),
        probe_candidates(
            runtime,
            resolve_candidates(bedrock, output_modality="TEXT", preferred=PREFERRED_GENERATION),
            purpose="generation",
            region=region,
            attempts=attempts,
        ),
    ]
    blocked = any(p.status != "ok" for p in probes)

    report = render_o5_report(probes, run_id=run_id) + render_run_context(
        region=region,
        alias=account_alias(region),
        run_at=run_at,
        attempts=attempts,
        blocked=blocked,
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"o5-{run_id}.md"
    report_path.write_text(report, encoding="utf-8")

    print(render_table(probes))
    print(render_env(probes), end="")
    print(f"\n報告：{report_path}")
    return 2 if blocked else 0


if __name__ == "__main__":  # pragma: no cover - 命令列進入點
    raise SystemExit(main())
