"""接入層：驗簽、正規化、接受去重與流程啟動。

owner 是 Phase 30；P31（正規化）、P32（接受／啟動）、P37（Rote 三層）、P42、P43、P59
之後會在同一支檔案往下追加。目前的區塊順序固定為：

1. 驗簽（P30）—— 解析 JSON 之前先用原始 request bytes 比對 HMAC-SHA256。
2. 整體期限（P30）—— webhook 的八秒 deadline，下游每一步開始前呼叫 `assert_time_left`。
3. 正規化（P31）—— 候選欄位轉成 canonical `Ticket`／`Release`，是唯一的 model 邊界。
4. 接線點（P30 stub → P32 接受端 → P37 完整三層）。

log 不得出現原始 body、簽名或 secret（00A §3.8）。
"""

import hashlib
import hmac
import string
from collections.abc import Mapping, Sequence
from datetime import datetime
from time import monotonic

from pydantic import ValidationError

from training_kb.clock import parse_iso
from training_kb.errors import IngressError, PermanentError
from training_kb.models import Release, ReleaseKind, ReleaseSource, Ticket, TicketSource
from training_kb.operations import Acceptance
from training_kb.pipelines.common import JSONValue

# --- 1. 驗簽（Phase 30）-------------------------------------------------------

SIGNATURE_HEADER = "X-Hub-Signature-256"
SIGNATURE_PREFIX = "sha256="
HEX_DIGEST_LENGTH = 64


def verify_github_signature(raw_body: bytes, signature_header: str | None, secret: bytes) -> None:
    """用原始 bytes 驗 GitHub 簽名；合法回 None，不合法丟 `IngressError`。

    `raw_body` 一定要是 Lambda 收到的原始 bytes。重新 `json.dumps()` 會改掉空白與鍵順序，
    算出來的 HMAC 一定對不上。secret 沒設定屬於環境設定錯誤（`PermanentError`），
    不能報成使用者輸入錯誤。
    """
    if not secret:
        raise PermanentError("webhook secret 未設定")  # 設定錯誤，不是使用者輸入錯誤
    if not signature_header or not signature_header.startswith(SIGNATURE_PREFIX):
        raise IngressError("GitHub 簽名缺少或格式錯誤", (SIGNATURE_HEADER,))
    supplied = signature_header.removeprefix(SIGNATURE_PREFIX).lower()
    # 先擋掉長度與字元明顯不對的值，避免把任意長度字串丟進比較。
    if len(supplied) != HEX_DIGEST_LENGTH or any(c not in string.hexdigits for c in supplied):
        raise IngressError("GitHub 簽名格式錯誤", (SIGNATURE_HEADER,))
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    # 一律固定時間比較，不可寫成 `expected == supplied`。訊息只說不符，不回報期望值。
    if not hmac.compare_digest(expected, supplied):
        raise IngressError("GitHub 簽名不符", (SIGNATURE_HEADER,))


# --- 2. 整體期限（Phase 30）---------------------------------------------------


def time_left(deadline: float) -> float:
    """還剩幾秒；小於等於 0 代表整體期限已到。

    `deadline` 一律是 `time.monotonic()` 的**絕對時刻**（單調時鐘，不受系統調時影響），
    由 handler 進入時算好 `monotonic() + WEBHOOK_DEADLINE_SECONDS` 一路往下傳。
    """
    return deadline - monotonic()


def assert_time_left(deadline: float, *, step: str) -> None:
    """下游每一步開始前呼叫；**不重新計一次八秒、也不自己呼叫 `monotonic()`**。

    逾時丟 Python 內建的 `TimeoutError`（不是 `TransientError`：這不是服務故障，
    而是來不及）。`step` 只用來讓訊息看得出卡在哪一步。
    """
    if time_left(deadline) <= 0:
        raise TimeoutError(f"{step} 時已超過 webhook 的八秒整體期限")


# --- 3. 正規化（Phase 31）-----------------------------------------------------

TICKET_REQUIRED = ("id", "source", "text", "author", "ts", "project_id")
RELEASE_REQUIRED = ("id", "source", "feature", "kind", "evidence", "ts")
RENAMED_REQUIRED = ("old_name", "new_name")
ANALYSIS_FIELDS = ("cluster_id", "feature_ids", "embedding")
"""接入不得預填的分析欄位：分群、Feature 命中與向量都由後面的 pipeline 補。"""


def missing_nonempty_strings(
    payload: Mapping[str, object], keys: Sequence[str]
) -> tuple[str, ...]:
    """回「缺少或不是非空字串」的欄位名 tuple，直接當 `IngressError.fields`。

    「一次回報所有缺欄位」只有這一份實作（00A §6.8）。全空白字串算缺值（D23 覆寫 D09）；
    這裡只判斷合不合法，**不 strip 之後改寫來源給的值**。
    """
    return tuple(
        key for key in keys
        if not isinstance(payload.get(key), str) or not str(payload[key]).strip()
    )


def _parsed_ts(payload: Mapping[str, object]) -> datetime:
    """`ts` 必須是帶時區的 ISO-8601 **整秒**（00A §3.5）；naive、格式錯與帶微秒一律拒絕。"""
    try:
        parsed = parse_iso(str(payload["ts"]))
    except ValueError as error:
        raise IngressError("ts 必須是 aware 的 UTC ISO-8601 時間", ("ts",)) from error
    if parsed.microsecond:  # 靜默截斷會讓以時間入鍵的計算悄悄改變答案
        raise IngressError("ts 必須是整秒", ("ts",))
    return parsed


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    """「必填但值可為 null」的欄位：沒出現或給 null 一律 `None`，給了非字串就是接入錯誤。

    `RELEASE_REQUIRED`（00A §6.8）不含這三個欄位，所以這裡只管型別，不要求 key 一定出現：
    `changed`／`removed` 事件本來就沒有名稱欄位，`changelog` 來源也沒有上游事件識別碼。
    """
    value = payload.get(key)
    if value is None or isinstance(value, str):
        return value
    raise IngressError(f"{key} 必須是字串或 null", (key,))


def _invalid_fields(error: ValidationError) -> tuple[str, ...]:
    """把 pydantic 的 `loc` 收斂成欄位名。

    這兩個函式是唯一的 canonical model 邊界，接入不合法時只能吐 `IngressError`；
    模型層的拒絕（例如 `id` 帶了 `#` 前綴）若原樣往外丟 `ValidationError`，
    webhook handler 只認 `IngressError`／`TimeoutError`，會變成 500 而不是明確拒絕。
    """
    return tuple(str(item["loc"][0]) for item in error.errors() if item["loc"])


def validate_ticket(payload: Mapping[str, object]) -> Ticket:
    """候選欄位 → canonical `Ticket`；不合法時 `IngressError.fields` 列出問題欄位。

    純函式：**不收 `deadline`**、不呼叫 `monotonic()`、不寫任何 item。正規化只做欄位檢查，
    沒有網路或 IO，期限由呼叫端（P32 的 `normalize_then_accept`）先 `assert_time_left` 管。
    順序固定：必填 → 分析欄位未預填 → enum 合法 → `ts` 可解析。
    """
    missing = missing_nonempty_strings(payload, TICKET_REQUIRED)
    if missing:
        raise IngressError("Ticket 必填欄位不完整", missing)
    prefilled = tuple(key for key in ANALYSIS_FIELDS if key in payload)
    if prefilled:
        raise IngressError("接入不得預填分析欄位", prefilled)
    if payload["source"] not in set(TicketSource):
        raise IngressError("Ticket source 不合法", ("source",))
    try:
        return Ticket(
            id=str(payload["id"]), source=TicketSource(str(payload["source"])),
            text=str(payload["text"]), author=str(payload["author"]),
            ts=_parsed_ts(payload), project_id=str(payload["project_id"]),
            cluster_id=None, feature_ids=[], embedding=None,
        )
    except ValidationError as error:
        raise IngressError("Ticket 欄位值不合法", _invalid_fields(error)) from error


def validate_release(payload: Mapping[str, object]) -> Release:
    """候選欄位 → canonical `Release`；`feature` 與 `kind` 在接入當下就要解析完成。

    `source_event_id`／`old_name`／`new_name` 是「必填但可為 null」，一律用 `payload.get(...)`：
    `changed`／`removed` 事件沒有名稱欄位，`payload["old_name"]` 會丟 `KeyError`，
    那是程式錯誤不該變成接入錯誤（00A §5.1「模型寬、入口嚴」）。
    """
    fields = missing_nonempty_strings(payload, RELEASE_REQUIRED)
    if payload.get("kind") == ReleaseKind.RENAMED:  # StrEnum 成員等於自己的字串值
        fields += missing_nonempty_strings(payload, RENAMED_REQUIRED)
    if fields:
        raise IngressError("Release 欄位不完整", fields)
    if payload["source"] not in set(ReleaseSource):
        raise IngressError("Release source 不合法", ("source",))
    if payload["kind"] not in set(ReleaseKind):
        raise IngressError("Release kind 不合法", ("kind",))
    try:
        return Release(
            id=str(payload["id"]), source_event_id=_optional_string(payload, "source_event_id"),
            source=ReleaseSource(str(payload["source"])), feature=str(payload["feature"]),
            kind=ReleaseKind(str(payload["kind"])), old_name=_optional_string(payload, "old_name"),
            new_name=_optional_string(payload, "new_name"),
            evidence=str(payload["evidence"]),
            ts=_parsed_ts(payload),
        )
    except ValidationError as error:
        raise IngressError("Release 欄位值不合法", _invalid_fields(error)) from error


# --- 4. 接線點（Phase 30 stub → Phase 32 接受端 → Phase 37 完整三層）----------


def normalize_then_accept(*, domain: str, adapter: str, event_type: str,
                          headers: Mapping[str, str], payload: Mapping[str, JSONValue],
                          deadline: float) -> Acceptance:
    """Phase 31 正規化 + Phase 32 接受的接線點。

    本 Phase 只固定呼叫位置與六個 keyword 參數（00A D-60）：`domain`／`adapter` 由可信
    入口設定提供，**不得從 payload 反推**；`headers` 一律小寫鍵；`deadline` 是 handler
    進入時算好的絕對時刻，往下傳而不重新計時。

    這裡刻意丟 `PermanentError` 而不是回一個假的成功：設計 §14.1 要求驗簽以外的任何一步
    失敗都回操作失敗，不能「先回成功、之後再背景處理」。
    """
    raise PermanentError("Phase 31／32 尚未接線；本 Phase 不得先回成功再背景處理")
