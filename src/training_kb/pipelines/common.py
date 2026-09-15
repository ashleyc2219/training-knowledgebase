"""三條 Standard Step Functions 共用的本機 Task 執行契約（設計 §5、§14.2、§14.3）。

`run_sequence` 把一串 Task 依序跑完，**自己不重試**：重試只由 ASL 的 `Retry` 管理
（00A §3.7「只有一層管理重試」），Lambda 內再疊一層會讓次數相乘。任何一個 Task
丟例外時，先用 `OperationCoordinator.fail(...)` 留下可追溯紀錄，再把**原例外**往外丟，
讓 Step Functions 的 `Catch` 導向 `PipelineFailed`，整次執行不建版、不發布。
"""

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from typing import Any, Literal, get_args

import boto3

from training_kb import faults
from training_kb.clock import now_utc
from training_kb.config import Settings, load_settings
from training_kb.errors import PermanentError, TransientError
from training_kb.operations import OperationCoordinator
from training_kb.repository import Repository
from training_kb.writing.client import (
    BedrockWriter,
    CallTrace,
    Writer,
    build_bedrock_client,
)

# --- 1. 型別 ---------------------------------------------------------------

PipelineName = Literal["ticket-analysis", "release-update", "feedback-review"]
"""只有三條 pipeline。Analytics 是獨立 Lambda，不是 pipeline，不得加成第四個值。"""

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
"""「可以直接寫進 JSON 的值」。全專案**只有這一個定義**（00A §6.9），其他模組一律 import。"""

TaskFn = Callable[[dict[str, JSONValue], "Deps"], dict[str, JSONValue]]
"""一個 Task：吃目前的 state、回新的 state。state 只放 ID、S3 ref 與小型判斷結果。"""

PIPELINE_NAMES: tuple[str, ...] = get_args(PipelineName)
"""`PipelineName` 的三個值；白名單由型別導出，不另外手打一份字串清單。"""

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Deps:
    """一個 Task 需要的外部相依。

    操作紀錄與時鐘是必填；`repository`／`writer`／`settings` 由 [Phase 38] 以「修改本檔」
    的方式追加（00A D-36），三個都**預設 `None`**，所以 Phase 29 既有的
    `Deps(operations=..., now=...)` 仍然成立。

    要用這三個相依的 Task 一律走 `need_*()`：沒接線時當場丟 `PermanentError` 說出缺了哪一個，
    而不是把 `None` 帶進業務函式，等到深處才爆出看不懂的 `AttributeError`。
    """

    operations: OperationCoordinator
    now: Callable[[], datetime]
    repository: Repository | None = None
    writer: Writer | None = None
    settings: Settings | None = None

    def need_repository(self) -> Repository:
        if self.repository is None:
            raise PermanentError("pipeline deps 缺少 repository")
        return self.repository

    def need_writer(self) -> Writer:
        if self.writer is None:
            raise PermanentError("pipeline deps 缺少 writer")
        return self.writer

    def need_settings(self) -> Settings:
        if self.settings is None:
            raise PermanentError("pipeline deps 缺少 settings")
        return self.settings


# --- 2. 序列執行 -------------------------------------------------------------


def run_sequence(pipeline: PipelineName, payload: dict[str, JSONValue],
                 tasks: Sequence[TaskFn], deps: Deps) -> dict[str, JSONValue]:
    """依序跑完 `tasks`，第一個失敗就停下來。

    `except Exception` 是刻意的：`PublishError` 與 `CoordinationError` 在 00A §4.1
    不是 `PermanentError` 的子類，只攔那兩類會讓它們繞過操作紀錄。攔下來之後**一定
    `raise` 原例外**，不吞錯也不改成回傳值；`retryable` 只看是不是 `TransientError`。
    """
    if pipeline not in PIPELINE_NAMES:
        raise PermanentError(f"unknown pipeline: {pipeline}")
    operation_id = payload.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise PermanentError("payload 缺少 operation_id")
    value = dict(payload)
    try:
        for task in tasks:
            value = task(value, deps)
    except Exception as error:   # 記錄後原樣往外丟，重試交給 ASL
        deps.operations.fail(operation_id, str(error),
                             isinstance(error, TransientError), now=deps.now())
        raise
    return value


# ---- Phase 41 ----------------------------------------------------------------
# 共用 Lambda `training-kb-pipeline-task` 的入口與相依組裝（00A D-24）。
# 本段只由 Phase 41 建立，Phase 48／52 追加各自的區段，不改寫這裡的既有行數。


def task_name(task: TaskFn) -> str:
    """Task 函式名去掉 `task_` 前綴，就是 ASL `Parameters.task` 的值（00A D-24）。

    名稱由函式本身導出，所以 ASL 與 Python 兩邊不可能各打一份字串而默默分岔；
    Phase 41 的 `test_ticket_asl.py` 就是拿它逐一比對 ASL 的七個 Task。
    """
    return getattr(task, "__name__", "").removeprefix("task_")


_PIPELINE_HANDLERS: dict[str, str] = {
    "ticket-analysis": "training_kb.pipelines.ticket:ticket_analysis_handler",
    "release-update": "training_kb.pipelines.release:release_update_handler",
    "feedback-review": "training_kb.pipelines.feedback:feedback_review_handler",
}
"""三條 pipeline 的直接入口；現在就寫滿，所以一律**延後 import**（P48／P52 還沒落地）。"""

FAULT_TASK_ENV = "TKB_FAULT_TASK"
"""`"<pipeline>:<task>"`：讓指定的那一個 Task 必定丟 `TransientError`（Phase 41 新增）。

不是 `Settings` 欄位，`load_settings` 不讀它（00A §3.5 的執行期開關清單）。
與 `faults.FAULT_POINTS` 的五個切點**無關**：那五個切點都不在三條 pipeline 的 Task 邊界上，
而 P59 的契約測試又要求它們在三支檔案裡各恰好出現一次，所以不得加第六個切點。
"""


def maybe_fail_task(pipeline: str, task: str, env: Mapping[str, str] | None = None) -> None:
    """`TKB_FAULT_TASK` 命中這一個 Task 就丟 `TransientError`；`TKB_ENV=prod` 一律不生效。

    丟的是 `TransientError` **本身**而不是 `faults.InjectedFault`：Step Functions 的
    `ErrorEquals` 比對 Lambda runtime 回報的**類別名字串**，不認繼承，丟子類等於證出
    「這個錯誤沒有被重試」的假陰性（Phase 41 §7 的停止條件就是在證這件事）。

    每次 invoke 都重讀環境變數，**不做模組層快取**：雲端是用
    `aws lambda update-function-configuration` 在兩次執行之間開關它的。

    正式環境的判斷走 `faults.is_production`（修正波：final review C#3）——原本這裡是
    `== faults.PRODUCTION` 的精確比對，`TKB_ENV=" Prod"` 會漏擋，而同一支檔的
    `faults.active_fault` 早就做了 `.strip().lower()`，兩個開關對「什麼是正式環境」
    必須是同一個答案。

    **打錯的 `TKB_FAULT_TASK` 一律 `PermanentError`**（同一個修正波）：靜靜當成「沒有注入」
    會讓一次復原演練白跑，事後也看不出是開關沒生效還是流程真的沒失敗——與
    `faults.active_fault` 對打錯切點名的處理一致。可以檢查的是**形狀**
    （恰好一個 `:`、兩邊都非空）與 pipeline 名稱在 `PIPELINE_NAMES` 內；task 名稱屬於
    各 pipeline 模組的 `_TASK_BY_NAME`，本模組不 import 它們（會循環），所以不在這裡驗。
    """
    values: Mapping[str, str] = os.environ if env is None else env
    if faults.is_production(values):
        return
    wanted = values.get(FAULT_TASK_ENV, "")
    if not wanted:
        return
    if wanted.count(":") != 1 or not all(part for part in wanted.split(":")):
        raise PermanentError(f"{FAULT_TASK_ENV} 不是 <pipeline>:<task> 的形狀：{wanted!r}")
    target_pipeline, _, target_task = wanted.partition(":")
    if target_pipeline not in PIPELINE_NAMES:
        raise PermanentError(f"{FAULT_TASK_ENV} 指到未知的 pipeline：{target_pipeline!r}")
    if wanted == f"{pipeline}:{task}":
        raise TransientError(f"注入 Task 故障：{pipeline}:{task}")


def build_deps(settings: Settings) -> Deps:
    """真實 AWS 的相依組裝；形狀照 `ingress._build_wiring`，只是不需要 `PipelineStarter`。

    client 一律在這裡才建立，模組 import 時不碰網路。`BedrockWriter` 在
    `generation_model_id` 是 `None` 時**建構不會失敗**（只有真的呼叫生成模型才丟
    `PermanentError`），所以 O5 BLOCKED 不影響這支函式本身。
    """
    region = settings.aws_region
    if not region:
        raise PermanentError("build_deps 需要 TKB_AWS_REGION")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    s3 = boto3.resource("s3", region_name=region)
    repository = Repository(dynamodb.Table(settings.table_name),
                            s3.Bucket(settings.content_bucket))
    writer = BedrockWriter(build_bedrock_client(settings.bedrock_region or region), CallTrace(),
                           generation_model_id=settings.generation_model_id,
                           embedding_model_id=settings.embedding_model_id)
    return Deps(operations=OperationCoordinator(repository), now=now_utc,
                repository=repository, writer=writer, settings=settings)


_DEPS_BY_PIPELINE: dict[str, Deps] = {}
"""三條 pipeline 的容器層級相依快取；`deps_for` 是**唯一**的讀寫入口。

原本三個 pipeline 模組各自 `global _DEPS`，`pipeline_task_handler` 因此拿不到
`OperationCoordinator`——雲端逐 Task 失敗時沒有人呼叫 `operations.fail(...)`，`OPS#`
永遠停在 `accepted`（final review A#4／B#3）。把快取收進本模組之後，分派層與三個
`*_handler` 看到的是**同一個** `Deps`，記帳與執行不會用到兩份相依。
"""


def deps_for(pipeline: str) -> Deps:
    """這條 pipeline 的相依；第一次呼叫才組（模組 import 時不碰網路），之後同容器沿用。

    三條 pipeline 統一走 `load_settings(os.environ)`（修正波：原本 feedback 帶
    `os.environ`、ticket／release 不帶，兩者等價但讀起來像有差別）。

    **不吞 `build_deps` 的失敗**：組不起來就代表這個執行環境根本沒有 coordinator，
    例外原樣往外丟給 ASL 的 Catch，不在這裡換成別的型別。
    """
    deps = _DEPS_BY_PIPELINE.get(pipeline)
    if deps is None:
        deps = build_deps(load_settings(os.environ))
        _DEPS_BY_PIPELINE[pipeline] = deps
    return deps


def _state_operation_id(event: Mapping[str, Any]) -> str | None:
    """`event["state"]["operation_id"]`；缺了或型別不對就回 `None`（代表不記帳）。

    ASL 每個 Task 都是 `state.$: $`＋Task 回傳 `{**state, ...}`，所以第一個 Task
    （`ListTargets`／`LocateFeature`／`EnsureEmbedding`）之後這個欄位一定在。
    """
    state = event.get("state")
    operation_id = state.get("operation_id") if isinstance(state, Mapping) else None
    return operation_id if isinstance(operation_id, str) and operation_id else None


def _record_task_failure(pipeline: str, event: Mapping[str, Any], error: Exception) -> None:
    """把一個 Task 的失敗記進 ledger；記不成就只留一行 log，**原例外照樣往外丟**。

    只用**已經組好**的相依（`_DEPS_BY_PIPELINE`）：`build_deps` 自己失敗時根本沒有
    coordinator 可寫，硬組一份只會把原例外換成「缺 TKB_AWS_REGION」之類看不出原因的
    第二個錯誤（final review C 的 soundness caveat）。

    `except Exception` 之後**不再往外丟**是刻意的：ASL 的 `Retry`／`Catch` 比對的是
    Lambda runtime 回報的**類別名字串**，把 `TransientError` 換成記帳時冒出來的
    `CoordinationError` 會讓第一條 retrier 比不中，等於用記帳改壞了重試語意。
    """
    operation_id = _state_operation_id(event)
    deps = _DEPS_BY_PIPELINE.get(pipeline)
    if operation_id is None or deps is None:
        return
    try:
        deps.operations.fail(operation_id, str(error), isinstance(error, TransientError),
                             now=deps.now())
    except Exception as failure:      # noqa: BLE001 - 記帳失敗不得改寫往外丟的 errorType
        _log.warning("operations.fail 失敗（%s）：%s: %s",
                     operation_id, type(failure).__name__, failure)


def pipeline_task_handler(event: dict[str, Any], context: object) -> dict[str, JSONValue]:
    """共用 Lambda `training-kb-pipeline-task` 的唯一入口（00A D-24）。

    依 `event["pipeline"]` 找到那條 pipeline 的直接入口，**只跑 `event["task"]` 那一個
    Task**：整條序列由 Step Functions 的 ASL 串，不是由這裡的迴圈串。

    三種「接不起來」的情況一律轉 `PermanentError`，因為它們都是部署或程式錯誤，重試不會
    變好：pipeline 名稱不在白名單、模組不存在、模組在但 handler 屬性還沒寫（controller
    預建的空殼就是這一種，丟 `AttributeError` 的話 `errorType` 會變成看不出原因的名字）。

    **失敗一律先記 ledger 再原樣往外丟**（修正波：final review A#4／B#3）：這是
    `run_sequence` 早就有的行為，雲端逐 Task 分派卻漏了，所以同一次失敗在本機看得到
    `OPS#` 轉 `failed`、在雲端卻永遠停在 `accepted`。記錄 ≠ 攔截：`raise` 沒有引數，
    往外丟的是**原例外**，`TransientError` 仍然走 ASL 的 Retry、`PermanentError` 仍然
    走 Catch，`*_handler` 那一層照舊不 try／except。

    `maybe_fail_task` 也移進被包住的區域：注入的故障與真實故障在 ledger 上要同形狀，
    否則一次演練會留下「執行失敗但 ledger 乾淨」的假象。
    """
    pipeline = str(event.get("pipeline"))
    target = _PIPELINE_HANDLERS.get(pipeline)
    if target is None:
        raise PermanentError(f"未知的 pipeline：{event.get('pipeline')!r}")
    try:
        maybe_fail_task(pipeline, str(event.get("task")))
        module_name, _, attribute = target.partition(":")
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as error:      # 模組整支不存在
            raise PermanentError(f"{module_name} 尚未建立") from error
        handler = getattr(module, attribute, None)
        if handler is None:                       # 模組在、handler 還沒寫
            raise PermanentError(f"{module_name} 還沒有 {attribute}")
        result: dict[str, JSONValue] = handler(event, context)
    except Exception as error:                    # 記錄後原樣往外丟，重試交給 ASL
        _record_task_failure(pipeline, event, error)
        raise
    return result
