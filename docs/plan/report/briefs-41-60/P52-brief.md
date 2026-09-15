# P52 brief — Release RETIRE 與流程驗收

文件：`docs/plan/unfinish/52-Phase52-Release-RETIRE與流程驗收.md`（W0 已更新，commit `4a0f0ac`）
波次：**W3（最後；需要 P41、P49、P50、P51 全部落地）**

## 1. 單一交付物與停止點
- **交付物**：`removed` 的 RETIRE 分支（含 **D-83 退役索引頁重寫**）＋ 把 P49–P51 接成 `release-update` Standard state machine ＋ 真實 AWS 證據。
- **停止點**：`run_release_update` 本機跑得通、`training-kb-release-update` 部署完成、**可實證路徑**有 `SUCCEEDED`／`FAILED` 各一個 execution，**BLOCKED 路徑**有原始錯誤文字。不新增第四條 pipeline、不建第二個 Lambda、不在 Map 內逐篇發布。

## 2. 已存在、直接重用
- `src/training_kb/pipelines/asl.py`：`RETRY`（**已是 D-53 的兩條 retrier**）、`CATCH`、`FAIL_STATE_NAME="PipelineFailed"`、`TASK_TIMEOUT_SECONDS=120`、`task_state`、`assert_safe_asl`（**已檢查 Choice 的 `Default`**、Task 前兩條 retrier 逐字相同、單一 `States.ALL` Catch 導向同層 `Fail`）、`canonical_json`、`save_asl_snapshot(repository, pipeline, number, body) -> str`（同 bytes 冪等、不同 bytes `PermanentError`）、`ASL_LOCAL_PATH`／`ASL_SNAPSHOT_KEY`。
- `src/training_kb/pipelines/common.py`：`Deps(operations, now, repository=None, writer=None, settings=None)` ＋ `need_*`、`run_sequence`（失敗時 `operations.fail(...)` 後原樣 re-raise）、`PIPELINE_NAMES`。
- `src/training_kb/content.py`（**不是 `publishing.py`**）：`retire_tutorial(slug, *, reason, successor, repository, now) -> Tutorial`（只改 `status`／`successor`；`successor` 只在目前為空時寫；空 `reason` → `PermanentError`；revision 不符 → `TransientError`；`changes` 為空就零次 `update_meta`）、`resolve_successor`、`RETIRED_NOTICE`、`parse_version_id`。
- `src/training_kb/publishing.py`：`Publisher(repository, renderer, operations)`、`prepare`／`inspect`／`commit`、`PublishRequest(version_ids, operation_id)`、`tutorial_index_key(slug)`、**`Publisher._write_tutorial_index(slug)`**（走 `_put_index` → `_put_public_object(..., if_none_match=False)`，索引頁可覆寫）。
- `src/training_kb/site.py:SiteRenderer.render_tutorial_index` — **退役區塊與後繼連結已完成**（修正波 `f1ef75a`）。
- `src/training_kb/keys.py:operation_ref`、`clock.py:to_iso`／`now_utc`、`ingress.py:validate_release`／`operation_id_for`／`execution_name`、`models.py:ReleaseKind.REMOVED`／`TutorialStatus.RETIRED`。
- **P41 提供（目前都不存在，等 P41）**：`task_name(task)`、`build_deps(settings)`、`pipeline_task_handler(event, context)`（在 `pipelines/common.py`）、`infra/training_kb_stack.py`、共用 Lambda `training-kb-pipeline-task`、log group、相依 layer／bundling（**R2：沿用，不各自再做**）。

## 3. 要新增／修改的東西
`src/training_kb/pipelines/release.py` → `# ---- Phase 52 ----`：
```python
RELEASE_STATE_FIELDS = ("operation_id","project_id","input_ref","release_id","feature_id",
                        "action","hit_refs","prepared_version_ids","publish_request_ref",
                        "alias_update","result_ref")            # 00A §7，十一個
def retire_for_release(release, hits, *, repository, successor_by_slug: Mapping[str,str],
                       now: datetime) -> tuple[str, ...]: ...
task_locate_feature / task_find_steps / task_safety_net / task_prepare_update /
task_publish_batch / task_update_aliases / task_retire            # 名稱固定（D-51）
RELEASE_UPDATE_TASKS: tuple[TaskFn, ...]
def run_release_update(state, deps) -> dict: ...
def release_update_handler(event, context) -> dict: ...           # 放這支檔，不開 handlers/（D-25）
```
- 建立 `infra/stepfunctions/release-update/v1.json`（七個 Task 用 `${PipelineTaskFunctionArn}`、`Parameters` 含 `pipeline`／`task`／`state.$`、**無 `Payload` 外層**；`ChooseAction` Choice ＋ `RecordKeep` Pass ＋ `Succeeded` ＋ `PipelineFailed`）。
- 修改 `infra/training_kb_stack.py`（P41 建）：加 `training-kb-release-update` Standard state machine、`task_fn.grant_invoke(...)`、`grant_start_execution(webhook_fn)`／`(import_fn)`。**不建第二個 Lambda。**
- 測試（00A §3.3）：`tests/unit/test_release_retire.py`、`tests/unit/test_release_asl.py`、`tests/integration/test_release_update_state_machine.py`（`@pytest.mark.aws`）。

## 4. Task 順序與紅燈訊號
1. **Task 1｜removed → RETIRE，successor 只來自維護者**
   - RED：`uv run pytest tests/unit/test_release_retire.py -q` → `cannot import name 'retire_for_release'`
   - GREEN：兩篇依 slug 升序退役；未指定 successor 仍退役（F19）；evidence 裡的 `successor:` 不被採用（F54）；`retire.json` 內容與 `result_ref` 正確；重送不重寫。
   - **Step 3b（D-83，必做）**：`task_retire` 在 `retire_for_release` **之後**對每個 slug 呼叫 `Publisher._write_tutorial_index(slug)`。斷言索引頁含 `RETIRED_NOTICE` 與後繼、**版本頁 bytes 未變**、`published_version_ids == []`。順序不可顛倒（索引內容讀 `get_tutorial(slug).status`）。
2. **Task 2｜ASL ＋ state machine**
   - RED：`uv run pytest tests/unit/test_release_asl.py -q` → `infra/stepfunctions/release-update/v1.json` 不存在
   - GREEN：`assert_safe_asl(asl)` 過；七個 Task 的 `Retry`／`Catch`／`TimeoutSeconds` 等於 `list(RETRY)`／`list(CATCH)`／`TASK_TIMEOUT_SECONDS`；`{p["task"]} == {task_name(t) for t in RELEASE_UPDATE_TASKS}`；`Choice` 有 `Default="RecordKeep"`、無 `Retry`／`Catch`／`End`；`RetireTutorials.Next == "Succeeded"`。
   - `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet` → 恰多一個 `AWS::StepFunctions::StateMachine`、沒有新的 `AWS::Lambda::Function`。
3. **Task 3｜串接三分支 ＋ 雲端驗收**
   - RED：`cannot import name 'RELEASE_UPDATE_TASKS'`
   - GREEN（本機）：task 名稱順序等於 `["locate_feature","find_steps","safety_net","prepare_update","publish_batch","update_aliases","retire"]`；零命中 → `("KEEP", [])`；`set(result) <= set(RELEASE_STATE_FIELDS)`。
   - 雲端：見 §8。
4. 收尾：`ruff check src tests infra`／`ruff format --check`／`mypy`／`uv run pytest tests -q -W error`。

## 5. 00B primary Rule → 測試
| Rule | 角色 | 測試 |
|---|---|---|
| `REL` 9 removed → RETIRE | **primary** | `test_release_retire.py::test_removed_retires_each_hit_tutorial` ＋ ASL `ChooseAction` 的 RETIRE 分支 |
| `REL` 12 未引用維持 KEEP | 相關（primary P50） | `test_release_asl.py::test_zero_hits_ends_as_keep` ＋ §8 B／C `current_version` 不變 |
| `REL` 16／17 標記過期／導向後繼 | 相關（primary P26） | 本 Phase 斷言流程中呼叫 `retire_tutorial`、successor 只來自 `successors.json`；**讀者看得到**靠 D-83 索引頁 |
| `RUN` 2／6／7／10 | 相關（primary P29） | `test_release_asl.py` 的節點名、Retry／Catch、`save_asl_snapshot` 條件寫入 |

## 6. 風險與陷阱
- **`infra/training_kb_stack.py`、`infra/stepfunctions/`、`task_name`／`build_deps`／`pipeline_task_handler` 目前都不存在** → 等 P41。
- **00A §7 的圖寫 `pipeline_task_handler -> run_sequence(...)`，但 ASL 是 per-Task 分派**（`Parameters.task`）。若 P41 真的把它實作成「一次跑完整條 sequence」，每個 Task state 都會重跑整條 pipeline。**開工前跟 P41／controller 確認**：正確語意是「依 `event["pipeline"]` 找到那條 pipeline 的 `*_TASKS`，再依 `event["task"]` 只跑那一個 task」。
- `cdk` 一律 `command npx aws-cdk@2 <子命令>` ＋ `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1`；`--outputs-file` 指 scratchpad；**不提交 `cdk.out/`**。stack id 以 P41 在 `infra/app.py` 建的為準（**不是** `TrainingKbApp`，目前已部署的只有 `TrainingKbData`）。
- 所有 `aws` CLI 都要 `--region us-east-1`（本機 profile 預設 ap-northeast-1）。
- **Choice 不支援 Retry／Catch／End**；`States.ALL` 只能單獨且放最後，抓不到 `States.Runtime`／`States.DataLimitExceeded` → state 只放 ID 與 S3 key。
- `RetireTutorials` **不經** `PublishBatch`；`UpdateAliases` 排在 `PublishBatch` 之後；`kind=changed` 時 `task_update_aliases` 原樣回傳 state。
- handler **不寫 try/except**：`TransientError` 要讓 Retry 抓、`PermanentError` 要讓 Catch 抓。
- `task_prepare_update` 只傳**這次 Release 的** `operation_id`；per-slug 子 operation 由 P51 內部處理（D-59），本 Phase 沒有第二份取號邏輯。
- **D-83 只重寫索引頁**：不呼叫 `prepare`／`inspect`／`commit`、不碰 `render_version_page`。已發布版本頁在協定 A 下不可覆寫（`_version_problems` 擋、`_put_public_object` 比對 bytes）。`retire_tutorial` 自己仍不寫任何 `site/`。
- ruff `select` 只有 `E`／`F`／`I`／`UP`，所以呼叫 `Publisher._write_tutorial_index` 不會被 lint 擋。

## 7. 需要裁決的點 → 建議裁決
1. **`_write_tutorial_index` 是私有方法**，要不要改成公開？→ **直接呼叫既有私有方法**，寫進報告當本計畫選擇；不複製索引渲染邏輯、不為此改 `publishing.py` 介面（P57 若改成公開，只要動呼叫點）。
2. **`Publisher` 在 `task_retire` 裡怎麼建？** → `Publisher(deps.need_repository(), SiteRenderer(), deps.operations)`；renderer 的實作 P57 才會換。
3. **雲端主案例選哪一條？** → 選 **RETIRE 與 KEEP**（不需要模型），`renamed` 主案例照跑但預期在 `SafetyNet`／`PrepareUpdate` 撞 O5，存 BLOCKED 證據。
4. **`hit_refs` 的字串格式**？→ `"<version_id>#<number>"`（文件已定），slug 用 `parse_version_id(version_id)[0]` 還原。
5. **`release_update_handler` 與 `pipeline_task_handler` 重疊**？→ 前者是「本 pipeline 的直接入口與測試鉤子」（D-24），依 `event["task"]` 分派單一 task；雲端實際部署的是後者。兩者共用 `_TASK_BY_NAME`。

## 8. 對 AWS 的實際操作（region 固定 `us-east-1`）
帳號 `123456789012`，IAM user `tkb-deploy-admin`。資源：state machine `training-kb-release-update`（Standard）、共用 Lambda `training-kb-pipeline-task`（P41）、table `training_kb`、bucket `training-kb-content-example`。

```bash
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 \
  command npx aws-cdk@2 deploy <P41 stack id> --require-approval never \
  --outputs-file "$SCRATCH/cdk-outputs.json"
# O6 未核定 pull_request → 走不進 webhook：先手動備好 ledger 與輸入
aws s3 cp ./release-r_42.json s3://<bucket>/operations/op-release-r_42/release.json --region us-east-1
#   OPS# item 用 uv run python 呼叫 OperationCoordinator.accept(AcceptOperation(...)) 寫，不手拼 item
aws stepfunctions start-execution --region us-east-1 --state-machine-arn "$TKB_RELEASE_SM_ARN" \
  --name "op-release-r_42" --input '{"operation_id":"op-release-r_42","project_id":"demo",
  "input_ref":"operations/op-release-r_42/release.json"}'
aws stepfunctions get-execution-history --region us-east-1 --execution-arn "$ARN" --max-results 200 \
  --query "events[?type=='TaskStateEntered'].stateEnteredEventDetails.name" --output text
```

**證據存放**：`docs/plan/report/phases/2026-09-14-Phase52-REP.md` §4／§7，兩張表照文件 §6 的「可實證」與「BLOCKED」分開寫。
- **可實證**：ASL 快照 `head-object`、`describe-state-machine`、KEEP 與 RETIRE 各一個 `SUCCEEDED`、注入 `TransientError` 的 `FAILED`（終點 `PipelineFailed`）、`TUTORIAL#prepare-meeting` 的 `get-item --consistent-read`、`operations/<op>/retire.json`、**退役索引頁 `site/tutorials/prepare-meeting/index.html`（D-83）**、`CallTrace` 呼叫數。
- **BLOCKED**（照實記、不得寫成通過）：webhook 入口（**O6** 未核定 `github.com/pull_request`，附 `tests/fixtures/o6/approved-sources.json` 原文，**不改那個 fixture**）、`LocateFeature` 語意層／`SafetyNet`／`PrepareUpdate`（**O5**，附 `TaskFailed` 的 `error`／`cause` 與 `docs/plan/report/o5-20260915T030245Z.md`）、`PublishBatch` 整批切換（**O3 FAIL**，附 `docs/plan/report/o3-20260914t181109z.md`、D-80）。
- **絕不**把金鑰、bucket 內容、outputs 檔提交進 repo（R11）；**絕不 push**（R8）。
