"""Bedrock 呼叫的唯一邊界：窄介面、逐次 attempt 追蹤與錯誤分類。

`CallTrace` 只保存 metadata（哪個操作、哪個節點、哪個模型、第幾次、結果），
不保存 prompt 原文、request body 或使用者全文（設計 §14.3、§17.2）。
`BedrockWriter` 的每個 public method 都只經過一個 `_request_once`：內部沒有迴圈，
SDK 也關掉自動重試，讓「只有一層管理重試」成立。
"""

import json
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError
from jsonschema.exceptions import ValidationError

from training_kb.clock import now_utc, to_iso
from training_kb.errors import ContentError, PermanentError, TransientError
from training_kb.writing.schemas import validate_schema
from training_kb.writing.validators import BusinessValidator

# 一筆 trace 的欄位 allowlist：多一個或少一個都是 PermanentError。
TRACE_FIELDS = ("operation_id", "node", "model", "attempt", "kind", "started_at", "outcome")
TRACE_KINDS = frozenset({"embedding", "generation", "tool_use"})
TRACE_OUTCOMES = frozenset({"success", "transient_error", "permanent_error"})

# 設計 §14.3 的判斷類起點：只設 maxTokens 與低 temperature，不同時調 topP。
# 每個生成 request 的 inferenceConfig 都由 inference_config(schema) 產出，這是它的底稿。
JUDGEMENT_INFERENCE_CONFIG: dict[str, object] = {"maxTokens": 512, "temperature": 0.1}

# 教學寫作類的唯一例外（設計 §14.3、00A §3.7）：其餘七個 schema 都留在判斷類的 512。
# 截斷（`stopReason == "max_tokens"`）一律是驗證失敗，不靠調高上限救，見 `_parse_schema_json`。
WRITING_MAX_TOKENS: dict[str, int] = {"TutorialDraft": 2048}

# 「向量幾維」這個數字的唯一一份（00A §5.4）：送出的 body 與收回的回應都拿它比。
TITAN_DIMENSIONS = 1024

TIMEOUT_ERRORS = (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError)
TRANSIENT_ERROR_CODES = frozenset({
    "ThrottlingException", "ServiceQuotaExceededException", "ModelNotReadyException",
    "ModelTimeoutException", "ServiceUnavailableException", "InternalServerException"})


class Writer(Protocol):
    """所有需要模型的 Phase 共用的窄介面；正式實作是 `BedrockWriter`，測試用 `RecordingWriter`。"""

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]: ...

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]: ...

    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]: ...


class CallTrace:
    """一次流程裡所有真實 request attempt 的清單；記憶體重用不進來。"""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def add(self, record: Mapping[str, Any]) -> None:
        if set(record) != set(TRACE_FIELDS):
            raise PermanentError(f"call trace fields must be exactly {TRACE_FIELDS}")
        if record["kind"] not in TRACE_KINDS or record["outcome"] not in TRACE_OUTCOMES:
            raise PermanentError(f"unknown kind/outcome: {record['kind']!r} {record['outcome']!r}")
        self._records.append({name: record[name] for name in TRACE_FIELDS})

    def count(self, *, operation_id: str | None = None) -> int:
        return sum(1 for row in self._records
                   if operation_id is None or row["operation_id"] == operation_id)

    def next_attempt(self, *, operation_id: str, node: str) -> int:
        """attempt 依 `(operation_id, node)` 重新起算：換節點就回到 1（Phase 58 靠這個判重試）。"""
        return 1 + sum(1 for row in self._records
                       if row["operation_id"] == operation_id and row["node"] == node)

    def to_json(self) -> str:
        return json.dumps(self._records, ensure_ascii=False, sort_keys=True)


def bedrock_config() -> Config:
    """全套唯一一份 Bedrock SDK 設定：連線 2 秒、等待 30 秒、SDK 這一層不重試。"""
    return Config(connect_timeout=2, read_timeout=30, retries={"total_max_attempts": 1})


def inference_config(schema: Mapping[str, Any]) -> dict[str, object]:
    """依 schema 的 `$id` 決定這次生成的 `inferenceConfig`：教學寫作 2048，其餘判斷類 512。

    吃的是 **schema dict 而不是節點名字**（00A §6.5）：節點會增加，schema 只有八個，
    用 `$id` 查表才不會有節點漏設 `maxTokens`。`temperature` 一律 0.1，而且永遠不設
    `topP`——同時調兩個取樣參數會互相干擾（設計 §14.3）。
    `$id` 缺席（測試用的裸 `{"type": "object"}`）時走判斷類預設，不丟例外。
    """
    config = dict(JUDGEMENT_INFERENCE_CONFIG)
    name = str(schema.get("$id", ""))
    if name in WRITING_MAX_TOKENS:
        config["maxTokens"] = WRITING_MAX_TOKENS[name]
    return config


def build_bedrock_client(region: str) -> Any:
    return boto3.client("bedrock-runtime", region_name=region, config=bedrock_config())


def _error_code(error: BaseException) -> str:
    """只取 botocore 的 Error.Code；Message 可能回聲使用者輸入，一律不取。"""
    response = getattr(error, "response", None)
    body = response.get("Error", {}) if isinstance(response, Mapping) else {}
    return str(body.get("Code", "")) if isinstance(body, Mapping) else ""


def _validated_embedding(value: object) -> list[float]:
    """Titan 回應的唯一出口檢查：長度必須是 1024，每個元素必須是有限的 int／float。

    `bool` 要先擋：`True` 是 `int` 的子型別，`isinstance(True, (int, float))` 與
    `math.isfinite(True)` 都成立。`NaN` 更要擋——它不會讓程式爆炸，只會讓 Phase 38 的
    `>= 0.85` 永遠 `False`，安靜地多開一個 cluster。
    """
    if not isinstance(value, list) or len(value) != TITAN_DIMENSIONS:
        raise PermanentError(f"Titan embedding must contain {TITAN_DIMENSIONS} values")
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise PermanentError(f"Titan embedding contains a non-numeric value: {item!r}")
        if not math.isfinite(item):
            raise PermanentError(f"Titan embedding contains a non-finite value: {item!r}")
    return [float(item) for item in value]


def _parse_schema_json(raw: str, schema: Mapping[str, Any], *, stop_reason: str) -> dict[str, Any]:
    """Claude response 的唯一出口檢查：截斷與 schema 都只在這裡判一次。

    `stopReason == "max_tokens"` 代表輸出被 token 上限切斷，內容不完整（設計 §14.3：
    截斷即驗證失敗、不發布）；欄位缺席時當成沒有截斷。錯誤訊息只帶 schema 的 `$id`，
    **不回印 response 內容**：那段文字可能整段回聲了不可信的來源資料（00A §3.8）。
    """
    name = str(schema.get("$id", "model"))
    if stop_reason == "max_tokens":
        raise PermanentError(f"{name} response truncated by maxTokens")
    try:
        value = json.loads(raw)
        validate_schema(schema, value)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise PermanentError(f"invalid {name} response") from exc
    if not isinstance(value, dict):
        raise PermanentError(f"invalid {name} response: not a JSON object")
    return value


# 修正 prompt 的固定形狀：`{code}` 只放 validator 的 `<代碼>: <欄位路徑>`，
# 不放模型輸出、不放 `<source_data>` 裡的不可信原文（設計 §14.3、00A §3.8）。
CORRECTION_TEMPLATE = ("{user}\n<validation_error>{code}</validation_error>\n"
                       "只修正上述違規，其餘逐字保留。")


def generate_validated_json(writer: Writer, system: str, user: str,
                            schema: Mapping[str, Any], validate: BusinessValidator, *,
                            operation_id: str, node: str) -> dict[str, Any]:
    """schema 合法之後再過業務 validator；不合法就**只**修正一次，仍不合法即確定失敗。

    這是固定演算法而不是迴圈：first + second 共兩次 request，第三次不存在（設計 §14.3）。

    **這是唯一合法的修正迴圈入口**（00A §6.5）：需要業務驗證的節點呼叫它**一次**，
    不自己包重試、也不自己再組一次修正 prompt。公開它是為了讓 P39–P51 有一份共用實作，
    不是為了讓呼叫端拆開來重排——「最多一次修正」這個上限只在這支函式裡成立。

    `TransientError`（節流、逾時、服務故障）**不進** `except`：它不是業務問題，重送有機會
    成功，交給 Phase 29 的單層 ASL Task Retry，也因此不消耗這一次修正預算。
    """
    first = writer.generate_json(system, user, schema, operation_id=operation_id, node=node)
    try:
        validate(first)
    except ContentError as exc:
        correction = CORRECTION_TEMPLATE.format(user=user, code=exc)
    else:
        return first
    second = writer.generate_json(system, correction, schema,
                                  operation_id=operation_id, node=node)
    try:
        validate(second)
    except ContentError as exc:
        raise PermanentError(f"business-invalid after one correction: {exc}") from exc
    return second


class BedrockWriter:
    """`Writer` 的正式實作：只封裝 Bedrock 請求與解析，不碰 DynamoDB、S3 或發布。"""

    def __init__(self, client: Any, trace: CallTrace, *,
                 generation_model_id: str | None, embedding_model_id: str) -> None:
        self.client, self.trace = client, trace
        self._gen_id, self._embed_id = generation_model_id, embedding_model_id

    def _gen_model(self) -> str:
        if not self._gen_id:
            raise PermanentError("O5 尚未通過：generation_model_id 還沒有實測值")
        return self._gen_id

    def _request_once(self, call: Callable[[], Any], *, model: str, operation_id: str,
                      node: str, kind: str) -> Any:
        """送一次 request：先配 attempt，成功或例外後各寫一筆 trace，內部沒有迴圈。"""
        row: dict[str, Any] = {
            "operation_id": operation_id, "node": node, "model": model, "kind": kind,
            "attempt": self.trace.next_attempt(operation_id=operation_id, node=node),
            "started_at": to_iso(now_utc())}
        try:
            response = call()
        except Exception as exc:
            code = _error_code(exc)
            transient = isinstance(exc, TIMEOUT_ERRORS) or code in TRANSIENT_ERROR_CODES
            outcome = "transient_error" if transient else "permanent_error"
            self.trace.add({**row, "outcome": outcome})
            # 只留錯誤碼或例外類別名：ClientError 的 message 可能回聲使用者輸入。
            raise_as: type[Exception] = TransientError if transient else PermanentError
            raise raise_as(code or type(exc).__name__) from exc
        self.trace.add({**row, "outcome": "success"})
        return response

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        """Titan V2 走 `invoke_model`：body 只有三個業務鍵，沒有任何生成參數（設計 §14.3）。

        空白文字在送出之前就擋掉，所以不產生 attempt：Titan 也會回 `ValidationException`，
        但先擋可以少一次計費請求，錯誤訊息也指向真正的欄位。
        """
        if not text.strip():
            raise PermanentError("embedding input must not be blank")
        body = json.dumps({"inputText": text, "dimensions": TITAN_DIMENSIONS,
                           "normalize": True})
        response = self._request_once(
            lambda: self.client.invoke_model(modelId=self._embed_id, body=body),
            model=self._embed_id, operation_id=operation_id, node=node, kind="embedding")
        # invoke_model 的 body 是 StreamingBody，不是 dict，而且只能讀一次。
        payload = json.loads(response["body"].read())
        return _validated_embedding(payload.get("embedding"))

    def _converse(self, *, model: str, system: str, messages: Sequence[Mapping[str, Any]],
                  extra: Mapping[str, Any], operation_id: str, node: str, kind: str,
                  inference: Mapping[str, object] = JUDGEMENT_INFERENCE_CONFIG) -> Any:
        """每個 Converse request 都帶 inferenceConfig：沒有「忘了設 maxTokens」的分支。

        `inference` 的預設是判斷類：Rote 的 tool use 沒有 schema，屬於判斷類。
        `generate_json` 則逐次傳 `inference_config(schema)`。
        """
        return self._request_once(
            lambda: self.client.converse(
                modelId=model, system=[{"text": system}], messages=list(messages),
                inferenceConfig=dict(inference), **extra),
            model=model, operation_id=operation_id, node=node, kind=kind)

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        model = self._gen_model()
        response = self._converse(
            model=model, system=system, extra={}, operation_id=operation_id, node=node,
            messages=[{"role": "user", "content": [{"text": user}]}], kind="generation",
            inference=inference_config(schema))
        raw = response["output"]["message"]["content"][0]["text"]
        return _parse_schema_json(raw, schema, stop_reason=response.get("stopReason", ""))

    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        """只送一次 request；拿到 toolUse 後要不要再問一輪由 Phase 37 決定。"""
        model = self._gen_model()
        result: dict[str, Any] = self._converse(
            model=model, system=system, messages=messages, kind="tool_use",
            extra={"toolConfig": {"tools": list(tools)}},
            operation_id=operation_id, node=node)
        return result
