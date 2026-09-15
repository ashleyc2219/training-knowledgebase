"""接入層：驗簽、正規化、接受去重與流程啟動。

owner 是 Phase 30；P31（正規化）、P32（接受／啟動）、P37（Rote 三層）、P42、P43、P59
之後會在同一支檔案往下追加。目前的區塊順序固定為：

1. 驗簽（P30）—— 解析 JSON 之前先用原始 request bytes 比對 HMAC-SHA256。
2. 整體期限（P30）—— webhook 的八秒 deadline，下游每一步開始前呼叫 `assert_time_left`。
3. 正規化（P31）—— 候選欄位轉成 canonical `Ticket`／`Release`，是唯一的 model 邊界。
4. 接受與啟動（P32）—— canonical 事件的永久去重、私有輸入與 pipeline 啟動。
5. 接線點（P30 stub → P32 接受端 → P37 完整三層）—— `trace_operation_id`、`_rote_deps`、
   `normalize_then_accept`。

log 不得出現原始 body、簽名或 secret（00A §3.8）。
"""

import hashlib
import hmac
import json
import re
import string
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING, Literal

import boto3
from pydantic import ValidationError

from training_kb.clock import now_utc, parse_iso, to_iso
from training_kb.config import DEFAULT_PROJECT_ID, Settings, load_settings
from training_kb.content import assert_accepts_feedback
from training_kb.errors import (
    CoordinationError,
    IngressError,
    ObjectAlreadyExists,
    PermanentError,
    TransientError,
)
from training_kb.keys import feedback_pk, operation_ref, parse_pk, version_pk, view_pk
from training_kb.models import (
    Feedback,
    Release,
    ReleaseKind,
    ReleaseSource,
    StrictModel,
    Ticket,
    TicketSource,
    Tutorial,
    TutorialView,
)
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
from training_kb.source_ids import stable_user_from_import
from training_kb.writing.client import Writer
from training_kb.writing.prompts import prompt_classify_comment
from training_kb.writing.schemas import CommentClassification

if TYPE_CHECKING:                       # 只給型別檢查用，執行期不 import（見 `_build_rote_deps`）
    from training_kb.adapters import ToolRegistry
    from training_kb.rote import RoteDeps

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


def _reset_wiring() -> None:
    """丟掉快取的 `Wiring`，下一次 `_wiring()` 會重建。

    給測試用：`_WIRING` 是模組層快取，一個忘了 monkeypatch 的測試會把**真的**連到 AWS
    的 wiring 留在那裡，後面的測試就算有 monkeypatch 也可能先讀到它。正式程式不呼叫
    （Lambda 的相依在容器生命週期內不會變）。
    """
    global _WIRING
    _WIRING = None


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
    return _accept_detailed(ticket, deadline=deadline)[0]


def accept_release(release: Release, *, deadline: float) -> Acceptance:
    """canonical `Release` → 永久去重的 operation ＋ 一次 `release-update` 啟動。

    `Release` 模型沒有 `project_id`（MVP 只有一個專案），所以由 `Settings.project_id` 取得
    後寫進 operation 紀錄與 ASL input（00A §6.8）。
    """
    return _accept_detailed(release, deadline=deadline)[0]


def accept_normalized(obj: Ticket | Release, *, deadline: float) -> Acceptance:
    """接受端總入口：依型別分派，呼叫端（P30／P37／P42）不必自己判斷是哪一種。"""
    return _accept_detailed(obj, deadline=deadline)[0]


def _accept_detailed(obj: Ticket | Release, *,
                     deadline: float) -> tuple[Acceptance, bool]:
    """`accept_normalized` 的完整版：多回一個**事實**——「進來之前就已經完整啟動過」。

    這個 bool 只能由 `_accept` 在**啟動之前**判斷，事後從 `Acceptance` 反推不出來：續跑
    （ledger 已 accepted／duplicate，但 `execution_arn` 還是空的）補完啟動之後，狀態同樣是
    `duplicate`、`execution_arn` 也同樣有值，與純重送長得一模一樣。`normalize_then_accept`
    靠它分辨「本次真的啟動了一條執行」與「什麼都沒做」（Phase 37 review 必修 B3）。

    三個公開 `accept_*` 的簽名因此完全不變，只是各自取 `[0]`。
    """
    if isinstance(obj, Ticket):
        return _accept("ticket", obj.id, obj.project_id, obj.model_dump(mode="json"), deadline)
    return _accept("release", obj.id, _wiring().settings.project_id,
                   obj.model_dump(mode="json"), deadline)


def _accept(kind: OperationKind, canonical_id: str, project_id: str,
            payload: dict[str, JSONValue], deadline: float) -> tuple[Acceptance, bool]:
    """固定次序：先永久接受 → 再保存私有輸入 → 最後啟動執行。

    回 `(Acceptance, 進來之前就已完整啟動)`。第二個值是**本函式開頭**的觀察，不是結束時的
    狀態：續跑補完啟動之後，`status` 與 `execution_arn` 與純重送完全一樣，分不出來。

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
        return accepted, True                # 已完整啟動過，回既有紀錄，不重跑
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
    return Acceptance(status=accepted.status, operation_id=operation_id, record=record), False


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

TRACE_ID_PREFIX = "op-ingress-"
DELIVERY_HEADERS = ("x-github-delivery", "x-tkb-delivery")
"""哪個 header 帶「這次投遞」的識別碼；GitHub 是 `X-GitHub-Delivery`，手動匯入由 P42 提供。"""


def trace_operation_id(headers: Mapping[str, str]) -> str:
    """正規化之前的臨時 operation id：`op-ingress-<來源投遞識別碼>`（00A §3.3）。

    這個值**只**給 `CallTrace` 與模型輸出 ref 用：它不經 `operation_id_for`、不會寫成
    `OPS#` item，也**不是**去重鍵——永久去重鍵是 `Acceptance.operation_id`
    （`op-<kind>-<canonical_id>`），正規化成功之後才拿得到。

    沒有投遞識別碼時回固定的 `op-ingress-unknown`，**不自己造隨機值**：trace 的用途是
    對回來源的那一次投遞，隨機值只會讓它對不回去。`headers` 一律是小寫鍵（P30）。
    """
    for name in DELIVERY_HEADERS:
        value = headers.get(name, "").strip()
        if value:
            return f"{TRACE_ID_PREFIX}{value}"
    return f"{TRACE_ID_PREFIX}unknown"


@dataclass(frozen=True)
class RoteWiring:
    """`Rote` 需要的五個相依；結構上滿足 `rote.RoteDeps`（00A §6.8 的結構型 Protocol）。"""

    repository: Repository
    operations: OperationCoordinator
    registry: "ToolRegistry"
    writer: Writer
    now: Callable[[], datetime]


_ROTE_DEPS: "RoteDeps | None" = None


def _rote_deps() -> "RoteDeps":
    """Rote 的相依（模組層工廠，快取一次）；測試 `monkeypatch.setattr` 覆寫它注入 fake。"""
    global _ROTE_DEPS
    if _ROTE_DEPS is None:
        _ROTE_DEPS = _build_rote_deps(_wiring())
    return _ROTE_DEPS


def _reset_rote_deps() -> None:
    """丟掉快取的相依，下一次 `_rote_deps()` 會重建（與 `_reset_wiring` 同一個理由）。"""
    global _ROTE_DEPS
    _ROTE_DEPS = None


def _build_rote_deps(wiring: Wiring) -> "RoteDeps":
    """建立連真實 AWS／Bedrock 的五個相依；**只有第一次呼叫 `_rote_deps()` 時執行**。

    `adapters` 與 `writing` 都在**函式內** import：Phase 36 的 `adapters.validate` 反向
    import 本模組，本模組若在模組層 import `adapters` 就會變成循環 import
    （controller 裁決 2026-09-14）。`rote.py` 則是模組層 import 本模組，所以
    `normalize_then_accept` 也用函式內 import 取得 `Rote`。

    **O5 未通過時 `generation_model_id` 是 `None`**：`BedrockWriter` 會在真的要呼叫模型時
    明確失敗，這裡不填猜測的 model ID，也不預先擋掉整條路徑（兩層重放不需要模型）。
    """
    from training_kb.adapters import default_registry
    from training_kb.writing import BedrockWriter, CallTrace
    from training_kb.writing.client import build_bedrock_client

    settings = wiring.settings
    client = build_bedrock_client(settings.bedrock_region or settings.aws_region or "")
    writer = BedrockWriter(client, CallTrace(),
                           generation_model_id=settings.generation_model_id,
                           embedding_model_id=settings.embedding_model_id)
    return RoteWiring(repository=wiring.repository, operations=wiring.operations,
                      registry=default_registry(), writer=writer, now=now_utc)


def normalize_then_accept(*, domain: str, adapter: str, event_type: str,
                          headers: Mapping[str, str], payload: Mapping[str, JSONValue],
                          deadline: float) -> list[Acceptance]:
    """整條接入的**唯一**固定次序：Rote 三層正規化 → `accept_normalized` → `commit_success`。

    六個參數全是 keyword（00A D-60）：`domain`／`adapter`／`event_type`／`headers` 由可信
    入口設定提供，**不得從 payload 反推**；`deadline` 是 handler 進入時算好的
    `time.monotonic()` 絕對時刻，往下傳而不重新計時。

    **回傳 `list[Acceptance]`（裁決 D-73，2026-09-14）**：F14 一個 PR 改到 n 個功能會展開成
    n 筆子 Release，每一筆各自 `accept_release`、各自一個 operation
    （`op-release-…-1`、`…-2`），但共用同一個 `source_event_id`。Ticket 與只改一個功能的
    PR 都只回長度 1 的 list，所以呼叫端取 `[0]` 就是原本的行為。

    **「先前就完整跑過」的判斷取自接受端進來時的狀態**（`_accept_detailed` 回的第二個值），
    不是啟動之後的 `status`／`execution_arn`：續跑（ledger 已 accepted／duplicate、
    `execution_arn` 還是空的，本次補完啟動）結束時與純重送長得一模一樣，用事後狀態判斷會
    把它誤判成重送而跳過 `commit_success`，這條 PROC 就永遠學不起來。只有真正的純重送才
    跳過，不會替同一次事件多記一個成功樣本；去重的權威仍然是 `record_proc_sample`。

    任何一筆丟例外都原樣往上拋，已成功的那幾筆靠自己的 operation 紀錄留存，不回頭刪除。
    """
    assert_time_left(deadline, step="normalize")
    # 函式內 import：`rote.py` 在模組層 import 本模組，這裡反向 import 才不會變成循環。
    from training_kb.rote import RawEvent, Rote

    event = RawEvent(domain=domain, adapter=adapter, event_type=event_type,
                     headers=dict(headers), payload=dict(payload))
    deps = _rote_deps()
    rote = Rote(deps)
    accepted: list[Acceptance] = []
    for result in rote.normalize_all(event, operation_id=trace_operation_id(headers),
                                     deadline=deadline):
        acceptance, already_started = _accept_detailed(result.entity, deadline=deadline)
        arn = acceptance.record.execution_arn or ""
        if not already_started:              # 純重送才跳過；續跑補啟動仍要提交 PROC 成功
            rote.commit_success(result, operation_id=acceptance.operation_id,
                                execution_arn=arn, now=deps.now())
        accepted.append(acceptance)
    if not accepted:
        raise PermanentError(f"{domain}/{event_type} 正規化沒有產出任何 canonical 物件")
    return accepted


# ---- Phase 43 ----------------------------------------------------------------
# 一筆回饋的 `category` 怎麼定（設計 §7.6、§12.1、§19.1 的 D12／D13）。決策表逐列互斥，
# 由上往下第一個命中者決定結果：
#
#     1  勾選值在核定表內        -> 原值            0 次模型呼叫
#     2  勾選值非空但未核定      -> 待分類          0 次
#     3  沒勾選且留言去頭尾後為空 -> None（只有評分） 0 次
#     4  沒勾選且留言非空        -> 模型值收斂      恰好 1 次
#
# 核定表 `CONFIG#feedback_categories` **只讀**：本區段沒有任何寫入路徑，模型輸出與使用者
# 勾選都不會擴充它（新增類別是維護者的受控匯入工作）。`CommentClassification` 在 Phase 18
# 的「走 correction？」對照表是**否**，所以這裡直接呼叫 `Writer.generate_json`，未核定的
# 回答由 `_settle` 降級成 `待分類`，全程只有一次 request。
#
# `DEFAULT_FEEDBACK_CATEGORIES` 由 controller 2026-09-14 預先宣告（值不變），讓 W1／W2
# 併行的 P44／P53／P54／P57 可以先 import。

PENDING_CATEGORY = "待分類"
"""收斂用的保留值。**不是**新的核定類別：設計 §12.1 的負面回饋數不算它。"""

DEFAULT_FEEDBACK_CATEGORIES: frozenset[str] = frozenset({"找不到按鈕", "缺少資訊"})
"""設定讀不到或形狀不合法時的退路（設計 §13 的 widget 初始兩類）。

**不得改成空集合**：Phase 44 的同類計數會整批歸零，一個壞掉的設定就等於「永遠沒有弱教學」。
"""

FEEDBACK_CATEGORIES_PK = "CONFIG#feedback_categories"
"""核定類別表的唯一來源；`CONFIG#` 與 `OPS#`／`SEQ#`／`LEASE#` 同屬不走模型的 item。"""

CLASSIFY_NODE = "classify_comment"
"""留言分類節點的名字；`CallTrace` 與 `Writer.generate_json` 的 `node` 都用它。"""


def approved_categories(repository: Repository) -> frozenset[str]:
    """讀核定類別表；查不到或形狀不合法一律退回 `DEFAULT_FEEDBACK_CATEGORIES`。

    用 Phase 10 的 `get_meta_item`（`CONFIG#` 不走 Pydantic，00A §3.6），不是 `get_meta`。
    `categories` 非 list、空 list、缺欄位、元素全是空白——四種都退回預設兩類而不是空集合。
    """
    item = repository.get_meta_item(FEEDBACK_CATEGORIES_PK)
    values = item.get("categories") if item is not None else None
    if isinstance(values, list):
        names = frozenset(str(value).strip() for value in values if str(value).strip())
        if names:
            return names
    return DEFAULT_FEEDBACK_CATEGORIES


def _settle(value: str | None, approved: frozenset[str]) -> str | None:
    """把任意字串收斂成「核定值／`待分類`／`None`」三選一。

    空字串與 `None` 回 **`None`**（決策表第 3 列「只有評分」），**不是** `PENDING_CATEGORY`：
    回保留值會讓只給評分的回饋憑空長出一個問題類別。`待分類` 本身再收斂一次仍然是它。
    """
    name = (value or "").strip()
    if not name:
        return None
    return name if name in approved or name == PENDING_CATEGORY else PENDING_CATEGORY


def classify_feedback_category(feedback: Feedback, *, approved: frozenset[str],
                               writer: Writer, operation_id: str) -> str | None:
    """決策表的四條分支；只有第 4 列會送出 request，而且**恰好一次**。

    勾選命中就 `return`，模型沒有機會覆蓋使用者的選擇（`COL` Rule 4）。留言去頭尾後為空
    回 `None`（只有評分，`COL` Rule 3 仍是有效回饋）。留言非空才呼叫模型，回來的值一樣
    走 `_settle`：未核定就降級成 `待分類`，**不重問第二次**（`COL` Rule 5、6）。

    `generate_json` 吃 schema **dict**、回 **dict**（00A D-02），所以讀值用
    `reply.get("category")` 而不是 `reply.category`——`CommentClassification` 不是 Pydantic
    類別。判斷類的 `maxTokens 512`／`temperature 0.1` 由 `inference_config(schema)` 依
    `$id` 自動決定（00A §3.7），本函式**不傳**任何推論參數。

    模型回空字串／非字串／缺欄位時 `_settle` 會回 `None`，這裡再收斂成 `PENDING_CATEGORY`：
    留言非空卻判不出來是「待分類」，不是「這筆沒有類別」。
    """
    chosen = _settle(feedback.category, approved)
    if chosen is not None:
        return chosen
    comment = (feedback.comment or "").strip()
    if not comment:
        return None
    system, user = prompt_classify_comment(comment, approved)
    reply = writer.generate_json(system, user, CommentClassification,
                                 operation_id=operation_id, node=CLASSIFY_NODE)
    answer = reply.get("category")
    return _settle(answer if isinstance(answer, str) else None, approved) or PENDING_CATEGORY


def _resolve_category(feedback: Feedback, *, repository: Repository, writer: Writer | None,
                      operation_id: str) -> Feedback:
    """`import_feedback` 的接線點：回一個 `category` 已判定好的**新** `Feedback`。

    `Feedback` 是 frozen，所以用 `model_copy(update=...)`——它在 Pydantic v2 **不重跑
    validator**，把 `category` 設成 `None` 因此不會踩到 `carries_signal`（`validate_feedback`
    已經保證 `rating` 是 1..5，不變條件本來就成立）。不要改成 `Feedback(**{...})` 重建。

    `writer is None` 走 Phase 42 單獨執行時的行為：只把勾選值收斂，完全不呼叫模型。
    """
    approved = approved_categories(repository)
    if writer is None:
        category = _settle(feedback.category, approved)
    else:
        category = classify_feedback_category(feedback, approved=approved, writer=writer,
                                              operation_id=operation_id)
    return feedback.model_copy(update={"category": category})


# ---- Phase 42 ----------------------------------------------------------------
# Feedback／View 的固定匯入（設計 §5、§7.1、§9.1、§9.2）：只有程式判斷的一條路徑，
# 沒有 adapter 選擇、沒有模型、沒有 Rote。**不建 `RawEvent`、不啟動 Step Functions、
# 不寫 PROC**——回饋與瀏覽是資料輸入，不是觸發器。
#
# 驗證順序固定：純欄位 → 圖譜（版本、退役）→ 操作紀錄（永久去重／續跑）→ 寫入。
# 三個判斷一律重用既有函式，本區段不另寫一份：`_parsed_ts`（`ts` aware 整秒）、
# `stable_user_from_import`（`user` 格式）、`assert_accepts_feedback`（退役）。

FEEDBACK_FIELDS: frozenset[str] = frozenset(
    {"id", "tutorial_version", "rating", "category", "comment", "user", "ts", "project_id"})
"""`validate_feedback` 認得的全部 key；多一個就是 `invalid_fields`（00A §5.1 註記）。

`project_id` 在表裡但**不是** `Feedback` 的欄位：它只用來替操作紀錄分組，缺值時用
`DEFAULT_PROJECT_ID`。哪幾欄「key 必須出現」由本清單與 `validate_feedback` 明寫，
不靠「必填但可為 null」那句通則推論，否則兩個入口會長出兩套規則。
"""

VIEW_FIELDS: frozenset[str] = frozenset({"tutorial_version", "user", "ts", "project_id"})
"""瀏覽紀錄只有三個欄位加分組用的 `project_id`；`ts` 必填，**沒有**補值分支。"""

FEEDBACK_ID_PREFIX = "f_"
"""設計 §7.1 的回饋 ID 形狀；widget 產生的是 `f_site-<slug>-<user>-<epoch>`（P57）。"""

_MISSING_VERSION = "版本不存在於圖譜"
_RETIRED_TUTORIAL = "此教學已退役，不再接受新回饋"
_DUPLICATE_FEEDBACK = "相同 Feedback ID 已匯入，不再計一筆有效回饋"
_DUPLICATE_VIEW = "相同的版本、使用者與時間已匯入過，不再計一筆瀏覽"
_SAVED_VIEW = "已保存瀏覽紀錄"


@dataclass(frozen=True)
class ImportResult:
    """固定匯入逐筆的結果；`handler` 直接 `asdict()` 成回應的一列。

    `invalid_fields` 是 **tuple**（`asdict()` 保留 tuple，JSON 序列化成 array），只有
    `status == "rejected"` 時才有值。`object_id` 在 Feedback 是 `id`、在 View 是
    `view_pk`（`rejected` 時是 `None`，因為當下根本組不出鍵）。
    """

    status: Literal["saved", "duplicate", "rejected"]
    object_id: str | None
    message: str
    invalid_fields: tuple[str, ...]


def _rejected(message: str, fields: Sequence[str]) -> ImportResult:
    """把 `IngressError` 收斂成 `rejected`：固定匯入不讓例外冒到呼叫端（00A §4.1、F51）。"""
    return ImportResult("rejected", None, message, tuple(fields))


def _project_id(payload: Mapping[str, object]) -> str:
    """操作紀錄的分組；`Feedback`／`TutorialView` 本身沒有這個欄位，不會寫進表。"""
    value = payload.get("project_id")
    return value if isinstance(value, str) and value.strip() else DEFAULT_PROJECT_ID


def _text(payload: Mapping[str, object], key: str, bad: list[str]) -> str:
    """必填非空字串；缺值把欄位名記進 `bad` 並回 `""`，讓呼叫端一次收齊所有問題欄位。"""
    if missing_nonempty_strings(payload, (key,)):
        bad.append(key)
        return ""
    return str(payload[key])


def _optional_text(payload: Mapping[str, object], key: str, bad: list[str]) -> str | None:
    """可缺可為 null 的文字欄位：空字串收斂成 `None`，非字串記進 `bad`。

    空字串不原樣保留：`Feedback.carries_signal` 看的是三者是否全空，留一個 `""`
    會讓「只有評分」與「留了空白留言」在下游長成兩種形狀。
    """
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        bad.append(key)
        return None
    return value if value.strip() else None


def _stable_user(payload: Mapping[str, object], bad: list[str]) -> str:
    """`user` 交給 Phase 13 的 `stable_user_from_import` 檢查（`COL` Rule 9）。

    它丟的正是 `IngressError(fields=("user",))`，所以這裡只要接住轉成 `bad`；
    本 Phase 不驗證前綴、也不自己造 ID（D-47）。
    """
    value = _text(payload, "user", bad)
    if not value:
        return ""
    try:
        return stable_user_from_import(value)
    except IngressError:
        bad.append("user")
        return ""


def _rating(payload: Mapping[str, object], bad: list[str]) -> int | None:
    """`rating` 必須是 1..5 的**嚴格**整數（`COL` Rule 3）。

    用 `type(value) is int` 而不是 `isinstance`：`bool` 是 `int` 的子類別，
    `isinstance(True, int)` 為真，`rating=True` 會被存成 1 分而污染平均。
    `Feedback` 模型自己也擋（`rating_is_strict_int`），入口再判斷一次是為了吐
    `IngressError(fields=("rating",))` 而不是 pydantic `ValidationError`（00A §6.8）。
    """
    value = payload.get("rating")
    if type(value) is int and 1 <= value <= 5:
        return value
    bad.append("rating")
    return None


def _import_ts(payload: Mapping[str, object], bad: list[str], *,
               required: bool) -> datetime | None:
    """`ts` 一律走既有的 `_parsed_ts`（aware ISO-8601 整秒），不只用 `parse_iso`。

    `parse_iso` 會放行微秒，之後 `view_pk` 內部的 `to_iso` 會丟 `PermanentError`——
    那不是使用者輸入錯誤該有的形狀（00A §3.5）。`required=False`（Feedback）時缺值回
    `None`，由呼叫端補匯入時間；`required=True`（View）時缺值就是不合法。
    """
    if payload.get("ts") is None:
        if required:
            bad.append("ts")
        return None
    try:
        return _parsed_ts(payload)
    except IngressError:
        bad.append("ts")
        return None


def validate_feedback(payload: Mapping[str, object], *, now: datetime) -> Feedback:
    """候選欄位 → canonical `Feedback`；不合法時 `IngressError.fields` 列出**所有**問題欄位。

    純欄位函式：不查圖譜、不碰操作紀錄，也**不做退役判斷**（那需要 `Tutorial`，
    呼叫點在 `import_feedback`；00A 第 915 列寫在本函式，以第 425 列的實質規則為準）。
    `ts` 缺值改記匯入時間 `now`，成功訊息會註明那不是使用者實際提交時間（設計 §7.1）。
    """
    bad: list[str] = sorted(set(payload) - FEEDBACK_FIELDS)
    feedback_id = _text(payload, "id", bad)
    if feedback_id and not feedback_id.startswith(FEEDBACK_ID_PREFIX):
        bad.append("id")
    rating = _rating(payload, bad)
    ts = _import_ts(payload, bad, required=False)
    tutorial_version = _text(payload, "tutorial_version", bad)
    user = _stable_user(payload, bad)
    category = _optional_text(payload, "category", bad)
    comment = _optional_text(payload, "comment", bad)
    if bad:
        raise IngressError("回饋欄位不合法", bad)   # IngressError 自己會排序去重
    try:
        return Feedback(id=feedback_id, tutorial_version=tutorial_version, rating=rating,
                        category=category, comment=comment, user=user,
                        ts=now if ts is None else ts)
    except ValidationError as error:
        raise IngressError("回饋欄位值不合法", _invalid_fields(error)) from error


def validate_view(payload: Mapping[str, object]) -> TutorialView:
    """候選欄位 → canonical `TutorialView`；`ts` 必填，**不得**用匯入時間補。

    補值會讓「先瀏覽、後開票」這個指標前提（`MET` Rule 4／5）變成偽造的證據，
    所以這裡沒有 `now` 參數可用。
    """
    bad: list[str] = sorted(set(payload) - VIEW_FIELDS)
    tutorial_version = _text(payload, "tutorial_version", bad)
    user = _stable_user(payload, bad)
    ts = _import_ts(payload, bad, required=True)
    if bad or ts is None:
        raise IngressError("瀏覽紀錄欄位不合法", bad or ("ts",))
    try:
        return TutorialView(tutorial_version=tutorial_version, user=user, ts=ts)
    except ValidationError as error:
        raise IngressError("瀏覽紀錄欄位值不合法", _invalid_fields(error)) from error


def _assert_open(tutorial: Tutorial) -> ImportResult | None:
    """退役判斷**只有**這一個來源：Phase 26 的 `assert_accepts_feedback`。

    不自己寫 `tutorial.status == "retired"`：狀態語意改動時兩份判斷會默默分岔。
    它丟的 `IngressError.fields` 就是 `("tutorial_version",)`，不必比對訊息字串。
    """
    try:
        assert_accepts_feedback(tutorial)
    except IngressError as error:
        return _rejected(_RETIRED_TUTORIAL, error.fields)
    return None


def _dedupe[MetaT: StrictModel](
        payload: Mapping[str, object], *, kind: OperationKind, canonical_id: str,
        pk: str, model: type[MetaT], repository: Repository,
        operations: OperationCoordinator, now: datetime) -> tuple[str, MetaT | None]:
    """向操作紀錄登記這一筆匯入，回 `(operation_id, 已經寫好的物件)`。

    第二個值是 `None` 就代表**本次要寫**（第一次，或 ledger 已接受但物件還沒寫成的續跑）；
    不是 `None` 就是真的重送，而且那個值是**表裡的現況**，不是這次 payload 解出來的物件。
    重送的收尾動作（補邊、關 operation）一律以表裡的現況為準，免得同一個 ID 被改成指向
    別的版本時多長出一條邊。

    **`accept` 回 duplicate 不等於物件已經存在**（00A D-45、設計 §14.1／§14.2）：上一次
    可能在寫 item 之前就中斷了。所以兩個條件都要成立才算重送；只有 ledger 有紀錄、
    物件卻不在，是**續跑**，本次要補寫，不是重複處理。
    """
    operation_id = operation_id_for(kind, canonical_id)
    acceptance = operations.accept(AcceptOperation(
        operation_id=operation_id, kind=kind, canonical_id=canonical_id,
        project_id=_project_id(payload), now=now))
    if acceptance.status != "duplicate":
        return operation_id, None
    return operation_id, repository.get_meta(pk, model)


def _complete_feedback(feedback: Feedback, *, repository: Repository,
                       operations: OperationCoordinator, operation_id: str,
                       now: datetime) -> None:
    """寫 metadata **之後**的兩個收尾動作；第一次與重送走的是同一條，所以必須冪等。

    `put_edge` 的鍵固定是 `FEEDBACK#<id>` ＋ `REFERS_TO#VERSION#<version_id>`，重寫一次
    只是同鍵覆寫，不會多一筆；`complete` 把 operation 設成 `done`，已經 done 再設一次
    仍然 done。版本一律取自傳進來的 `feedback`（重送時是表裡的現況）。
    """
    repository.put_edge(feedback_pk(feedback.id), "REFERS_TO",
                        version_pk(feedback.tutorial_version))
    operations.complete(operation_id, now=now)


def _saved_message(payload: Mapping[str, object], feedback_id: str, ts: datetime) -> str:
    """成功訊息；`ts` 是補的就必須講清楚它不是使用者實際提交時間（設計 §7.1）。"""
    if payload.get("ts") is not None:
        return f"已保存 {feedback_id}"
    return (f"已保存 {feedback_id}；來源未提供 ts，改記匯入時間 {to_iso(ts)}，"
            "非使用者實際提交時間")


def import_feedback(payload: Mapping[str, object], *, repository: Repository,
                    operations: OperationCoordinator, now: datetime,
                    writer: Writer | None = None) -> ImportResult:
    """固定匯入一筆回饋：欄位 → 版本與退役 → 永久去重 → 判定類別 → 寫 metadata 與邊。

    **不觸發任何後續**（`ING` Rule 29、`COL` Rule 8）：不啟動 Step Functions、不更新 PROC、
    不建立教學版本。邊一律指向**提交時指定的那一版**（`COL` Rule 7），不改綁
    `Tutorial.current_version`。

    `writer` 是 Phase 43 追加的**有預設值** keyword（00A 第 915 列），所以 Phase 42 的呼叫端
    不受影響；`None` 代表「只收斂勾選值、不做留言分類」，那是 Phase 42 單獨執行時的行為，
    **不是** O5 BLOCKED 的替代方案。分類固定發生在 `_dedupe` **之後**、`put_meta` 之前：
    放到 `accept` 之前的話每次重送都會多一次 Bedrock 呼叫（`COL` Rule 6）。
    """
    try:
        feedback = validate_feedback(payload, now=now)
    except IngressError as error:
        return _rejected(error.message, error.fields)
    version = repository.get_version(feedback.tutorial_version)
    if version is None:
        return _rejected(_MISSING_VERSION, ("tutorial_version",))
    tutorial = repository.get_tutorial(version.slug)
    if tutorial is None:
        return _rejected(_MISSING_VERSION, ("tutorial_version",))
    closed = _assert_open(tutorial)
    if closed is not None:
        return closed
    pk = feedback_pk(feedback.id)
    operation_id, existing = _dedupe(payload, kind="feedback", canonical_id=feedback.id,
                                     pk=pk, model=Feedback, repository=repository,
                                     operations=operations, now=now)
    if existing is not None:
        # **重送要冪等收尾，不能只是短路回 duplicate**（review 修正回合 1 的 Critical）：
        # 一筆回饋是「metadata item ＋ REFERS_TO 邊」兩筆寫入，中間斷掉（或 `put_edge`
        # 丟 `TransientError`）會留下「item 在、邊不在、ledger 停在 accepted」的狀態。
        # `list_feedback_of_version` 只走 `by_target` GSI，沒有邊就永遠看不到這筆回饋。
        # `put_edge` 是同鍵覆寫、`complete` 是把 status 設成 done，兩者重做都安全。
        _complete_feedback(existing, repository=repository, operations=operations,
                           operation_id=operation_id, now=now)
        return ImportResult("duplicate", existing.id, _DUPLICATE_FEEDBACK, ())
    feedback = _resolve_category(feedback, repository=repository, writer=writer,
                                 operation_id=operation_id)
    repository.put_meta(feedback, create_only=True)
    _complete_feedback(feedback, repository=repository, operations=operations,
                       operation_id=operation_id, now=now)
    ts = now if feedback.ts is None else feedback.ts   # 模型放寬才可能 None；入口一定補過
    return ImportResult("saved", feedback.id, _saved_message(payload, feedback.id, ts), ())


def import_view(payload: Mapping[str, object], *, repository: Repository,
                operations: OperationCoordinator, now: datetime | None = None) -> ImportResult:
    """固定匯入一筆瀏覽紀錄：欄位 → 版本存在 → 三元組去重 → 寫 metadata。

    **不查退役**：退役教學的歷史頁仍會被讀，瀏覽數是「重開票率」的分母，一起擋掉會讓
    指標失真（設計 §8.4）。**不建 `VIEWED` 邊**（設計 §9.2），去重完全靠 `view_pk`
    的 SHA-256；`canonical_id` 取它 `#` 後面那 64 個 hex，`operation_id` 才不會超長。
    `now` 是可選的**接受時間**（缺值用 `now_utc()`），與事件時間 `view.ts` 是兩件事：
    前者屬於操作紀錄，後者是使用者真的看到教學的時刻。
    """
    accepted_at = now_utc() if now is None else now
    try:
        view = validate_view(payload)
    except IngressError as error:
        return _rejected(error.message, error.fields)
    if repository.get_version(view.tutorial_version) is None:
        return _rejected(_MISSING_VERSION, ("tutorial_version",))
    pk = view_pk(view.tutorial_version, view.user, view.ts)
    operation_id, existing = _dedupe(payload, kind="view", canonical_id=parse_pk(pk)[1],
                                     pk=pk, model=TutorialView, repository=repository,
                                     operations=operations, now=accepted_at)
    if existing is not None:
        # 同 `import_feedback` 的冪等收尾：View 沒有邊，但 `put_meta` 與 `complete` 之間
        # 一樣斷得掉，斷了就會留下一筆永遠停在 accepted 的 operation。
        operations.complete(operation_id, now=accepted_at)
        return ImportResult("duplicate", pk, _DUPLICATE_VIEW, ())
    repository.put_meta(view, create_only=True)
    operations.complete(operation_id, now=accepted_at)
    return ImportResult("saved", pk, _SAVED_VIEW, ())
