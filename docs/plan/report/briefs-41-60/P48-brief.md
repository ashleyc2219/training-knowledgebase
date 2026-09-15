# P48 brief — Feedback Review 排程流程

## 1. 單一交付物與停止點
- **交付物**：`pipelines/feedback.py` 的五個 task 函式 ＋ `FEEDBACK_REVIEW_PIPELINE`／`REVIEW_MODES`／`review_operation_id`／`FEEDBACK_REVIEW_TASKS`／`run_feedback_review`／`feedback_review_handler`，`infra/stepfunctions/feedback-review/v1.json`，以及 `infra/training_kb_stack.py` 追加的 `training-kb-feedback-review` Standard state machine ＋ EventBridge Scheduler `cron(30 0 * * ? *)`。
- **停止點**：`CommitBatch` 寫出 `review-result.json` 並 `operations.complete(...)`。**不新增第四條 pipeline、不改 P44–P47 的判斷邏輯、不寫 `RULE.status`、不加 CloudFront／公開讀取 API、不做部分發布。**

## 2. 已存在、直接重用
- `pipelines/asl.py`：`RETRY`（:33，**兩條 retrier 的 tuple**，D-53）、`CATCH`（:42）、`FAIL_STATE_NAME="PipelineFailed"`（:25）、`TASK_TIMEOUT_SECONDS=120`（:28）、`task_state(arn, next)`（:66，**不含 `Parameters`**，自己補）、`assert_safe_asl`（:82）、`ASL_LOCAL_PATH`（:138）、`ASL_SNAPSHOT_KEY`（:141）、`canonical_json`（:145，`indent=2, sort_keys=True`）、`save_asl_snapshot`（:150）。
- `pipelines/common.py`：`Deps`（:36 ＋ `need_repository`／`need_writer`／`need_settings`）、`run_sequence(pipeline, payload, tasks, deps)`（:72，**第一參數是 pipeline 名**，D-07；檢查 `payload["operation_id"]` 非空、失敗先 `operations.fail` 再原樣 raise）、`PIPELINE_NAMES`（:31，含 `feedback-review`）。
- `publishing.py`：`PublishRequest(version_ids, operation_id)`（:108）、`PreparedPublish(request, version_ids, staged_keys, prepared_at)`（:117）、`PublishInspection(ok, problems)`（:131）、`PublishResult(published, failed, reasons)`（:139）、`MAX_BATCH_VERSIONS=50`（:90）、`assert_batch_publishable`（:243）、`Publisher(repository, renderer, operations)` ＋ `prepare(req,*,now)`／`inspect(prepared)`／`commit(prepared,*,now)`（:394 起）、`promote_site_objects`（:372）、`pending-promote.json`（:95）。
- `site.py:99` `SiteRenderer()`（無參數建構是既定用法）。
- `operations.py`：`AcceptOperation(operation_id, kind, canonical_id, project_id, now)`（:67）、`accept`／`complete(op,*,now)`；`OperationKind`（:47）含 `"feedback-review"` 與 `"feedback"`。
- `ingress.py:243` `operation_id_for`、`:252` `execution_name`。
- `repository.py`：`put_object(key, body, content_type, *, if_none_match)`（:399，**必填 keyword**）、`get_object`（:422）、`object_exists`（:436）、`scan_entity`（:539）、`get_version`／`get_tutorial`、`item_to_model`（:152）。
- P44–P47 的 `select_weak_targets`／`diagnose_weak`／`prepare_refine`／`candidate_groups`／`candidate_rule_id`／`propose_candidate`／`evidence_fingerprint`／`refine_operation_id`（**同模組，不用 import**）。
- CDK 已就緒（本機 `aws-cdk-lib 2.269.0`）：`aws_scheduler.CfnSchedule` ＋ `FlexibleTimeWindowProperty`／`TargetProperty`、`aws_stepfunctions.DefinitionBody.from_file`、`StateMachineType.STANDARD`。

## 3. 要新增／修改的東西
**波次 W3（P44–P47 全部落地、且 P41 已合併之後）。**

`src/training_kb/pipelines/feedback.py`（區段 `# ---- Phase 48 ----`）
- **擁有**：`FEEDBACK_REVIEW_PIPELINE: PipelineName = "feedback-review"`、`REVIEW_MODES = ("formal","demo")`、`_review_mode`（私有，不列公開介面）、`_review_targets`、`review_operation_id(state, deps) -> str`、`task_list_targets`／`task_evaluate_targets`／`task_prepare_batch`／`task_inspect_batch`／`task_commit_batch`、`_publisher`、`_prepared`、`FEEDBACK_REVIEW_TASKS`、`_TASK_BY_NAME`、`run_feedback_review`、`feedback_review_handler`。
- **不得碰**：P44／P45／P46／P47 的所有名稱（`is_weak`、`select_weak_targets`、`diagnose_weak`、`prepare_refine`、`evidence_fingerprint`、`refine_operation_id`、`candidate_*`、`propose_candidate`…）——只呼叫、不修改、不改名、不重排。
- 新檔 `infra/stepfunctions/feedback-review/v1.json`（本 Phase 獨有）。
- `infra/training_kb_stack.py`（**P41 建立**）：只追加 `FeedbackReview` state machine、`ReviewSchedulerRole`、`DailyFeedbackReview` 三個 construct ＋ `task_fn.grant_invoke(review)`；不動 P41／P42 既有資源。

00A §6.9／§7 契約：五個 Task 一條直線 `ListTargets → EvaluateTargets → PrepareBatch → InspectBatch → CommitBatch → Succeeded`，**沒有 Choice、沒有 Map**；state 只有八個欄位 `operation_id, project_id, mode, target_version_ids, candidate_rule_ids, prepared_version_ids, publish_request_ref, result_ref`；input 只有 `{"mode": "formal"|"demo"}`（`project_id` 可選，**沒有 `scheduled_for`**，D-61）；`operation_id` 由 `ListTargets` 以 `operation_id_for("feedback-review", f"{project_id}-{UTC 日期}")` 產生（**連字號不用 `#`**）。
新測試：`tests/unit/test_feedback_review_flow.py`、`tests/integration/test_feedback_review_state_machine.py`（`@pytest.mark.aws`）。

## 4. Task 順序與紅燈訊號
1. **Task 1（兩條獨立分支與 state 契約）** — `uv run pytest tests/unit/test_feedback_review_flow.py -q` → `cannot import name 'FEEDBACK_REVIEW_TASKS' from 'training_kb.pipelines.feedback'`。
2. **Task 2（整批 prepare／inspect／commit 與 F49）** — 同指令 → `cannot import name 'run_feedback_review'`。綠燈後**手動**把 `task_commit_batch` 改成逐篇 commit，確認 `test_second_version_failing_inspection_publishes_nothing` 轉紅，再改回來。
3. **Task 3（ASL／排程／雲端）** — 同指令 → `FileNotFoundError: infra/stepfunctions/feedback-review/v1.json`。若變成 `cannot import name 'RETRY'`，代表 P29 還停在單一 retrier，**回頭改 P29**，不要在本 Phase 補第三份常數。
收尾：`uv run ruff check src tests infra`、`ruff format --check`、`uv run mypy`、`uv run pytest tests -q -W error`。

## 5. 00B primary Rule 與測試檔
| Rule | 內容 | 測試 |
|---|---|---|
| `REV` 1（**primary**，00B §3.2 裁決） | Periodic Feedback Review 每日執行 | `tests/unit/test_feedback_review_flow.py::test_stack_has_review_machine_and_exactly_one_daily_schedule`（`cron(30 0 * * ? *)`／`UTC`／`{"mode": "formal"}`）＋ `aws scheduler get-schedule` |
相關（**不要搶 primary**）：`REV` 2–8（P44/45/46）、`REV` 9（P47）、`PRP` 1–5（P47）、`RUN` 2／6／7／10（P29）、`PUB` 4／5（P24）。

## 6. 風險與陷阱
- **P41 還沒做**：`infra/training_kb_stack.py`、`infra/stepfunctions/`、`task_name`／`build_deps`／`pipeline_task_handler`（00A §6.9 說在 `pipelines/common.py`）、`training-kb-pipeline-task` Lambda **目前都不存在**。開工前先確認 P41 已合併。
- **R2 打包**：`Code.from_asset("src")` 不含 `pydantic`／`jsonschema`（pydantic-core 是編譯套件）。**沿用 P41 的 layer／bundling，不自己再做一套。**
- **CDK 指令**：本機 shell 把 `node` 定成會拒絕的 function → 一律 `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 <子命令>`；`--outputs-file` 指到 scratchpad；**不提交 `cdk.out/`**；stack id `TrainingKbApp`（D-43）。`aws` CLI 一律帶 `--region us-east-1`。
- **ASL bytes 一致**：本地檔用 `canonical_json(definition)` 落檔，路徑用 `ASL_LOCAL_PATH.format(pipeline="feedback-review", number=1)`，快照 key 用 `ASL_SNAPSHOT_KEY`；`save_asl_snapshot` 撞鍵先比 bytes，不同才 `PermanentError`。
- **Lambda 名稱集合斷言**依賴 P42 已加 `training-kb-import`（D-58）；P42 未合併就改成 `names >= {...}` 並在報告寫明，**別自己把 P42 的資源補進 stack**。
- `assert_safe_asl` 要求：前兩條 retrier 逐字等於 `RETRY`、沒有 retrier 涵蓋 `States.ALL`、**恰好一條** `States.ALL` 的 Catch 指向同層 `Fail`。多寫一條 Catch 會被擋。
- `ErrorEquals` 只寫**類別名**（`TransientError`），不得加模組前綴（D-15）。handler **不 try／except**。
- `run_sequence` 自己會 `operations.fail` 再原樣 raise；`run_feedback_review` 要先把 `operation_id` 補進 payload 才交給它（雲端路徑不經 `run_sequence`）。
- **D-59 子 operation**：每個弱教學 target 先 `accept` 一筆 `refine_operation_id(...)`（`op-feedback-<64 位指紋>`），再當成 `diagnose_weak`／`prepare_refine` 的 `operation_id`；兩篇共用當日 review operation 會搶同一個版號。
- keyword 不可互改：P44 與 Publisher 用 `repository=`，P45/46/47 用 `repo=`。
- **gate**：**O2 PASS**（重送去重可依賴）；**O3 FAIL**——整批切點照協定 A 在 moto 驗證，真實 AWS 上跑到發布切點**原樣記錄**，不放寬 F49、不宣稱 PASS（D-80）；**O5 BLOCKED**——真實 AWS 上 `diagnose_weak`／`refine_steps`／`propose_rule` 會 `PermanentError → Catch → PipelineFailed`，那是 **BLOCKED 證據不是 bug**；唯一能在雲端跑到 `Succeeded` 的是「沒有任何 active 已發布版本」那條。§8 驗收矩陣已改寫成 8.1 可實證／8.2 BLOCKED 兩段。

## 7. 需要裁決的點 → 建議裁決
- 雲端跑不到 happy path（O5）怎麼交差 → **跑三條**：(1) 空資料 → `SUCCEEDED` 全五個 `TaskStateEntered`；(2) `{"mode":"staging"}` → `PipelineFailed`（不需模型）；(3) 有弱教學 → `PipelineFailed` 並存 `errorType`／`cause` 當 BLOCKED 證據。
- 故障切點整合測試 → **在 moto 跑兩個 `TKB_FAULT` 切點（協定 A）**；真實 AWS 那兩次因 O5 到不了發布切點，照實記錄「未達切點」。
- P42 未合併時的 Lambda 名稱斷言 → **改 `>=` 並註明**。
- `review-no-change.json` 是否進 state → **不進**（00A §7 只有八個欄位）；寫 `operations/<op>/review-no-change.json`，`CommitBatch` 併進 `review-result.json`。

## 8. 對 AWS 的實際操作（region 一律 us-east-1，帳號 123456789012）
```bash
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 deploy TrainingKbApp \
  --require-approval never --outputs-file "$SCRATCH/tkb-outputs.json"
aws scheduler get-schedule --region us-east-1 --name training-kb-feedback-review-daily \
  --query '{expr:ScheduleExpression,tz:ScheduleExpressionTimezone,input:Target.Input}'
aws stepfunctions start-execution --region us-east-1 --state-machine-arn "$TKB_REVIEW_SM_ARN" \
  --name "op-feedback-review-demo-2026-09-13" --input '{"mode":"formal"}'
aws stepfunctions describe-execution   --region us-east-1 --execution-arn "$ARN"
aws stepfunctions get-execution-history --region us-east-1 --execution-arn "$ARN" --max-results 200
```
資源名：state machine `training-kb-feedback-review`、schedule `training-kb-feedback-review-daily`、共用 Lambda `training-kb-pipeline-task`、table `training_kb`、bucket `training-kb-content-example`。
證據存 `docs/plan/report/phases/2026-09-14-Phase48-REP.md` §4／§7：execution ARN、`describe-execution` 的 `status`／`error`／`cause`、`get-execution-history` 的 `TaskStateEntered` 清單與失敗事件原文、`get-schedule` 輸出、ASL 快照 key。ASL 定義本身可入 repo；**outputs 檔、憑證、bucket 內容一律不入 repo**（R11）。
