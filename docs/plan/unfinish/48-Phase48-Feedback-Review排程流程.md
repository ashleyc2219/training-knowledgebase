# Phase 48：Feedback Review 排程流程實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作，每個 Task 留下可單獨審查的提交。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **(a) 已存在、可直接重用（不要重寫）**
> - `src/training_kb/pipelines/asl.py`：`RETRY`（:33，**兩條 retrier 的 tuple**，D-53）、`CATCH`（:42，`States.ALL` → `PipelineFailed`）、`FAIL_STATE_NAME = "PipelineFailed"`（:25）、`TASK_TIMEOUT_SECONDS = 120`（:28）、`task_state(resource_arn, next_state)`（:66，回 `Type/Resource/Next/TimeoutSeconds/Retry/Catch`，**不含 `Parameters`**）、`assert_safe_asl(definition)`（:82）、`ASL_LOCAL_PATH = "infra/stepfunctions/{pipeline}/v{number}.json"`（:138）、`ASL_SNAPSHOT_KEY = "stepfunctions/{pipeline}/v{number}.json"`（:141）、`canonical_json(definition) -> bytes`（:145，`indent=2, sort_keys=True`）、`save_asl_snapshot(repository, pipeline, number, body) -> str`（:150，撞鍵先比 bytes 再決定是否 `PermanentError`）。
> - `src/training_kb/pipelines/common.py`：`Deps`（:36，`operations`、`now` 必填，`repository`／`writer`／`settings` 預設 `None` ＋ `need_repository`／`need_writer`／`need_settings`）、`run_sequence(pipeline, payload, tasks, deps)`（:72，**第一個參數是 pipeline 名稱**，D-07；會檢查 `payload["operation_id"]` 非空字串）、`PipelineName`／`PIPELINE_NAMES`（:31，含 `feedback-review`）。
> - `src/training_kb/publishing.py`：`PublishRequest(version_ids, operation_id)`（:108）、`PreparedPublish(request, version_ids, staged_keys, prepared_at)`（:117）、`PublishInspection(ok, problems)`（:131）、`PublishResult(published, failed, reasons)`（:139）、`MAX_BATCH_VERSIONS = 50`（:90）、`assert_batch_publishable(prepared)`（:243）、`Publisher(repository, renderer, operations)` 與 `prepare(request, *, now)`／`inspect(prepared)`／`commit(prepared, *, now)`（:394 起）、`promote_site_objects`（:372）與 `pending-promote.json`（:95）。
> - `src/training_kb/site.py:99` `SiteRenderer()`（四個 keyword 都有預設值，無參數建構是既定用法）。
> - `src/training_kb/operations.py`：`AcceptOperation(operation_id, kind, canonical_id, project_id, now)`（:67）、`OperationCoordinator.accept`／`.complete(operation_id, *, now)`；`OperationKind`（:47）**已含 `"feedback-review"` 與 `"feedback"`**。
> - `src/training_kb/ingress.py:243` `operation_id_for(kind, canonical_id)`、`:252` `execution_name(operation_id)`。
> - `src/training_kb/repository.py`：`put_object(key, body, content_type, *, if_none_match)`（:399，**`if_none_match` 必填、無預設值**）、`get_object`（:422）、`object_exists`（:436）、`scan_entity`（:539）、`get_version`／`get_tutorial`、`item_to_model`（:152）。
> - CDK 相依已就緒（本機實測 `aws-cdk-lib 2.269.0`）：`aws_cdk.aws_scheduler.CfnSchedule` 及其 `FlexibleTimeWindowProperty`／`TargetProperty` 都存在，`aws_stepfunctions.DefinitionBody.from_file` 與 `StateMachineType.STANDARD` 也存在。
> - `src/training_kb/pipelines/feedback.py`：controller 已預建空殼（commit `5f8a430`）。
>
> **(b) 文件因上一批裁決／實作而修正的點**
> 1. **本 Phase 是 W3，硬性前置是 Phase 41 而且 P41 目前還沒做。** 下列名稱**現在都不存在**，實作前必須先確認 P41 已合併：`infra/training_kb_stack.py`（整支檔）、`infra/stepfunctions/` 目錄、`task_name(task)`／`build_deps(settings)`／`pipeline_task_handler(event, context)`（00A §6.9 說三個都在 `pipelines/common.py`，P41 追加）、`training-kb-pipeline-task` Lambda。
> 2. **R2（Lambda 打包）**：`lambda_.Code.from_asset("src")` 不含 `pydantic`／`jsonschema`。P41 會做一支可重現的相依 layer 或 Docker bundling，**P48 沿用同一支，不自己再做一套**（COMMON.md R2）。
> 3. `cdk` 指令要照 COMMON.md §1：本機互動 shell 把 `node` 定成會拒絕的 function，一律 `command npx aws-cdk@2 <子命令>`，並帶 `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1`；`--outputs-file` 指到 scratchpad，**不要提交 `cdk.out/`**。`aws` CLI 一律帶 `--region us-east-1`（預設是 ap-northeast-1）。
> 4. ASL 本地檔請用 `canonical_json(...)` 的 bytes 落檔（`indent=2, sort_keys=True`），這樣 `DefinitionBody.from_file` 讀到的 bytes 與 `save_asl_snapshot` 存的 bytes **逐 byte 相同**；路徑用 `ASL_LOCAL_PATH.format(pipeline="feedback-review", number=1)`，不要在測試裡手打字串。
> 5. Task 3 的 `names == {"training-kb-pipeline-task", "training-kb-webhook", "training-kb-import"}` **依賴 P42 已把 `training-kb-import` 加進 stack**（D-58）；P42 未合併就改成 `names >= {...}` 或先只斷言前兩支，並在報告寫明。P54 之後會再加 `training-kb-analytics`，屆時要補齊。
> 6. `assert_safe_asl` 對每個 Task 檢查三件事：**前兩條 retrier 逐字等於 `RETRY`**、沒有 retrier 涵蓋 `States.ALL`、**恰好一條** `States.ALL` 的 `Catch` 導向同層 `Fail` state。自己多加第三條 retrier 會過，但多寫一條 Catch 會被擋。
> 7. `run_sequence` 遇到例外先 `operations.fail(...)` 再**原樣 raise**（不吞、不轉型），所以 `run_feedback_review` 不必也不得自己 try／except。
>
> **(c) gate 現況對本 Phase 的影響**（COMMON.md §2、§3 R1）
> - O1 provisionally accepted（D-71）；**O2 PASS**（P11，`docs/plan/report/o2-20260914t182824z.md`）——原文「**O2** 未 PASS 前……不得宣稱永久去重已驗證」已不成立，重送去重可以依賴 `accept` 的條件寫入；**O3 FAIL**（P12，`docs/plan/report/o3-20260914t181109z.md`；P24／P25 已依協定 A 在 moto 重現切點，**F49 未放寬，決策出口仍在維護者手上**，D-80）；**O5 BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`）；O6 待核定；O4／O7 未到。
> - **R1：本 Phase 要真的部署與執行**（`training-kb-feedback-review` state machine、EventBridge Scheduler、真實 execution），並保存 execution ARN、`describe-execution`、`get-execution-history`、CloudWatch 證據。做不到的部分標 BLOCKED 並附實際錯誤原文，不填猜測值、不假裝通過。
> - **O5 BLOCKED 的具體後果**：真實 AWS 執行時 `EvaluateTargets` 裡需要模型的三個節點（`diagnose_weak`、`refine_steps`、`propose_rule`）會丟 `PermanentError` → `Catch` → `PipelineFailed`。**那是 BLOCKED 證據，不是 bug，也不是通過。** 要保留 `get-execution-history` 原文與 `errorType`／`cause`。
> - **O3 FAIL 的具體後果**：多篇整批發布只能依協定 A 在 moto 驗證切點；真實 AWS 上跑到發布切點就**把觀察到的結果原樣記錄**，不宣稱 PASS、不放寬 F49。
> - §8 驗收矩陣已依此改寫成「可實證路徑」與「BLOCKED／原樣記錄路徑」兩段。
>
> **(d) controller 裁決 R1–R11 的適用項**
> - **R3（同檔併行）**：`pipelines/feedback.py`（P44／P45／P46／P47 都動過）與 `infra/training_kb_stack.py`（P41 建、P42 已加 import Lambda、P54 之後還會加）都是共用檔。只用 Edit 不用 Write；動手前先重讀要改的那一段；自己的程式放 `# ---- Phase 48 ----` 區段；不重排、不重格式化；共用檔只跑 `ruff format --check`；`git add` 只加自己的檔案路徑；整套測試紅燈若來自別的 Phase 進行中的測試檔，用 `--ignore=` 排除並在報告寫明。
> - **R4**：`pipelines/feedback.py` 空殼已建，直接 Edit。**R5**：文件片段是示意，簽名以 00A ＋ 既有程式為準。
> - **R6／R7／R8**：逐 Task 先紅燈再綠燈；報告寫 `docs/plan/report/phases/2026-09-14-Phase48-REP.md`；commit trailer 照 COMMON.md R8；**絕不 push**。
> - 測試檔照 00A §3.3 平放：`tests/unit/test_feedback_review_flow.py`、`tests/integration/test_feedback_review_state_machine.py`（兩個 basename 全專案唯一）。

**目標：** 把弱教學選取、診斷、REFINE 與 candidate 提案接成每日一次的 `feedback-review` Standard workflow，並保證多篇要嘛一起發布、要嘛一篇都不發布。

**架構：** EventBridge Scheduler 每日 UTC 00:30 用固定 input 啟動 `training-kb-feedback-review`。五個 Task 共用 Phase 41 的 `training-kb-pipeline-task` Lambda，靠 `Parameters.pipeline` 與 `Parameters.task` 分派；本 Phase 只做 orchestration，業務判斷全部呼叫 Phase 44–47 的既有函式。

**技術：** Python 3.12、AWS Step Functions Standard、EventBridge Scheduler、AWS CDK、pytest，以及 Phase 29 的 `run_sequence`／`RETRY`／`CATCH`／`task_state` 與 Phase 24／25 的 `Publisher`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.5、§8.3、§14.2、§14.3、§18](../../design/training-kb.md)；名稱與簽名以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 為準（第 3.7 節 Retry／Catch、第 6.9 節 `pipelines`、第 7 節 state 與 Task 契約），Rule 歸屬以 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 為準。
- 前置是 [Phase 29：共用 Pipeline 執行器與 ASL 失敗語意](29-Phase29-共用Pipeline執行器與ASL失敗語意.md)（`run_sequence`、`RETRY`、`CATCH`、`task_state`）、[Phase 41：Ticket Analysis 雲端流程驗收](41-Phase41-Ticket-Analysis雲端流程驗收.md)（`pipeline_task_handler`、`build_deps`、`task_name`、`infra/training_kb_stack.py`）、[Phase 44](44-Phase44-弱教學門檻與目標選取.md)–[Phase 47](47-Phase47-Candidate規則提出與溯源.md)（四個業務函式）與 [Phase 12：O3 發布切換整合驗證](12-Phase12-O3發布切換整合驗證.md)。前置未通過時停止。
- 下一階段是 [Phase 49：Release 功能定位與 Alias](49-Phase49-Release功能定位與Alias.md)。
- 本階段不做：不新增第四條 pipeline（Demo 手動觸發共用同一個 state machine）；不改弱教學門檻、診斷、REFINE 或 candidate 的判斷邏輯（Phase 44–47）；不寫 `RULE.status`（只有 Phase 55 能寫）；不新增 CloudFront、公開讀取 API 或人工發布審核佇列；不做部分發布。
- **`O` 開頭是設計文件 §18 的七個待確認事項**（現況核對 2026-09-14，見 COMMON.md §2）。**O3 FAIL**（P12，`docs/plan/report/o3-20260914t181109z.md`）：`CommitBatch` 依 Phase 24／25 的停止條件回失敗是**預期**結果，整批切點照協定 A 在 moto 驗證、真實 AWS 上原樣記錄，本階段只能宣稱「未發布版本已建立」，不得宣稱公開發布已驗收、不得放寬 F49；**O2 PASS**（P11，原寫「未 PASS」已不成立）：「同 operation 重送不重複建版」由 `OperationCoordinator.accept` 的條件寫入與既有 staging 物件核對達成，永久去重可以依賴；**O5 BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`）：單元測試用假 `Writer`，真實 AWS 上需要模型的節點會走 `Catch` → `PipelineFailed`，那是 BLOCKED 證據不是 bug。
- 每個 Task 都有有界 `Retry` 與導向 `PipelineFailed` 的 `Catch`；Catch 之後整次失敗、不建版也不發布（設計 F49；`F` 開頭是設計文件 §19.2 的功能決策編號）。
- 每日只看 active Tutorial 的 current 已發布版本，累計該版截至本次執行的全部有效回饋（設計 §7.5），不做「上次檢視之後」的浮水印切分。
- state 只放 ID、S3 key 與小型判斷結果，不放教學全文、回饋留言或向量（設計 §14.3、00A 第 7 節）。
- 以下程式檔與 ASL 檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
EventBridge Scheduler  cron(30 0 * * ? *) UTC  input = {"mode": "formal"}
                v
   [你在這裡] training-kb-feedback-review（Standard）
                |
        ListTargets -> active Tutorial 的 current 已發布版本
                |
        EvaluateTargets（每篇兩條獨立分支，不共用條件）
       +--------+---------------------------+
       |                                    |
  candidate 分支 Phase 47              弱教學分支 Phase 44/45/46
  candidate_groups -> propose_candidate  select_weak_targets ->
       |                                 diagnose_weak -> prepare_refine
       +--------+---------------------------+
                v
        PrepareBatch -> InspectBatch -> CommitBatch -> Succeeded
                |            |              |
             任一失敗 -----> Catch ------> PipelineFailed（零發布）
```

## 2. 完成後看得到什麼

排程與手動入口用**同一個** state machine、同一種 input `{"mode": "formal"}`，只有 `mode` 不同：`"formal"` 是正式門檻（n >= 10）、`"demo"` 是隔離門檻（n >= 8），其他值直接 `PermanentError`。`operation_id` 不由呼叫端提供，由 `ListTargets` 以「專案加當日 UTC 日期」產生，所以同一天重送會落在同一筆 operation 紀錄。成功結束後 `result_ref` 指向私有物件 `operations/op-feedback-review-demo-2026-09-13/review-result.json`：

```json
{
  "reviewed_version_ids": ["notification-settings@v1", "prepare-meeting@v1", "share-summary@v1"],
  "candidate_rule_ids": ["R-ad0afde8"],
  "prepared_version_ids": ["prepare-meeting@v2"],
  "published_version_ids": ["prepare-meeting@v2"],
  "no_change_reasons": {"notification-settings@v1": "不是弱教學", "share-summary@v1": "不是弱教學"}
}
```

若第二篇的私有產物檢查失敗，第一篇也**不會**發布：兩篇的 `current_version` 與公開頁都維持舊值，execution 是 `FAILED`。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| Standard workflow | Step Functions 的一種類型，執行紀錄可逐節點回查；三條 pipeline 都用它。 |
| EventBridge Scheduler | AWS 的排程服務；`cron(30 0 * * ? *)` 是六欄位寫法（分 時 日 月 週 年），意思是每天 00:30。 |
| `Parameters.task` | ASL 傳給共用 Lambda 的 task 名稱，等於 Python 函式名去掉 `task_` 前綴。 |
| prepare／inspect／commit | Phase 24／25 的固定三段式發布：先把產物放私有 staging、再整批檢查、最後一次提交。 |
| `PipelineFailed` | 三條 pipeline 共用的 Fail state 名稱；所有 `Catch` 都指向它，之後不得再產生新版本。 |
| 整批（batch） | 本次所有待發布版本一起提交；任一篇不通過就整批不提交（設計 F49）。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/feedback.py` | 五個 task 函式、`FEEDBACK_REVIEW_PIPELINE`、`REVIEW_MODES`、`review_operation_id`、`FEEDBACK_REVIEW_TASKS`、`run_feedback_review`、`feedback_review_handler`（檔案 owner 是 Phase 44；controller 已預建空殼，本 Phase 是 **W3**，只用 Edit 追加 `# ---- Phase 48 ----` 區段）。 |
| 建立 | `infra/stepfunctions/feedback-review/v1.json` | 固定 Standard ASL 定義。 |
| 修改 | `infra/training_kb_stack.py` | state machine、Scheduler 角色與每日排程（檔案 owner 是 Phase 41）。**現況核對 2026-09-14：這支檔與 `infra/stepfunctions/` 目錄目前都不存在，由 P41 建立；P48 開工前先確認 P41 已合併。** Lambda 相依打包沿用 P41 的 layer／bundling，不自己再做一套（COMMON.md R2）。 |
| 測試 | `tests/unit/test_feedback_review_flow.py` | 分支互不阻擋、整批語意、ASL 結構與 CDK template。 |
| 測試 | `tests/integration/test_feedback_review_state_machine.py` | 真實 AWS 執行與 O3 故障切點（`@pytest.mark.aws`）。 |

## 5. 固定介面

### Consumes

```text
PermanentError / TransientError、load_settings(env) -> Settings                    # Phase 02
Tutorial / TutorialStatus / TutorialVersion                                       # Phase 03／04
Repository.scan_entity / get_version / list_feedback_of_version / get_tutorial    # Phase 06／08
Repository.put_object(key, body, content_type, *, if_none_match) -> None、
           get_object(key) -> bytes | None、object_exists(key) -> bool             # Phase 07
item_to_model(item, model) -> T（模組函式，不是方法；00A D-29）                      # Phase 08
AcceptOperation、OperationCoordinator.accept / .complete                           # Phase 10
operation_id_for(kind: OperationKind, canonical_id: str) -> str                   # Phase 32
run_sequence(pipeline, payload, tasks, deps) -> dict                              # Phase 29（D-07）
RETRY / CATCH / task_state(resource_arn, next_state) / assert_safe_asl /
save_asl_snapshot(repository, pipeline, number, body) -> str                      # Phase 29
Deps(operations, now, repository=None, writer=None, settings=None) 與三個 need_*    # Phase 29＋38（D-36）
task_name(task) / build_deps(settings) / pipeline_task_handler(event, context)    # Phase 41
approved_categories(repository) -> frozenset[str]                                 # Phase 43
select_weak_targets(*, repository, mode, now, thresholds=None)                    # Phase 44
diagnose_weak(target, *, repo, writer, operation_id) -> DiagnosisResult           # Phase 45
prepare_refine(diagnosis, *, repo, writer, operations, operation_id)、
evidence_fingerprint(version_id, category, ids)、refine_operation_id(...)          # Phase 46
candidate_groups(feedback, approved) / candidate_rule_id(group) /
propose_candidate(group, *, writer, repo, operation_id, rule_id)                  # Phase 47
PublishRequest / PreparedPublish / Publisher.prepare|inspect|commit / SiteRenderer()  # Phase 24
assert_batch_publishable(prepared) -> None、MAX_BATCH_VERSIONS                     # Phase 25
```

`run_sequence` 會先檢查 payload 有非空 `operation_id`（Phase 29），但 `feedback-review` 沒有外部事件，ASL input 只有 `mode`，`operation_id` 是由 `ListTargets` 依「專案＋當日 UTC 日期」產生的——所以本機整條跑的 `run_feedback_review` 要先呼叫 `review_operation_id(...)` 把它補進 payload 再交給 `run_sequence`；雲端路徑不經 `run_sequence`，Step Functions 直接逐個 Task 呼叫 handler，因此不受這個前置檢查影響。另外三個最容易寫錯的地方：`run_sequence` 的第一個參數是 **pipeline 名稱**、第二個才是 state（00A D-07）；`Deps` 要用 Phase 38 擴充後的版本，`repository`／`writer`／`settings` 一律經 `need_*` 取得（D-36）；Phase 45–47 的 keyword 是 `repo=`，Phase 44 與 Publisher 相關的是 `repository=`，兩邊都不得互改（00A 第 6.9 節）。

### Produces

```python
FEEDBACK_REVIEW_PIPELINE: PipelineName = "feedback-review"
FEEDBACK_REVIEW_TASKS: tuple[TaskFn, ...]

def review_operation_id(state: dict, deps: Deps) -> str: ...
def task_list_targets(state: dict, deps: Deps) -> dict: ...
def task_evaluate_targets(state: dict, deps: Deps) -> dict: ...
def task_prepare_batch(state: dict, deps: Deps) -> dict: ...
def task_inspect_batch(state: dict, deps: Deps) -> dict: ...
def task_commit_batch(state: dict, deps: Deps) -> dict: ...
def run_feedback_review(state: dict, deps: Deps) -> dict: ...
def feedback_review_handler(event: dict, context: object) -> dict: ...
```

`review_operation_id` 與 `_review_mode` 是本 Phase 新增的小工具；[00A 第 6.9 節](00A-共用契約與名詞.md) 的 P48 那一列已列出 `review_operation_id`（依 D-65 補入），私有的 `_review_mode` 刻意不列。它的 canonical id 逐字是 `f"{project_id}-{UTC 日期}"`——**用連字號，不用 `#`**（00A D-61），所以 `operation_id` 就是 `op-feedback-review-demo-2026-09-13`，`execution_name` 可以原樣沿用而不必走 SHA-256 截取（`execution_name` 只接受 `[A-Za-z0-9_-]`，`#` 會觸發截取，同一天的名稱就變得認不出來）。state 只有八個欄位（00A 第 7 節逐字）：`operation_id`、`project_id`、`mode`、`target_version_ids`、`candidate_rule_ids`、`prepared_version_ids`、`publish_request_ref`、`result_ref`。逐篇的「沒有改動」理由不進 state：`EvaluateTargets` 先寫 `operations/<operation_id>/review-no-change.json`，`CommitBatch` 再把它併進 `result_ref` 指向的 `review-result.json`。

## 6. ASL 與失敗語意

```text
task 函式 raise TransientError -> handler 不攔截，直接往外拋
        |
Lambda runtime 回 errorType = "TransientError"（只有類別名，沒有模組路徑）
        |
Retry[0] 命中 -> 等 1 秒、再等 2 秒；Retry[1] 只接 Lambda 服務層暫時錯誤
        |
仍失敗，或任何 PermanentError -> Catch ["States.ALL"] -> PipelineFailed (Fail)
        |
        v
整次 execution FAILED；沒有任何 published_at 被切換、site/ 沒有新物件
```

`Retry` 與 `Catch` **一律 import Phase 29 的 `RETRY`／`CATCH`，不在本 Phase 另寫一份**。每個 Task 固定兩個 retrier（00A 裁決 D-53）：第一個接業務的 `TransientError`，第二個接 `Lambda.ServiceException`、`Lambda.AWSLambdaException`、`Lambda.SdkClientException`、`Lambda.TooManyRequestsException`，兩者都是 1 秒／2 次／倍率 2。`ErrorEquals` 只寫**類別名**，不得加模組或套件前綴（00A §3.7、D-15）——Python Lambda 未處理例外回給 Step Functions 的 `errorType` 就是類別名本身。`PermanentError` 刻意不進 `ErrorEquals`，資料不合法時直接進 Catch。以下是 `infra/stepfunctions/feedback-review/v1.json` 的節錄，其餘四個 Task 與 `ListTargets` 逐字相同，只改 `Parameters.task` 與 `Next`：

```json
{
  "Comment": "Training KB feedback-review（設計 7.5）；五個 Task 呼叫同一個 Lambda，用 pipeline 與 task 名稱分派。",
  "StartAt": "ListTargets",
  "States": {
    "ListTargets": {
      "Type": "Task",
      "Resource": "${PipelineTaskFunctionArn}",
      "Parameters": {"pipeline": "feedback-review", "task": "list_targets", "state.$": "$"},
      "TimeoutSeconds": 120,
      "Retry": [{"ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2},
                {"ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.failure", "Next": "PipelineFailed"}],
      "Next": "EvaluateTargets"
    },
    "Succeeded": {"Type": "Succeed"},
    "PipelineFailed": {"Type": "Fail", "Error": "PipelineFailed", "Cause": "本次整批失敗，不發布任何新版本"}
  }
}
```

| ASL state | `Parameters.task` | `Next` |
|---|---|---|
| `ListTargets` | `list_targets` | `EvaluateTargets` |
| `EvaluateTargets` | `evaluate_targets` | `PrepareBatch` |
| `PrepareBatch` | `prepare_batch` | `InspectBatch` |
| `InspectBatch` | `inspect_batch` | `CommitBatch` |
| `CommitBatch` | `commit_batch` | `Succeeded` |

五個 Task 是一條直線，**沒有 Choice，也沒有 Map**：把逐篇處理拆進 Map 會讓「第一篇已 publish、第二篇失敗」變成可能，那正是 F49 禁止的形狀。`EvaluateTargets` 內含兩條獨立判斷（candidate 與 REFINE），00A 第 7 節明講不拆成兩個 Task。Lambda Task 用**直接函式 ARN**，事件封套只有 `Parameters` 的三個欄位，**沒有** `Payload` 外層（00A D-24、D-49）。`TimeoutSeconds` 120 與 Lambda 的 90 秒逾時都取自設計 §14.3。執行角色只需要對共用 Lambda 的 `lambda:InvokeFunction`；Scheduler 角色只可對這一條 state machine `states:StartExecution`。

## 7. TDD Tasks

### Task 1：兩條獨立分支與 state 契約

- [x] **Step 1：建立失敗測試**

```python
# tests/unit/test_feedback_review_flow.py
import json
from datetime import UTC, datetime

import pytest

from training_kb.errors import PermanentError
from training_kb.pipelines.common import task_name
from training_kb.pipelines.feedback import (FEEDBACK_REVIEW_TASKS, refine_operation_id,
                                            select_weak_targets, task_evaluate_targets,
                                            task_list_targets)

NOW = datetime(2026, 9, 13, 0, 30, tzinfo=UTC)
OP = "op-feedback-review-demo-2026-09-13"

def test_task_order_and_names_are_fixed():
    assert [task_name(task) for task in FEEDBACK_REVIEW_TASKS] == [
        "list_targets", "evaluate_targets", "prepare_batch", "inspect_batch", "commit_batch"]

def test_unknown_mode_is_permanent(review_deps):
    with pytest.raises(PermanentError):
        task_list_targets({"mode": "staging"}, review_deps)

def test_list_targets_only_takes_active_published_current_versions(review_deps):
    state = task_list_targets({"mode": "formal"}, review_deps)
    assert state["target_version_ids"] == ["b@v1", "c@v1", "d@v1"]   # a 已退役、e 尚未發布
    assert state["operation_id"] == OP and state["project_id"] == "demo"

def test_candidate_and_refine_branches_do_not_block_each_other(review_deps):
    # b：五筆 rating=5 的同類回饋 -> 只有 candidate；c：正式弱教學 -> candidate 與 RefinePlan；d：兩者皆無
    state = task_evaluate_targets(task_list_targets({"mode": "formal"}, review_deps), review_deps)
    assert state["candidate_rule_ids"] == ["R-b", "R-c"]
    assert state["prepared_version_ids"] == ["c@v2"]
    assert set(state) == {"operation_id", "project_id", "mode", "target_version_ids",
                          "candidate_rule_ids", "prepared_version_ids"}

def test_each_weak_target_gets_its_own_refine_operation(review_deps):
    listed = task_list_targets({"mode": "formal"}, review_deps)
    target = select_weak_targets(repository=review_deps.need_repository(), mode="formal",
                                 now=review_deps.now(),
                                 thresholds=review_deps.need_settings().thresholds)[0]
    task_evaluate_targets(listed, review_deps)
    sub_id = refine_operation_id(target.version_id, target.category, target.feedback_ids)
    assert sub_id != OP and sub_id.startswith("op-feedback-")
    assert review_deps.operations.accepted_ids == [OP, sub_id]   # 當日主 operation + 子 operation
```

`review_deps` 是本檔的 fixture：用 Phase 44–47 既有的假 `Repository`／`Writer` 組出 `Deps(operations=FakeOperations(), now=lambda: NOW, repository=..., writer=..., settings=load_settings({}))`，資料就是上面註解的五篇教學；`FakeOperations.accepted_ids` 是測試鉤子，依接受順序記下每一個 `accept` 進來的 `operation_id`。另外補一個 `test_refine_failure_keeps_candidate`：讓 `prepare_refine` 丟 `PermanentError`，斷言 c 的 candidate 仍已寫入且 `status` 是 `candidate`。

- [x] **Step 2：執行 `uv run pytest tests/unit/test_feedback_review_flow.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'FEEDBACK_REVIEW_TASKS' from 'training_kb.pipelines.feedback'`。

- [x] **Step 3：建立最小實作**

```python
# src/training_kb/pipelines/feedback.py（檔案由 Phase 44 建立，本階段追加 pipeline 組裝）
import json

from training_kb.errors import PermanentError
from training_kb.ingress import approved_categories, operation_id_for
from training_kb.models import Tutorial, TutorialStatus
from training_kb.operations import AcceptOperation
from training_kb.pipelines.common import Deps, PipelineName
from training_kb.repository import Repository, item_to_model

FEEDBACK_REVIEW_PIPELINE: PipelineName = "feedback-review"
REVIEW_MODES = ("formal", "demo")

def _review_targets(repository: Repository) -> list[str]:
    found = []
    for item in repository.scan_entity("TUTORIAL"):
        tutorial = item_to_model(item, Tutorial)
        if tutorial.status is not TutorialStatus.ACTIVE or tutorial.current_version is None:
            continue
        version = repository.get_version(tutorial.current_version)
        if version is not None and version.published_at is not None:
            found.append(version.version_id)
    return sorted(found)

def _review_mode(state: dict) -> str:
    mode = str(state.get("mode") or "formal")
    if mode not in REVIEW_MODES:
        raise PermanentError(f"未知的 review mode：{mode!r}")
    return mode

def review_operation_id(state: dict, deps: Deps) -> str:
    """feedback-review 沒有外部事件，operation_id 由「專案＋當日 UTC 日期」決定。"""
    project_id = str(state.get("project_id") or deps.need_settings().project_id)
    canonical = f"{project_id}-{deps.now().date().isoformat()}"     # 連字號，不用 `#`（D-61）
    return str(state.get("operation_id") or operation_id_for("feedback-review", canonical))

def task_list_targets(state: dict, deps: Deps) -> dict:
    mode, now = _review_mode(state), deps.now()
    project_id = str(state.get("project_id") or deps.need_settings().project_id)
    operation_id = review_operation_id(state, deps)
    deps.operations.accept(AcceptOperation(
        operation_id=operation_id, kind="feedback-review", project_id=project_id,
        canonical_id=f"{project_id}-{now.date().isoformat()}", now=now))
    return {"operation_id": operation_id, "project_id": project_id, "mode": mode,
            "target_version_ids": _review_targets(deps.need_repository())}

def task_evaluate_targets(state: dict, deps: Deps) -> dict:
    repository, writer = deps.need_repository(), deps.need_writer()
    operation_id, approved = str(state["operation_id"]), approved_categories(repository)
    weak = {target.version_id: target
            for target in select_weak_targets(repository=repository, mode=str(state["mode"]),
                                              now=deps.now(),
                                              thresholds=deps.need_settings().thresholds)}
    rule_ids: list[str] = []
    prepared: list[str] = []
    reasons: dict[str, str] = {}
    for version_id in [str(value) for value in state["target_version_ids"]]:
        found: list[str] = []
        for group in candidate_groups(repository.list_feedback_of_version(version_id), approved):
            found.append(propose_candidate(group, writer=writer, repo=repository,
                                           operation_id=operation_id,
                                           rule_id=candidate_rule_id(group)).rule_id)
        target, plan = weak.get(version_id), None
        if target is not None:
            fingerprint = evidence_fingerprint(target.version_id, target.category,
                                               target.feedback_ids)
            refine_id = refine_operation_id(target.version_id, target.category,
                                            target.feedback_ids)
            deps.operations.accept(AcceptOperation(      # 每個 target 一個子 operation（D-59）
                operation_id=refine_id, kind="feedback", canonical_id=fingerprint,
                project_id=str(state["project_id"]), now=deps.now()))
            plan = prepare_refine(diagnose_weak(target, repo=repository, writer=writer,
                                                operation_id=refine_id),
                                  repo=repository, writer=writer, operations=deps.operations,
                                  operation_id=refine_id)
            if plan is not None:
                prepared.append(plan.version_id)
        rule_ids.extend(found)
        if not found and plan is None:
            reasons[version_id] = "不是弱教學" if target is None else "診斷沒有可改步驟，或沒有新證據"
    repository.put_object(f"operations/{operation_id}/review-no-change.json",
                          json.dumps(reasons, ensure_ascii=False).encode("utf-8"),
                          "application/json", if_none_match=False)
    return {**state, "candidate_rule_ids": sorted(rule_ids),
            "prepared_version_ids": sorted(prepared)}
```

`select_weak_targets` 的四個 keyword（`repository`／`mode`／`now`／`thresholds`）一個都不能省，`thresholds` 一律取 `deps.need_settings().thresholds`，才不會讓 `demo` 門檻在這裡被預設值蓋掉。它**呼叫在 `EvaluateTargets`、不是 `ListTargets`**：`ListTargets` 只負責列出「active 且 current 已發布」的版本 ID（那是 state 裡的 `target_version_ids`），弱教學判斷與 candidate 判斷是同一個 Task 裡的兩條獨立分支，00A 第 7 節明講不拆成兩個 Task；`WeakTarget` 物件也不能放進 state。

兩條分支寫在同一個迴圈但**沒有共用條件**：candidate 只看 `candidate_groups` 的同版同類門檻，REFINE 只看 `select_weak_targets` 的結果，所以「平均 5.0 但同類五筆」仍會提規則，「弱教學但診斷無命中」仍不會建版。`select_weak_targets`、`diagnose_weak`、`prepare_refine`、`candidate_*`、`evidence_fingerprint`、`refine_operation_id` 都在同一個模組，不需要 import。

**每個弱教學 target 都有自己的子 operation（00A D-59）。** 「子 operation」就是在當日這筆 review operation 底下，為每一篇教學另外開一筆自己的 `OPS#` 紀錄。必須這樣做，是因為 `allocate_version` 以 `operation_id` 當唯一鍵、`OperationRecord.version_id` 只有一個值：兩篇教學共用當日的 `op-feedback-review-...` 會互相搶同一個版號。所以這裡先用 Phase 46 的 `refine_operation_id(...)`（證據指紋導出，形狀 `op-feedback-<64 位指紋>`）`accept` 一筆子 operation，再把它當成 `diagnose_weak` 與 `prepare_refine` 的 `operation_id`；`prepare_refine` 內部會再核對一次指紋，對不上就丟 `CoordinationError`。當日的 review `operation_id` 仍然是整批流程的主鍵（`review-no-change.json`、`publish-request.json`、`review-result.json` 都掛在它底下），candidate 分支也繼續用它。

- [x] **Step 4：執行 `uv run pytest tests/unit/test_feedback_review_flow.py -q` 確認綠燈**

預期五個測試全部 `passed`，且 `state` 的鍵集合恰好落在 00A 第 7 節那八個欄位內，沒有回饋留言或教學全文。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_feedback_review_flow.py
git commit -m "feat(feedback): 組合每日回饋檢視的兩條獨立分支"
```

### Task 2：整批 prepare／inspect／commit 與 F49

- [x] **Step 1：建立失敗測試**

```python
# 續寫 tests/unit/test_feedback_review_flow.py
# review_deps_two_weak：b 與 c 都是弱教學且診斷有命中；review_deps_bad_second：c 的私有產物
# 會讓 inspect 不通過；review_deps_no_target：沒有任何 active 已發布版本。
from training_kb.pipelines.feedback import feedback_review_handler, run_feedback_review

def test_two_prepared_versions_commit_together(review_deps_two_weak):
    result = run_feedback_review({"mode": "formal"}, review_deps_two_weak)
    published = json.loads(review_deps_two_weak.need_repository()
                           .get_object(result["result_ref"]).decode("utf-8"))
    assert result["prepared_version_ids"] == ["b@v2", "c@v2"]
    assert published["published_version_ids"] == ["b@v2", "c@v2"]
    assert published["no_change_reasons"] == {"d@v1": "不是弱教學"}

def test_second_version_failing_inspection_publishes_nothing(review_deps_bad_second):
    with pytest.raises(PermanentError):
        run_feedback_review({"mode": "formal"}, review_deps_bad_second)
    repository = review_deps_bad_second.need_repository()
    assert repository.get_tutorial("b").current_version == "b@v1"
    assert repository.get_tutorial("c").current_version == "c@v1"
    assert [k for k in repository.object_keys() if k.startswith("site/")] == []  # 假 Repository 的輔助

def test_empty_batch_succeeds_without_touching_publisher(review_deps_no_target):
    result = run_feedback_review({"mode": "formal"}, review_deps_no_target)
    assert result["publish_request_ref"] is None and result["prepared_version_ids"] == []
    assert review_deps_no_target.need_writer().calls == []

def test_resend_reuses_prepared_artifacts(review_deps_two_weak):
    first = run_feedback_review({"mode": "formal"}, review_deps_two_weak)
    before = list(review_deps_two_weak.need_writer().calls)
    second = run_feedback_review({"mode": "formal"}, review_deps_two_weak)
    assert second["publish_request_ref"] == first["publish_request_ref"]
    assert review_deps_two_weak.need_writer().calls == before   # 不重打模型、不重配版號

def test_handler_rejects_unknown_task():
    with pytest.raises(PermanentError):
        feedback_review_handler({"task": "publish_everything", "state": {}}, None)
```

- [x] **Step 2：執行 `uv run pytest tests/unit/test_feedback_review_flow.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'run_feedback_review'`。

- [x] **Step 3：建立最小實作**

```python
# src/training_kb/pipelines/feedback.py（續）
import os

from training_kb.config import load_settings
from training_kb.pipelines.common import TaskFn, build_deps, run_sequence, task_name
from training_kb.publishing import (MAX_BATCH_VERSIONS, PreparedPublish, Publisher,
                                    PublishRequest, assert_batch_publishable)
from training_kb.site import SiteRenderer

def _publisher(deps: Deps) -> Publisher:
    return Publisher(deps.need_repository(), SiteRenderer(), deps.operations)

def _prepared(state: dict, deps: Deps) -> PreparedPublish | None:
    """同 operation 重跑會得到同一批 staging 產物（設計 §14.2），所以不必把它塞進 state。"""
    version_ids = tuple(str(value) for value in state["prepared_version_ids"])
    if not version_ids:
        return None
    if len(version_ids) > MAX_BATCH_VERSIONS:
        raise PermanentError(f"單批最多 {MAX_BATCH_VERSIONS} 個版本，本次 {len(version_ids)} 個")
    request = PublishRequest(version_ids=version_ids, operation_id=str(state["operation_id"]))
    return _publisher(deps).prepare(request, now=deps.now())

def task_prepare_batch(state: dict, deps: Deps) -> dict:
    prepared = _prepared(state, deps)
    if prepared is None:
        return {**state, "publish_request_ref": None}
    assert_batch_publishable(prepared)
    key = f"operations/{state['operation_id']}/publish-request.json"
    deps.need_repository().put_object(
        key, json.dumps({"version_ids": list(prepared.version_ids),
                         "staged_keys": list(prepared.staged_keys)},
                        ensure_ascii=False).encode("utf-8"), "application/json",
        if_none_match=False)
    return {**state, "publish_request_ref": key}

def task_inspect_batch(state: dict, deps: Deps) -> dict:
    prepared = _prepared(state, deps)
    if prepared is None:
        return dict(state)
    inspection = _publisher(deps).inspect(prepared)
    if not inspection.ok:
        raise PermanentError("整批未通過檢查：" + "；".join(inspection.problems))
    return dict(state)

def task_commit_batch(state: dict, deps: Deps) -> dict:
    repository, operation_id = deps.need_repository(), str(state["operation_id"])
    published: tuple[str, ...] = ()
    prepared = _prepared(state, deps)
    if prepared is not None:
        result = _publisher(deps).commit(prepared, now=deps.now())
        if result.failed is not None:
            raise PermanentError(f"整批提交失敗：{result.failed}；{'；'.join(result.reasons)}")
        published = result.published
    body = repository.get_object(f"operations/{operation_id}/review-no-change.json")
    key = f"operations/{operation_id}/review-result.json"
    repository.put_object(key, json.dumps({
        "reviewed_version_ids": list(state["target_version_ids"]),
        "candidate_rule_ids": list(state["candidate_rule_ids"]),
        "prepared_version_ids": list(state["prepared_version_ids"]),
        "published_version_ids": list(published),
        "no_change_reasons": json.loads((body or b"{}").decode("utf-8")),
    }, ensure_ascii=False).encode("utf-8"), "application/json", if_none_match=False)
    deps.operations.complete(operation_id, now=deps.now())
    return {**state, "result_ref": key}

FEEDBACK_REVIEW_TASKS: tuple[TaskFn, ...] = (task_list_targets, task_evaluate_targets,
                                             task_prepare_batch, task_inspect_batch,
                                             task_commit_batch)
_TASK_BY_NAME = {task_name(task): task for task in FEEDBACK_REVIEW_TASKS}
_DEPS: Deps | None = None

def run_feedback_review(state: dict, deps: Deps) -> dict:
    """本機與測試用的整條序列；雲端由 Step Functions 逐個 Task 呼叫 handler。"""
    payload = {**state, "mode": _review_mode(state),
               "operation_id": review_operation_id(state, deps)}
    return run_sequence(FEEDBACK_REVIEW_PIPELINE, payload, FEEDBACK_REVIEW_TASKS, deps)

def feedback_review_handler(event: dict, context: object) -> dict:
    global _DEPS
    task = _TASK_BY_NAME.get(str(event.get("task")))
    if task is None:
        raise PermanentError(f"feedback-review 沒有名為 {event.get('task')!r} 的 task")
    if _DEPS is None:
        _DEPS = build_deps(load_settings(os.environ))
    return task(dict(event.get("state") or {}), _DEPS)
```

三段式的分工來自 Phase 24／25：`prepare` 只寫私有 staging、`inspect` 只讀不寫、`commit` 用一筆交易切 `published_at` 與 `current_version` 後才寫 `site/`。**本 Phase 唯一多做的事是把它們拆成三個 Task**，這樣「第二篇檢查失敗」一定發生在任何公開前綴寫入之前。`handler` 不 try／except：`TransientError` 要讓 ASL 的 Retry 抓到，`PermanentError` 要讓 Catch 抓到。

- [x] **Step 4：執行 `uv run pytest tests/unit/test_feedback_review_flow.py -q` 確認綠燈**

預期全部 `passed`。再手動把 `task_commit_batch` 改成在迴圈裡逐篇 commit 重跑，`test_second_version_failing_inspection_publishes_nothing` 必須變紅；確認後改回來。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_feedback_review_flow.py
git commit -m "feat(feedback): 整批 prepare/inspect/commit 與零部分發布"
```

### Task 3：ASL、每日排程與雲端整批驗收

- [x] **Step 1：建立失敗測試**

```python
# 續寫 tests/unit/test_feedback_review_flow.py
import pathlib

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from infra.training_kb_stack import TrainingKbStack
from training_kb.errors import TransientError
from training_kb.pipelines.asl import CATCH, RETRY, assert_safe_asl, task_state

ARN = "${PipelineTaskFunctionArn}"
NEXT = {"ListTargets": "EvaluateTargets", "EvaluateTargets": "PrepareBatch",
        "PrepareBatch": "InspectBatch", "InspectBatch": "CommitBatch",
        "CommitBatch": "Succeeded"}

def load_asl() -> dict:
    return json.loads(pathlib.Path("infra/stepfunctions/feedback-review/v1.json").read_text())

def test_every_task_state_equals_phase29_template_plus_parameters():
    asl = load_asl()
    assert len(RETRY) == 2 and RETRY[0]["ErrorEquals"] == ["TransientError"]        # D-53
    assert RETRY[1]["ErrorEquals"][0] == "Lambda.ServiceException"
    for name, next_state in NEXT.items():
        state, expected = asl["States"][name], task_state(ARN, next_state)
        expected["Parameters"] = {"pipeline": "feedback-review",
                                  "task": state["Parameters"]["task"], "state.$": "$"}
        assert state == expected, name     # Retry／Catch／TimeoutSeconds 全部來自 Phase 29

def test_asl_matches_python_tasks_and_has_no_map():
    asl = load_asl()
    assert [asl["States"][name]["Parameters"]["task"] for name in NEXT] == [
        task_name(task) for task in FEEDBACK_REVIEW_TASKS]
    assert all("Payload" not in asl["States"][name]["Parameters"] for name in NEXT)
    assert '"Map"' not in json.dumps(asl, ensure_ascii=False)      # F49：不得逐篇發布
    assert_safe_asl(asl)
    assert CATCH[0]["Next"] == "PipelineFailed"
    assert asl["States"]["PipelineFailed"]["Type"] == "Fail"
    assert asl["States"]["Succeeded"]["Type"] == "Succeed"
    assert TransientError.__name__ == "TransientError"   # ASL 用類別名比對，不帶模組路徑

def test_stack_has_review_machine_and_exactly_one_daily_schedule():
    template = Template.from_stack(TrainingKbStack(cdk.App(), "TrainingKbApp"))
    template.has_resource_properties("AWS::StepFunctions::StateMachine", {
        "StateMachineName": "training-kb-feedback-review", "StateMachineType": "STANDARD",
        "DefinitionSubstitutions": Match.object_like({"PipelineTaskFunctionArn": Match.any_value()})})
    template.resource_count_is("AWS::Scheduler::Schedule", 1)
    template.has_resource_properties("AWS::Scheduler::Schedule", {
        "ScheduleExpression": "cron(30 0 * * ? *)", "ScheduleExpressionTimezone": "UTC",
        "Target": Match.object_like({"Input": '{"mode": "formal"}'})})
    names = {function["Properties"]["FunctionName"]
             for function in template.find_resources("AWS::Lambda::Function").values()}
    assert names == {"training-kb-pipeline-task", "training-kb-webhook",
                     "training-kb-import"}                                 # 00A D-23、D-58
```

- [x] **Step 2：執行 `uv run pytest tests/unit/test_feedback_review_flow.py -q` 確認紅燈**

預期 FAIL，訊號是 `FileNotFoundError: infra/stepfunctions/feedback-review/v1.json`。若改成 `cannot import name 'RETRY'`，代表 Phase 29 還停在單一 retrier，**先回頭改 Phase 29**，不要在本 Phase 自己補一份常數。

- [x] **Step 3：建立 ASL 與 CDK 資源**

依第 6 節的節錄與對照表把五個 Task 逐字展開寫進 `infra/stepfunctions/feedback-review/v1.json`，再加上 `Succeeded`（Succeed）與 `PipelineFailed`（Fail）兩個終點；五個 Task 只有 `Parameters.task` 與 `Next` 不同，可直接用 `task_state(ARN, next_state)` 的輸出再補 `Parameters`，避免手抄出錯。

```python
# infra/training_kb_stack.py（Phase 41 建立；task_fn 與 log_group 沿用同一個 stack）
review = sfn.StateMachine(
    self, "FeedbackReview", state_machine_name="training-kb-feedback-review",
    state_machine_type=sfn.StateMachineType.STANDARD,
    definition_body=sfn.DefinitionBody.from_file("infra/stepfunctions/feedback-review/v1.json"),
    definition_substitutions={"PipelineTaskFunctionArn": task_fn.function_arn},
    logs=sfn.LogOptions(destination=log_group, level=sfn.LogLevel.ALL),
    timeout=Duration.hours(1))
task_fn.grant_invoke(review)
scheduler_role = iam.Role(self, "ReviewSchedulerRole",
                          assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"))
review.grant_start_execution(scheduler_role)        # 只授權這一條 state machine
scheduler.CfnSchedule(
    self, "DailyFeedbackReview", name="training-kb-feedback-review-daily",
    schedule_expression="cron(30 0 * * ? *)", schedule_expression_timezone="UTC",
    flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
    target=scheduler.CfnSchedule.TargetProperty(arn=review.state_machine_arn,
                                                role_arn=scheduler_role.role_arn,
                                                input=json.dumps({"mode": "formal"})))
```

`from aws_cdk import aws_scheduler as scheduler`。EventBridge Scheduler 的 cron 是**六個欄位**（分 時 日 月 週 年），`cron(30 0 * * ? *)` 就是每天 00:30；`schedule_expression_timezone="UTC"` 明寫時區，不依賴預設值；`flexible_time_window` 必填，設 `OFF` 才準點觸發。本 Phase **不新增任何 Lambda**：stack 裡的三支分別由 Phase 41（`training-kb-pipeline-task`、`training-kb-webhook`）與 Phase 42（`training-kb-import`）建立，state machine 才叫 `training-kb-feedback-review`（00A D-23、D-58）。[Phase 54](54-Phase54-重開票與呼叫規則指標.md) 之後會再加第四支 `training-kb-analytics`，屆時要把上面那個名稱集合補齊，否則這個測試會轉紅。**（現況核對 2026-09-14：這個等號斷言依賴 P42 已把 `training-kb-import` 加進 stack；P42 若尚未合併，先寫成 `names >= {"training-kb-pipeline-task", "training-kb-webhook"}` 並在報告註明差異，不要為了綠燈把 P42 的資源自己補進 stack。）**Demo 手動觸發用同一個 ARN 改傳 `{"mode": "demo"}`，**不另建第四條 pipeline**。

- [x] **Step 4：跑綠燈、存快照、部署並做雲端整批故障驗收**

```bash
uv run pytest tests/unit/test_feedback_review_flow.py -q
# 現況核對 2026-09-14：本機互動 shell 把 node 定成會拒絕的 function，cdk 一律走 `command npx aws-cdk@2`，
# 並固定 us-east-1（aws configure 預設是 ap-northeast-1）；--outputs-file 指到 scratchpad，不提交 cdk.out/。
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 deploy TrainingKbApp \
  --require-approval never --outputs-file "$SCRATCH/tkb-outputs.json"
aws scheduler get-schedule --region us-east-1 --name training-kb-feedback-review-daily \
  --query '{expr:ScheduleExpression,tz:ScheduleExpressionTimezone,input:Target.Input}'
aws stepfunctions start-execution --region us-east-1 --state-machine-arn "$TKB_REVIEW_SM_ARN" \
  --name "op-feedback-review-demo-2026-09-13" --input '{"mode":"formal"}'
aws stepfunctions get-execution-history --region us-east-1 --execution-arn "$ARN" --max-results 200 \
  --query "events[?type=='TaskStateEntered'].stateEnteredEventDetails.name" --output text
# O5 BLOCKED：有弱教學或 candidate group 時，上面這次執行會在 EvaluateTargets 走 Catch → PipelineFailed。
# 把 describe-execution 與 get-execution-history 的 errorType／cause 原文存下來當 BLOCKED 證據。
TKB_FAULT=publish_before_transact TKB_RUN_AWS_INTEGRATION=1 \
  uv run pytest tests/integration/test_feedback_review_state_machine.py -m aws -q
```

部署前先照 [Phase 41](41-Phase41-Ticket-Analysis雲端流程驗收.md) Task 3 的同一段腳本，用 `save_asl_snapshot(repository, "feedback-review", 1, ...)` 把**與部署完全相同的 bytes** 存成私有快照 `stepfunctions/feedback-review/v1.json`（設計 §9.3）；同一版重跑丟 `ObjectAlreadyExists` 是預期行為，改定義就升成 `v2.json`。**（現況核對 2026-09-14：要讓「相同 bytes」成立，本地 ASL 檔請直接用 `canonical_json(definition)` 的輸出落檔（`indent=2, sort_keys=True`），路徑用 `ASL_LOCAL_PATH.format(pipeline="feedback-review", number=1)`、快照 key 用 `ASL_SNAPSHOT_KEY`，測試不要手打字串；`save_asl_snapshot` 撞鍵時會先比 bytes，不同才丟 `PermanentError`。）** `cdk` 是 Node.js 套件，指令**不加** `uv run`，而且本機要寫成 `command npx aws-cdk@2 <子命令>` 並帶 `AWS_REGION=us-east-1`（00A §3.1、D-22 ＋ COMMON.md §1）；stack id 用 `TrainingKbApp`（D-43）。整合測試準備兩篇都會產生 `RefinePlan` 的資料，分別在 `TKB_FAULT=publish_before_transact` 與 `publish_after_transact_before_site`（Phase 59 的故障切點）各跑一次，每次都必須是 execution `FAILED`，而且兩篇的 `current_version`、`published_at` 與公開頁**同時**是舊值——出現「A 新、B 舊」就停止、保留 FAIL，不改 F49、不加 CloudFront 或公開讀取 API。移除故障後以**同一個** execution name 重送，預期沿用既有 staging 與版號，兩篇一起變成新狀態。CDK 環境未建立時先完成 Phase 01／09，不要把「目前跑不了」寫成通過，也不要把 `cdk synth` 成功當成部署成功。

- [x] **Step 5：保存證據後提交**

```bash
git add infra/stepfunctions/feedback-review/v1.json infra/training_kb_stack.py tests/unit/test_feedback_review_flow.py tests/integration/test_feedback_review_state_machine.py
git commit -m "feat(infra): feedback-review ASL 與每日排程"
```

## 8. 驗收矩陣

（現況核對 2026-09-14：原本一張表把「單元／moto 可實證」與「真實 AWS 需要 Bedrock」混在一起。依 COMMON.md §2 拆成兩段——**可實證路徑**必須跑出綠燈或明確的失敗證據，**BLOCKED／原樣記錄路徑**只保留觀察與錯誤原文，不得宣稱通過。）

### 8.1 可實證路徑（單元測試、moto、真實 AWS 中不需要 Bedrock 的部分）

| 路徑 | 刺激 | 預期資料結果與證據 | 怎麼實證 |
|---|---|---|---|
| Happy | 三篇：只有 candidate／candidate＋REFINE／兩者皆無 | 五個 Task 依序跑完；`review-result.json` 五個欄位齊全。 | 單元（假 Writer）＋`run_feedback_review` |
| Happy | 兩篇都產生 `RefinePlan` | 兩篇在同一次 `commit` 一起切 `published_at`；`site/` 同時出現兩個新頁。 | 單元＋moto（協定 A） |
| Failure | 第二篇 `InspectBatch` 不通過 | `PermanentError` → `PipelineFailed`；兩篇 `current_version` 皆舊值；`site/` 零新物件。 | 單元＋moto |
| Failure | 任一 Task `TransientError` 重試耗盡 | 三次 `TaskFailed`（`error` 為 `TransientError`）後 `PipelineFailed`；零新發布。 | 真實 AWS（不需模型的 Task，例如注入 `TransientError` 的 `ListTargets`）；`get-execution-history` |
| Boundary | 沒有任何 active 已發布版本 | `SUCCEEDED`；`target_version_ids == []`、**零次模型呼叫**、`publish_request_ref` 為 `null`。 | 單元＋**真實 AWS 可整條跑完**（這是 O5 BLOCKED 之下唯一能跑到 `Succeeded` 的雲端路徑） |
| Boundary | `mode` 是 `"staging"` | `PermanentError` 直接進 Catch，不重試、不讀資料。 | 單元＋真實 AWS（`{"mode":"staging"}`） |
| Schedule | Scheduler 設定 | 一個 `AWS::Scheduler::Schedule`、`cron(30 0 * * ? *)`、`UTC`、input `{"mode": "formal"}`。 | `Template.from_stack` ＋ `aws scheduler get-schedule --region us-east-1` |
| ASL | 逐 state 比對與靜態檢查 | 每個 Task 等於 `task_state(ARN, next)` 加 `Parameters`；`assert_safe_asl` 通過；沒有 `Map`；快照 bytes 與部署定義相同。 | 單元（讀本地 ASL 檔）＋`save_asl_snapshot` |
| Idempotency | 同日重送同一個 execution name | `accept` 回 `duplicate`；沿用既有 staging 與版號，不重打模型。 | 單元＋真實 DynamoDB（**O2 已 PASS，可以依賴**） |
| Boundary | 同一天兩篇都是弱教學 | 兩篇各自 `accept` 一筆 `refine_operation_id` 子 operation，版號各自獨立，不共用當日 review operation（D-59）。 | 單元＋真實 DynamoDB |

### 8.2 BLOCKED／原樣記錄路徑（不得宣稱通過）

| 路徑 | 刺激 | 現況會觀察到什麼 | 怎麼處理 |
|---|---|---|---|
| **O5 BLOCKED** | 真實 AWS 上有弱教學或 candidate group 的任何一次執行 | `EvaluateTargets` 在 `diagnose_weak`／`refine_steps`／`propose_rule` 丟 `PermanentError`（Bedrock 回 `ValidationException: Operation not allowed`）→ `Catch` → `PipelineFailed`。 | **保留 FAIL**，存 execution ARN、`describe-execution`、`get-execution-history` 的 `errorType`／`cause` 原文與 CloudWatch log 片段，標 **BLOCKED**；不填猜測的 `TKB_GENERATION_MODEL_ID`、不 mock 掉雲端 Writer。 |
| **O3 FAIL（協定 A）** | 多篇整批發布的兩個故障切點（`TKB_FAULT=publish_before_transact`、`publish_after_transact_before_site`） | 依 P12／P24／P25 的觀察，某些切點會出現 partial。 | 切點驗證**在 moto 上做**（協定 A，與 P24／P25 同一套）；真實 AWS 上跑到發布切點就**把觀察到的結果原樣記錄**（含「A 新 B 舊」這種情形），**不改 F49、不加 CloudFront 或公開讀取 API、不宣稱 O3 PASS**，決策出口留給維護者（D-80）。 |
| **O3 FAIL** | 「兩篇一起公開」的最終人工驗收 | Bedrock 不可用，實務上到不了這一步。 | 只能宣稱「未發布版本已建立」「整批語意在 moto 上成立」；`CommitBatch` 依 Phase 24／25 停止條件回失敗是**預期**結果。 |

人工驗收（不能只看 PASS）：在 Step Functions console 各打開一個成功（`target_version_ids == []` 那條）與一個故障（O5 BLOCKED 那條）執行逐節點核對；用 `aws dynamodb get-item --consistent-read --region us-east-1` 核對教學的 `current_version` 沒有被動過；最後用 `aws scheduler get-schedule --region us-east-1` 看實際排程字串與 input。所有 AWS CLI 一律帶 `--region us-east-1`（`aws configure` 預設是 ap-northeast-1）。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| A 已公開、B 失敗 | 在 Map 或迴圈內逐篇 publish | 停止流程；全部 prepare／inspect 之後才由 `Publisher.commit` 一次整批提交（F49）。 |
| candidate 因平均分高被跳過 | 兩條分支共用同一個 `if` | 分開跑：candidate 只看同版同類 >= 5，與 `is_weak` 無關（設計 F26）。 |
| Retry 沒命中，Task 一失敗就 Catch | `ErrorEquals` 寫成 `TrainingKB.TransientError`，或只有一個 retrier | 改 import Phase 29 的 `RETRY`／`CATCH`（兩個 retrier，00A D-53）；錯誤名只用類別名。 |
| Catch 最後走到 `Succeeded` | 把錯誤包成回傳值 | handler 不 try／except；`Catch` 一律指向 `PipelineFailed`。 |
| 重送又多打一次模型、又配一個新版號 | 沒有沿用同 operation 的既有產物 | `accept` 回 `duplicate` 時沿用既有 operation，`prepare` 對同 operation 回同一批 staging（設計 §14.2）。 |
| execution history 看得到回饋留言 | 把 `Feedback` 或全文放進 state | state 只留 00A 第 7 節那八個欄位；細節寫私有 `operations/` 物件。 |
| O3 仍 FAIL 卻宣稱公開發布完成 | 把 spike 結論當建議 | 停在 FAIL，保留可追溯證據與決策出口，不改產品契約。 |

## 10. 來源與 Rule 對照

- [定期檢視回饋.feature](../../spec/features/定期檢視回饋.feature)（縮寫 `REV`）
  - Rule 1：「Periodic Feedback Review 每日執行」（**primary**，00B 第 3.2 節裁決）→ Task 3 的 `test_stack_has_review_machine_and_exactly_one_daily_schedule` 直接斷言 `cron(30 0 * * ? *)`、`UTC` 與固定 input，雲端再用 `aws scheduler get-schedule` 核對。
  - Rule 9：「Feedback Review 是唯一提出 Authoring Rule 的 pipeline」→ 相關（primary 在 [Phase 47](47-Phase47-Candidate規則提出與溯源.md)）；本 Phase 補流程層證據：只有 `FEEDBACK_REVIEW_TASKS` 會組進 `propose_candidate`，`TICKET_ANALYSIS_TASKS` 與 `RELEASE_UPDATE_TASKS` 都不含它。
  - Rule 2–8 → 相關（primary 在 [Phase 44](44-Phase44-弱教學門檻與目標選取.md)、[45](45-Phase45-回饋診斷與命中步驟.md)、[46](46-Phase46-REFINE精準改寫與證據去重.md)）；本 Phase 只驗證它們在同一條固定流程裡沒有互相吞掉。
- [提出教學規則.feature](../../spec/features/提出教學規則.feature)（縮寫 `PRP`）Rule 1–5 → 相關（primary 在 Phase 47）；`EvaluateTargets` 只負責在每篇目標上呼叫一次 `candidate_groups` 與 `propose_candidate`。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature)（縮寫 `RUN`）Rule 2「教學 pipeline 依 Step Functions 預定義節點執行」、Rule 6「每個 Step Functions Task 設定 Retry」、Rule 7「每個 Step Functions Task 設定 Catch」、Rule 10「Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json`」→ 四條都**相關**（primary 在 [Phase 29](29-Phase29-共用Pipeline執行器與ASL失敗語意.md)，00B 第 3.2 節裁決）；本 Phase 在 Task 3 於 `feedback-review` 這條流程上再驗一次（逐 state 比對＋`assert_safe_asl`，快照由 `save_asl_snapshot` 寫出）。
- [發布教學版本.feature](../../spec/features/發布教學版本.feature)（縮寫 `PUB`）Rule 4、5 → 相關（primary 在 [Phase 24](24-Phase24-單篇教學發布提交.md)）；本 Phase 只在流程層觀察切點，Task 3 的故障注入是 O3 的追驗證據。
- 設計 §7.5：兩個判斷分開做、每日只看 current 已發布版本、失敗時已保存的合法 candidate 不因此變成 active。設計 §14.2、§14.3：只讓一層管理重試、`Retry` 1 秒與 2 秒最多兩次、Task 逾時 120 秒、每日 Review 固定 UTC 00:30、state 只傳 ID 與 S3 key。設計決策 F49、F26。
- [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 3.4、3.5、3.7、6.9、7 節；裁決 D-07、D-14、D-15／D-53、D-21、D-22、D-23、D-24、D-25、D-36、D-41、D-49。
- 官方文件：[EventBridge Scheduler 排程類型與 cron 語法](https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html)、[CDK `aws_scheduler.CfnSchedule`](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_scheduler/CfnSchedule.html)、[Step Functions 錯誤處理](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)。

## 11. 完成清單

- [x] 五個 Task 的名稱、順序與 ASL state 名稱逐字對得上 00A 第 7 節。
- [x] Candidate 與 REFINE 兩條分支可獨立觸發，任一條失敗不改變另一條的判斷結果。
- [x] 每個 Task 的 `Retry`／`Catch` 直接來自 Phase 29 的 `RETRY`／`CATCH`，沒有 `TrainingKB.` 前綴、沒有第三份常數。
- [x] 所有 `Catch` 走到 `PipelineFailed`；ASL 沒有 `Map`，不存在逐篇發布路徑。
- [x] 多篇先全部 prepare／inspect，最後由 `Publisher.commit` 一次整批提交；失敗時零篇公開。
- [x] 同一天、同 operation 重送不重複提案、不重打模型、不配新版號。
- [x] 每個弱教學 target 都先 `accept` 一筆 `refine_operation_id` 子 operation 再交給 `prepare_refine`，兩篇不共用版號（D-59）；當日 review operation 的 canonical id 是 `f"{project_id}-{UTC 日期}"`（D-61）。
- [x] 每日 UTC 00:30 排程與手動入口共用同一個 state machine，input 固定 `{"mode": ...}`。
- [x] ASL 快照已寫到 `stepfunctions/feedback-review/v1.json`，bytes 與部署中的定義相同。
- [x] `REV` Rule 1 有直接 assertion；其餘引用的 Rule 都標明 primary 在哪一份。
- [x] 尚未部署或未跑 `@pytest.mark.aws` 測試前，文件與報告一律寫「預計／待驗證」；**O3 FAIL** 不得宣稱公開發布完成、不得放寬 F49；**O5 BLOCKED** 造成的 `Catch → PipelineFailed` 已保留 `errorType`／`cause` 原文當證據，沒有寫成 bug 或通過；**O2 PASS** 才可依賴的宣稱（重送去重）已註明來源。
- [x] 前置 P41（`infra/training_kb_stack.py`、`task_name`／`build_deps`／`pipeline_task_handler`、`training-kb-pipeline-task` 與相依 layer）確認已合併後才開工；Lambda 打包沿用 P41 那一套（R2）。
- [x] `pipelines/feedback.py` 與 `infra/training_kb_stack.py` 只用 Edit 追加 `# ---- Phase 48 ----` 自己的區段，沒有動 P41／P42／P44–P47 的程式。

---

## 12. 實作結果（2026-09-14）

已完成並部署。state machine `arn:aws:states:us-east-1:123456789012:stateMachine:training-kb-feedback-review`、
排程 `training-kb-feedback-review-daily`（`cron(30 0 * * ? *)`／`UTC`／`{"mode": "formal"}`）。
完整證據與逐 Task 紅綠原文見 [`docs/plan/report/phases/2026-09-14-Phase48-REP.md`](../report/phases/2026-09-14-Phase48-REP.md)。

### 本計畫選擇（2026-09-14）

1. **`EvaluateTargets` 的核定類別用 `DEFAULT_FEEDBACK_CATEGORIES`**：§7 的片段寫
   `approved_categories(repository)`，但 Phase 43 尚未合併（`ingress.py` 只有
   `DEFAULT_FEEDBACK_CATEGORIES`，第 584 列註明 P43 會補）。改用同一個常數，與
   `select_weak_targets` 目前用的是同一份表，兩條分支不會分岔；P43 合併後兩處一起改。
2. **Task 1 的紅燈訊號是 `cannot import name 'FEEDBACK_REVIEW_PIPELINE'`**：§7 寫
   `FEEDBACK_REVIEW_TASKS`，但那個名稱要等五個 Task 都存在才生得出來（Task 2）。Task 1 的
   測試只 import 它真的交付的名稱，Task 2 的紅燈才是 `cannot import name
   'FEEDBACK_REVIEW_TASKS'`（與 brief §4 的第 2 條一致）。
3. **重送那條測試改斷言三件事**：§7 的 `test_resend_reuses_prepared_artifacts` 斷言兩次的
   `publish_request_ref` 相同。第一次已經把 b@v2／c@v2 發布出去、`current_version` 因此前進，
   第二次的目標變成沒有回饋的 b@v2／c@v2，`prepare_refine` 也會在 `_guard` 判定
   `no_new_evidence`（F23）而回 `None`——第二次本來就**不該**再有 publish request。改成直接
   斷言 §11 真正要守的「不重複提案、不重打模型、不配新版號」。
4. **「第二篇檢查失敗」的切點用基底位移**：`InspectBatch` 的三類問題裡，只有「基底已位移」
   是 `prepare` 會放過、只有 `inspect` 擋得住的，所以測試證的是「檢查失敗時零篇公開」，
   不是「產物根本沒做出來」。動手腳的時機在 `EvaluateTargets` 與 `PrepareBatch` 之間
   （雲端逐個 Task 呼叫，那正是真的會出現的空隙）。
5. **Lambda 名稱集合改成包含關係**：`{"training-kb-pipeline-task", "training-kb-webhook",
   "training-kb-analytics"} <= names`。`training-kb-import`（P42）與 P52 的資源同波次落地，
   等號會讓別人一提交就把這個檔轉紅（controller 2026-09-14 裁決）。
6. **雲端執行名稱帶時間戳**：`p48-<情境>-<epoch>` 而不是裸 `operation_id`，同一天重跑整合
   測試才不會撞 `ExecutionAlreadyExists`。正式路徑的名稱仍由 `ingress.execution_name` 決定。
7. **單元測試器材用 moto ＋真 `Repository`**：比照 `tests/unit/test_feedback_refine.py`（P46）
   與 `tests/unit/test_publisher_single.py`（P24）。整條流程會走到 `create_version`／
   `verify_version_complete`／`Publisher.prepare|inspect|commit`／`transact_write`，
   手寫記憶體替身只會複製一份會漂移的 `Repository` 副本。

### 未做／做不到（原因）

- **§7 Task 3 Step 4 的 `TKB_FAULT=publish_before_transact`／`publish_after_transact_before_site`
  兩次整合測試沒有做。** `faults.maybe_fail` 目前**沒有**被插進 `publishing.py`（`grep` 全案
  只有 `faults.py` 自己定義它）——五個切點的插入點是 **Phase 59** 的 Task，本 Phase 不預先
  插入別人的區段。同一組「多篇整批的可觀察切點」在 moto 上已經有 P25 的
  `tests/integration/test_batch_publish_cutpoints.py`（協定 A），本 Phase 另在
  `tests/unit/test_feedback_review_flow.py` 加了流程層的
  `test_second_version_failing_inspection_publishes_nothing`。**O3 維持 FAIL，不放寬 F49。**
- **真實 AWS 上沒有任何一次執行走到發布切點。** O5 BLOCKED 先擋在 `EvaluateTargets`
  （`PermanentError: O5 尚未通過：generation_model_id 還沒有實測值`），所以「兩篇一起公開」
  的雲端驗收到不了，**照實記錄、不宣稱通過**（§8.2 第 3 列）。
- **每日 00:30 的實際觸發沒有等。** 排程用 `aws scheduler get-schedule` 存證
  （`ENABLED`／`cron(30 0 * * ? *)`／`UTC`／`FlexibleTimeWindow OFF`／目標 ARN 與 input），
  沒有等到隔天 00:30 看真的被觸發。
