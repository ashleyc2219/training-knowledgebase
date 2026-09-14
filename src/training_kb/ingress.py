"""接入層：驗簽、正規化、接受去重與流程啟動。

owner 是 Phase 30；P31（正規化）、P32（接受／啟動）、P37（Rote 三層）、P42、P43、P59
之後會在同一支檔案往下追加。目前的區塊順序固定為：

1. 驗簽（P30）—— 解析 JSON 之前先用原始 request bytes 比對 HMAC-SHA256。
2. 整體期限（P30）—— webhook 的八秒 deadline，下游每一步開始前呼叫 `assert_time_left`。
3. 正規化（P31）—— 候選欄位轉成 canonical `Ticket`／`Release`，是唯一的 model 邊界。
4. 接受與啟動（P32）—— canonical 事件的永久去重、私有輸入與 pipeline 啟動。
5. 接線點（P30 stub → P32 接受端 → P37 完整三層）。

log 不得出現原始 body、簽名或 secret（00A §3.8）。
"""

import hashlib
import hmac
import json
import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from time import monotonic

import boto3
from pydantic import ValidationError

from training_kb.clock import now_utc, parse_iso
from training_kb.config import Settings, load_settings
from training_kb.errors import (
    CoordinationError,
    IngressError,
    ObjectAlreadyExists,
    PermanentError,
    TransientError,
)
from training_kb.keys import operation_ref
from training_kb.models import Release, ReleaseKind, ReleaseSource, Ticket, TicketSource
from training_kb.operations import (
    KINDS,
    Acceptance,
    AcceptOperation,
    OperationCoordinator,
    OperationKind,
)
from training_kb.pipeline_starter import (
    BotoPipelineStarter,
    PipelineStarter,
    state_machine_arns,
)
from training_kb.pipelines.common import JSONValue, PipelineName
from training_kb.repository import Repository

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


# --- 4. 接受與啟動（Phase 32）-------------------------------------------------

MAX_EXECUTION_NAME = 80
"""Step Functions 執行名稱的長度上限（00A §3.3）。"""

SAFE_EXECUTION_NAME = re.compile(rf"[A-Za-z0-9_-]{{1,{MAX_EXECUTION_NAME}}}\Z")
_ALLOWED = frozenset(string.ascii_letters + string.digits + "_-")
_NAME_HEAD = len("op-") + max(len(kind) for kind in KINDS) + len("-")
"""最長的 `op-<kind>-` 前綴要留得住：`feedback-review`／`ticket-analysis` 各 15 字，所以是 19。

長度由 `OperationKind` 自己導出，之後多一種 kind 也不會悄悄把前綴切掉。
"""

_DIGEST_LENGTH = MAX_EXECUTION_NAME - _NAME_HEAD - 1
"""`19 + 1 + 60 = 80`：前綴、連字號與雜湊剛好填滿上限。

60 個十六進位字元＝240 bits，遠超過撞名需要的強度；**長度是算出來的，不是猜的**，
所以前綴變長時雜湊會跟著縮，不會出現「超過 80 字被 AWS 拒絕」這種只在雲端才炸的錯。
"""


def operation_id_for(kind: OperationKind, canonical_id: str) -> str:
    """`op-<kind>-<canonical_id>`（00A §3.3）。canonical ID 已經是裸 ID，這裡不再加工。

    `kind` 用 Phase 10 的 `OperationKind`，所以 P42 的 `feedback`／`view` 直接沿用同一個
    函式，行為不變。名稱只由 kind 與已核定的 canonical ID 組成，**不含 user、留言或標題**。
    """
    return f"op-{kind}-{canonical_id}"


def execution_name(operation_id: str) -> str:
    """Step Functions 的執行名稱：必須符合 `[A-Za-z0-9_-]{1,80}`，而且同輸入永遠同輸出。

    冪等只對「同名、同 input、仍在執行」成立，所以名稱一定要由 `operation_id` 決定：
    **不得追加時間戳、隨機字尾或新的 operation ID**（設計 §14.2）。不合規（超長或含非 ASCII）
    時取固定的 UTF-8 SHA-256，前面保留完整的 `op-<kind>-` 前綴，長度由 `_NAME_HEAD` 與
    `_DIGEST_LENGTH` 算出來剛好填滿 80。
    """
    if SAFE_EXECUTION_NAME.match(operation_id):
        return operation_id
    digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    head = "".join(ch for ch in operation_id if ch in _ALLOWED)[:_NAME_HEAD].rstrip("-")
    return f"{head}-{digest[:_DIGEST_LENGTH]}"


PIPELINE_FOR_KIND: dict[OperationKind, PipelineName] = {
    "ticket": "ticket-analysis",
    "release": "release-update",
}
"""哪一種 canonical 事件觸發哪一條 pipeline（00B ING Rule 26／27）。

只有這兩種：Feedback／View 走 P42 的固定匯入（不啟動任何 pipeline），
feedback-review 由排程觸發、不經 `PipelineStarter`（00A D-61）。
"""

INPUT_NAME = "input"
"""私有 canonical 輸入的檔名；`operation_ref(operation_id, "input")` 會補上 `.json`。"""


@dataclass(frozen=True)
class Wiring:
    """接受路徑要用的四個相依。測試直接覆寫 `_wiring` 注入 fake。"""

    operations: OperationCoordinator
    starter: PipelineStarter
    repository: Repository
    settings: Settings


_WIRING: Wiring | None = None


def _wiring() -> Wiring:
    """取得四個相依（模組層工廠，快取一次）。

    **本計畫選擇**（00A §6.8）：讓 `accept_ticket(x, *, deadline)` 維持 00A 的兩個參數，
    又能取得 operations／starter／repository／settings。前面的底線代表模組內部用，
    其他 Phase 不得 import；測試 `monkeypatch.setattr(ingress, "_wiring", ...)` 即可注入。
    """
    global _WIRING
    if _WIRING is None:
        _WIRING = _build_wiring(load_settings())
    return _WIRING


def _build_wiring(settings: Settings) -> Wiring:
    """建立連真實 AWS 的四個相依；**只有第一次呼叫 `_wiring()` 時執行**。

    client 一律在這裡才建立，模組 import 時不碰網路。帳號由 STS 現查、Region 由 client
    自己回報，所以程式裡沒有寫死的帳號，也不必新增環境變數（00A §3.5 的 `TKB_` 清單裡
    沒有帳號）。**真正的雲端接線、IAM 與 state machine ARN 由 Phase 41 驗收**，
    本批（離線開發）只在測試裡覆寫 `_wiring`，不跑這條路徑。
    """
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    s3 = boto3.resource("s3", region_name=settings.aws_region)
    repository = Repository(dynamodb.Table(settings.table_name),
                            s3.Bucket(settings.content_bucket))
    operations = OperationCoordinator(repository)
    client = boto3.client("stepfunctions", region_name=settings.aws_region)
    identity = boto3.client("sts", region_name=settings.aws_region).get_caller_identity()
    arns = state_machine_arns(region=str(client.meta.region_name),
                              account_id=identity["Account"])
    return Wiring(operations=operations, starter=BotoPipelineStarter(client, arns, operations),
                  repository=repository, settings=settings)


def accept_ticket(ticket: Ticket, *, deadline: float) -> Acceptance:
    """canonical `Ticket` → 永久去重的 operation ＋ 一次 `ticket-analysis` 啟動。"""
    return _accept("ticket", ticket.id, ticket.project_id,
                   ticket.model_dump(mode="json"), deadline)


def accept_release(release: Release, *, deadline: float) -> Acceptance:
    """canonical `Release` → 永久去重的 operation ＋ 一次 `release-update` 啟動。

    `Release` 模型沒有 `project_id`（MVP 只有一個專案），所以由 `Settings.project_id` 取得
    後寫進 operation 紀錄與 ASL input（00A §6.8）。
    """
    return _accept("release", release.id, _wiring().settings.project_id,
                   release.model_dump(mode="json"), deadline)


def accept_normalized(obj: Ticket | Release, *, deadline: float) -> Acceptance:
    """接受端總入口：依型別分派，呼叫端（P30／P37／P42）不必自己判斷是哪一種。"""
    if isinstance(obj, Ticket):
        return accept_ticket(obj, deadline=deadline)
    return accept_release(obj, deadline=deadline)


def _accept(kind: OperationKind, canonical_id: str, project_id: str,
            payload: dict[str, JSONValue], deadline: float) -> Acceptance:
    """固定次序：先永久接受 → 再保存私有輸入 → 最後啟動執行。

    次序不能換。`accept` 先寫 `OPS#<operation_id>` 才有永久去重的依據；輸入物件與
    execution 都可以事後補，但「已接受」這件事一旦漏寫，同一個事件就會長出第二條版本鏈。

    **duplicate 但尚未啟動是合法的續跑**（00A D-45）：`accept` 已寫 `OPS#`、但 input 物件
    或 execution 還沒建立時，本次補完即可，不建立第二筆 operation、也不換名字重跑。
    判斷依據是 `input_ref`／`execution_arn` 這兩個**事實**欄位，不是 `status`。
    """
    wiring = _wiring()
    operations = wiring.operations
    operation_id = operation_id_for(kind, canonical_id)
    accepted = operations.accept(AcceptOperation(
        operation_id=operation_id, kind=kind, canonical_id=canonical_id,
        project_id=project_id, now=now_utc(),
    ))
    if accepted.status == "duplicate" and accepted.record.execution_arn:
        return accepted                      # 已完整啟動過，回既有紀錄，不重跑
    assert_time_left(deadline, step="put-input")
    input_ref = _put_canonical_input_once(wiring.repository, operation_id, payload)
    if accepted.record.input_ref != input_ref:
        operations.record_normalized(operation_id, input_ref)
    assert_time_left(deadline, step="start-execution")
    # ASL input 的 project_id 以 **ledger** 為準：續跑時本次請求的設定可能已經換過
    # （例如 `Settings.project_id` 改了），但這筆 operation 從接受當下就綁定一個專案。
    arn = _start_once(wiring.starter, operations, PIPELINE_FOR_KIND[kind], operation_id,
                      {"operation_id": operation_id,
                       "project_id": accepted.record.project_id,
                       "input_ref": input_ref})
    operations.record_execution(operation_id, arn)
    record = operations.load(operation_id)
    if record is None:
        raise CoordinationError(f"{operation_id} 接受後讀不回紀錄")
    return Acceptance(status=accepted.status, operation_id=operation_id, record=record)


def _put_canonical_input_once(repository: Repository, operation_id: str,
                              payload: dict[str, JSONValue]) -> str:
    """把 canonical 輸入寫進私有 S3；同一個 operation 重送沿用既有物件，不覆寫。

    `sort_keys=True` 讓同一份 canonical 物件每次算出同一串 bytes；`ensure_ascii=False`
    讓中文原樣存下來（這是私有物件，不是 log）。`ObjectAlreadyExists` 用**型別**判斷，
    不比對訊息字串；其他 S3 錯誤照常往上拋，不吞錯。
    """
    key = operation_ref(operation_id, INPUT_NAME)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    try:
        repository.put_object(key, body, "application/json", if_none_match=True)
    except ObjectAlreadyExists:
        pass                                 # 同一 operation 重送：沿用既有輸入
    return key


def _start_once(starter: PipelineStarter, operations: OperationCoordinator,
                pipeline: PipelineName, operation_id: str,
                asl_input: dict[str, JSONValue]) -> str:
    """啟動執行；失敗先留下可追溯紀錄，再把**原例外**往外丟。

    `retryable` 只看是不是 `TransientError`（與 `run_sequence` 同一條判準）。紀錄失敗之後
    `input_ref` 仍在，重送會走續跑分支、沿用同一個 execution name，不會換名重跑。
    這裡**不自己重試**：重試由呼叫端（webhook 的來源重送、ASL 的 Retry）管，只有一層。
    """
    try:
        return starter.start(pipeline, execution_name(operation_id), asl_input)
    except Exception as error:
        operations.fail(operation_id, str(error), isinstance(error, TransientError),
                        now=now_utc())
        raise


# --- 5. 接線點（Phase 30 stub → Phase 32 接受端 → Phase 37 完整三層）----------


def normalize_then_accept(*, domain: str, adapter: str, event_type: str,
                          headers: Mapping[str, str], payload: Mapping[str, JSONValue],
                          deadline: float) -> Acceptance:
    """Phase 31 正規化 + Phase 32 接受的接線點。

    本 Phase 只固定呼叫位置與六個 keyword 參數（00A D-60）：`domain`／`adapter` 由可信
    入口設定提供，**不得從 payload 反推**；`headers` 一律小寫鍵；`deadline` 是 handler
    進入時算好的絕對時刻，往下傳而不重新計時。

    本 Phase 補的是**接受**那半邊：`_normalize` 拿到 canonical 物件後交給
    `accept_normalized` 依型別分派。正規化那半邊是 Phase 37 的 Rote 三層，在它接上之前
    `_normalize` 刻意丟 `PermanentError` 而不是回一個假的成功：設計 §14.1 要求驗簽以外的
    任何一步失敗都回操作失敗，不能「先回成功、之後再背景處理」。
    """
    assert_time_left(deadline, step="normalize")
    normalized = _normalize(domain=domain, adapter=adapter, event_type=event_type,
                            headers=headers, payload=payload)
    return accept_normalized(normalized, deadline=deadline)


def _normalize(*, domain: str, adapter: str, event_type: str,
               headers: Mapping[str, str],
               payload: Mapping[str, JSONValue]) -> Ticket | Release:
    """留給 Phase 37 的接縫：組 `RawEvent` → `Rote.normalize` → canonical `Ticket`／`Release`。

    四個參數本 Phase 不解讀，只固定它們會被原樣轉交（`domain`／`adapter` 來自可信入口設定，
    不得從 payload 反推）。接上之前一律明確失敗。
    """
    raise PermanentError(f"Phase 37 尚未接線：{domain}/{event_type}（adapter={adapter}）"
                         f"；headers={len(headers)} 個、payload={len(payload)} 個鍵")
