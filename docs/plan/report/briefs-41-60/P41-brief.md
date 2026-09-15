# P41 brief — Ticket Analysis 雲端流程驗收

> 讀本 brief 前先讀 `.superpowers/sdd/phase0914-2/COMMON.md`。文件已於 2026-09-14 依現況更新（commit `e861b39`），
> 文件最前面的「現況核對」區塊是權威版本，本 brief 只是不重做考古的捷徑。

## 1. 單一交付物與停止點
- **交付物：** 把 P38–P40 的判斷包成七個 task ＋ `ticket-analysis` 的 ASL ＋ `infra/training_kb_stack.py`，**真的部署到 us-east-1 並留下 execution 證據**。
- **停止點：** `taskFailedEventDetails.error` 不是逐字 `TransientError` 時停止（`ErrorEquals` 沒命中＝重試是假的），回頭與 P29 一起改，不改測試遷就。

## 2. 已存在、直接重用
- `pipelines/common.py`：`PipelineName`／`PIPELINE_NAMES`／`JSONValue`／`TaskFn`／`Deps`（後三欄預設 `None`＋`need_*`）／`run_sequence`。**`task_name`／`build_deps`／`pipeline_task_handler` 還沒有，D-24 指定由你做。**
- `pipelines/asl.py`：`RETRY`（**兩條 retrier 的 tuple**，D-53 已落地）／`CATCH`／`task_state`／`assert_safe_asl`／`canonical_json`／`save_asl_snapshot`／`ASL_LOCAL_PATH`／`ASL_SNAPSHOT_KEY`／`FAIL_STATE_NAME`／`TASK_TIMEOUT_SECONDS=120`。**一律 import，不抄字面值。**
- `pipelines/ticket.py`：P38–P40 業務函式全就位（`ensure_embedding`、`assign_cluster`、`new_cluster_id`、`is_recurring`、`recurring_window`、`known_features`、`name_gap`、`TicketGap`、`decide_ticket_action`、`record_decision`、`tutorial_slug`、`create_tutorial_identity`、`create_first_version`）。
- `ingress.py:_build_wiring(settings)`（`src/training_kb/ingress.py:318`）：**唯一一份真連 AWS 的相依組裝**，`build_deps` 照抄它的 boto3 → `Repository(table, bucket)` → `OperationCoordinator(repository)`，加 `BedrockWriter(build_bedrock_client(region), CallTrace(), generation_model_id=…, embedding_model_id=…)`，不要 `PipelineStarter`。
- `handlers/github_webhook.py`：`handler`、`load_secret`、`SECRET_ENV="TKB_GITHUB_WEBHOOK_SECRET"`、`WEBHOOK_DEADLINE_SECONDS=8.0`。
- `infra/training_kb_data_stack.py`（P09，**已部署**）：`self.table`／`self.bucket`／`self.data_role`。
- 測試 fixture：`tests/unit/pipelines/conftest.py`（`fake_operations`／`fake_clock`／`embedding_writer`／`fake_repo`／`settings`／`ticket_without_embedding`／`clustered`／`unclustered`）；`tests/unit/pipelines/test_ticket_decide.py` 的 `FakeRepository`／`FakeOperations`／`FakeWriter`／`GAP`／`dt`（prepend import mode 跨檔共用，P40 已示範）。`tests/unit/infra/` **不存在**，你建。

## 3. 要新增／修改的東西
| 檔 | 動作 | 名稱／簽名（00A） | 同波次併行風險 |
|---|---|---|---|
| `src/training_kb/pipelines/common.py` | **Edit** | `task_name(task) -> str`；`build_deps(settings) -> Deps`；`pipeline_task_handler(event, context) -> dict`（D-24） | **高**：P48／P52 也會碰 |
| `src/training_kb/pipelines/ticket.py` | **Edit** | 七個 `task_*`；`TICKET_ANALYSIS_TASKS: tuple[TaskFn, ...]`；`run_ticket_analysis`；`ticket_analysis_handler` | 中 |
| `src/training_kb/faults.py` | **建立第一片** | `FAULT_POINTS`（P59 的五個名稱，**一個不多**）、`InjectedFault(TransientError)`、`active_fault`、`maybe_fail` | P59 擴充；見 §7 |
| `infra/stepfunctions/ticket-analysis/v1.json` | 建立 | 七 Task ＋ 2 Choice ＋ 4 Succeed ＋ `PipelineFailed` | 無 |
| `infra/training_kb_stack.py` | 建立 | `TrainingKbStack(scope, id, *, data: TrainingKbDataStack, **kwargs)` | **高**：P42／P48／P52／P54 都會改 |
| `infra/app.py` | Edit | 加 `TrainingKbStack(app, "TrainingKbApp", data=data, env=env)`（D-43） | 低 |
| `infra/scripts/build_lambda_layer.py` | 建立 | uv `--target` 產 `build/lambda-layer/python` | 無 |
| `tests/unit/pipelines/test_ticket_flow.py`／`tests/unit/infra/test_ticket_asl.py`／`tests/integration/test_ticket_state_machine.py` | 建立 | 檔名逐字照 00A §3.3 | 無 |

## 4. Task 順序與紅燈訊號
1. `uv run pytest tests/unit/pipelines/test_ticket_flow.py -q` → `cannot import name 'TICKET_ANALYSIS_TASKS'`。
2. `uv run pytest tests/unit/infra/test_ticket_asl.py -q` → `FileNotFoundError: infra/stepfunctions/ticket-analysis/v1.json`（若變成 `cannot import name 'RETRY'`，是 P29 沒落地 D-53 —— 實際上已落地，不會發生）。
3. `uv run pytest tests/unit/infra/test_ticket_asl.py -q` → `No module named 'infra.training_kb_stack'`。
4. 綠燈後：`uv run python -m infra.scripts.build_lambda_layer` → `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet` → deploy。
5. 全套：`uv run pytest tests -q -W error`（基線 924 passed / 23 skipped / 11 xfailed）＋ `ruff check`／`ruff format --check`／`mypy`。

## 5. 00B primary Rule
**沒有 primary Rule**（00B 第 1 節：P25／P41／P59／P60 是驗收型）。相關：`RUN` Rule 2、6、7、10（primary P29）→ `tests/unit/infra/test_ticket_asl.py`；`ING` Rule 26（primary P32）→ 驗收矩陣 Idempotency 列。§10 已對齊。

## 6. 風險與陷阱
- **`ensure_embedding` 先一致讀表再決定要不要呼叫模型**（`pipelines/ticket.py:54`）：`current.embedding` 非空就原樣回傳，**0 次 Bedrock**。這是 O5 BLOCKED 下唯一能跑通的槓桿。
- **`assign_cluster` 只判斷不寫入**（docstring 明說），寫回 `cluster_id` 是你的 `task_assign_cluster` 的責任：先 `get_meta(..., consistent=True)` 再 `put_meta(create_only=False)`。
- **`name_gap` 回 `dict`**（`GapNaming` 是 JSON schema 不是型別，D-02）：`naming["feature_id"]`。
- **`BedrockWriter` 的錯誤分類**（`writing/client.py:40-43`、`:202-220`）：只有 6 個碼 ＋ 3 個 timeout 例外算 transient，其餘一律 `PermanentError(錯誤碼)`。`ValidationException` → `PermanentError`，**一次 TaskFailed 就進 Catch**。
- **`errorType` 比對的是類別名字串，不認繼承** → `InjectedFault(TransientError)` 在雲端**不會**命中 `ErrorEquals:["TransientError"]`。
- **`FAULT_POINTS` 五個切點都不在 ticket-analysis 的 modelless 段**（三個在 `content.py`／`publishing.py`，一個在 `ingress.py`），而且 P59 有「每個名稱在三個檔恰好出現一次」的測試 → **不得加第六個切點**。
- **moto 做不到**：GSI 落後（moto 即時）、真實 S3 條件寫入的 409、Step Functions 的 `errorType`。
- `save_asl_snapshot` 同版重跑丟 `ObjectAlreadyExists`（bytes 相同時視為冪等、不丟；bytes 不同才 `PermanentError`）—— 看 `asl.py:150-166` 再寫測試。
- R3：`pipelines/common.py`／`ticket.py`／`infra/training_kb_stack.py` 只用 Edit、自己的區段用 `# ---- Phase 41 ----` 分隔、`git add` 只加自己的路徑。

## 7. 需要裁決的點 → 建議的裁決（可直接採用）
1. **`TrainingKbStack` 怎麼拿到 table／bucket？** → 建構子 `*, data: TrainingKbDataStack`，`infra/app.py` 在**同一個 App、同一個 `env`** 傳進來，CDK 自動產生跨 stack `Export`／`Fn::ImportValue`。**不要**改 P09 的 `CfnOutput` 加 `export_name`（那支檔 owner 是 P09、下一個修改者是 P57）。單元測試也要建兩支 stack。
2. **`TKB_CONTENT_BUCKET`** → `bucket.bucket_name`（跨 stack 參照）。`load_settings` 的預設值 `training-kb-content` 在雲端不存在；`Template` 斷言要擋住字面值。
3. **Lambda 打包** → `uv pip install --target build/lambda-layer/python --python-platform x86_64-manylinux2014 --python-version 3.12 --only-binary=:all: "pydantic>=2,<3" "jsonschema>=4,<5"`，做成一支 `LayerVersion(layer_version_name="training-kb-deps", compatible_architectures=[X86_64])`，兩支 Lambda 共用、以 `self.deps_layer` 公開給 P42／P48／P52／P54。**boto3 不放進 layer**（runtime 自帶）。**已實測（2026-09-14，uv 0.11.32）**：10 個套件、9.3 MB、`_pydantic_core.cpython-312-x86_64-linux-gnu.so` 是 ELF x86-64。Docker bundling 是等效替代但較慢。layer 要在 `cdk synth` 之前建好。
4. **失敗路徑怎麼注入 `TransientError`（不搶 P59 owner）** →
   (a) P41 建 `src/training_kb/faults.py` 的第一片：`FAULT_POINTS` 就是 P59 那**五個**名稱、`InjectedFault`／`active_fault`／`maybe_fail` 逐字照 00A 第 1230 列，**不在 `content.py`／`publishing.py`／`ingress.py` 插任何 `maybe_fail`**（那是 P59 Task 1，P59 的「三檔各一次」測試因此不受影響）。
   (b) P41 在自己 owner 的 `pipelines/common.py` 加 `maybe_fail_task(pipeline, task, env=None)`：讀 `TKB_FAULT_TASK="<pipeline>:<task>"`，`TKB_ENV=="prod"` 時一律不生效，命中就 **`raise TransientError(...)`**（**不是** `InjectedFault` —— 類別名要逐字等於 `TransientError` 才命中 retrier）。`pipeline_task_handler` 分派前呼叫一次，**每次 invoke 重讀環境變數**，不要跟 `_DEPS` 一起做模組層快取。
   (c) 雲端：`aws lambda update-function-configuration --function-name training-kb-pipeline-task --region us-east-1 --environment 'Variables={…,TKB_FAULT_TASK=ticket-analysis:name_gap}'`，跑完立刻移除並存證移除後的 `get-function-configuration`。
   (d) 回報 controller：00A §3.5 要補 `TKB_FAULT_TASK`、§3.2 `faults.py` 那列註明「P41 建第一片、P59 擴充」、P60 部署清單加「`TKB_FAULT_TASK` 未設 ＋ `TKB_ENV=prod`」；順帶提醒 P59 的 `InjectedFault` 在雲端不會命中第一條 retrier。
5. **`dynamodb:DeleteItem` 的條件授權（D-79）** → DynamoDB 的 IAM 條件鍵只有 `dynamodb:LeadingKeys`（比 **PK**）等，**沒有比 SK 的條件鍵**，逐字的「`SK begins_with APPLIED_TO#`」在 IAM 層做不到。裁決：授權寫成「單一 table、只給 `DeleteItem`、不得 `dynamodb:*`」，範圍由程式層 `DELETABLE_RELATIONS` 白名單守住，`Template` 斷言固定「只有一條 `DeleteItem` 敘述、資源只有這張表」，並把實際 policy JSON 貼進報告。
6. **`approved_model_arns`** → O5 BLOCKED 期間**只列** `arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0`；`TKB_GENERATION_MODEL_ID` 不設，生成模型 ARN 等 O5 過後再加。
7. **`TKB_GITHUB_WEBHOOK_SECRET`** → 由執行 `cdk deploy` 的 shell 帶進來，`infra/training_kb_stack.py` 用 `os.environ["TKB_GITHUB_WEBHOOK_SECRET"]` 讀（缺值讓 synth `KeyError` 當場失敗）。值不進 repo／報告／log。MVP 不引入 Secrets Manager／SSM，但要在報告寫明「明文環境變數會出現在 `get-function-configuration`」這個取捨並列為 P60 `check_secrets` 項目。
8. **`local_deps` fixture** → 定義在 `tests/unit/pipelines/test_ticket_flow.py` 自己檔內（`from test_ticket_decide import FakeOperations, FakeRepository, FakeWriter, dt`），**不要改 `tests/unit/pipelines/conftest.py`**（同波次 P48／P52 也用）。文件示意的 `writer.generate_calls`／`repository.created_versions` 不存在，實際是 `FakeWriter.calls`／`FakeRepository.writes`。

## 8. 對 AWS 的實際操作
- 帳號 `123456789012`，**region 一律 `us-east-1`**（CLI 帶 `--region us-east-1`）。
- CDK：`AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 <子命令>`（本機 `node` 被 shell function 擋住）。`--outputs-file` 指到 scratchpad，**不提交 `cdk.out/`**。已部署：`TrainingKbData`（table `training_kb`、bucket `training-kb-content-example`）、`CDKToolkit`。部署樣板見 `docs/plan/report/phases/2026-09-14-Phase09-REP.md` §7。
- **種子資料（關鍵）**：用 `uv run python` ＋ `Repository.put_meta` 寫合成 `Ticket`。
  - `SUCCEEDED` 路徑：一筆 `t_881`，`project_id="demo"`，`embedding` = 1024 個浮點數，`cluster_id=None`，同群不到五筆 → `NotRecurring`，**0 次 Bedrock**、3 個 `TaskStateEntered`。
  - 走到 `NameGap`：同 `cluster_id` 五筆、`ts` 都落在 anchor 的 14 天 UTC 窗口、每筆都有 `embedding`。
- 證據要存的（缺一項不算完成，全部進報告 §3／§4）：兩個 execution ARN ＋ `describe-execution` 的 `status`／`startDate`／`stopDate`／`output`；`get-execution-history` 的 `TaskStateEntered` 名稱序列；失敗那次的 `taskFailedEventDetails.[error,cause]` **原文**；`aws logs tail <state machine log group> --since 15m`；`TUTORIAL#`／`VERSION#` 的 `current_version`／`published_at` 實際值；`CallTrace` 的逐次 attempt（O5 BLOCKED 時 `NotRecurring` 那次應為 0 筆）；`save_asl_snapshot` 兩次執行的輸出（第二次 `ObjectAlreadyExists`）；`start-execution` 回傳 ARN 與 `STATE_MACHINE_NAMES` 推導 ARN 的逐字比對；`by_target` 在種子寫入後立刻 query 的原始輸出。
- §7A 的 A1–A9 每一項在報告要有一行結論（做到／去向 P48・P52・P57・P59／BLOCKED 原因）。
