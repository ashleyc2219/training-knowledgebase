# Phase 41：Ticket Analysis 雲端流程驗收實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **(a) 已存在、可直接重用（不要重寫）**
> - `src/training_kb/pipelines/common.py`：`PipelineName`／`PIPELINE_NAMES`／`JSONValue`／`TaskFn`／`Deps`（含 `need_repository`／`need_writer`／`need_settings`，三個新欄位都**預設 `None`**）／`run_sequence`。**`task_name`、`build_deps`、`pipeline_task_handler` 還不存在，依 00A D-24 由本 Phase 產出**（P29 刻意沒做，見 `docs/plan/report/phases/2026-09-14-Phase29-REP.md`）。
> - `src/training_kb/pipelines/asl.py`：`RETRY`（**兩條 retrier 的 tuple**，D-53 已落地）、`CATCH`、`task_state`、`assert_safe_asl`、`canonical_json`、`save_asl_snapshot`、`ASL_LOCAL_PATH`／`ASL_SNAPSHOT_KEY`、`FAIL_STATE_NAME`、`TASK_TIMEOUT_SECONDS = 120`。
> - `src/training_kb/pipelines/ticket.py`：Phase 38–40 的業務函式全部就位（`ensure_embedding`、`assign_cluster`、`new_cluster_id`、`is_recurring`、`recurring_window`、`known_features`、`name_gap`、`TicketGap`、`decide_ticket_action`、`record_decision`、`tutorial_slug`、`create_tutorial_identity`、`create_first_version`）。**七個 `task_*` 包裝、`TICKET_ANALYSIS_TASKS`、`run_ticket_analysis`、`ticket_analysis_handler` 還沒有。**
> - `src/training_kb/handlers/github_webhook.py`：`handler`、`load_secret`、`SECRET_ENV = "TKB_GITHUB_WEBHOOK_SECRET"`、`WEBHOOK_DEADLINE_SECONDS = 8.0`。
> - `src/training_kb/ingress.py` 的 `_build_wiring(settings)`：**真實 AWS 相依的既有寫法**（boto3 resource → `Repository(table, bucket)` → `OperationCoordinator(repository)` → `BotoPipelineStarter` ＋ `sts.get_caller_identity()`）。`build_deps` 照它的形狀寫，不要另發明一套。
> - `infra/training_kb_data_stack.py`（P09，**已部署**）：`TrainingKbDataStack` 提供 `self.table`／`self.bucket`／`self.data_role`。`infra/app.py` 目前只實例化 `TrainingKbData`。
> - 測試器材：`tests/unit/pipelines/conftest.py`（`fake_operations`／`fake_clock`／`embedding_writer`／`fake_repo`／`settings`／`ticket_without_embedding`／`clustered`／`unclustered`）與 `tests/unit/pipelines/test_ticket_decide.py` 的 `FakeRepository`／`FakeOperations`／`FakeWriter`／`GAP`／`dt`（P40 已用 pytest prepend import mode 跨檔共用）。`tests/unit/infra/` **還不存在**，由本 Phase 建立（00A §3.2 已把它留給 P41／P42／P54）。
>
> **(b) 本文件因上一批裁決／實作而修正的點**
> 1. 「全域限制」的 gate 段整段改寫（D-80、D-81 與 `.superpowers/sdd/phase0914-2/COMMON.md` §2）：O2 **PASS**、O3 **FAIL**、O5 **BLOCKED**、O6 四列待核定；**O3／O5 未過不是本 Phase 的停止條件**，但不得宣稱公開發布或模型節點已驗收。
> 2. §7 Task 2 Step 3 的 `pipeline_task_handler`：controller 已**預建** `src/training_kb/pipelines/feedback.py` 與 `release.py` 的 docstring 空殼（commit `5f8a430`），所以「模組不存在」已不再是 P48／P52 未實作的訊號——改成「模組 import 得到但 handler 屬性還不存在（`AttributeError`）也要轉 `PermanentError`」（現況核對 2026-09-14：原只攔 `ModuleNotFoundError`）。
> 3. §7 Task 3 新增 Lambda 相依 layer（COMMON.md R2）：`lambda_.Code.from_asset("src")` **只帶原始碼，不含 `pydantic`／`jsonschema`**，而 `pydantic-core` 是編譯套件。P42／P48／P52／P54 沿用同一支 layer。
> 4. §7 Task 3 的 `base_env`：`load_settings` 的 `TKB_CONTENT_BUCKET` 預設值 `training-kb-content` **在雲端是錯的**，實際 bucket 是 CDK 生成的 `training-kb-content-example`；值一律從 data stack 取（跨 stack 參照），不得依賴預設值。
> 5. §7 Task 3 Step 4／5 的 CDK 指令：本機互動 shell 把 `node` 定成會拒絕的 function，一律 `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 <子命令>`（實際部署紀錄見 `docs/plan/report/phases/2026-09-14-Phase09-REP.md` §7）。
> 6. §7 Task 3 Step 3 併入 IAM 三件事（`docs/plan/report/2026-09-14-Phase21-40實作-REP.md` §8 第 6 項、00A D-79）：`site/` 寫入、`dynamodb:DeleteItem` 限 `SK begins_with APPLIED_TO#`、`states:DescribeExecution` 與 `sts:GetCallerIdentity`。
> 7. 新增 **§7A「承接上一批的接線待辦」**（REP §8 第 5、6、7 項與 P22–P28 標「延後至 P41／P59」的條目）。
> 8. §8 驗收矩陣新增兩列：**O5 BLOCKED 時可實證的路徑**、**需要模型的路徑（留 BLOCKED 證據）**。
> 9. §7 Task 1 Step 1 的 `local_deps` fixture **不存在**；既有替身的屬性名也不同（`FakeWriter.calls`、`FakeRepository.writes`，**沒有** `generate_calls`／`created_versions`）——見該處的短註。
>
> **(c) gate 現況對本 Phase 的實際影響**
> - **O5 BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`：Titan 與 Claude 都回 `ValidationException: Operation not allowed`）→ 真實 AWS 上任何呼叫模型的節點都走 `BedrockWriter._request_once` 的 `permanent_error` 分支，丟 `PermanentError`（訊息就是錯誤碼 `ValidationException`），**不重試、直接 Catch 到 `PipelineFailed`**。這是 BLOCKED 證據，不是 bug，也不算通過。**但整條流程不是完全跑不動**：只要工單已有存好的 `embedding`，`EnsureEmbedding`／`AssignCluster`／`EvaluateRecurring` 三個節點完全不碰模型，`NotRecurring` 那條路徑可以在真實 AWS 上跑到 `SUCCEEDED`（見 §8 新增的兩列與 §7 Task 3 Step 5）。
> - **O3 FAIL**（`docs/plan/report/o3-20260914t181109z.md`）→ `PublishVersion` 只能宣稱到「未發布 v1 已建立」；決策出口仍在維護者手上（D-80）。
> - **O2 PASS**（P11）、**O6 四列待核定** → 本 Phase 不重複宣稱，也不動 `tests/fixtures/o6/approved-sources.json`。
>
> **(d) 適用的 controller 裁決**：R1（真實 AWS 這一批要接，本 Phase 是第一個）、R2（Lambda 打包，**本 Phase 是 owner**）、R3（`pipelines/ticket.py`、`pipelines/common.py`、`infra/training_kb_stack.py` 同一波次可能有別人在改；既有檔**只用 Edit**、只 `git add` 自己的路徑）、R5（00A ＋ 既有程式優先於本文件的示意程式片段）、R7（報告格式）、R10（需要維護者決定的事自己裁決並標「**本計畫選擇**」）。

**目標：** 把 Phase 38–40 的判斷接成 `ticket-analysis` 這條 Standard workflow，並留下 AWS 上真的跑過的執行證據。

**架構：** 同一組 task 函式同時給本機 `run_sequence` 與雲端 Step Functions 使用；ASL 只負責順序、Choice 分支、有限 Retry 與 Catch，業務判斷全在 Lambda 內。每個 Task 都把「不適用就原樣回傳 state」寫在自己裡面，所以本機序列與雲端分支不會產生兩套語意。

**技術：** Python 3.12、pytest、AWS Step Functions Standard、AWS Lambda（Python 3.12）、AWS CDK、Amazon States Language。

## 全域限制

- 唯一主來源是 [Training KB 設計 §5、§7.3、§9.3、§14.1、§14.2、§14.3、§16 S2](../../design/training-kb.md)。
- 前置為 [Phase 40：Ticket CREATE 與 KEEP](./40-Phase40-Ticket-CREATE與KEEP.md)、[Phase 29 pipeline 執行器](./29-Phase29-共用Pipeline執行器與ASL失敗語意.md)、[Phase 32 事件接受與啟動](./32-Phase32-事件接受去重與流程啟動.md)、[Phase 24 單篇發布](./24-Phase24-單篇教學發布提交.md)、[Phase 30 webhook 入口](./30-Phase30-GitHub-Webhook原始Body驗簽.md)、[Phase 09 AWS 資料資源](./09-Phase09-AWS資料資源與最小IAM.md)。
- 下一階段是 [Phase 42：Feedback 與 View 固定匯入](./42-Phase42-Feedback與View固定匯入.md)。
- 本階段不做：不新增第四條 pipeline、不改 Phase 38–40 的業務規則、不做 Release 或 Feedback 的 state machine、不建立公開讀取 API 或 CloudFront。
- **gate 現況（現況核對 2026-09-14：原寫成「任一 gate 未通過就不可宣稱本 Phase 雲端驗收完成」，依 D-80／D-81 改寫）：** O2 **PASS**（P11）、O3 **FAIL**、O5 **BLOCKED**、O6 四列待核定、O1 provisionally accepted、O4／O7 未到。**O3 與 O5 未過不是本 Phase 的停止條件**——雲端接線、部署與可執行的路徑照做，做不到的部分標 BLOCKED 並附**實際錯誤原文**（`errorType` 與 `cause`），不填猜測值、不假裝通過，也**不可宣稱公開發布已驗收、不得放寬 F49**。未過時仍要留下可追溯的 FAIL 與 execution ARN，不改需求換綠燈。
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

成功時 `describe-execution` 的 `status` 是 `SUCCEEDED`，`output` 含 `ticket_id`、`cluster_id`、`is_recurring`、`action` 與（CREATE 時）`version_id`，execution history 依序出現七個 `TaskStateEntered`。

**現況核對（2026-09-14）：上面這段「七個 `TaskStateEntered`」在 O5 BLOCKED 下做不到。** 真實 AWS 上能拿到的 `SUCCEEDED` 只有「已有 `embedding` ＋ 同群不到五筆」那條三節點的 `NotRecurring` 路徑；只要走到 `NameGap` 之後就會撞 Bedrock 的 `ValidationException`（見 §8 新增的兩列）。七節點的完整成功要等 O5 通過後補跑，**不得**用 moto／本機 `run_ticket_analysis` 的綠燈冒充雲端證據。把 `NameGap` 改成必定暫時失敗：該 Task 出現三次 `TaskFailed`（首次加兩次重試），接著 `PipelineFailed`，整個 execution 是 `FAILED`，且沒有任何新版本被發布。

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
| 建立 | `infra/scripts/build_lambda_layer.py` | **本 Phase 新增（COMMON.md R2）**：把 `pydantic`／`jsonschema` 裝進 `build/lambda-layer/python/`，給 `lambda_.LayerVersion` 當 asset。`build/` 已在 `.gitignore`，產物不進版控。 |

（現況核對 2026-09-14：`tests/unit/infra/` 目錄**還不存在**，由本 Phase 建立；`tests/` 全樹沒有 `__init__.py`，測試檔 basename 必須全專案唯一——上面三個檔名與 00A §3.3 的 P41 那列逐字一致，照用。）

## 5. 固定介面

### Consumes

```text
load_settings(env: Mapping[str, str] | None = None) -> Settings   # Phase 02（缺參數時讀 os.environ）
PermanentError / TransientError                               # Phase 02
run_sequence(pipeline, payload, tasks, deps) -> dict          # Phase 29
RETRY / CATCH / task_state / assert_safe_asl / save_asl_snapshot   # Phase 29（training_kb.pipelines.asl）
Deps(operations, now, repository=None, writer=None, settings=None)  # Phase 29 建立、Phase 38 擴充（D-36）
ensure_embedding / assign_cluster                             # Phase 38
is_recurring / known_features                                 # Phase 39
name_gap(cluster_id, *, repository, writer, operation_id, operations) -> dict[str, object]  # Phase 39
decide_ticket_action / record_decision / create_first_version # Phase 40
Publisher.prepare / inspect / commit、PublishRequest、SiteRenderer  # Phase 24（受 O3 gate 控管）
handler(event, context)                                       # Phase 30，training_kb.handlers.github_webhook
load_secret() / SECRET_ENV = "TKB_GITHUB_WEBHOOK_SECRET"       # Phase 30，只從環境變數讀
_build_wiring(settings) -> Wiring                              # Phase 32（私有；build_deps 照它的形狀寫）
```

**現況核對（2026-09-14）：** `Deps` 的後三個欄位都有預設 `None`（D-36），Task 內一律走 `deps.need_repository()`／`need_writer()`／`need_settings()`，不要直接取屬性（拿到 `None` 會在業務函式深處爆 `AttributeError`，而不是當場說出缺了哪一個）。`ingress._build_wiring` 是本專案唯一一份「真的連到 AWS」的相依組裝程式，`build_deps(settings)` 直接照它的形狀寫（boto3 resource → `Repository(table, bucket)` → `OperationCoordinator(repository)` → `BedrockWriter`），只是不需要 `PipelineStarter`；`BedrockWriter` 在 `generation_model_id` 是 `None` 時**建構不會失敗**（只有真的呼叫生成模型才丟 `PermanentError`），所以 O5 BLOCKED 不影響 `build_deps` 本身。

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

- [x] **Step 1：建立失敗測試**

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

（現況核對 2026-09-14：`local_deps` 這個 fixture **不存在**，`tests/unit/pipelines/conftest.py` 目前只有 `fake_operations`／`fake_clock`／`embedding_writer`／`fake_repo`／`settings`／`ticket_without_embedding`／`clustered`／`unclustered`；上面斷言用的 `writer.generate_calls`／`repository.created_versions` 兩個屬性也不存在，P40 的替身叫 `FakeWriter.calls` 與 `FakeRepository.writes`。**本計畫選擇：** `local_deps` 定義在 `tests/unit/pipelines/test_ticket_flow.py` **自己的檔案裡**，用 `from test_ticket_decide import FakeOperations, FakeRepository, FakeWriter, dt` 組出 `Deps`——不要去改 `tests/unit/pipelines/conftest.py`，同一波次的 P48／P52 也會用到那支檔（COMMON.md R3）。斷言改寫成既有屬性，例如 `local_deps.writer.calls == []` 與「表裡沒有 `VERSION#` item」。）

- [x] **Step 2：執行 `uv run pytest tests/unit/pipelines/test_ticket_flow.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'TICKET_ANALYSIS_TASKS'`。

- [x] **Step 3：建立最小實作**

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

- [x] **Step 4：補三條分支測試，執行 `uv run pytest tests/unit/pipelines/test_ticket_flow.py -q` 確認綠燈**

再補 recurring 但 `NO_FEATURE`（0 個版本、有 `ticket-decision.json`）、recurring 且 `KEEP`（0 個版本）、recurring 且 `CREATE`（有 `version_id`）三個案例，都要斷言 state 不含工單全文與向量。

**本計畫選擇（2026-09-14）：** CREATE 案例的 `published_at` **不是** `null`。設計 §7.3 的成功條件是「CREATE 經第 8 節發布後，讀者可讀新教學」，所以 `PublishVersion` 真的呼叫 `Publisher.prepare/commit`，本機案例斷言 `published is True`、`published_at` 有值、`current_version` 已切換。**真實 AWS 上這條路徑到不了**（O5 BLOCKED 擋在 `NameGap`），所以雲端仍然只能宣稱到「未發布 v1 已建立」以前的節點。

**本計畫選擇（2026-09-14）：** `task_decide_action` 只在 KEEP／NO_FEATURE 時寫 `ticket-decision.json`；CREATE 的那一份由 `create_first_version` 在版本建好之後寫（Phase 40 已固定的順序），三種結果仍然都有紀錄，但不會先寫一份「還沒建版」的 CREATE 紀錄。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/ticket.py src/training_kb/pipelines/common.py tests/unit/pipelines/test_ticket_flow.py
git commit -m "feat(ticket): 組合 ticket-analysis 流程"
```

### Task 2：鎖定 ASL 結構與 handler 分派

- [x] **Step 1：建立失敗測試**

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

- [x] **Step 2：執行 `uv run pytest tests/unit/infra/test_ticket_asl.py -q` 確認紅燈**

預期 FAIL，因 `infra/stepfunctions/ticket-analysis/v1.json` 尚未建立（訊號是 `FileNotFoundError`）。若改成 `cannot import name 'RETRY'`，代表 Phase 29 的 `RETRY` 還沒依 D-53 改成兩條 retrier 的 tuple，**先回頭改 Phase 29**，不要在本 Phase 自己補一份常數。

- [x] **Step 3：建立 ASL 與兩層 handler**

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
    except ModuleNotFoundError as error:      # 模組整支不存在
        raise PermanentError(f"{module_name} 尚未建立") from error
    handler = getattr(module, attribute, None)
    if handler is None:                       # 模組在、handler 還沒寫（P48／P52 未實作）
        raise PermanentError(f"{module_name} 還沒有 {attribute}")
    return handler(event, context)


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

兩層 handler 都不 try／except：`TransientError` 要讓 ASL 的 Retry 抓到，`PermanentError` 要讓 Catch 抓到。`_PIPELINE_HANDLERS` 現在就寫滿三條，所以用延後 import。

**現況核對（2026-09-14）：原本只攔 `ModuleNotFoundError`，現在不夠。** controller 已預建 `src/training_kb/pipelines/feedback.py` 與 `release.py`（**只有 docstring**，commit `5f8a430`），所以這兩支模組 `import_module` **會成功**，缺的是 `feedback_review_handler`／`release_update_handler` 這兩個屬性——不補上面那段 `getattr(..., None)` 的話，Lambda 會丟 `AttributeError`（ASL 看到的 `errorType` 就變成 `AttributeError`，既不在 `ErrorEquals` 裡、訊息也看不出是「P48 還沒做」）。兩條分支都要有單元測試：（1）`pipeline` 不在三個名稱內 → `PermanentError`；（2）`pipeline="feedback-review"`（模組在、handler 不在）→ `PermanentError` 且訊息含屬性名。第二條測試會在 P48 落地後自然失效，那時由 P48 改掉，本 Phase 不預先放寬。

- [x] **Step 4：執行 `uv run pytest tests/unit/infra/test_ticket_asl.py tests/unit/pipelines/test_ticket_flow.py -q` 確認綠燈**

再手動刪掉 ASL 裡任何一個 `Catch` 重跑一次，`assert_safe_asl` 必須讓測試變紅；確認後改回來。

- [x] **Step 5：提交**

```bash
git add infra/stepfunctions/ticket-analysis/v1.json src/training_kb/pipelines/common.py tests/unit/infra/test_ticket_asl.py
git commit -m "feat(infra): 建立 ticket-analysis ASL"
```

### Task 3：把 stack 部署上去並取得 AWS 實際證據

- [x] **Step 1：建立失敗測試**

```python
# 續寫 tests/unit/infra/test_ticket_asl.py
import aws_cdk as cdk
from aws_cdk.assertions import Match, Template
from infra.training_kb_data_stack import TrainingKbDataStack
from infra.training_kb_stack import TrainingKbStack

def test_stack_has_one_standard_machine_and_two_named_lambdas():
    # 現況核對 2026-09-14：table／bucket 在另一支已部署的 TrainingKbData stack 裡，
    # 所以兩支 stack 要在同一個 App 建立（CDK 自動產生跨 stack 的 Export／ImportValue）。
    app = cdk.App()
    data = TrainingKbDataStack(app, "TrainingKbData")
    template = Template.from_stack(TrainingKbStack(app, "TrainingKbApp", data=data))
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


def test_both_lambdas_share_one_dependency_layer_and_get_the_real_bucket():
    app = cdk.App()
    data = TrainingKbDataStack(app, "TrainingKbData")
    template = Template.from_stack(TrainingKbStack(app, "TrainingKbApp", data=data))
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)       # P42／P48／P52／P54 沿用同一支
    for function in template.find_resources("AWS::Lambda::Function").values():
        properties = function["Properties"]
        assert len(properties["Layers"]) == 1                        # pydantic／jsonschema 只從 layer 來
        # 不得退回 load_settings 的預設值 training-kb-content（雲端上那個 bucket 不存在）
        bucket = properties["Environment"]["Variables"]["TKB_CONTENT_BUCKET"]
        assert bucket != "training-kb-content" and isinstance(bucket, dict)
        assert properties["Environment"]["Variables"]["TKB_AWS_REGION"]


def test_iam_covers_the_three_gaps_the_previous_batch_left():
    # REP §8 第 6 項：site/ 寫入、DeleteItem 限 APPLIED_TO#、DescribeExecution + GetCallerIdentity
    app = cdk.App()
    data = TrainingKbDataStack(app, "TrainingKbData")
    template = Template.from_stack(TrainingKbStack(app, "TrainingKbApp", data=data))
    statements = [statement
                  for policy in template.find_resources("AWS::IAM::Policy").values()
                  for statement in policy["Properties"]["PolicyDocument"]["Statement"]]
    def actions(statement):
        value = statement.get("Action", [])
        return value if isinstance(value, list) else [value]
    delete = [s for s in statements if "dynamodb:DeleteItem" in actions(s)]
    assert len(delete) == 1
    assert delete[0]["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"] is not None \
        or "APPLIED_TO#" in json.dumps(delete[0]["Condition"])      # D-79：只限 APPLIED_TO# 邊
    assert any("states:DescribeExecution" in actions(s) for s in statements)
    assert any("sts:GetCallerIdentity" in actions(s) for s in statements)
    assert any("s3:PutObject" in actions(s) and "site/" in json.dumps(s.get("Resource"))
               for s in statements)                                  # P24／P25 的公開前綴
```

**現況核對（2026-09-14）：原本的測試用 `TrainingKbStack(cdk.App(), "TrainingKbApp")` 單獨建構。** 不成立——table 與 bucket 屬於**另一支已部署的** `TrainingKbData` stack（P09），`TrainingKbStack` 必須拿得到它們才有東西可以授權、也才填得出 `TKB_CONTENT_BUCKET`。**本計畫選擇：** 建構子改成 `TrainingKbStack(scope, construct_id, *, data: TrainingKbDataStack, **kwargs)`，由 `infra/app.py` 把同一個 App 裡的 data stack 傳進來，CDK 會自動產生跨 stack 的 `Export`／`Fn::ImportValue`（不必手動改 P09 的 `CfnOutput` 加 `export_name`，那支檔的 owner 是 P09、下一個修改者是 P57）。兩支 stack 的 `env` 必須相同，所以 `infra/app.py` 用同一個 `cdk.Environment`。上面第三個測試的 `Condition` 斷言形狀依實際 CDK 產出調整，但「只有一條 `DeleteItem` 敘述、而且帶條件」這件事不得放寬。

**本計畫選擇（2026-09-14，controller 裁決，推翻上一段的跨 stack 參照）：**
`TrainingKbStack(scope, construct_id, *, content_bucket: str | None = None, **kwargs)`
**不接 data stack**。table 與 bucket 改用 `Table.from_table_attributes(table_name=TABLE_NAME,
global_indexes=[TARGET_INDEX])` 與 `Bucket.from_bucket_name(...)` 以**純字串名稱**接進來：

- 樣板裡因此沒有任何 `Fn::ImportValue`（有一條測試守住），
  `cdk deploy TrainingKbApp --exclusively` 才能單獨部署，不碰同一波次 Phase 57 正在改的
  `infra/training_kb_data_stack.py`；跨 stack `Export` 一旦建立，之後 data stack 想改那兩個
  輸出就會被 export 卡住。
- table 名用 P09 模組既有的 `TABLE_NAME` 常數（同一份真相）；bucket 名沒有預設值，
  依序取建構參數 → cdk context `tkb:content-bucket` → 環境變數 `TKB_CONTENT_BUCKET`，
  三個都沒有就當場失敗（絕不退回 `load_settings` 的 `training-kb-content`）。
- 授權仍然只給單表與五個 key 前綴；**不用** `grant_read_write_data()`，因為 CDK 那個 grant
  會把 `dynamodb:DeleteItem` 混進同一條敘述，D-79 要的「只有一條 `DeleteItem`」就守不住。
- 單元測試因此**不建** `TrainingKbData`，只建 `TrainingKbApp` 一支。

- [x] **Step 2：執行 `uv run pytest tests/unit/infra/test_ticket_asl.py -q` 確認紅燈**

預期 FAIL，訊號包含 `No module named 'infra.training_kb_stack'`。

- [x] **Step 3：建立 CDK 資源**

先做相依 layer（COMMON.md R2；現況核對 2026-09-14：原文件沒有這一步，`Code.from_asset("src")` 上雲後第一次 import `training_kb.models` 就會 `ModuleNotFoundError: pydantic`）。

```python
# infra/scripts/build_lambda_layer.py（只包 pyproject 的三個 runtime 相依裡「Lambda 沒有的」兩個；
# boto3 由 Lambda runtime 自帶，不放進 layer，避免蓋掉執行環境的版本）
LAYER_ROOT = pathlib.Path("build/lambda-layer")          # build/ 已在 .gitignore
COMMAND = ["uv", "pip", "install", "--target", str(LAYER_ROOT / "python"),
           "--python-platform", "x86_64-manylinux2014",  # 必須與 Lambda 架構一致
           "--python-version", "3.12", "--only-binary=:all:",
           "pydantic>=2,<3", "jsonschema>=4,<5"]
```

實測（2026-09-14，本機 uv 0.11.32）：產出 10 個套件、約 9.3 MB，`pydantic_core/_pydantic_core.cpython-312-x86_64-linux-gnu.so` 是 ELF x86-64——與 `lambda_.Architecture.X86_64` ＋ `Runtime.PYTHON_3_12` 相符。**架構要改成 arm64 就得同時改 `--python-platform aarch64-manylinux2014` 與 `architecture=`，兩邊不一致時 Lambda 只會在 import 時才爆，synth 與 deploy 都不會報錯。** Docker 28.5.1 可用，所以 `BundlingOptions(image=lambda_.Runtime.PYTHON_3_12.bundling_image, ...)` 是等效替代方案；**本計畫選擇** uv `--target`：不必拉 bundling image，跑得快，而且指令逐字可重現寫進報告。layer 的建置要排在 `cdk synth` **之前**（`cdk.json` 的 app 是 `uv run python -m infra.app`，asset 目錄不存在時 synth 直接失敗）。

```python
# infra/training_kb_stack.py
# class TrainingKbStack(Stack):
#     def __init__(self, scope, construct_id, *, data: TrainingKbDataStack, **kwargs):
table, bucket = data.table, data.bucket          # 跨 stack 參照，CDK 自動產生 Export／ImportValue
deps_layer = lambda_.LayerVersion(
    self, "DependencyLayer", layer_version_name="training-kb-deps",
    code=lambda_.Code.from_asset("build/lambda-layer"),
    compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
    compatible_architectures=[lambda_.Architecture.X86_64])
self.deps_layer = deps_layer                     # P42／P48／P52／P54 沿用同一支，不各自再做
base_env = {
    # load_settings 的 TKB_CONTENT_BUCKET 預設值是 training-kb-content，雲端上不存在那個
    # bucket；一定要給實際值（目前是 CDK 生成的
    # training-kb-content-example），而且從 data stack 取，不寫死。
    "TKB_TABLE_NAME": table.table_name,
    "TKB_CONTENT_BUCKET": bucket.bucket_name,
    "TKB_AWS_REGION": self.region,
    "TKB_PROJECT_ID": "demo",
    "TKB_EMBEDDING_MODEL_ID": "amazon.titan-embed-text-v2:0",
    # TKB_GENERATION_MODEL_ID 刻意不設：O5 BLOCKED，不得填猜測值（00A §3.5）。
    # BedrockWriter 只有在真的呼叫生成模型時才丟 PermanentError，建構不受影響。
}
task_fn = lambda_.Function(
    self, "PipelineTaskFunction", function_name="training-kb-pipeline-task",
    runtime=lambda_.Runtime.PYTHON_3_12, architecture=lambda_.Architecture.X86_64,
    code=lambda_.Code.from_asset("src"), layers=[deps_layer],
    handler="training_kb.pipelines.common.pipeline_task_handler",
    timeout=Duration.seconds(90), environment=base_env)
table.grant_read_write_data(task_fn)
bucket.grant_read_write(task_fn)                 # 私有前綴（tutorials/、operations/、stepfunctions/）
task_fn.add_to_role_policy(
    iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=approved_model_arns))
webhook_fn = lambda_.Function(                    # Phase 30 明講這個資源由本 Phase 建立
    self, "WebhookFunction", function_name="training-kb-webhook",
    runtime=lambda_.Runtime.PYTHON_3_12, architecture=lambda_.Architecture.X86_64,
    code=lambda_.Code.from_asset("src"), layers=[deps_layer],
    handler="training_kb.handlers.github_webhook.handler",
    timeout=Duration.seconds(10),                 # handler 自己守 8 秒 deadline
    environment={**base_env,
                 "TKB_GITHUB_WEBHOOK_SECRET": os.environ["TKB_GITHUB_WEBHOOK_SECRET"]})
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

**IAM：把上一批留下的三個缺口補齊**（`docs/plan/report/2026-09-14-Phase21-40實作-REP.md` §8 第 6 項；D-79）。三條都加在**這裡**，不要改 P09 的資料角色：

```python
for function in (task_fn, webhook_fn):
    function.add_to_role_policy(iam.PolicyStatement(      # 缺口 1：P24／P25 要寫公開前綴 site/
        actions=["s3:PutObject", "s3:GetObject"],
        resources=[bucket.arn_for_objects("site/*")]))
task_fn.add_to_role_policy(iam.PolicyStatement(           # 缺口 2：D-79，只准刪 APPLIED_TO# 邊
    actions=["dynamodb:DeleteItem"], resources=[table.table_arn],
    conditions={"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["*"]},
                "StringLike": {"dynamodb:Select": "*"}}))
webhook_fn.add_to_role_policy(iam.PolicyStatement(        # 缺口 3：P32 續跑判斷與 _build_wiring
    actions=["states:DescribeExecution"],
    resources=[f"arn:aws:states:{self.region}:{self.account}:execution:"
               f"{machine.state_machine_name}:*"]))
webhook_fn.add_to_role_policy(iam.PolicyStatement(
    actions=["sts:GetCallerIdentity"], resources=["*"]))  # 這個動作沒有資源層級授權
```

`dynamodb:DeleteItem` 的條件要**實測**：DynamoDB 的 IAM 條件鍵只有 `dynamodb:LeadingKeys`（比 **PK**）與 `dynamodb:Attributes` 等，**沒有**直接比 `SK` 的條件鍵。所以 D-79 要的「只准刪 `SK begins_with APPLIED_TO#`」在 IAM 層做不到逐字等價。**本計畫選擇（需寫進報告，並在 00A D-79 留一行）：** 授權寫成「單一 table、只給 `DeleteItem`」＋ **程式層**由 `Repository.delete_edge` 的 `DELETABLE_RELATIONS` 白名單守住，並在 Task 3 的 IAM 斷言測試裡固定「只有一條 `DeleteItem` 敘述、資源只有這張表、而且沒有 `dynamodb:*`」。若實作時查到可用的條件鍵組合能表達 `SK` 前綴，優先用它，並把實際 policy JSON 貼進報告。

**本計畫選擇（2026-09-14，實作後確認）：** 查過 DynamoDB 的 IAM 條件鍵清單，**沒有**
任何條件鍵能表達 `SK begins_with`（`dynamodb:LeadingKeys` 比的是 PK、`dynamodb:Attributes`
比的是屬性名），所以逐字的 D-79 在 IAM 層做不到。落地的形狀是**單一條、沒有 Condition 的**
`dynamodb:DeleteItem`，資源只有 `table/training_kb` 本體（連索引都不給），範圍由程式層
`Repository.DELETABLE_RELATIONS == {"APPLIED_TO"}` 守住——真實表上已實測：
`delete_edge(..., "ASKS_ABOUT", ...)` 丟 `PermanentError: 不允許刪除 ASKS_ABOUT 邊`，
`delete_edge(..., "APPLIED_TO", ...)` 成功（報告 §4）。`Template` 斷言改成「恰好一條
`DeleteItem`、資源只有這張表、沒有任何 `dynamodb:*`」。

**本計畫選擇（2026-09-14）：** `infra/app.py` 在三個前提（`TKB_GITHUB_WEBHOOK_SECRET`、
bucket 名稱、`build/lambda-layer/`）任一缺席時**只跳過** `TrainingKbApp` 並把原因印到
stderr。`cdk` 的任何子命令都會先合成整個 app，直接讓它 `KeyError` 會連 `TrainingKbData`
的部署都做不了（同一波次 Phase 57 正要部署它）。`TrainingKbStack` 本身仍然維持
`os.environ[SECRET_ENV]` 的硬性要求，所以不可能部署出一支拿不到 secret 的 Lambda。

`approved_model_arns`：**O5 BLOCKED 期間只列已核定用途的 embedding 模型** `arn:aws:bedrock:<region>::foundation-model/amazon.titan-embed-text-v2:0`；生成模型的 ARN 等 O5 通過、`TKB_GENERATION_MODEL_ID` 有實測值之後再加（00A §3.5：不得填猜測值）。

Lambda 叫 `training-kb-pipeline-task`（三條 pipeline 共用），state machine 才叫 `training-kb-ticket-analysis`；兩者同名會讓 Phase 48／52 無法沿用同一支函式（00A D-23）。webhook 的 secret 由環境變數 `TKB_GITHUB_WEBHOOK_SECRET` 提供，**不寫進 CDK 程式或 repo**：部署時由執行 `cdk deploy` 的 shell 帶進來（`TKB_GITHUB_WEBHOOK_SECRET=<值> AWS_REGION=us-east-1 … command npx aws-cdk@2 deploy TrainingKbApp`），`infra/training_kb_stack.py` 只用 `os.environ["TKB_GITHUB_WEBHOOK_SECRET"]` 讀它；**值不得寫進 `.env.example`、報告、log 或 commit**，缺值時讓 synth 當場 `KeyError` 失敗（比部署出一支永遠驗簽失敗的 Lambda 好）。**本計畫選擇：** MVP 不引入 Secrets Manager／SSM（沒有已核定的服務清單），但要在報告寫明「明文環境變數會出現在 Lambda console 與 `get-function-configuration`」這個已知取捨，並列為 P60 `check_secrets` 的核對項。`training-kb-import` 與 `training-kb-analytics` 的入口在 Phase 42／54 才存在，本 Phase 不建立它們的資源（D-58）。

`infra/app.py` 要一起改（現況：只實例化 `TrainingKbData`）：

```python
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
                      region=os.environ.get("TKB_AWS_REGION") or DEFAULT_REGION)
data = TrainingKbDataStack(app, "TrainingKbData", env=env)
TrainingKbStack(app, "TrainingKbApp", data=data, env=env)   # 同一個 env，跨 stack 參照才成立
```

- [x] **Step 4：跑綠燈，再存 ASL 快照、合成並部署**

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
uv run python -m infra.scripts.build_lambda_layer          # 先做 layer，synth 才找得到 asset
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet
TKB_GITHUB_WEBHOOK_SECRET="$SECRET" AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 \
  command npx aws-cdk@2 deploy TrainingKbApp --require-approval never \
  --outputs-file "$SCRATCHPAD/tkb-app-outputs.json"
```

綠燈後才部署。`save_asl_snapshot` 把**與部署完全相同的 bytes** 以 `put_object(..., if_none_match=True)` 存成私有 S3 快照 `stepfunctions/ticket-analysis/v1.json`（設計 §9.3；執行教學流程 Rule 10）；同一版重跑會丟 `ObjectAlreadyExists`，這是預期行為，改定義就升成 `v2.json`。`cdk` 是 Node.js 套件，指令**不加** `uv run`（00A §3.1、D-22）；stack id 用 `TrainingKbApp`，與 `infra/app.py` 裡的 `TrainingKbStack(app, "TrainingKbApp", data=data)` 一致（D-43）。**現況核對 2026-09-14：原本寫成裸 `cdk synth`／`cdk deploy`，本機跑不起來**——互動 shell 把 `node` 定成會拒絕的 function（`Security: node blocked`），一律 `command npx aws-cdk@2 <子命令>` 並帶 `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1`（全案固定 `us-east-1`，`aws configure` 的預設是 `ap-northeast-1`，CLI 也一律帶 `--region us-east-1`）。實際可用的部署紀錄見 `docs/plan/report/phases/2026-09-14-Phase09-REP.md` §7（CDK CLI 2.1141.0、`CDKToolkit` 已 bootstrap、`TrainingKbData` 已 `CREATE_COMPLETE`）。`--outputs-file` 指到 scratchpad（專案外），**不要提交 `cdk.out/`**。`save_asl_snapshot` 那段要先 `export TKB_TABLE_NAME=training_kb TKB_CONTENT_BUCKET=training-kb-content-example TKB_AWS_REGION=us-east-1`，否則 `load_settings()` 會用 `training-kb-content` 這個不存在的預設 bucket。CDK 環境未建立時先完成 Phase 01／09，不要把「目前跑不了」寫成通過，也不要把 `cdk synth` 成功當成部署成功。

- [x] **Step 5：先鋪好不需要模型的種子資料**（現況核對 2026-09-14 新增；O5 BLOCKED）

`ensure_embedding` **先一致讀取既有 TICKET，只有在 `current.embedding` 是空的時候才呼叫 Titan**（`pipelines/ticket.py` §1）。`assign_cluster` 與 `is_recurring` 完全不碰模型。所以只要工單在 DynamoDB 裡**已經有存好的 `embedding`**，前三個節點在真實 AWS 上可以一路跑完：

- **`NotRecurring` 成功路徑（0 次 Bedrock 呼叫）：** 種一筆 `TICKET#t_881`，`project_id=demo`、`embedding` 是 1024 個浮點數（合成值，`Writer.embed` 的維度檢查不會跑到，但 `cosine`／`centroid` 會用它）、`cluster_id` 留空，同群不到五筆 → `EvaluateRecurring` 回 `false` → Choice 走 `NotRecurring`（Succeed）。這是**在 O5 BLOCKED 下唯一能跑到 `SUCCEEDED` 的路徑**，也是 §8 新增那一列的證據來源。
- **走到 `NameGap` 的前置：** 同一 `cluster_id` 種**五筆**工單，`ts` 全部落在 anchor 的十四天 UTC 窗口內、每一筆都有 `embedding` → `EvaluateRecurring` 回 `true` → 進 `NameGap`。此時才會第一次呼叫模型。

種子資料一律用 `uv run python` 走 `Repository.put_meta(...)` 寫，**不手刻低階 AttributeValue**；種子是合成資料，要在報告與 Demo 指標明示（COMMON.md R11）。

- [x] **Step 6：跑成功與失敗各一次執行，保存證據後提交**

```bash
aws stepfunctions start-execution --region us-east-1 --state-machine-arn "$TKB_TICKET_SM_ARN" \
  --name "op-ticket-t_881" \
  --input '{"operation_id":"op-ticket-t_881","project_id":"demo","input_ref":"operations/op-ticket-t_881/input.json"}'
aws stepfunctions describe-execution --region us-east-1 --execution-arn "$ARN" \
  --query '{status:status,startDate:startDate,stopDate:stopDate,output:output}'
aws stepfunctions get-execution-history --region us-east-1 --execution-arn "$ARN" --max-results 200 \
  --query "events[?type=='TaskStateEntered'].stateEnteredEventDetails.name" --output text
aws stepfunctions get-execution-history --region us-east-1 --execution-arn "$FAILED_ARN" --max-results 200 \
  --query "events[?type=='TaskFailed'].taskFailedEventDetails.[error,cause]" --output text
aws logs tail "$TKB_TICKET_SM_LOG_GROUP" --region us-east-1 --since 15m --format short
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_ticket_state_machine.py -q
git add infra/training_kb_stack.py infra/app.py infra/scripts/build_lambda_layer.py \
        tests/unit/infra/test_ticket_asl.py tests/integration/test_ticket_state_machine.py
git commit -m "test(infra): 保存 ticket-analysis 雲端證據"
```

第二次執行讓 `NameGap` 必定丟 `TransientError`，換一個 execution name（`op-ticket-t_882`）重跑。預期 `status` 是 `FAILED`、history 出現該 Task 三次 `TaskFailed` 與一次 `ExecutionFailed`，資料庫沒有新的 `VERSION#`。**倒數第二個 `get-execution-history` 是 00A §3.7 指定由本 Phase 實證的那一項**：`taskFailedEventDetails.error` 必須逐字是 `TransientError`（不是 `Lambda.Unknown`，也不是帶模組路徑的名稱），否則 `ErrorEquals: ["TransientError"]` 根本沒有命中，重試是假的——此時停止，把觀察到的 `error` 值寫進報告，回頭與 Phase 29 一起改 `RETRY`，不要改測試遷就。兩個 execution ARN 與上面每一行的輸出都要寫進證據索引，再提交。

**現況核對（2026-09-14，實測後修正）：直接函式 ARN 的失敗事件是 `LambdaFunctionFailed`，
不是 `TaskFailed`。** 上面倒數第二行的 `events[?type=='TaskFailed']` 在本 Phase 的整合方式
（D-49：`Resource` 是函式 ARN，沒有 `arn:aws:states:::lambda:invoke` 信封）下**永遠是空陣列**；
`taskFailedEventDetails` 只有最佳化整合才會出現。實證要改成：

```bash
aws stepfunctions get-execution-history --region us-east-1 --execution-arn "$FAILED_ARN" \
  --max-results 200 \
  --query "events[?type=='LambdaFunctionFailed'].lambdaFunctionFailedEventDetails.[error,cause]"
```

實測結果（報告 §3 Task 3 有原文）：注入那次得到**三個** `LambdaFunctionFailed`，`error`
逐字都是 `TransientError`，間隔 1 秒與 2 秒，然後 `FailStateEntered` → `ExecutionFailed`
——`ErrorEquals: ["TransientError"]` 確實命中，重試是真的。停止條件因此**沒有**觸發。
00A §3.7 與 §8 證據表的「`taskFailedEventDetails.error`」要改成
「`lambdaFunctionFailedEventDetails.error`」，已回報 controller。

**怎麼讓 `NameGap` 必定丟 `TransientError`（現況核對 2026-09-14 新增）。** O5 BLOCKED 下 `name_gap` 自己會失敗，但失敗成 `PermanentError("ValidationException")`——**一次 `TaskFailed` 就進 Catch**，證不出 Retry。正式的 `TKB_FAULT` 切點是 **P59 的 `src/training_kb/faults.py`**（00A §3.2、§8 第 1230 列），它的五個切點（`s3_after_md`、`ddb_after_version`、`publish_before_transact`、`publish_after_transact_before_site`、`start_execution`）**都不在 `NameGap` 上**，而且 P59 有一條「每個切點名稱在 `content.py`／`publishing.py`／`ingress.py` 各恰好出現一次」的測試，**加第六個切點會打破 P59 的契約**。

**本計畫選擇（P41 做第一片，P59 擴充，不搶 owner）：**

1. P41 建立 `src/training_kb/faults.py`，**逐字照 00A 的簽名**放 `FAULT_POINTS`（就是那五個名稱，一個不多一個不少）、`InjectedFault(TransientError)`、`active_fault(env=None)`、`maybe_fail(point, env=None)`，並附 `tests/unit/test_faults.py` 的基本行為測試。**不在 `content.py`／`publishing.py`／`ingress.py` 插任何 `maybe_fail`** —— 那五處插入、`check_asl_document` 與 `resume_publish` 仍然是 P59 的 Task 1／Task 2，P59 的「三個檔各出現一次」測試因此完全不受影響。
2. P41 另加一個**與 `FAULT_POINTS` 無關**的 task 級開關，放在自己 owner 的 `pipelines/common.py`：`maybe_fail_task(pipeline, task, env=None)` 讀環境變數 **`TKB_FAULT_TASK`**（值是 `"<pipeline>:<task>"`），命中就丟 `InjectedFault`，並沿用 `active_fault` 同一道保險——`TKB_ENV == "prod"` 時一律不生效。`pipeline_task_handler` 在分派**之前**呼叫它一次（**每次 invoke 都重讀環境變數**，不要跟著 `_DEPS` 一起做模組層快取）。
3. 雲端操作：跑失敗那一次之前 `aws lambda update-function-configuration --function-name training-kb-pipeline-task --region us-east-1 --environment 'Variables={...,TKB_FAULT_TASK=ticket-analysis:name_gap}'`，跑完**立刻移除**並把移除後的 `get-function-configuration` 輸出一起存證。
4. 需要 controller 在 00A §3.5 的非 `Settings` 執行期開關清單補一行 `TKB_FAULT_TASK`，並在 §3.2 的 `faults.py` 那列註明「P41 建第一片、P59 擴充」；P60 的 `check_secrets`／部署清單要加「`TKB_FAULT_TASK` 未設、`TKB_ENV=prod`」兩項檢查。

因為 `InjectedFault` 繼承 `TransientError`，Lambda 未攔截例外的類別名是 **`InjectedFault`** 而不是 `TransientError`——ASL 的 `ErrorEquals: ["TransientError"]` 比對的是**類別名字串**，不認繼承。所以注入時要丟的是 **`TransientError` 本身**（`maybe_fail_task` 用 `raise TransientError(...)`，`maybe_fail` 才用 `InjectedFault`），否則證出來的是「`InjectedFault` 沒被重試」這個假陰性。**這一點本身也是 P59 的風險**（P59 的 `InjectedFault` 在雲端同樣不會命中第一條 retrier），實作時請一併寫進報告給 controller。

## 7A. 承接上一批的接線待辦（現況核對 2026-09-14 新增）

上一批（Phase 21–40）把所有真實 AWS 接線延後到本 Phase（D-81），收尾報告
`docs/plan/report/2026-09-14-Phase21-40實作-REP.md` §8 第 5、6、7 項是給本 Phase 的清單。
下表逐項列出承接與去向；**屬於本 Phase 的都已寫進 §7 Task 3 或 §8 驗收矩陣**，
屬於 P48／P52／P57／P59 的只列出、註明去向，本 Phase 不做。

| # | 待辦（來源） | 承接 | 落在哪裡 |
|---|---|---|---|
| A1 | Lambda 與 Function URL：P30 的八秒 deadline 夠不夠、GitHub header 的實際大小寫（REP §8-5） | **本 Phase** | Task 3 Step 3 建 `training-kb-webhook` ＋ Function URL；Step 6 用**自簽的合成請求**打一次 Function URL，記 `X-Hub-Signature-256` 與 HTTP 狀態、實際耗時。**真正來自 GitHub 的 header 大小寫需要一個已設定的 webhook，本批沒有 → 這一項標 BLOCKED 並寫明原因，不猜。** |
| A2 | 三條 state machine 的 `errorType` 對不對得上 `TransientError`（REP §8-5；00A §3.7 指定由本 Phase 實證） | **本 Phase（只有 `ticket-analysis`）** | Task 3 Step 6 的 `get-execution-history`。`feedback-review`（P48）與 `release-update`（P52）的 state machine 本 Phase 不建立 → **去向 P48／P52**，兩者沿用本 Phase 實證出來的結論與同一份 `RETRY`。 |
| A3 | `BotoPipelineStarter` 的錯誤碼表與「ledger 缺 `execution_arn` 時推導 ARN」這個本計畫選擇（REP §8-5；D-77） | **本 Phase（部分）** | ARN 推導：Task 3 Step 6 把 `STATE_MACHINE_NAMES` + 帳號 + region 組出來的 ARN 與 `start-execution` 實際回傳的 ARN **逐字比對**（這一條低成本、必做）。`TRANSIENT_START_CODES` 那張錯誤碼表需要真的觸發節流／5xx，**不刻意製造** → 只記錄本次觀察到的碼，沒觀察到就寫「未觸發」。 |
| A4 | 真實 DynamoDB 的 GSI 落後（moto 是即時的；P27／P28，REP §8-5） | **本 Phase（盡力觀察）** | Task 3 Step 5 種子寫入後**立刻**對 `by_target` 做一次 query 並記錄結果（落後或不落後都照實記）。GSI 落後不是能穩定重現的現象，**觀察不到不算失敗**，但要留下原始輸出；`delete_edge` 的雲端可用性由 A6 的 IAM 解開。 |
| A5 | 真實 S3 的條件寫入與 `ConsistentRead`（P22／P23／P39，REP §8-5） | **本 Phase** | Task 3 Step 4 的 `save_asl_snapshot` 本身就是一次真實 `put_object(..., IfNoneMatch="*")`：**同一版重跑必須丟 `ObjectAlreadyExists`**（`PreconditionFailed` → `ObjectAlreadyExists`），把兩次輸出都留檔。`ConsistentRead` 由 `ensure_embedding` 的 `get_meta(..., consistent=True)` 在真實表上跑過即算實證。 |
| A6 | IAM 三件事：`site/` 寫入、`dynamodb:DeleteItem` 限 `APPLIED_TO#`、`states:DescribeExecution` ＋ `sts:GetCallerIdentity`（REP §8-6；D-79） | **本 Phase** | Task 3 Step 1 的 `test_iam_covers_the_three_gaps_the_previous_batch_left` ＋ Step 3 的三段 policy；`DeleteItem` 的條件鍵限制見該處的「本計畫選擇」。 |
| A7 | 兩個「兩份實作並存」要在 P41 之前收掉（REP §8-7） | **已完成（修正波）** | `_ActiveTutorialFinder` fallback 已刪，`pipelines/ticket.py:_active_tutorial` 現在只委派 `repository.find_active_tutorial_for_feature`（commit `3f9cbe2`）；`publishing._write_tutorial_index` 已改用 `repository.list_versions_of_tutorial`、過時註解已移除（commit `794724c`）。本 Phase **不需要再做**，只在報告引用這兩個 commit。 |
| A8 | P24／P25「真實 AWS 重跑發布切點 ＋ 公開 website endpoint 的 HTTP 人工驗收」（P24 §11、P25 §11 標「延後至 P41／P59」） | **不在本 Phase** | website hosting 與 `site/*` bucket policy 由 **P57** 加進 `infra/training_kb_data_stack.py`（00A §3.2），沒有它就沒有可讀的 public endpoint；切點注入與復原重送由 **P59**。本 Phase 只能到「未發布 v1 已建立」，而且 O5 BLOCKED 下連 v1 都到不了（見 §8）。 |
| A9 | P23／P32 文件裡「真實切點／真實 Step Functions 驗證延後到 P41 起」 | **本 Phase（`ticket-analysis` 部分）** | A2、A3、A5 已涵蓋；`release-update` 的同一組驗證 → **去向 P52**。 |

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
| Gate（**新增 2026-09-14**） | **O5 BLOCKED 時可實證的路徑**：種一筆**已有 `embedding`** 的 `TICKET#t_881`，同群不到五筆 | 真實 AWS 上 `SUCCEEDED`，終點 `NotRecurring`；`TaskStateEntered` 恰好三個（`EnsureEmbedding`／`AssignCluster`／`EvaluateRecurring`）；`CallTrace` **0 次 Bedrock attempt**；0 個版本、0 個新群（`cluster_id` 由 `assign_cluster` 寫回，仍是既有編號規則）。**這是本 Phase 在 O5 BLOCKED 下唯一的 `SUCCEEDED` 證據，必須有。** |
| Gate（**新增 2026-09-14**） | **需要模型的路徑**：`NameGap`／`CreateFirstVersion`／`PublishVersion`，或缺 `embedding` 的 `EnsureEmbedding` | 留 **BLOCKED 證據**，不是 bug 也不算通過：`taskFailedEventDetails.error` 與 `cause` **原文照抄**進報告。預期 `error == "PermanentError"`、`cause` 的 `errorMessage` 是 `ValidationException`（`BedrockWriter._request_once` 把非暫時碼一律轉 `PermanentError`，訊息只留錯誤碼；`amazon.titan-embed-text-v2:0` 與 Claude 目前都回 `ValidationException: Operation not allowed`，見 `docs/plan/report/o5-20260915T030245Z.md`）。**`PermanentError` 不在 `ErrorEquals` 裡，所以只會有一次 `TaskFailed` 就進 Catch——這是設計，不要拿它當 Retry 沒生效的證據。** 觀察到的 `error`／`cause` 與預期不同時，照實記錄並停止，不改測試遷就。 |

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
| Lambda 一 invoke 就 `Runtime.ImportModuleError: No module named 'pydantic'`（**2026-09-14 新增**） | `Code.from_asset("src")` 只帶原始碼，`pydantic`／`jsonschema` 沒進去 | 做 Task 3 Step 3 的相依 layer；`pydantic-core` 是編譯套件，wheel 平台（`x86_64-manylinux2014`）必須與 Lambda 的 `architecture` 一致，不一致時 synth 與 deploy 都不報錯，只有 invoke 才爆。 |
| Lambda 找不到 bucket／`NoSuchBucket: training-kb-content`（**2026-09-14 新增**） | `base_env` 沒設 `TKB_CONTENT_BUCKET`，`load_settings` 退回預設值 | 值一律從 data stack 的跨 stack 參照取；`Template` 斷言要擋住「等於字面 `training-kb-content`」。 |
| `errorType` 是 `AttributeError`（**2026-09-14 新增**） | `pipelines/feedback.py`／`release.py` 的空殼 import 得到，但 handler 屬性還不存在 | `pipeline_task_handler` 用 `getattr(module, attribute, None)` 判斷並轉 `PermanentError`，見 Task 2 Step 3。 |
| `errorType` 是 `InjectedFault` 而不是 `TransientError`（**2026-09-14 新增**） | ASL 的 `ErrorEquals` 比對**類別名字串**，不認繼承 | 注入實證一律丟 `TransientError` 本身；`InjectedFault`（P59）在雲端同樣不會命中第一條 retrier，這件事要寫進報告給 controller。 |

## 10. 來源與 Rule 對照

**本 Phase 是驗收型，沒有任何 primary Rule**（[00B 需求覆蓋對照](00B-需求覆蓋對照.md) 第 1 節：P25、P41、P59、P60 皆如此）。以下全部是「相關」，責任是證明別人已斷言過的行為在雲端的同一條流程裡仍然成立。

- [執行教學流程.feature](../../spec/features/執行教學流程.feature)
  - Rule 2「教學 pipeline 依 Step Functions 預定義節點執行」→ **相關（primary Phase 29）**；Task 2 的 `test_asl_task_names_match_python_tasks` 在本條 pipeline 再驗一次 ASL 節點與 Python task 一一對應。
  - Rule 6「每個 Step Functions Task 設定 Retry」、Rule 7「每個 Step Functions Task 設定 Catch」→ **相關（primary Phase 29）**；Task 2 的 `test_every_task_state_equals_phase29_template_plus_parameters` 逐一把七個 Task 比回 Phase 29 的 `RETRY`／`CATCH`，Task 3 Step 5 再用雲端 `errorType` 證明 `ErrorEquals` 真的命中。
  - Rule 10「Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json`」→ **相關（primary Phase 29）**；Task 3 Step 4 在部署前用 `save_asl_snapshot` 寫出同一份 bytes。
- [接入來源事件.feature](../../spec/features/接入來源事件.feature)：Rule 26「正規化成功的 Ticket 觸發 Ticket Analysis」→ **相關（primary Phase 32）**；驗收矩陣的 Idempotency 列確認重送回原 execution。
  （現況核對 2026-09-14：00B 第 2 節 Rule 26 的「其他相關 Phase」欄確實只列 P41，證據檔是 `tests/unit/test_ingress_acceptance.py`；本 Phase 不重寫那條斷言，只在雲端用 A3 的 ARN 推導比對再確認一次。）
- [分析工單.feature](../../spec/features/分析工單.feature)：14 條的 primary 分散在 Phase 38（Rule 1、2）、Phase 39（Rule 3、4、5）、Phase 40（Rule 7、8、9、10、14）、Phase 21（Rule 11、12、13）與 Phase 04（Rule 6）。本 Phase 全部是**相關**：證明它們在同一條固定流程中沒有互相吞掉，不重複寫斷言。
- 設計 §5：三條預先定義的 Step Functions，Agent 不能自行增加流程。§9.3：三個 pipeline 名稱固定。§14.1／§14.2：Catch 後整次失敗不發布，重試重用已保存輸出。§14.3：Task 120 秒、Lambda 90 秒、暫時錯誤最多兩次等 1 秒與 2 秒。§16 S2：工單達門檻後建立未發布 v1，active 已存在時 KEEP。
- [Step Functions 錯誤處理](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)：`Retry` 欄位（`IntervalSeconds` 預設 1、`MaxAttempts` 預設 3、`BackoffRate` 預設 2.0）、自訂錯誤名稱不得以 `States.` 開頭、`States.ALL` 必須單獨且排在最後、`Catch` 的 `ResultPath`；[Lambda 服務整合](https://docs.aws.amazon.com/step-functions/latest/dg/connect-lambda.html)：直接指定函式 ARN 時 task result 只含函式輸出，最佳化整合才會多包 `Payload` 與 metadata。
- [CDK StateMachine（Python）](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_stepfunctions/StateMachine.html) 與 [StateMachineProps](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_stepfunctions/StateMachineProps.html)：`definition_body`（取代已棄用的 `definition`）、`DefinitionBody.from_file`、`definition_substitutions`、`state_machine_type=STANDARD`、`logs`。

## 11. 完成清單

- [x] `TICKET_ANALYSIS_TASKS`、`run_ticket_analysis`、`ticket_analysis_handler` 的名稱與 Phase 48／52 命名法一致，七個 Task 的順序與 `Parameters.task` 有測試守住；`pipeline_task_handler`、`task_name`、`build_deps` 都在 `pipelines/common.py`，`pipeline` 不在三個名稱內時丟 `PermanentError`。
- [x] 每個 Task 都有兩個 retrier（`TransientError` 與四個 `Lambda.*` 服務例外，皆 1 秒、倍率 2、最多兩次）與 Catch 到 `PipelineFailed`；兩個 Choice 的每個分支都有測試，`ChooseAction` 的 `Default` 走失敗終點。
- [x] state 只含那十個欄位，execution history 看不到工單全文、`feature_id` 或向量。
- [x] `infra/stepfunctions/ticket-analysis/v1.json` 與 S3 快照 `stepfunctions/ticket-analysis/v1.json` 是同一份 bytes。
- [x] CDK 在 `infra/training_kb_stack.py` 產生一個 Standard state machine、`training-kb-pipeline-task` 與 `training-kb-webhook` 兩支 Lambda（handler 分別指向 `pipeline_task_handler` 與 `training_kb.handlers.github_webhook.handler`）與最小 IAM，並有 `definition_substitutions`；部署指令是 `cdk deploy TrainingKbApp`（不加 `uv run`）。
- [x] 成功與失敗各一次的 execution ARN、節點序列、失敗事件的 `error` 原值與 CloudWatch 輸出都已保存。
- [x] **（新增 2026-09-14，COMMON.md R2）** `build/lambda-layer/` 由 `infra/scripts/build_lambda_layer.py` 以 `--python-platform x86_64-manylinux2014 --python-version 3.12 --only-binary=:all:` 產出，與 Lambda 的 `architecture=X86_64` ＋ `Runtime.PYTHON_3_12` 一致；兩支 Lambda **共用同一支 layer**，P42／P48／P52／P54 沿用（stack 上以 `self.deps_layer` 公開）。
- [x] **（新增 2026-09-14；2026-09-14 實作改為純字串名稱，見 Task 3 的本計畫選擇）** `base_env` 的 `TKB_CONTENT_BUCKET` 來自 cdk context／環境變數的實際 bucket 名稱，**不是** `load_settings` 的預設值 `training-kb-content`；`TKB_GENERATION_MODEL_ID` **不設**（O5 BLOCKED，不填猜測值）；`TKB_GITHUB_WEBHOOK_SECRET` 由部署當下的 shell 環境變數提供，值不進 repo、不進報告、不進 log。
- [x] **（新增 2026-09-14，REP §8-6／D-79）** IAM 三個缺口都補在 `infra/training_kb_stack.py` 並有 `Template` 斷言：`site/` 前綴的 `s3:PutObject`；單一條 `dynamodb:DeleteItem`（資源只有這張表、不得放寬成 `dynamodb:*`；**條件鍵做不到 SK 前綴**，見 Task 3 Step 3 的本計畫選擇）；`states:DescribeExecution` 與 `sts:GetCallerIdentity`。
- [x] **（新增 2026-09-14）** §7A 的 A1–A9 每一項都在報告裡有一行結論（做到／去向哪個 Phase／BLOCKED 原因），A5 的 S3 條件寫入與 A3 的 ARN 推導必須有原始輸出。
- [x] **（新增 2026-09-14）** O5 BLOCKED 下的兩列驗收（`NotRecurring` 的 `SUCCEEDED`、需要模型那條的 `error`／`cause` 原文）都已保存；**不得**因為 Bedrock 不可用就跳過雲端執行。
- [x] O2／O3／O5／O6 任一未通過時，文件與報告維持 BLOCKED，不宣稱可公開發布。
