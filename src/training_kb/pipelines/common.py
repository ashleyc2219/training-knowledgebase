"""三條 Standard Step Functions 共用的本機 Task 執行契約（設計 §5、§14.2、§14.3）。

`run_sequence` 把一串 Task 依序跑完，**自己不重試**：重試只由 ASL 的 `Retry` 管理
（00A §3.7「只有一層管理重試」），Lambda 內再疊一層會讓次數相乘。任何一個 Task
丟例外時，先用 `OperationCoordinator.fail(...)` 留下可追溯紀錄，再把**原例外**往外丟，
讓 Step Functions 的 `Catch` 導向 `PipelineFailed`，整次執行不建版、不發布。
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, get_args

from training_kb.config import Settings
from training_kb.errors import PermanentError, TransientError
from training_kb.operations import OperationCoordinator
from training_kb.repository import Repository
from training_kb.writing.client import Writer

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
