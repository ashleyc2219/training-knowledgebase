"""三條 Standard Step Functions 共用的本機 Task 執行契約（設計 §5、§14.2、§14.3）。

`run_sequence` 把一串 Task 依序跑完，**自己不重試**：重試只由 ASL 的 `Retry` 管理
（00A §3.7「只有一層管理重試」），Lambda 內再疊一層會讓次數相乘。任何一個 Task
丟例外時，先用 `OperationCoordinator.fail(...)` 留下可追溯紀錄，再把**原例外**往外丟，
讓 Step Functions 的 `Catch` 導向 `PipelineFailed`，整次執行不建版、不發布。
"""

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from typing import Any, Literal, get_args

import boto3

from training_kb import faults
from training_kb.clock import now_utc
from training_kb.config import Settings
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
    """
    values: Mapping[str, str] = os.environ if env is None else env
    if values.get(faults.ENV_NAME_ENV) == faults.PRODUCTION:
        return
    if values.get(FAULT_TASK_ENV, "") == f"{pipeline}:{task}":
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


def pipeline_task_handler(event: dict[str, Any], context: object) -> dict[str, JSONValue]:
    """共用 Lambda `training-kb-pipeline-task` 的唯一入口（00A D-24）。

    依 `event["pipeline"]` 找到那條 pipeline 的直接入口，**只跑 `event["task"]` 那一個
    Task**：整條序列由 Step Functions 的 ASL 串，不是由這裡的迴圈串。

    這一層與 `*_handler` 都**不 try／except**：`TransientError` 要讓 ASL 的 Retry 抓到，
    `PermanentError` 要讓 Catch 抓到。三種「接不起來」的情況一律轉 `PermanentError`，
    因為它們都是部署或程式錯誤，重試不會變好：pipeline 名稱不在白名單、模組不存在、
    模組在但 handler 屬性還沒寫（controller 預建的空殼就是這一種，丟 `AttributeError`
    的話 `errorType` 會變成看不出原因的名字）。
    """
    pipeline = str(event.get("pipeline"))
    target = _PIPELINE_HANDLERS.get(pipeline)
    if target is None:
        raise PermanentError(f"未知的 pipeline：{event.get('pipeline')!r}")
    maybe_fail_task(pipeline, str(event.get("task")))
    module_name, _, attribute = target.partition(":")
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as error:      # 模組整支不存在
        raise PermanentError(f"{module_name} 尚未建立") from error
    handler = getattr(module, attribute, None)
    if handler is None:                       # 模組在、handler 還沒寫（P48／P52 未實作）
        raise PermanentError(f"{module_name} 還沒有 {attribute}")
    result: dict[str, JSONValue] = handler(event, context)
    return result
