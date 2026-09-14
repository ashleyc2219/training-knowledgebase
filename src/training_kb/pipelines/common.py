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

from training_kb.errors import PermanentError, TransientError
from training_kb.operations import OperationCoordinator

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

    現在只有操作紀錄與時鐘；[Phase 38] 會以「修改本檔」的方式追加 `repository`、
    `writer`、`settings` 三個**預設 `None`** 的欄位與 `need_repository()`／
    `need_writer()`／`need_settings()`（00A D-36）。因為有預設值，現在寫的
    `Deps(operations=..., now=...)` 在 Phase 38 之後仍然成立。
    """

    operations: OperationCoordinator
    now: Callable[[], datetime]


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
