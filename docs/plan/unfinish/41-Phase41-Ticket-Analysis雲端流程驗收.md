# Phase 41：Ticket Analysis 雲端流程驗收實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 把 Phase 38–40 的判斷接成 `ticket-analysis` 這條 Standard workflow，並留下 AWS 上真的跑過的執行證據。

**架構：** 同一組 task 函式同時給本機 `run_sequence` 與雲端 Step Functions 使用；ASL 只負責順序、Choice 分支、有限 Retry 與 Catch，業務判斷全在 Lambda 內。每個 Task 都把「不適用就原樣回傳 state」寫在自己裡面，所以本機序列與雲端分支不會產生兩套語意。

**技術：** Python 3.12、pytest、AWS Step Functions Standard、AWS Lambda（Python 3.12）、AWS CDK、Amazon States Language。

## 全域限制

- 唯一主來源是 [Training KB 設計 §5、§7.3、§9.3、§14.1、§14.2、§14.3、§16 S2](../../design/training-kb.md)。
- 前置為 [Phase 40：Ticket CREATE 與 KEEP](./40-Phase40-Ticket-CREATE與KEEP.md)、[Phase 29 pipeline 執行器](./29-Phase29-共用Pipeline執行器與ASL失敗語意.md)、[Phase 32 事件接受與啟動](./32-Phase32-事件接受去重與流程啟動.md)、[Phase 24 單篇發布](./24-Phase24-單篇教學發布提交.md)、[Phase 30 webhook 入口](./30-Phase30-GitHub-Webhook原始Body驗簽.md)、[Phase 09 AWS 資料資源](./09-Phase09-AWS資料資源與最小IAM.md)。
- 下一階段是 [Phase 42：Feedback 與 View 固定匯入](./42-Phase42-Feedback與View固定匯入.md)。
- 本階段不做：不新增第四條 pipeline、不改 Phase 38–40 的業務規則、不做 Release 或 Feedback 的 state machine、不建立公開讀取 API 或 CloudFront。
- **O2／O3／O5／O6 任一 gate 未通過，就不可公開發布，也不可宣稱本 Phase 雲端驗收完成。** 未過時仍要留下可追溯的 FAIL 與 execution ARN，不改需求換綠燈。
- Lambda 與 state machine 都只給最小權限：單一 table、單一 bucket 前綴、已核定的 Bedrock 模型。以下程式檔與 AWS 資源都是實作時預計建立，本計畫不代表它們已存在或已部署。

---

## 1. 你在整體流程的位置

```text
Phase 32 accept_ticket -> StartExecution(ticket-analysis)
   |  [你在這裡] Standard workflow
   v
 EnsureEmbedding -> AssignCluster -> EvaluateRecurring -> IsRecurring?
                                       否 --> NotRecurring (Succeed) | 是
 NameGap -> DecideAction -> ChooseAction
   | CREATE -> CreateFirstVersion -> PublishVersion -> Published (Succeed)
   | KEEP -> Kept (Succeed)   | NO_FEATURE -> GapRetained (Succeed)
   | 其他值 -> Default -> PipelineFailed
        任一 Task Retry 用盡 -> Catch -> PipelineFailed (Fail)
```

## 2. 完成後看得到什麼

用與 Phase 32 相同形狀的 input 手動啟動一次：`{"operation_id":"op-ticket-t_881","project_id":"demo","input_ref":"operations/op-ticket-t_881/input.json"}`。

成功時 `describe-execution` 的 `status` 是 `SUCCEEDED`，`output` 含 `ticket_id`、`cluster_id`、`is_recurring`、`action` 與（CREATE 時）`version_id`，execution history 依序出現七個 `TaskStateEntered`。把 `NameGap` 改成必定暫時失敗：該 Task 出現三次 `TaskFailed`（首次加兩次重試），接著 `PipelineFailed`，整個 execution 是 `FAILED`，且沒有任何新版本被發布。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| Standard workflow | 會保留每一步執行紀錄的 Step Functions 類型，事後查得到。 |
| definition substitution | CDK 部署時把 ASL 裡的 `${...}` 換成真實資源 ARN。 |
| Task／Choice／Fail | ASL 的三種節點：做事、分岔、明確失敗。`Retry` 是同一 Task 的有限重試，`Catch` 是重試用完後的失敗分支。 |
| 錯誤名稱 | ASL 用來比對的字串；Python 未攔截例外的類別名就是它，例如 `TransientError`。 |
| execution ARN | 一次執行的唯一識別碼，是雲端驗收的主要證據。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/ticket.py` | 七個 task、`TICKET_ANALYSIS_TASKS`、`run_ticket_analysis`、`ticket_analysis_handler`。 |
| 修改 | `src/training_kb/pipelines/common.py` | `task_name`、`build_deps`、共用 Lambda 入口 `pipeline_task_handler`。 |
| 建立 | `infra/stepfunctions/ticket-analysis/v1.json` | 固定的 Standard ASL 定義（一條 pipeline 一個檔）。 |
| 建立 | `infra/training_kb_stack.py` | 兩支 Lambda（`training-kb-pipeline-task`、`training-kb-webhook`）、state machine、log group 與最小 IAM（Phase 48／52 之後在同一支擴充）。 |
| 修改 | `infra/app.py` | 加上 `TrainingKbStack(app, "TrainingKbApp")`（Phase 09 已建立此檔與 `TrainingKbData`）。 |
| 測試 | `tests/unit/pipelines/test_ticket_flow.py` | 順序、跳過分支、handler 分派。 |
| 測試 | `tests/unit/infra/test_ticket_asl.py` | Task 的 Retry／Catch／Timeout、Choice 與 CDK template。 |
| 測試 | `tests/integration/test_ticket_state_machine.py` | 真實 AWS 執行與失敗切點證據；標 `@pytest.mark.aws`，未設 `TKB_RUN_AWS_INTEGRATION=1` 時 skip（00A D-41）。 |

## 5. 固定介面

### Consumes

```text
load_settings(env) -> Settings                                # Phase 02
PermanentError / TransientError                               # Phase 02
run_sequence(pipeline, payload, tasks, deps) -> dict          # Phase 29
RETRY / CATCH / task_state / assert_safe_asl / save_asl_snapshot   # Phase 29（training_kb.pipelines.asl）
Deps(operations, now, repository, writer, settings)           # Phase 38 擴充
ensure_embedding / assign_cluster                             # Phase 38
is_recurring / known_features                                 # Phase 39
name_gap(cluster_id, *, repository, writer, operation_id, operations) -> dict[str, object]  # Phase 39
decide_ticket_action / record_decision / create_first_version # Phase 40
Publisher.prepare / inspect / commit、PublishRequest、SiteRenderer  # Phase 24（受 O3 gate 控管）
handler(event, context)                                       # Phase 30，training_kb.handlers.github_webhook
```

`RETRY`（D-53 的兩個 retrier）、`CATCH` 與 `task_state` **一律從 `training_kb.pipelines.asl` import**，本 Phase 的 ASL 與測試都不另外抄一份參數；抄一份就會在 Phase 29 改動時默默分岔。`name_gap` 回的是 **dict**（`GapNaming` 是 JSON schema 不是型別，見 [00A](00A-共用契約與名詞.md) D-02），取值一律寫 `naming["feature_id"]`，不寫 `naming.feature_id`。

### Produces

```python
TICKET_ANALYSIS_TASKS: tuple["TaskFn", ...]
# 以下三個加在 pipelines/common.py（00A D-24），後兩個加在 pipelines/ticket.py
def task_name(task: "TaskFn") -> str: ...     # 函式名去掉 "task_"，對應 ASL 的 Parameters.task
def build_deps(settings: "Settings") -> "Deps": ...
def pipeline_task_handler(event: dict, context: object) -> dict: ...   # 共用 Lambda 入口，依 event["pipeline"] 分派
def run_ticket_analysis(state: dict, deps: "Deps") -> dict: ...
def ticket_analysis_handler(event: dict, context: object) -> dict: ...
```

`TICKET_ANALYSIS_TASKS` 的順序固定為 `ensure_embedding`、`assign_cluster`、`evaluate_recurring`、`name_gap`、`decide_action`、`create_first_version`、`publish_version`。state 只放這十個欄位：`operation_id`、`project_id`、`input_ref`、`ticket_id`、`cluster_id`、`is_recurring`、`gap_ref`、`action`、`version_id`、`published`；不放工單全文、向量、`feature_id` 或模型輸出全文（設計 §14.3；00A 第 7 節）。`decide_action` 需要 Feature 時自己用 `gap_ref` 把 `gap-naming.json` 讀回來。`training-kb-pipeline-task` 是三條 pipeline 共用的 Lambda，`pipeline_task_handler` 是它唯一的 `handler=`；`ticket_analysis_handler` 保留為本條 pipeline 的直接入口與測試鉤子（Phase 48 的 `feedback_review_handler`、Phase 52 的 `release_update_handler` 同法）。

## 6. ASL 與失敗語意

```text
task 函式 raise TransientError -> handler 不攔截 -> Lambda runtime 回
        errorType = "TransientError"（只有類別名，沒有模組路徑）
        v
Retry[0].ErrorEquals 命中 -> 等 1 秒、再等 2 秒，最多兩次 -> 仍失敗
        v
Catch ["States.ALL"] -> PipelineFailed (Fail) -> 整次 execution FAILED；不發布、不切 current_version
```

每個 Task 用**直接函式 ARN**當 `Resource`：task result 只含函式輸出，不會多包一層 `Payload`／`SdkHttpMetadata`，所以 state 進出形狀一致。`PermanentError` 刻意不在 `ErrorEquals` 裡，資料不合法時直接進 Catch，不浪費兩次重試（設計 §14.2「區分暫時服務故障與確定非法資料」）。**每個 Task 固定兩個 retrier**（00A 裁決 D-53）：第一個接業務的 `TransientError`，第二個接 Lambda 服務層的暫時錯誤（`Lambda.ServiceException`、`Lambda.AWSLambdaException`、`Lambda.SdkClientException`、`Lambda.TooManyRequestsException`），兩者參數相同。這兩個 retrier 與 `Catch` 的值就是 Phase 29 的 `RETRY`／`CATCH`，本檔只是把它們序列化進 JSON，Task 2 的測試會逐欄比對回去。

七個 Task state 的名稱與 `Parameters.task`、`Next` 對照如下（Choice 與 Succeed 不是 Task，不進 `TICKET_ANALYSIS_TASKS`）：`EnsureEmbedding`→`ensure_embedding`→`AssignCluster`；`AssignCluster`→`assign_cluster`→`EvaluateRecurring`；`EvaluateRecurring`→`evaluate_recurring`→`IsRecurring`；`NameGap`→`name_gap`→`DecideAction`；`DecideAction`→`decide_action`→`ChooseAction`；`CreateFirstVersion`→`create_first_version`→`PublishVersion`；`PublishVersion`→`publish_version`→`Published`。以下節錄 `infra/stepfunctions/ticket-analysis/v1.json`，其餘六個 Task 與 `EnsureEmbedding` 逐字相同，只改這兩欄。

```json
{
  "StartAt": "EnsureEmbedding",
  "States": {
    "EnsureEmbedding": {
      "Type": "Task", "Resource": "${PipelineTaskFunctionArn}", "Next": "AssignCluster",
      "Parameters": {"pipeline": "ticket-analysis", "task": "ensure_embedding", "state.$": "$"},
      "TimeoutSeconds": 120,
      "Retry": [{"ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2},
                {"ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.failure", "Next": "PipelineFailed"}]
    },
    "IsRecurring": {"Type": "Choice", "Default": "NotRecurring",
      "Choices": [{"Variable": "$.is_recurring", "BooleanEquals": true, "Next": "NameGap"}]},
    "ChooseAction": {"Type": "Choice", "Default": "PipelineFailed",
      "Choices": [{"Variable": "$.action", "StringEquals": "CREATE", "Next": "CreateFirstVersion"},
                  {"Variable": "$.action", "StringEquals": "KEEP", "Next": "Kept"},
                  {"Variable": "$.action", "StringEquals": "NO_FEATURE", "Next": "GapRetained"}]},
    "Published": {"Type": "Succeed"}, "Kept": {"Type": "Succeed"},
    "GapRetained": {"Type": "Succeed"}, "NotRecurring": {"Type": "Succeed"},
    "PipelineFailed": {"Type": "Fail", "Error": "PipelineFailed", "Cause": "以失敗結束，不發布新版本"}
  }
}
```

七個 Task 的 `Parameters.pipeline` 一律是 `"ticket-analysis"`，`pipeline_task_handler` 就是靠它知道該把事件交給哪一條 `run_*`；直接函式 ARN **沒有** `Payload` 外層，封套只有 `Parameters` 這三個欄位（00A D-24、D-49）。`TimeoutSeconds` 120 與 Lambda 的 90 秒逾時都來自設計 §14.3；兩者不同是刻意的，Task 逾時比函式逾時寬一點，才能區分「函式自己超時」與「Step Functions 放棄等待」。**本計畫選擇：** `ChooseAction` 的 `Default` 指向 `PipelineFailed`——出現三種以外的 `action` 代表程式有錯，不能靜默走成功終點。`PublishVersion` 只是呼叫 Phase 24 的 `Publisher.prepare/inspect/commit`；O3 gate 未 PASS 時 Publisher 依其停止條件回失敗，本 Task 會走 Catch 到 `PipelineFailed`。這是**預期**狀態而不是本 Phase 的 bug：該情況下只能宣稱「未發布 v1 已建立」，不能說公開發布已驗收。

## 7. TDD Tasks

### Task 1：固定本機序列與跳過分支

- [ ] **Step 1：建立失敗測試**

```python
# tests/unit/pipelines/test_ticket_flow.py
from training_kb.pipelines.common import task_name
from training_kb.pipelines.ticket import TICKET_ANALYSIS_TASKS, run_ticket_analysis


def test_ticket_analysis_task_order_and_names():
    assert [task_name(task) for task in TICKET_ANALYSIS_TASKS] == [
        "ensure_embedding", "assign_cluster", "evaluate_recurring", "name_gap",
        "decide_action", "create_first_version", "publish_version"]


def test_non_recurring_run_skips_model_and_version(local_deps):
    state = {"operation_id": "op-1", "project_id": "demo", "input_ref": "operations/op-1/input.json"}
    result = run_ticket_analysis(state, local_deps)   # 同群只有四筆
    assert (result["is_recurring"], "version_id" in result) == (False, False)
    assert local_deps.writer.generate_calls == []
    assert local_deps.repository.created_versions == []
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/pipelines/test_ticket_flow.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'TICKET_ANALYSIS_TASKS'`。

- [ ] **Step 3：建立最小實作**

```python
def task_name(task):                        # pipelines/common.py
    return task.__name__.removeprefix("task_")


def task_name_gap(state, deps):             # pipelines/ticket.py
    if not state.get("is_recurring"):
        return dict(state)              # 不適用就原樣回傳，本機與雲端語意一致
    op = str(state["operation_id"])
    name_gap(str(state["cluster_id"]), repository=deps.need_repository(),
             writer=deps.need_writer(), operation_id=op, operations=deps.operations)
    return {**state, "gap_ref": f"operations/{op}/gap-naming.json"}


def run_ticket_analysis(state, deps):
    return run_sequence("ticket-analysis", state, TICKET_ANALYSIS_TASKS, deps)
```

其餘六個 task 照同一形狀：先檢查前置條件，不適用就 `return dict(state)`，適用才呼叫 Phase 38–40 的函式並把小型結果併回 state。`name_gap` 自己已經把結果寫進 `operations/<op>/gap-naming.json`（Phase 39），所以這個 task 只要把 ref 放進 state；`gap` 與 `feature_id` 都不進 state。`task_decide_action` 用 `gap_ref` 把那份 JSON 讀回來（它是 `dict`，欄位用 `naming["feature_id"]` 取，不是屬性），組出 Phase 40 的 `TicketGap` 再呼叫 `decide_ticket_action` 與 `record_decision`。

- [ ] **Step 4：補三條分支測試，執行 `uv run pytest tests/unit/pipelines/test_ticket_flow.py -q` 確認綠燈**

再補 recurring 但 `NO_FEATURE`（0 個版本、有 `ticket-decision.json`）、recurring 且 `KEEP`（0 個版本）、recurring 且 `CREATE`（有 `version_id`、`published_at` 仍為 `null`）三個案例，都要斷言 state 不含工單全文與向量。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/ticket.py src/training_kb/pipelines/common.py tests/unit/pipelines/test_ticket_flow.py
git commit -m "feat(ticket): 組合 ticket-analysis 流程"
```

### Task 2：鎖定 ASL 結構與 handler 分派

- [ ] **Step 1：建立失敗測試**

```python
# tests/unit/infra/test_ticket_asl.py
import json, pathlib, pytest
from training_kb.errors import PermanentError, TransientError
from training_kb.pipelines.asl import CATCH, RETRY, assert_safe_asl, task_state
from training_kb.pipelines.common import task_name
from training_kb.pipelines.ticket import TICKET_ANALYSIS_TASKS

ARN = "${PipelineTaskFunctionArn}"
NEXT = {"EnsureEmbedding": "AssignCluster", "AssignCluster": "EvaluateRecurring",
        "EvaluateRecurring": "IsRecurring", "NameGap": "DecideAction",
        "DecideAction": "ChooseAction", "CreateFirstVersion": "PublishVersion",
        "PublishVersion": "Published"}


@pytest.fixture
def asl() -> dict:
    return json.loads(pathlib.Path("infra/stepfunctions/ticket-analysis/v1.json").read_text())


def test_every_task_state_equals_phase29_template_plus_parameters(asl):
    assert len(RETRY) == 2 and RETRY[0]["ErrorEquals"] == ["TransientError"]   # D-53
    for name, next_state in NEXT.items():
        state, expected = asl["States"][name], task_state(ARN, next_state)
        expected["Parameters"] = {"pipeline": "ticket-analysis",
                                  "task": state["Parameters"]["task"], "state.$": "$"}
        assert state == expected, name        # Retry／Catch／TimeoutSeconds 全部來自 Phase 29


def test_asl_task_names_and_branches_match_python(asl):
    parameters = [asl["States"][n]["Parameters"] for n in NEXT]
    assert [p["task"] for p in parameters] == [task_name(t) for t in TICKET_ANALYSIS_TASKS]
    assert all(p["pipeline"] == "ticket-analysis" and p["state.$"] == "$" and "Payload" not in p
               for p in parameters)
    assert_safe_asl(asl)
    assert asl["States"]["PipelineFailed"]["Type"] == "Fail"
    assert asl["States"]["ChooseAction"]["Default"] == CATCH[0]["Next"] == "PipelineFailed"
    assert asl["States"]["IsRecurring"]["Default"] == "NotRecurring"
    # Lambda runtime 把未攔截例外的類別名放進 errorType，ASL 就用它比對
    assert (TransientError.__name__, PermanentError.__name__) == ("TransientError", "PermanentError")
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/infra/test_ticket_asl.py -q` 確認紅燈**

預期 FAIL，因 `infra/stepfunctions/ticket-analysis/v1.json` 尚未建立（訊號是 `FileNotFoundError`）。若改成 `cannot import name 'RETRY'`，代表 Phase 29 的 `RETRY` 還沒依 D-53 改成兩條 retrier 的 tuple，**先回頭改 Phase 29**，不要在本 Phase 自己補一份常數。

- [ ] **Step 3：建立 ASL 與兩層 handler**

```python
# src/training_kb/pipelines/common.py：共用 Lambda 的唯一入口
_PIPELINE_HANDLERS = {"ticket-analysis": "training_kb.pipelines.ticket:ticket_analysis_handler",
                      "release-update": "training_kb.pipelines.release:release_update_handler",
                      "feedback-review": "training_kb.pipelines.feedback:feedback_review_handler"}


def pipeline_task_handler(event, context):
    target = _PIPELINE_HANDLERS.get(str(event.get("pipeline")))
    if target is None:
        raise PermanentError(f"未知的 pipeline：{event.get('pipeline')!r}")
    module_name, _, attribute = target.partition(":")
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as error:      # Phase 48／52 尚未實作時
        raise PermanentError(f"{module_name} 尚未建立") from error
    return getattr(module, attribute)(event, context)


# src/training_kb/pipelines/ticket.py：本條 pipeline 的直接入口
_TASK_BY_NAME = {task_name(task): task for task in TICKET_ANALYSIS_TASKS}
_DEPS: "Deps | None" = None


def ticket_analysis_handler(event, context):
    global _DEPS
    task = _TASK_BY_NAME.get(str(event.get("task")))
    if task is None:
        raise PermanentError(f"ticket-analysis 沒有名為 {event.get('task')!r} 的 task")
    if _DEPS is None:
        _DEPS = build_deps(load_settings(os.environ))
    return task(dict(event.get("state") or {}), _DEPS)
```

兩層 handler 都不 try／except：`TransientError` 要讓 ASL 的 Retry 抓到，`PermanentError` 要讓 Catch 抓到。`_PIPELINE_HANDLERS` 現在就寫滿三條，但 Phase 48／52 的模組還不存在，所以用延後 import；單元測試要有一條「`pipeline` 不在三個名稱內 → `PermanentError`」的案例。

- [ ] **Step 4：執行 `uv run pytest tests/unit/infra/test_ticket_asl.py tests/unit/pipelines/test_ticket_flow.py -q` 確認綠燈**

再手動刪掉 ASL 裡任何一個 `Catch` 重跑一次，`assert_safe_asl` 必須讓測試變紅；確認後改回來。

- [ ] **Step 5：提交**

```bash
git add infra/stepfunctions/ticket-analysis/v1.json src/training_kb/pipelines/common.py tests/unit/infra/test_ticket_asl.py
git commit -m "feat(infra): 建立 ticket-analysis ASL"
```

### Task 3：把 stack 部署上去並取得 AWS 實際證據

- [ ] **Step 1：建立失敗測試**

```python
# 續寫 tests/unit/infra/test_ticket_asl.py
import aws_cdk as cdk
from aws_cdk.assertions import Match, Template
from infra.training_kb_stack import TrainingKbStack

def test_stack_has_one_standard_machine_and_two_named_lambdas():
    template = Template.from_stack(TrainingKbStack(cdk.App(), "TrainingKbApp"))
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    template.has_resource_properties("AWS::StepFunctions::StateMachine", {
        "StateMachineName": "training-kb-ticket-analysis", "StateMachineType": "STANDARD",
        "DefinitionSubstitutions": Match.object_like({"PipelineTaskFunctionArn": Match.any_value()})})
    functions = template.find_resources("AWS::Lambda::Function").values()
    handlers = {f["Properties"]["FunctionName"]: f["Properties"]["Handler"] for f in functions}
    # 用包含關係而不是等號：Phase 42／54 會在同一支 stack 再加 training-kb-import
    # 與 training-kb-analytics，那時這個斷言不該轉紅。
    assert handlers["training-kb-pipeline-task"] == "training_kb.pipelines.common.pipeline_task_handler"
    assert handlers["training-kb-webhook"] == "training_kb.handlers.github_webhook.handler"
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/infra/test_ticket_asl.py -q` 確認紅燈**

預期 FAIL，訊號包含 `No module named 'infra.training_kb_stack'`。

- [ ] **Step 3：建立 CDK 資源**

```python
# infra/training_kb_stack.py（class TrainingKbStack(Stack)，由 infra/app.py 以 id "TrainingKbApp" 實例化）
task_fn = lambda_.Function(
    self, "PipelineTaskFunction", function_name="training-kb-pipeline-task",
    runtime=lambda_.Runtime.PYTHON_3_12, code=lambda_.Code.from_asset("src"),
    handler="training_kb.pipelines.common.pipeline_task_handler",
    timeout=Duration.seconds(90), environment=base_env)
table.grant_read_write_data(task_fn)
bucket.grant_read_write(task_fn)
task_fn.add_to_role_policy(
    iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=approved_model_arns))
webhook_fn = lambda_.Function(                    # Phase 30 明講這個資源由本 Phase 建立
    self, "WebhookFunction", function_name="training-kb-webhook",
    runtime=lambda_.Runtime.PYTHON_3_12, code=lambda_.Code.from_asset("src"),
    handler="training_kb.handlers.github_webhook.handler",
    timeout=Duration.seconds(10), environment=base_env)   # handler 自己守 8 秒 deadline
webhook_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
machine = sfn.StateMachine(
    self, "TicketAnalysis", state_machine_name="training-kb-ticket-analysis",
    state_machine_type=sfn.StateMachineType.STANDARD,
    definition_body=sfn.DefinitionBody.from_file("infra/stepfunctions/ticket-analysis/v1.json"),
    definition_substitutions={"PipelineTaskFunctionArn": task_fn.function_arn},
    logs=sfn.LogOptions(destination=log_group, level=sfn.LogLevel.ALL),
    timeout=Duration.minutes(15))
task_fn.grant_invoke(machine)
machine.grant_start_execution(webhook_fn)
```

Lambda 叫 `training-kb-pipeline-task`（三條 pipeline 共用），state machine 才叫 `training-kb-ticket-analysis`；兩者同名會讓 Phase 48／52 無法沿用同一支函式（00A D-23）。webhook 的 secret 由環境變數 `TKB_GITHUB_WEBHOOK_SECRET` 提供，**不寫進 CDK 程式或 repo**；`auth_type=NONE` 只代表不做 IAM 驗證，驗簽仍由 Phase 30 的 handler 負責。`training-kb-import` 與 `training-kb-analytics` 的入口在 Phase 42／54 才存在，本 Phase 不建立它們的資源。

- [ ] **Step 4：跑綠燈，再存 ASL 快照、合成並部署**

```bash
uv run pytest tests/unit/infra/test_ticket_asl.py -q
uv run python - <<'PY'
import boto3, pathlib
from training_kb.config import load_settings
from training_kb.pipelines.asl import save_asl_snapshot
from training_kb.repository import Repository
settings = load_settings()
repository = Repository(boto3.resource("dynamodb").Table(settings.table_name),
                        boto3.resource("s3").Bucket(settings.content_bucket))
print(save_asl_snapshot(repository, "ticket-analysis", 1,
      pathlib.Path("infra/stepfunctions/ticket-analysis/v1.json").read_bytes()))
PY
cdk synth --quiet && cdk deploy TrainingKbApp --require-approval never
```

綠燈後才部署。`save_asl_snapshot` 把**與部署完全相同的 bytes** 以 `put_object(..., if_none_match=True)` 存成私有 S3 快照 `stepfunctions/ticket-analysis/v1.json`（設計 §9.3；執行教學流程 Rule 10）；同一版重跑會丟 `ObjectAlreadyExists`，這是預期行為，改定義就升成 `v2.json`。`cdk` 是 Node.js 套件，指令**不加** `uv run`（00A §3.1、D-22）；stack id 用 `TrainingKbApp`，與 `infra/app.py` 裡的 `TrainingKbStack(app, "TrainingKbApp")` 一致（D-43）。CDK 環境未建立時先完成 Phase 01／09，不要把「目前跑不了」寫成通過，也不要把 `cdk synth` 成功當成部署成功。

- [ ] **Step 5：跑成功與失敗各一次執行，保存證據後提交**

```bash
aws stepfunctions start-execution --state-machine-arn "$TKB_TICKET_SM_ARN" \
  --name "op-ticket-t_881" \
  --input '{"operation_id":"op-ticket-t_881","project_id":"demo","input_ref":"operations/op-ticket-t_881/input.json"}'
aws stepfunctions describe-execution --execution-arn "$ARN" \
  --query '{status:status,startDate:startDate,stopDate:stopDate,output:output}'
aws stepfunctions get-execution-history --execution-arn "$ARN" --max-results 200 \
  --query "events[?type=='TaskStateEntered'].stateEnteredEventDetails.name" --output text
aws stepfunctions get-execution-history --execution-arn "$FAILED_ARN" --max-results 200 \
  --query "events[?type=='TaskFailed'].taskFailedEventDetails.[error,cause]" --output text
aws logs tail "$TKB_TICKET_SM_LOG_GROUP" --since 15m --format short
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_ticket_state_machine.py -q
git add infra/training_kb_stack.py infra/app.py tests/unit/infra/test_ticket_asl.py tests/integration/test_ticket_state_machine.py
git commit -m "test(infra): 保存 ticket-analysis 雲端證據"
```

第二次執行讓 `NameGap` 必定丟 `TransientError`，換一個 execution name（`op-ticket-t_882`）重跑。預期 `status` 是 `FAILED`、history 出現該 Task 三次 `TaskFailed` 與一次 `ExecutionFailed`，資料庫沒有新的 `VERSION#`。**最後一個 `get-execution-history` 是 00A §3.7 指定由本 Phase 實證的那一項**：`taskFailedEventDetails.error` 必須逐字是 `TransientError`（不是 `Lambda.Unknown`，也不是帶模組路徑的名稱），否則 `ErrorEquals: ["TransientError"]` 根本沒有命中，重試是假的——此時停止，把觀察到的 `error` 值寫進報告，回頭與 Phase 29 一起改 `RETRY`，不要改測試遷就。兩個 execution ARN 與上面每一行的輸出都要寫進證據索引，再提交。

## 8. 驗收矩陣

| 路徑 | 刺激 | 預期資料結果與證據 |
|---|---|---|
| Happy | recurring 且無 active 教學 | `SUCCEEDED`；七個 `TaskStateEntered`；未發布 v1 存在。 |
| Happy | 同群只有四筆 | `SUCCEEDED` 走 `NotRecurring`；0 次模型呼叫、0 個版本。 |
| Failure | `NameGap` 連續 `TransientError` | 三次 `TaskFailed`（`error` 為 `TransientError`）後 `PipelineFailed`；execution `FAILED`。 |
| Happy | active 教學已存在 | `SUCCEEDED` 走 `Kept`；只有 `ticket-decision.json`。 |
| Failure／Boundary | 模型回不存在的 Feature；`action` 是三種以外的值 | 前者 `PermanentError` 不重試直接 Catch，後者走 `Default`；兩者都到 `PipelineFailed`、0 個新版本。 |
| Idempotency | 同 `operation_id` 重送 | Phase 32 回原 execution，不新增版本或分群。 |
| Gate | O3 未 PASS | `PublishVersion` 失敗並留 FAIL；只能宣稱到「未發布 v1 已建立」。 |

證據格式（每一項都要留檔，缺一項就不算雲端驗收完成）：

| 證據 | 形狀 |
|---|---|
| execution ARN 與執行結果 | `arn:aws:states:<region>:<account>:execution:training-kb-ticket-analysis:op-ticket-t_881`，加上 `describe-execution` 的 `status`／`startDate`／`stopDate`／`output` JSON。 |
| 節點順序與錯誤名稱 | `get-execution-history` 的 `TaskStateEntered` 名稱序列；失敗那次的 `taskFailedEventDetails.error` 原值（應為 `TransientError`，00A §3.7 指定的實證項）。 |
| CloudWatch 與資料結果 | state machine log group 名稱與該次執行的時間區間輸出；`TUTORIAL#`／`VERSION#` item 的 `current_version`、`published_at` 實際值。 |
| Bedrock 次數 | 該 operation 的 `CallTrace` 逐次 attempt，含 embedding 與重試。 |

人工驗收：在 Step Functions console 同時打開成功與失敗各一個執行逐節點核對，再回資料庫確認失敗那次沒有留下新版本或新群。只有本機 pytest 綠燈不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 每個 Task 重試六次，或 `PermanentError` 也被重試 | Lambda SDK 與 ASL 各自重試；把 `PermanentError` 放進 `ErrorEquals` | 只保留 ASL 的 Retry（設計 §14.3），handler 不得自行迴圈；兩條 retrier 各司其職，第一條對 `TransientError`、第二條對四個 `Lambda.*` 服務例外。 |
| Catch 走到 `Succeed` | 把失敗包成正常回傳值 | Catch 一律指向 `PipelineFailed`。 |
| execution history 看得到工單全文 | 把整個 Ticket 放進 state | state 只放 ID 與私有 key。 |
| 只寫了一條 retrier（D-53 要求兩條），或測試裡自己抄了一份 `Retry` | 漏掉 D-53，或沒有從 `pipelines.asl` import | `RETRY`／`CATCH` 一律 import Phase 29 的；Phase 29 若還沒改成兩條就先改它，Phase 48／52 一起對齊，不可只在這裡分岔。 |
| 部署後 Phase 48／52 蓋掉 Lambda | 每條 pipeline 各建一支函式 | 三條 pipeline 共用 `training-kb-pipeline-task`，靠 `Parameters.pipeline` 分派（D-23、D-24）。 |
| `errorType` 不是 `TransientError` | Lambda runtime 包裝了例外，或 handler 自己攔截 | 停止並記下實際值；ASL 的 `ErrorEquals` 沒命中就等於沒有重試，不可改測試遷就。 |
| 宣稱流程通過但沒有 ARN | 把 CDK synth 當部署成功 | synth 只證明 template 合法，沒有 execution ARN 就是未驗收；O3 FAIL 時停止公開路徑並保留決策出口。 |

## 10. 來源與 Rule 對照

**本 Phase 是驗收型，沒有任何 primary Rule**（[00B 需求覆蓋對照](00B-需求覆蓋對照.md) 第 1 節：P25、P41、P59、P60 皆如此）。以下全部是「相關」，責任是證明別人已斷言過的行為在雲端的同一條流程裡仍然成立。

- [執行教學流程.feature](../../spec/features/執行教學流程.feature)
  - Rule 2「教學 pipeline 依 Step Functions 預定義節點執行」→ **相關（primary Phase 29）**；Task 2 的 `test_asl_task_names_match_python_tasks` 在本條 pipeline 再驗一次 ASL 節點與 Python task 一一對應。
  - Rule 6「每個 Step Functions Task 設定 Retry」、Rule 7「每個 Step Functions Task 設定 Catch」→ **相關（primary Phase 29）**；Task 2 的 `test_every_task_state_equals_phase29_template_plus_parameters` 逐一把七個 Task 比回 Phase 29 的 `RETRY`／`CATCH`，Task 3 Step 5 再用雲端 `errorType` 證明 `ErrorEquals` 真的命中。
  - Rule 10「Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json`」→ **相關（primary Phase 29）**；Task 3 Step 4 在部署前用 `save_asl_snapshot` 寫出同一份 bytes。
- [接入來源事件.feature](../../spec/features/接入來源事件.feature)：Rule 26「正規化成功的 Ticket 觸發 Ticket Analysis」→ **相關（primary Phase 32）**；驗收矩陣的 Idempotency 列確認重送回原 execution。
- [分析工單.feature](../../spec/features/分析工單.feature)：14 條的 primary 分散在 Phase 38（Rule 1、2）、Phase 39（Rule 3、4、5）、Phase 40（Rule 7、8、9、10、14）、Phase 21（Rule 11、12、13）與 Phase 04（Rule 6）。本 Phase 全部是**相關**：證明它們在同一條固定流程中沒有互相吞掉，不重複寫斷言。
- 設計 §5：三條預先定義的 Step Functions，Agent 不能自行增加流程。§9.3：三個 pipeline 名稱固定。§14.1／§14.2：Catch 後整次失敗不發布，重試重用已保存輸出。§14.3：Task 120 秒、Lambda 90 秒、暫時錯誤最多兩次等 1 秒與 2 秒。§16 S2：工單達門檻後建立未發布 v1，active 已存在時 KEEP。
- [Step Functions 錯誤處理](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)：`Retry` 欄位（`IntervalSeconds` 預設 1、`MaxAttempts` 預設 3、`BackoffRate` 預設 2.0）、自訂錯誤名稱不得以 `States.` 開頭、`States.ALL` 必須單獨且排在最後、`Catch` 的 `ResultPath`；[Lambda 服務整合](https://docs.aws.amazon.com/step-functions/latest/dg/connect-lambda.html)：直接指定函式 ARN 時 task result 只含函式輸出，最佳化整合才會多包 `Payload` 與 metadata。
- [CDK StateMachine（Python）](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_stepfunctions/StateMachine.html) 與 [StateMachineProps](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_stepfunctions/StateMachineProps.html)：`definition_body`（取代已棄用的 `definition`）、`DefinitionBody.from_file`、`definition_substitutions`、`state_machine_type=STANDARD`、`logs`。

## 11. 完成清單

- [ ] `TICKET_ANALYSIS_TASKS`、`run_ticket_analysis`、`ticket_analysis_handler` 的名稱與 Phase 48／52 命名法一致，七個 Task 的順序與 `Parameters.task` 有測試守住；`pipeline_task_handler`、`task_name`、`build_deps` 都在 `pipelines/common.py`，`pipeline` 不在三個名稱內時丟 `PermanentError`。
- [ ] 每個 Task 都有兩個 retrier（`TransientError` 與四個 `Lambda.*` 服務例外，皆 1 秒、倍率 2、最多兩次）與 Catch 到 `PipelineFailed`；兩個 Choice 的每個分支都有測試，`ChooseAction` 的 `Default` 走失敗終點。
- [ ] state 只含那十個欄位，execution history 看不到工單全文、`feature_id` 或向量。
- [ ] `infra/stepfunctions/ticket-analysis/v1.json` 與 S3 快照 `stepfunctions/ticket-analysis/v1.json` 是同一份 bytes。
- [ ] CDK 在 `infra/training_kb_stack.py` 產生一個 Standard state machine、`training-kb-pipeline-task` 與 `training-kb-webhook` 兩支 Lambda（handler 分別指向 `pipeline_task_handler` 與 `training_kb.handlers.github_webhook.handler`）與最小 IAM，並有 `definition_substitutions`；部署指令是 `cdk deploy TrainingKbApp`（不加 `uv run`）。
- [ ] 成功與失敗各一次的 execution ARN、節點序列、失敗事件的 `error` 原值與 CloudWatch 輸出都已保存。
- [ ] O2／O3／O5／O6 任一未通過時，文件與報告維持 BLOCKED，不宣稱可公開發布。
