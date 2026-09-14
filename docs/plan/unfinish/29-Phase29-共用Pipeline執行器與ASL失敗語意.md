# Phase 29：共用 Pipeline 執行器與 ASL 失敗語意實作計畫

> **給 agentic worker：** 必須使用 `superpowers:subagent-driven-development`（建議）或 `superpowers:executing-plans`，逐一執行本文件的 checkbox。

**目標：** 建立三條 Standard Step Functions 共用的 Task 執行契約，保證有限重試耗盡後進入 `Fail`，整次執行不發布新版。

**架構：** Lambda handler 以 `run_sequence` 執行同一套本機契約；部署用 ASL 則由產生器為每個 `Task` 補齊 `Retry` 與 `Catch`。兩者都把失敗寫入 operation，但不在這個 Phase 實作 Ticket、Release 或 Feedback 的業務狀態機。

**技術：** Python 3.12、pytest、AWS Step Functions Standard Workflow、Amazon States Language（ASL）。

## 1. 文件定位

- **讀者：** 第一次接觸 Step Functions、但會 Python 與 pytest 的工程師。**唯一主來源：** [Training KB 設計 §5、§9.3、§14.2、§14.3、§20.3](../../design/training-kb.md)。名稱與簽名以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 6.9 節（`pipelines`）與第 7 節（三條 pipeline 契約）為準；兩邊不一致時改本文件，不改 00A。
- **前置 Phase：** [Phase 02 設定時間與錯誤契約](02-Phase02-設定時間與錯誤契約.md) 的錯誤型別、[Phase 07 S3 物件與關係邊讀寫](07-Phase07-S3物件與關係邊讀寫.md) 的條件寫入、[Phase 10 O2 操作紀錄與永久去重契約](10-Phase10-O2操作紀錄與永久去重契約.md) 與 [Phase 11 O2 接受順序與重啟整合驗證](11-Phase11-O2接受順序與重啟整合驗證.md) 的 operation 契約、[Phase 12 O3 發布切換整合驗證](12-Phase12-O3發布切換整合驗證.md) 的 gate 結果。前置未通過時停止。
- **前一份：** [Phase 28 引用 Backfill 與規則投影重建](28-Phase28-引用Backfill與規則投影重建.md)。**下一份：** [Phase 30 GitHub Webhook 原始 Body 驗簽](30-Phase30-GitHub-Webhook原始Body驗簽.md)。**下游：** [Phase 38](38-Phase38-Ticket-Embedding與群中心分群.md) 以「修改」方式替 `Deps` 追加三個欄位；[Phase 41](41-Phase41-Ticket-Analysis雲端流程驗收.md)、[Phase 48](48-Phase48-Feedback-Review排程流程.md)、[Phase 52](52-Phase52-Release-RETIRE與流程驗收.md) 把具體節點接到這個骨架。
- **本階段不做：** 不建立第四條 pipeline；不寫三條 pipeline 的業務 Task；不產生正式 ASL 檔（`infra/stepfunctions/<pipeline>/v1.json` 由 Phase 41、48、52 各自建立，本 Phase 只測產生器與檢查器）；不建立 state machine、不部署、不發布教學。
- **與本 Phase 有關的 gate：** O2（操作紀錄與接受順序）與 O3（發布提交）都尚未 PASS。本 Phase 只能宣稱「本機契約測試通過」，**不得宣稱雲端流程通過**，也不得啟用任何會建版或公開發布的路徑。ASL 的 `Retry` 是否真的命中 Python Lambda 的 `errorType`，由 Phase 41 用 `get-execution-history` 實證；實證前不得寫成已驗證。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

## 2. 你在整體流程的位置

```text
Ingress（Phase 30-32）
   |  ASL input 只有 operation_id / project_id / input_ref
   v
[你在這裡] 共用 run_sequence + ASL Task 模板
   |                  |
   | 成功             +-- Retry 耗盡 --> Catch --> Fail（PipelineFailed）
   v                                          |
Phase 41 / 48 / 52 的業務節點                  +--> 不 publish、不建版
```

三條固定名稱只有：`ticket-analysis`、`release-update`、`feedback-review`。沒有第四條教學 pipeline；Analytics 是獨立 Lambda，不是 pipeline。

## 3. 完成後看得到什麼

輸入一個只含 `operation_id="op-ticket-t_881"`、`project_id="demo"`、`input_ref="operations/op-ticket-t_881/input.json"` 的測試 payload，兩個 Task 依序回傳資料，最終結果是三個輸入欄位加上 Task 寫入的 `ticket_id="t_881"`。若第二個 Task 丟出 `PermanentError("invalid business result")`，`run_sequence` 會先呼叫 `operations.fail("op-ticket-t_881", "invalid business result", False, now=...)` 再把例外往外丟；後續 Task 不會被呼叫，publish spy 的呼叫次數為 0。

## 4. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| ASL | Amazon States Language，用一份 JSON 描述流程有哪些 state、怎麼接。 |
| `Task`／`Fail`／`Succeed`／`Choice`／`Map` | ASL 的 state 型態：做事、明確失敗、明確成功、分支、逐項處理。 |
| `Retry`／`Catch` | `Retry` 是同一個 `Task` 內的有限重試設定（等幾秒、幾次、倍率）；`Catch` 是重試耗盡後的失敗分支，固定導向 `PipelineFailed` 這個 `Fail` state。 |
| Step／Task | Step 是教學裡的操作步驟；Task 是 Step Functions 的工作節點，兩者不可混稱。 |
| `JSONValue` | 「可以直接寫進 JSON 的值」的型別別名，全專案只在 `pipelines/common.py` 定義一次。 |
| `Deps` | 一個 Task 需要的外部相依（操作紀錄、時鐘，之後還有 repository／writer／settings）打包成的唯讀物件。 |

## 5. 預計新增／修改檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `src/training_kb/pipelines/__init__.py`、`common.py` | 套件入口（**不 re-export**，00A 第 6.9 節把 import 路徑定在 `pipelines.common`／`pipelines.asl`）；`PipelineName`、`JSONValue`、`TaskFn`、`PIPELINE_NAMES`、`Deps`、`run_sequence`。 |
| 新增 | `src/training_kb/pipelines/asl.py` | `task_state`、`assert_safe_asl`、`canonical_json`、`save_asl_snapshot`，以及 `FAIL_STATE_NAME`、`TASK_TIMEOUT_SECONDS`、`RETRY`、`CATCH`、`ASL_LOCAL_PATH`、`ASL_SNAPSHOT_KEY` 六個固定常數。 |
| 新增 | `tests/unit/pipelines/test_common.py`、`test_asl.py` | 順序與失敗終止；每個 `Task`（含 `Map` 內）都有 `Retry`／`Catch`／`Fail` 與快照條件寫入。 |
| 消費 | `src/training_kb/errors.py`、`operations.py`、`repository.py` | 錯誤型別、`OperationCoordinator.fail`、`put_object`／`get_object`。 |

`infra/stepfunctions/<pipeline>/v1.json` 三份實際定義檔不在本 Phase 建立；本 Phase 只保證「產生它們的模板」與「檢查它們的函式」被測試鎖住。

表中的 `common.py` 之後還會被 [Phase 38](38-Phase38-Ticket-Embedding與群中心分群.md) 以「修改」方式再動一次：替 `Deps` 追加 `repository`、`writer`、`settings` 三個預設 `None` 的欄位（00A 第 8 節 D-36）。本 Phase 只建立 `operations`／`now` 兩欄的版本，不要先預留那三個欄位。

## 6. 固定介面

### Consumes

```text
OperationCoordinator.fail(operation_id: str, error: str, retryable: bool, *, now: datetime) -> None   # Phase 10
Repository.put_object(key: str, body: bytes, content_type: str, *, if_none_match: bool) -> None       # Phase 07
Repository.get_object(key: str) -> bytes | None                                                       # Phase 07
TransientError / PermanentError（Phase 02）、ObjectAlreadyExists（Phase 07，PermanentError 子類，S3 412）
```

### Produces

```python
# pipelines/common.py
PipelineName = Literal["ticket-analysis", "release-update", "feedback-review"]
JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
TaskFn = Callable[[dict[str, JSONValue], "Deps"], dict[str, JSONValue]]

@dataclass(frozen=True)
class Deps:
    operations: OperationCoordinator
    now: Callable[[], datetime]

def run_sequence(pipeline: PipelineName, payload: dict[str, JSONValue],
                 tasks: Sequence[TaskFn], deps: Deps) -> dict[str, JSONValue]: ...
PIPELINE_NAMES: tuple[str, ...]           # = get_args(PipelineName)，就是上面三個名稱

# pipelines/asl.py
TASK_TIMEOUT_SECONDS = 120
FAIL_STATE_NAME = "PipelineFailed"
RETRY: tuple[dict[str, JSONValue], ...]   # D-53：固定兩條 retrier，兩條都是 1 秒／2 次／倍率 2
CATCH: tuple[dict[str, JSONValue], ...]   # 一條 States.ALL -> PipelineFailed（ResultPath 是 $.failure）
ASL_LOCAL_PATH = "infra/stepfunctions/{pipeline}/v{number}.json"
ASL_SNAPSHOT_KEY = "stepfunctions/{pipeline}/v{number}.json"
def task_state(resource_arn: str, next_state: str) -> dict[str, JSONValue]: ...
def assert_safe_asl(definition: dict[str, JSONValue]) -> None: ...
def canonical_json(definition: dict[str, JSONValue]) -> bytes: ...
def save_asl_snapshot(repository: Repository, pipeline: PipelineName,
                      number: int, body: bytes) -> str: ...
```

- `run_sequence` **不自行重試**；`Retry` 只由 ASL 管理，避免 Lambda 與 Step Functions 疊加重試（設計 §14.3「只讓一層管理重試」）。Task 輸入不得放 webhook 原始 body、教學全文、Release evidence 原文、回饋留言或向量，只傳裸 ID 與私有 S3 key。
- `JSONValue` 只有這一個定義；Phase 36 與其他需要它的模組一律從 `training_kb.pipelines.common` import，不得各寫一份。`Deps` 在 [Phase 38](38-Phase38-Ticket-Embedding與群中心分群.md) 會以「修改本檔」的方式追加 `repository`、`writer`、`settings` 三個預設 `None` 的欄位與 `need_repository()`／`need_writer()`／`need_settings()`。因為有預設值，本 Phase 寫的 `Deps(operations=..., now=...)` 測試在 Phase 38 之後仍成立；沒接線就取用時由 `need_*` 丟 `PermanentError`，不會拿到 `None` 才在深處爆炸。
- 三條 pipeline 的 `*_TASKS`、`run_*`、`*_handler`，以及共用 Lambda 入口 `pipeline_task_handler(event, context)`、`task_name(task)`、`build_deps(settings)` 都**不在本 Phase 產出**：前者由 Phase 41、48、52 各自產出，後三者由 [Phase 41](41-Phase41-Ticket-Analysis雲端流程驗收.md) 加在 `pipelines/common.py`（00A 第 8 節 D-24）。本 Phase 只要讓 `common.py` 的形狀能直接接上它們。

## 7. 設計細節

一次 Task 失敗的完整路徑固定如下（設計 §14.2、§14.3；00A 第 3.7 節）：

```text
Lambda 丟 TransientError            --> ASL Retry 第 1 條: 等 1 秒 -> 等 2 秒 -> 仍失敗
Lambda 服務層暫時錯誤（Lambda.*）    --> ASL Retry 第 2 條: 等 1 秒 -> 等 2 秒 -> 仍失敗
Lambda 丟 PermanentError            --> 不重試（刻意不列進 ErrorEquals）
                                   |
                                   v
              Catch: States.ALL -> PipelineFailed（Type=Fail）
                                   |
                                   v
   OperationCoordinator.fail(op, error, retryable) -> 整次失敗、不建版、不 publish
```

三個固定數值來自設計 §14.3「最多重試兩次，等待 1 秒、2 秒」，所以 ASL 固定寫 `IntervalSeconds: 1`、`MaxAttempts: 2`、`BackoffRate: 2`，同一張表另外規定 Task 時限 `TimeoutSeconds: 120`。依 00A 第 8 節裁決 D-53，**每個 Task 固定兩條 `Retry`**：第一條的 `ErrorEquals` 是 `["TransientError"]`（業務自己丟的暫時錯誤；Python Lambda 未處理例外的 `errorType` 就是類別名，所以不加任何前綴），第二條是 Lambda 服務層自己的四個暫時錯誤 `Lambda.ServiceException`、`Lambda.AWSLambdaException`、`Lambda.SdkClientException`、`Lambda.TooManyRequestsException`（函式還沒開始跑就失敗的情況，例如服務端暫時故障或被限流），兩條的等待秒數與次數完全相同。Lambda Task 一律用**直接函式 ARN**（`"Resource": "<function arn>"`），不用 `arn:aws:states:::lambda:invoke` 信封，所以 task result 就是函式輸出，沒有 `Payload` 外層。`Choice` state 沒有 `Retry`／`Catch` 是正確的，但必須有 `Default` 分支。

## 8. Task 1：先固定本機序列的成功與失敗

- [x] **Step 1：建立失敗測試**

```python
# tests/unit/pipelines/test_common.py
from datetime import UTC, datetime
import pytest
from training_kb.errors import PermanentError
from training_kb.pipelines.common import Deps, run_sequence

INPUT = {"operation_id": "op-ticket-t_881", "project_id": "demo",
         "input_ref": "operations/op-ticket-t_881/input.json"}

class FakeOperations:
    """只記錄呼叫的假 OperationCoordinator，不碰 DynamoDB。"""
    def __init__(self) -> None:
        self.failures: list[tuple[str, str, bool]] = []
    def fail(self, operation_id: str, error: str, retryable: bool, *, now: datetime) -> None:
        self.failures.append((operation_id, error, retryable))

def make_deps() -> tuple[Deps, FakeOperations]:
    operations = FakeOperations()
    return Deps(operations=operations, now=lambda: datetime(2026, 9, 13, tzinfo=UTC)), operations

def test_run_sequence_stops_at_first_failure() -> None:
    calls: list[str] = []
    def ok(value, deps):
        calls.append("ok")
        return {**value, "ticket_id": "t_881"}
    def broken(value, deps):
        calls.append("broken")
        raise PermanentError("invalid business result")
    deps, operations = make_deps()
    with pytest.raises(PermanentError):
        run_sequence("ticket-analysis", INPUT, [ok, broken], deps)
    assert calls == ["ok", "broken"]
    assert operations.failures == [("op-ticket-t_881", "invalid business result", False)]
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/pipelines/test_common.py -q
```

預期：FAIL，訊號包含 `cannot import name 'run_sequence'`。若測試直接綠燈，先確認不是讀到舊實作或同名檔案。

- [x] **Step 3：建立最小實作**

```python
# src/training_kb/pipelines/common.py
# PipelineName / JSONValue / TaskFn / Deps 逐字照第 6 節 Produces，這裡只列新增的部分。
from typing import get_args
from training_kb.errors import PermanentError, TransientError

PIPELINE_NAMES: tuple[str, ...] = get_args(PipelineName)

def run_sequence(pipeline: PipelineName, payload: dict[str, JSONValue],
                 tasks: Sequence[TaskFn], deps: Deps) -> dict[str, JSONValue]:
    if pipeline not in PIPELINE_NAMES:
        raise PermanentError(f"unknown pipeline: {pipeline}")
    operation_id = payload.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise PermanentError("payload 缺少 operation_id")
    value = dict(payload)
    try:
        for task in tasks:
            value = task(value, deps)
    except Exception as exc:   # 記錄後原樣往外丟，重試交給 ASL
        deps.operations.fail(operation_id, str(exc), isinstance(exc, TransientError), now=deps.now())
        raise
    return value
```

`except Exception` 是刻意的：`PublishError` 與 `CoordinationError` 在 00A 第 4.1 節不是 `PermanentError` 的子類，只攔那兩類會讓它們繞過操作紀錄。攔下來之後**一定 `raise` 原例外**，不吞錯、不改成回傳值；`retryable` 只看是不是 `TransientError`。

- [x] **Step 4：補邊界測試並跑 `uv run pytest tests/unit/pipelines/test_common.py -q` 確認綠燈**

補五個案例：成功路徑（結果保留輸入三欄並合併 Task 產出）、失敗後的第三個 Task 不被呼叫、未知名稱（`run_sequence("analytics", ...)` 丟 `PermanentError`，證明沒有第四條 pipeline）、`tasks=[]`（回傳輸入的複本且沒有任何 `fail` 呼叫）、`TransientError`（斷言 `failures == [("op-ticket-t_881", "bedrock timeout", True)]` 且該 Task 只被呼叫一次）。預期：全部 PASS；`failures` 第三欄在 `TransientError` 時是 `True`、`PermanentError` 時是 `False`。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/__init__.py src/training_kb/pipelines/common.py tests/unit/pipelines/test_common.py
git commit -m "feat(pipelines): 建立共用執行契約"
```

## 9. Task 2：讓每個 ASL Task 都有 Retry 與 Catch

- [x] **Step 1：建立失敗測試**

```python
# tests/unit/pipelines/test_asl.py
import pytest
from training_kb.errors import PermanentError
from training_kb.pipelines.asl import assert_safe_asl, task_state

TASK_ARN = "arn:aws:lambda:ap-northeast-1:123456789012:function:training-kb-pipeline-task"

def sample_definition() -> dict:
    return {
        "Comment": "ticket-analysis v1",
        "StartAt": "EnsureEmbedding",
        "States": {
            "EnsureEmbedding": task_state(TASK_ARN, "AssignCluster"),
            "AssignCluster": task_state(TASK_ARN, "Done"),
            "Done": {"Type": "Succeed"},
            "PipelineFailed": {"Type": "Fail", "Error": "PipelineFailed", "Cause": "本次不建版也不發布"},
        },
    }

def test_every_task_retries_then_catches_to_fail() -> None:
    definition = sample_definition()
    assert_safe_asl(definition)
    for state in definition["States"].values():
        if state["Type"] != "Task":
            continue
        assert state["Resource"] == TASK_ARN   # 直接函式 ARN，沒有 lambda:invoke 信封
        business, service = state["Retry"][0], state["Retry"][1]   # D-53：固定兩條 retrier
        assert business["ErrorEquals"] == ["TransientError"]
        assert service["ErrorEquals"] == ["Lambda.ServiceException", "Lambda.AWSLambdaException",
                                          "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]
        for retry in (business, service):
            assert (retry["IntervalSeconds"], retry["MaxAttempts"], retry["BackoffRate"]) == (1, 2, 2)
        assert state["TimeoutSeconds"] == 120
        assert state["Catch"][0]["ErrorEquals"] == ["States.ALL"]
        assert state["Catch"][0]["Next"] == "PipelineFailed"
    assert definition["States"]["PipelineFailed"]["Type"] == "Fail"

def test_missing_catch_inside_map_is_rejected() -> None:
    definition = sample_definition()
    inner = task_state(TASK_ARN, "InnerDone")
    del inner["Catch"]
    definition["States"]["AssignCluster"] = {
        "Type": "Map", "Next": "Done",
        "ItemProcessor": {"StartAt": "InnerTask",
                          "States": {"InnerTask": inner, "InnerDone": {"Type": "Succeed"}}},
    }
    with pytest.raises(PermanentError) as error:
        assert_safe_asl(definition)
    assert "AssignCluster.ItemProcessor.InnerTask" in str(error.value)

def test_task_with_only_the_first_retrier_is_rejected() -> None:
    definition = sample_definition()
    definition["States"]["AssignCluster"]["Retry"] = [definition["States"]["AssignCluster"]["Retry"][0]]
    with pytest.raises(PermanentError) as error:
        assert_safe_asl(definition)
    assert "AssignCluster" in str(error.value)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/pipelines/test_asl.py -q
```

預期：FAIL，訊號包含 `cannot import name 'task_state'`。

- [x] **Step 3：建立最小實作**

```python
# src/training_kb/pipelines/asl.py
from training_kb.errors import PermanentError
from training_kb.pipelines.common import JSONValue

FAIL_STATE_NAME = "PipelineFailed"
TASK_TIMEOUT_SECONDS = 120
# D-53：兩條固定 retrier，第一條接業務的 TransientError，第二條接 Lambda 服務層的暫時錯誤。
# 寫成唯讀 tuple，呼叫端不會不小心就地改掉共用常數；要放進 ASL 時一律複製成新的 list。
RETRY: tuple[dict[str, JSONValue], ...] = (
    {"ErrorEquals": ["TransientError"],
     "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2},
    {"ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException",
                     "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
     "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2},
)
CATCH: tuple[dict[str, JSONValue], ...] = (
    {"ErrorEquals": ["States.ALL"], "ResultPath": "$.failure", "Next": FAIL_STATE_NAME},
)

def task_state(resource_arn: str, next_state: str) -> dict[str, JSONValue]:
    """每個 Lambda Task 的唯一模板：直接函式 ARN + 有界 Retry + Catch 到 Fail。"""
    return {"Type": "Task", "Resource": resource_arn, "Next": next_state,
            "TimeoutSeconds": TASK_TIMEOUT_SECONDS,
            "Retry": [dict(item) for item in RETRY], "Catch": [dict(item) for item in CATCH]}

def assert_safe_asl(definition: dict[str, JSONValue]) -> None:
    _check_scope(definition, path="")

def _check_scope(scope: dict, *, path: str) -> None:
    states = scope.get("States")
    if not isinstance(states, dict) or not states:
        raise PermanentError(f"ASL 缺少 States：{path or '<root>'}")
    if scope.get("StartAt") not in states:
        raise PermanentError(f"StartAt 不在同層 States 內：{path}{scope.get('StartAt')}")
    for name, state in states.items():
        where = f"{path}{name}"
        if state.get("Type") == "Task":
            _check_task(state, states, where=where)
        if state.get("Type") == "Choice" and "Default" not in state:
            raise PermanentError(f"Choice 缺少 Default 分支：{where}")
        for key in ("ItemProcessor", "Iterator"):
            if isinstance(state.get(key), dict):
                _check_scope(state[key], path=f"{where}.{key}.")
        for index, branch in enumerate(state.get("Branches") or []):   # Parallel
            _check_scope(branch, path=f"{where}.Branches[{index}].")

def _check_task(state: dict, states: dict, *, where: str) -> None:
    retries, catches = state.get("Retry") or [], state.get("Catch") or []
    if list(retries[: len(RETRY)]) != [dict(item) for item in RETRY]:
        raise PermanentError(f"Task 的前 {len(RETRY)} 條 Retry 不是固定參數：{where}")
    if any("States.ALL" in (item.get("ErrorEquals") or []) for item in retries):
        raise PermanentError(f"Retry 不得涵蓋 States.ALL：{where}")
    if len(catches) != 1 or catches[0].get("ErrorEquals") != ["States.ALL"]:
        raise PermanentError(f"Task 缺少 States.ALL 的 Catch：{where}")
    target = catches[0].get("Next")
    if not isinstance(target, str) or states.get(target, {}).get("Type") != "Fail":
        raise PermanentError(f"Catch 沒有導向同層的 Fail state：{where} -> {target}")
```

實作與上面草稿有兩處必要差異（mypy strict 與共用常數安全，2026-09-14 實作時修正）：
（a）`task_state` 用私有的 `_copies(...)` 取代 `[dict(item) for item in RETRY]`——`dict(item)` 是淺複製，所有 Task 會共用同一個 `ErrorEquals` list，任何一處就地 append 就污染全部定義；`_copies` 連 list 值一起複製，產出的 JSON 完全相同。（b）`_check_scope`／`_check_task` 的參數型別是 `Mapping[str, JSONValue]`，取值後一律 `isinstance` 收斂（`JSONValue` 是 union，裸 `dict` 註記過不了 `mypy --strict`）；順帶多一條檢查：`States` 裡的值不是物件時丟 `PermanentError(f"state 不是物件：{where}")`。

`_check_scope` 會遞迴進 `Map` 的 `ItemProcessor`／`Iterator` 與 `Parallel` 的 `Branches`，錯誤訊息帶完整 state 路徑，所以漏掉保護的是哪一個節點看得出來。`Catch` 的目標只在**同一層** `States` 內找，因為 ASL 不允許從 `Map` 內部跳到外層 state。`task_state` 只給骨架：事件封套 `"Parameters": {"pipeline": ..., "task": ..., "state.$": "$"}`（00A D-49）由 Phase 41、48、52 各自補在結果上，因為這個簽名看不到 pipeline 與 task 名稱。

`assert_safe_asl` 強制每個 Task 的 `Retry` **前兩條**與 `RETRY` 逐字相同（00A 第 8 節 D-53），而且任何一條 retrier 都不得涵蓋 `States.ALL`——那等於連 `PermanentError` 也重試，資料不合法時白等三次。第三條之後的有界 retrier 不擋，但三條 pipeline 目前都只用這兩條，[Phase 41](41-Phase41-Ticket-Analysis雲端流程驗收.md)、[Phase 48](48-Phase48-Feedback-Review排程流程.md)、[Phase 52](52-Phase52-Release-RETIRE與流程驗收.md) 一律 `from training_kb.pipelines.asl import CATCH, RETRY, task_state`，不各自抄一份字面值。

- [x] **Step 4：跑 `uv run pytest tests/unit/pipelines/test_asl.py -q` 確認綠燈**

預期：三個測試都 PASS。再手動把 `sample_definition()` 其中一個 Task 的 `Catch` 刪掉重跑一次，必須紅燈；確認後改回來。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/asl.py tests/unit/pipelines/test_asl.py
git commit -m "test(pipelines): 鎖定ASL失敗語意"
```

## 10. Task 3：保存版本化 ASL 快照

- [x] **Step 1：建立失敗測試**

```python
# 續寫 tests/unit/pipelines/test_asl.py
from training_kb.errors import ObjectAlreadyExists
from training_kb.pipelines.asl import canonical_json, save_asl_snapshot

class FakeRepository:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
    def put_object(self, key: str, body: bytes, content_type: str, *, if_none_match: bool) -> None:
        if if_none_match and key in self.objects:
            raise ObjectAlreadyExists(key)
        self.objects[key] = body
    def get_object(self, key: str) -> bytes | None:
        return self.objects.get(key)

def test_snapshot_versioned_and_never_overwritten() -> None:
    repository = FakeRepository()
    body = canonical_json(sample_definition())
    key = save_asl_snapshot(repository, "ticket-analysis", 1, body)
    assert key == "stepfunctions/ticket-analysis/v1.json"
    assert save_asl_snapshot(repository, "ticket-analysis", 1, body) == key   # 同內容重送＝冪等
    with pytest.raises(PermanentError):
        save_asl_snapshot(repository, "ticket-analysis", 1, body + b"\n")
    assert repository.objects[key] == body
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/pipelines/test_asl.py -q -k snapshot
```

預期：FAIL，訊號包含 `cannot import name 'save_asl_snapshot'`。

- [x] **Step 3：建立最小實作**

```python
# 續寫 src/training_kb/pipelines/asl.py
import json
from training_kb.errors import ObjectAlreadyExists
from training_kb.pipelines.common import PIPELINE_NAMES, PipelineName

ASL_LOCAL_PATH = "infra/stepfunctions/{pipeline}/v{number}.json"
ASL_SNAPSHOT_KEY = "stepfunctions/{pipeline}/v{number}.json"

def canonical_json(definition: dict[str, JSONValue]) -> bytes:
    """固定序列化方式，讓同一份定義每次產出相同 bytes。"""
    return json.dumps(definition, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")

def save_asl_snapshot(repository, pipeline: PipelineName, number: int, body: bytes) -> str:
    if pipeline not in PIPELINE_NAMES:
        raise PermanentError(f"unknown pipeline: {pipeline}")
    key = ASL_SNAPSHOT_KEY.format(pipeline=pipeline, number=number)
    try:
        repository.put_object(key, body, "application/json", if_none_match=True)
    except ObjectAlreadyExists:
        if repository.get_object(key) != body:
            raise PermanentError(f"ASL 快照已存在且內容不同：{key}") from None
    return key
```

實作把 `repository` 註記成 00A 第 6.9 節的 `Repository`（草稿沒有註記，`mypy --strict` 不接受）；測試用鴨子型別的 `FakeRepository`，`mypy` 不掃 `tests/`，兩邊不衝突。

本地定義檔是 `ASL_LOCAL_PATH`（`infra/stepfunctions/ticket-analysis/v1.json`），S3 私有快照是 `ASL_SNAPSHOT_KEY`（`stepfunctions/ticket-analysis/v1.json`），兩者是**同一份 bytes**；簡報早期寫的 `<pipeline>.asl.json` 單檔佈局已作廢，不要再出現。版本號與教學版本無關，由部署者遞增。

- [x] **Step 4：跑 `uv run pytest tests/unit/pipelines -q` 確認綠燈**

預期：`test_common.py` 與 `test_asl.py` 全綠；不同內容撞同 key 時是 `PermanentError`，既有物件內容保持不變。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/asl.py tests/unit/pipelines/test_asl.py
git commit -m "feat(pipelines): 保存ASL版本快照"
```

## 11. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | `run_sequence("ticket-analysis", INPUT, [ok, ok2], deps)` | 回傳含 `operation_id`／`project_id`／`input_ref` 與 Task 產出；`operations.failures == []`。 |
| Failure | 第二個 Task 丟 `PermanentError("invalid business result")` | 例外往外丟；`failures == [("op-ticket-t_881", "invalid business result", False)]`；第三個 Task 未被呼叫；publish spy 為 0。丟 `TransientError("bedrock timeout")` 時同形狀但 `retryable` 為 `True`，且 `run_sequence` 自己**沒有**重試（Task 只被呼叫一次）。 |
| Boundary | `run_sequence("analytics", ...)`、payload 缺 `operation_id`、`tasks=[]` | 前兩者 `PermanentError`；`tasks=[]` 回傳輸入複本且無 `fail` 呼叫。 |
| Boundary | `Map.ItemProcessor` 內的 Task 缺 `Catch`、`Choice` 缺 `Default`、Retry 涵蓋 `States.ALL` | `assert_safe_asl` 丟 `PermanentError`，訊息含完整 state 路徑。 |
| Boundary | 同 key 同 bytes 重送／同 key 不同 bytes | 前者冪等回同一個 key；後者 `PermanentError` 且既有快照不被覆蓋。 |

人工驗收（不能只看 PASS）：打開產生的 ASL 片段，用眼睛確認每個 `Task` 的 `Resource` 是函式 ARN、`Retry` 的前兩條逐字等於 `RETRY`（業務的 `TransientError` 一條、四個 `Lambda.*` 服務層錯誤一條）、`Catch` 指向 `PipelineFailed`；確認 `run_sequence` 原始碼裡沒有任何 `for attempt in range(...)`、`time.sleep` 或 SDK retry 設定；確認 `Deps` 只有 `operations` 與 `now` 兩個欄位。**停止條件：** O2 或 O3 gate 尚未通過時，可完成本骨架，但不得啟用會建版或公開發布的雲端路徑，也不得把本機 fixture 稱為「雲端流程通過」。

## 12. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| Lambda 與 ASL 各重試一輪，總共四次 | 兩層 retry 疊加 | 移除 handler 內的重試與 SDK retry 設定，只留 ASL；重新核對呼叫計數。 |
| `Catch` 之後接到 `Succeed` | 把失敗包成正常結果 | `Catch` 必須導向 `Fail`；已建立的版本保持未發布。 |
| `Retry` 只寫一條，或 `ErrorEquals` 自行加套件前綴、多列 `States.Timeout` | 漏掉 D-53 的第二條；或自行擴充錯誤名 | 前兩條逐字照 `RETRY`：業務的 `TransientError` 一條、四個 `Lambda.*` 服務層錯誤一條；錯誤名就是類別名，不加前綴；是否命中由 Phase 41 雲端實證。 |
| ASL input 放完整事件；或寫出第四條流程 | execution history 會留下資料；把 Analytics 當 pipeline | 只傳 `operation_id`／`project_id`／`input_ref`；Analytics 是獨立 Lambda，`PipelineName` 只有三個值。 |
| 快照被覆蓋成新內容 | `if_none_match` 忘了帶或吞掉 `ObjectAlreadyExists` | 不同 bytes 一律 `PermanentError`；快照是事後追溯用的證據。 |

## 13. 來源與 Rule 對照

- [執行教學流程.feature](../../spec/features/執行教學流程.feature)
  - Rule 2：「教學 pipeline 依 Step Functions 預定義節點執行」（primary）→ Task 1 的未知 pipeline 名稱測試與固定 `tasks` 序列。
  - Rule 6：「每個 Step Functions Task 設定 Retry」（primary）→ `test_every_task_retries_then_catches_to_fail` 與 `assert_safe_asl` 的遞迴檢查。
  - Rule 7：「每個 Step Functions Task 設定 Catch」（primary）→ 同上，加 `test_missing_catch_inside_map_is_rejected`。
  - Rule 10：「Step Functions 的 ASL 版本快照存於 stepfunctions/&lt;pipeline&gt;/v&lt;n&gt;.json」（primary）→ `test_snapshot_versioned_and_never_overwritten`。
  - Rule 3：「Agent 的工具選擇自由度只用於接入層」→ 相關（primary 在 [Phase 37](37-Phase37-Rote-Agent回退與成功提交.md)）；本 Phase 只提供固定節點骨架，不提供工具選擇。
- [設計 §5](../../design/training-kb.md)：`pipelines` 負責三條固定流程與呼叫次序，不讓模型任選下一個流程。
- 設計 §9.3：ASL 快照 key 為 `stepfunctions/<pipeline>/v<n>.json`，版本號與教學無關。設計 §14.2、§14.3：每個 Task 都設 `Retry` 與 `Catch`；暫時錯誤最多重試兩次、等待 1 秒與 2 秒；只讓一層管理重試；Task 時限 120 秒；state 只傳 ID、小型判斷結果或 S3 key。
- F48／F49（設計 §19.2）：schema 合法仍需業務驗證；`Catch` 後整次執行以失敗結束，不發布新版本。
- [Step Functions 錯誤處理](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)：`Retry` 欄位語意、自訂錯誤名稱不得以 `States.` 開頭、`States.ALL` 必須單獨且排在最後；[Step Functions 與 Lambda 整合](https://docs.aws.amazon.com/step-functions/latest/dg/connect-lambda.html)：直接函式 ARN 與 `lambda:invoke` 最佳化整合的輸出形狀差異。

## 14. 完成清單

- [x] `run_sequence` 的成功、永久失敗、暫時失敗與空 `tasks` 測試全部通過，失敗時一定先寫 `OperationCoordinator.fail(...)` 再把原例外往外丟。
- [x] 所有 `Task`（含 `Map`／`Parallel` 內）都有兩條 `IntervalSeconds 1`／`MaxAttempts 2`／`BackoffRate 2` 的 `Retry` 與導向 `Fail` 的 `Catch`。
- [x] `Retry` 前兩條逐字等於 `RETRY`（`TransientError` 一條、四個 `Lambda.*` 服務層錯誤一條，D-53）、`TimeoutSeconds` 是 120、`Choice` 都有 `Default`、Lambda Task 用直接函式 ARN；三條固定 pipeline 名稱已鎖定（`PipelineName` 沒有第四個值），ASL input 僅含 `operation_id`／`project_id`／`input_ref`。
- [x] 快照 key 為 `stepfunctions/<pipeline>/v<n>.json`，條件寫入且不覆蓋既有內容；`Deps` 仍只有兩個欄位，並標明 Phase 38 會追加三個預設 `None` 的欄位。
- [x] 未把本機 fixture 稱為 AWS runtime 通過；O2／O3 未通過時的阻擋狀態仍清楚可見。
