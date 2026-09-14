"""ASL（Amazon States Language）的失敗語意：Task 模板、固定 Retry／Catch 與靜態檢查。

三條 pipeline 的部署定義都由這裡產生片段，保證**每個 Task 都有有界重試，重試耗盡就
進 `PipelineFailed` 這個 `Fail` state**，整次執行不建版、不發布（設計 §14.2、§14.3；
00A §3.7）。`RETRY`／`CATCH`／`task_state` 只有這一份，Phase 41／48／52 一律
`from training_kb.pipelines.asl import CATCH, RETRY, task_state`，不各自抄字面值。

**尚未雲端實證**：Python Lambda 未處理例外在 Step Functions 看到的 `errorType` 是不是
類別名（也就是第一條 retrier 的 `"TransientError"` 會不會命中），由 Phase 41 用
`get-execution-history` 實測；在那之前這裡只是靜態產生與檢查。

部署前的版本化快照也在這裡：本地定義檔 `ASL_LOCAL_PATH` 與 S3 私有快照
`ASL_SNAPSHOT_KEY` 是**同一份 bytes**，用條件寫入保存，事後才追溯得到當時跑的是哪一版。
"""

import json
from collections.abc import Iterable, Mapping

from training_kb.errors import ObjectAlreadyExists, PermanentError
from training_kb.pipelines.common import PIPELINE_NAMES, JSONValue, PipelineName
from training_kb.repository import Repository

# --- 1. 固定常數 -------------------------------------------------------------

FAIL_STATE_NAME = "PipelineFailed"
"""三條 ASL 的 `Fail` state 一律叫這個名字（00A §6.9、D-15／D-53）。"""

TASK_TIMEOUT_SECONDS = 120
"""每個 Task state 的 `TimeoutSeconds`（設計 §14.3 的固定值）。"""

# D-53：兩條固定 retrier，第一條接業務的 TransientError，第二條接 Lambda 服務層的暫時錯誤。
# 寫成唯讀 tuple，呼叫端不會不小心就地改掉共用常數；要放進 ASL 時一律複製成新的 list。
RETRY: tuple[dict[str, JSONValue], ...] = (
    {"ErrorEquals": ["TransientError"],
     "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2},
    {"ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException",
                     "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
     "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2},
)
"""`PermanentError` 刻意不進 `ErrorEquals`：資料確定不合法時直接進 Catch，不空等三次。"""

CATCH: tuple[dict[str, JSONValue], ...] = (
    {"ErrorEquals": ["States.ALL"], "ResultPath": "$.failure", "Next": FAIL_STATE_NAME},
)


def _copies(items: Iterable[Mapping[str, JSONValue]]) -> list[JSONValue]:
    """把唯讀常數複製成可寫的新 list；連 `ErrorEquals` 這層 list 也一起複製。

    只複製一層 dict（`dict(item)`）會讓所有 Task 共用同一個 `ErrorEquals` list，
    任何一處就地 append 就污染全部定義；這裡把 list 值也複製掉，常數才真的是唯讀的。
    """
    copied: list[JSONValue] = []
    for item in items:
        entry: dict[str, JSONValue] = {
            key: list(value) if isinstance(value, list) else value
            for key, value in item.items()
        }
        copied.append(entry)
    return copied


# --- 2. Task 模板 ------------------------------------------------------------


def task_state(resource_arn: str, next_state: str) -> dict[str, JSONValue]:
    """每個 Lambda Task 的唯一模板：直接函式 ARN + 有界 Retry + Catch 到 Fail。

    只給骨架：事件封套 `"Parameters": {"pipeline": ..., "task": ..., "state.$": "$"}`
    （00A D-49）由 Phase 41／48／52 各自補在結果上，因為這個簽名看不到 pipeline 與
    task 名稱。`Resource` 是直接函式 ARN，不用 `arn:aws:states:::lambda:invoke` 信封，
    所以 task result 就是函式輸出，沒有 `Payload` 外層。
    """
    return {"Type": "Task", "Resource": resource_arn, "Next": next_state,
            "TimeoutSeconds": TASK_TIMEOUT_SECONDS,
            "Retry": _copies(RETRY), "Catch": _copies(CATCH)}


# --- 3. 靜態檢查 -------------------------------------------------------------


def assert_safe_asl(definition: dict[str, JSONValue]) -> None:
    """檢查整份定義的失敗語意；不合格丟 `PermanentError`，訊息帶完整 state 路徑。"""
    _check_scope(definition, path="")


def _check_scope(scope: Mapping[str, JSONValue], *, path: str) -> None:
    """遞迴進 `Map` 的 `ItemProcessor`／`Iterator` 與 `Parallel` 的 `Branches`。"""
    states = scope.get("States")
    if not isinstance(states, dict) or not states:
        raise PermanentError(f"ASL 缺少 States：{path or '<root>'}")
    if scope.get("StartAt") not in states:
        raise PermanentError(f"StartAt 不在同層 States 內：{path}{scope.get('StartAt')}")
    for name, state in states.items():
        where = f"{path}{name}"
        if not isinstance(state, dict):
            raise PermanentError(f"state 不是物件：{where}")
        if state.get("Type") == "Task":
            _check_task(state, states, where=where)
        if state.get("Type") == "Choice" and "Default" not in state:
            raise PermanentError(f"Choice 缺少 Default 分支：{where}")
        for key in ("ItemProcessor", "Iterator"):
            nested = state.get(key)
            if isinstance(nested, dict):
                _check_scope(nested, path=f"{where}.{key}.")
        branches = state.get("Branches")
        if isinstance(branches, list):   # Parallel
            for index, branch in enumerate(branches):
                if isinstance(branch, dict):
                    _check_scope(branch, path=f"{where}.Branches[{index}].")


def _check_task(state: Mapping[str, JSONValue], states: Mapping[str, JSONValue],
                *, where: str) -> None:
    """一個 Task 的三件事：前兩條 retrier 逐字相同、沒有 retrier 涵蓋 `States.ALL`、
    有一條 `States.ALL` 的 Catch 導向**同一層**的 `Fail` state。"""
    retries = state.get("Retry")
    catches = state.get("Catch")
    retry_items: list[JSONValue] = retries if isinstance(retries, list) else []
    catch_items: list[JSONValue] = catches if isinstance(catches, list) else []
    if retry_items[: len(RETRY)] != _copies(RETRY):
        raise PermanentError(f"Task 的前 {len(RETRY)} 條 Retry 不是固定參數：{where}")
    for item in retry_items:
        errors = item.get("ErrorEquals") if isinstance(item, dict) else None
        if isinstance(errors, list) and "States.ALL" in errors:
            raise PermanentError(f"Retry 不得涵蓋 States.ALL：{where}")
    catch = catch_items[0] if len(catch_items) == 1 else None
    if not isinstance(catch, dict) or catch.get("ErrorEquals") != ["States.ALL"]:
        raise PermanentError(f"Task 缺少 States.ALL 的 Catch：{where}")
    target = catch.get("Next")
    destination = states.get(target) if isinstance(target, str) else None
    if not isinstance(destination, dict) or destination.get("Type") != "Fail":
        raise PermanentError(f"Catch 沒有導向同層的 Fail state：{where} -> {target}")


# --- 4. 版本化快照 -----------------------------------------------------------

ASL_LOCAL_PATH = "infra/stepfunctions/{pipeline}/v{number}.json"
"""本地定義檔；三份實際定義由 Phase 41／48／52 各自建立，本模組只給路徑樣板。"""

ASL_SNAPSHOT_KEY = "stepfunctions/{pipeline}/v{number}.json"
"""S3 私有快照（00A §3.4）。`<pipeline>.asl.json` 那種單檔佈局已作廢。"""


def canonical_json(definition: dict[str, JSONValue]) -> bytes:
    """固定序列化方式，讓同一份定義每次產出相同 bytes。"""
    return json.dumps(definition, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def save_asl_snapshot(repository: Repository, pipeline: PipelineName,
                      number: int, body: bytes) -> str:
    """把定義存成 `stepfunctions/<pipeline>/v<n>.json`，回傳 key。

    條件寫入（`if_none_match=True`）撞到同一個 key 時**先核對 bytes**：完全相同代表
    同一次部署重送，視為冪等；不同就是有人想改掉既有版本的歷史，一律 `PermanentError`，
    既有快照保持原樣。版本號與教學版本無關，由部署者遞增。
    """
    if pipeline not in PIPELINE_NAMES:
        raise PermanentError(f"unknown pipeline: {pipeline}")
    key = ASL_SNAPSHOT_KEY.format(pipeline=pipeline, number=number)
    try:
        repository.put_object(key, body, "application/json", if_none_match=True)
    except ObjectAlreadyExists:
        if repository.get_object(key) != body:
            raise PermanentError(f"ASL 快照已存在且內容不同：{key}") from None
    return key
