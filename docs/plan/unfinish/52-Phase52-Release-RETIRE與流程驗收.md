# Phase 52：Release RETIRE 與流程驗收實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 補上 `kind=removed` 的退役分支，把 Phase 49–51 接成 `release-update` Standard workflow，並留下「A 只改第 3 步、B 與 C 完全不變」的實際 AWS 證據。

**架構：** 七個 Task 節點共用 Phase 41 建好的 Lambda `training-kb-pipeline-task`，由 ASL 的 `Parameters.pipeline` 與 `Parameters.task` 分派；`ChooseAction` 這個 Choice 節點決定走 UPDATE、RETIRE 還是 KEEP。發布仍由 Phase 25 的 `Publisher` 整批提交，alias 更新排在發布成功之後。

**技術：** Python 3.12、AWS Step Functions Standard、AWS Lambda、AWS CDK、pytest、Phase 29 的 `run_sequence`、`RETRY`／`CATCH` 與 `assert_safe_asl`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.4、§8.4、§9.3、§14、§15、§16 S5、§18 O3](../../design/training-kb.md)。
- 前置為 [Phase 51：Release UPDATE 精準改寫](51-Phase51-Release-UPDATE精準改寫.md)；另需 [Phase 26 教學退役](26-Phase26-教學退役與後繼導向.md)、[Phase 29 Pipeline 執行器](29-Phase29-共用Pipeline執行器與ASL失敗語意.md)、[Phase 41 Ticket Analysis 雲端流程](41-Phase41-Ticket-Analysis雲端流程驗收.md)（建立共用 Lambda 與 `infra/training_kb_stack.py`）、[Phase 25 整批發布](25-Phase25-多篇教學整批發布.md) 已完成。
- 下一階段是 [Phase 53：評分與負面回饋指標](53-Phase53-評分與負面回饋指標.md)。
- 本階段不做：不新增第四條 pipeline、不建立人工發布審核佇列、不另建第二個 Lambda、不在 Map 內逐篇發布、不自行決定 successor。
- successor 只由維護者透過 `successor_by_slug` 傳入；來源事件不得指定（F54）。沒有 successor 仍完成退役（F19）。
- O1–O7 是設計文件第 18 節的七個待確認事項，F 與 D 開頭的編號（F19、F49…）是第 19 節的決策編號；本文件引用它們只是指出依據，不代表已驗證。
- O1–O7 狀態：O3 未通過時停止公開發布路徑，保留可追溯 FAIL；O2、O5、O6 任一未通過時，本 Phase 的雲端驗收只能記為 BLOCKED。**本 Phase 不得把文件、CDK synth 或 mock 綠燈寫成雲端流程已通過。**
- 以下程式檔與 AWS 資源均是實作時預計建立；本計畫本身不代表它們已存在或已部署。

---

## 1. 你在整體流程的位置

```text
Phase 32 StartExecution(release-update, execution_name(operation_id))
             |
             v
[你在這裡] LocateFeature -> FindSteps -> SafetyNet -> ChooseAction
                                                          |
        +---------------------+---------------------------+
        | UPDATE              | RETIRE                    | 其他（Default）
        v                     v                           v
  PrepareUpdate          RetireTutorials              RecordKeep（Pass）
        |                     |                           |
        v                     |                           |
  PublishBatch（全有或全無）-> UpdateAliases --+-------------+--> Succeeded

任一 Task 的 Retry 耗盡 -> Catch -> PipelineFailed（Fail，零新版本公開）
```

## 2. 完成後看得到什麼

用與 Phase 32 相同的 input 手動啟動一次（ASL input 固定只有這三個欄位）：

```json
{"operation_id": "op-release-r_42", "project_id": "demo", "input_ref": "operations/op-release-r_42/release.json"}
```

成功執行的輸出必須列出 `release_id`、`feature_id`、`action`、`hit_refs`、`prepared_version_ids`、`publish_request_ref` 與 `alias_update`。核對 AWS 後應看到：

```text
A  prepare-meeting          current_version: v2 -> v3   第 3 步改為 Prepare；第 1、2、4 步逐字相同
B  share-summary            current_version: v1（不變）  沒有 v2
C  notification-settings    current_version: v1（不變）  沒有 v2
FEATURE#Prepare             name: Meeting Summary -> Prepare；PK 不變
```

另外送一則 `kind=removed` 的 Release，維護者事先把 `{"prepare-meeting": "share-summary"}` 放進 `operations/<operation_id>/successors.json`，A 的 `status` 變成 `retired`、`successor="share-summary"`，歷史版本與原文全部保留，`operations/<operation_id>/retire.json` 留下這次退役了哪幾篇。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| Standard workflow／ASL 快照 | 有完整可查執行紀錄的 Step Functions 類型，三條 pipeline 都用它；部署前把同一份 definition bytes 存成私有 S3 物件 `stepfunctions/release-update/v1.json`。 |
| Choice 節點／`Default` | 依 state 裡的值決定走哪條分支，不是 Task 所以不支援 Retry／Catch；`Default` 是沒有條件成立時的去處，缺它會讓執行直接報錯。 |
| 直接函式 ARN | `Resource` 直接寫 Lambda 的 ARN，不包 `arn:aws:states:::lambda:invoke` 信封，所以沒有 `Payload` 外層。 |
| RETIRE | 把 Tutorial 的 `status` 改為 `retired`，保留歷史原文，拒絕新回饋；successor 由維護者選定，沒有也要能完成（F19）。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/release.py` | `retire_for_release`、七個 `task_*`、`RELEASE_UPDATE_TASKS`、`run_release_update`、`release_update_handler`。 |
| 建立 | `infra/stepfunctions/release-update/v1.json` | 固定 Standard ASL 定義（00A D-14）。 |
| 修改 | `infra/training_kb_stack.py` | 第二條 state machine 與最小執行角色（Lambda 與 log group 沿用 Phase 41 的）。 |
| 測試 | `tests/unit/test_release_retire.py` | removed 分支、successor 來源、無 successor、退役紀錄。 |
| 測試 | `tests/unit/test_release_asl.py` | Retry／Catch／`Default`、task 名稱與 Python 對齊、本機三分支序列。 |
| 測試 | `tests/integration/test_release_update_state_machine.py` | 真實隔離環境的雲端驗收（`@pytest.mark.aws`）。 |

`release_update_handler` 依 00A D-25 放在 `pipelines/release.py`，**不**另開 `handlers/release_update.py`；`handlers/` 只放 webhook、import、analytics 三支非 pipeline Lambda。

## 5. 固定介面

### Consumes

```text
locate_feature / update_feature_aliases                                          # Phase 49
StepHit / find_release_hits / needs_safety_net / safety_net                      # Phase 50
prepare_update(release, hits, *, repository, writer, operations, operation_id)   # Phase 51
retire_tutorial(slug, *, reason, successor, repository, now) -> Tutorial         # Phase 26
Publisher.prepare / inspect / commit ; PublishRequest(version_ids, operation_id) # Phase 24/25
run_sequence(pipeline, payload, tasks, deps) -> dict ; RETRY / CATCH / task_state /
    assert_safe_asl / canonical_json / save_asl_snapshot                         # Phase 29
task_name(task) / build_deps(settings) / pipeline_task_handler(event, context)   # Phase 41
Deps(operations, now, repository, writer, settings) 與 need_* 三個方法             # Phase 29 + 38
OperationCoordinator.load / record_version / complete / fail ; operation_ref(op, name)  # Phase 10
Repository.get_object / put_object(key, body, content_type, *, if_none_match)    # Phase 07
validate_release(payload) -> Release # Phase 31 ; parse_version_id(value)        # Phase 20
load_settings(env) / to_iso(dt) / PermanentError / TransientError  # Phase 02
ReleaseKind.REMOVED / TutorialStatus.RETIRED  # Phase 03
```

### Produces

```python
RELEASE_STATE_FIELDS: tuple[str, ...]
RELEASE_UPDATE_TASKS: tuple[TaskFn, ...]
def retire_for_release(release: Release, hits: Sequence[StepHit], *,
                       repository: Repository, successor_by_slug: Mapping[str, str],
                       now: datetime) -> tuple[str, ...]: ...
def run_release_update(state: dict, deps: Deps) -> dict: ...
def release_update_handler(event: dict, context: object) -> dict: ...
```

固定 state 只傳 `RELEASE_STATE_FIELDS` 這十一個欄位：`operation_id`／`project_id`／`input_ref`／`release_id`／`feature_id`／`action`／`hit_refs`／`prepared_version_ids`／`publish_request_ref`／`alias_update`／`result_ref`（00A 第 7 節）。不傳教學全文、Release evidence 原文或向量；需要全文的 Task 自己用 `input_ref` 讀回來。七個 task 函式命名固定為 `task_locate_feature`、`task_find_steps`、`task_safety_net`、`task_prepare_update`、`task_publish_batch`、`task_update_aliases`、`task_retire`，`task_name(...)` 去掉 `task_` 後就是 ASL 的 `Parameters.task`。**`find_steps` 是 Task 名稱，它包裝的模組函式仍叫 Phase 50 的 `find_release_hits`，兩者不是同一層，不得互相取代（00A D-51）。**

`Retire` 這個 task 另外寫一份退役紀錄 `operations/<operation_id>/retire.json`（00A §6.6）：內容是一個 JSON 陣列，每個元素是 `{"slug", "reason", "retired_at", "successor"}`。用陣列而不是單一物件是**本計畫選擇**——一則 removed Release 可能命中多篇教學，單篇時就是長度 1 的陣列。`Tutorial` 模型沒有 `retired_at`／`retired_reason` 欄位，這些執行資訊只能放 operation 紀錄（00A D-40）。

## 6. ASL 與失敗語意

```text
task 函式 raise TransientError -> handler 不攔截，直接往外拋
        |
Lambda runtime 回 errorType = "TransientError"（只有類別名）
        |
Retry[0] 命中 -> 等 1 秒、再等 2 秒，最多兩次
        |
仍失敗 -> Catch ["States.ALL"] -> PipelineFailed (Fail)
        -> 整次 execution FAILED；不發布、不切 current_version、不退役
```

每個 Task 用**直接函式 ARN**當 `Resource`，指向 Phase 41 建立的共用 Lambda `training-kb-pipeline-task`（00A D-23；不得出現 `tkb-release-update` 這種一條 pipeline 一個函式的寫法）。封套固定是 `Parameters`，必須含 `pipeline`、`task`、`state.$` 三個欄位，`pipeline_task_handler` 才有東西可分派，而且**沒有** `Payload` 外層（00A D-24、D-49）。`Retry`／`Catch` 直接用 Phase 29 的 `RETRY` 與 `CATCH` 常數產生，**每個 Task 固定兩個 retrier**（00A D-53）：第一個接業務的 `TransientError`，第二個接 Lambda 服務層暫時錯誤，兩者參數相同；不寫 `TrainingKB.TransientError`、不列 `States.Timeout`、`BackoffRate` 是 `2`。以下是 `infra/stepfunctions/release-update/v1.json` 的節錄，其餘六個 Task 與 `LocateFeature` 逐字相同，只改 `Parameters.task` 與 `Next`。

```json
{
  "Comment": "Training KB release-update（設計 §7.4）；七個 Task 呼叫同一個 Lambda，用 pipeline 與 task 名稱分派。",
  "StartAt": "LocateFeature",
  "States": {
    "LocateFeature": {
      "Type": "Task",
      "Resource": "${PipelineTaskFunctionArn}",
      "Parameters": {"pipeline": "release-update", "task": "locate_feature", "state.$": "$"},
      "TimeoutSeconds": 120,
      "Retry": [{"ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2},
                {"ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.failure", "Next": "PipelineFailed"}],
      "Next": "FindSteps"
    },
    "ChooseAction": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.action", "StringEquals": "UPDATE", "Next": "PrepareUpdate"},
        {"Variable": "$.action", "StringEquals": "RETIRE", "Next": "RetireTutorials"}
      ],
      "Default": "RecordKeep"
    },
    "RecordKeep": {"Type": "Pass", "Result": "KEEP", "ResultPath": "$.action", "Next": "Succeeded"},
    "Succeeded": {"Type": "Succeed"},
    "PipelineFailed": {"Type": "Fail", "Error": "PipelineFailed", "Cause": "以失敗結束，不發布新版本"}
  }
}
```

| Task state | `Parameters.task` | `Next` |
|---|---|---|
| `LocateFeature` | `locate_feature` | `FindSteps` |
| `FindSteps` | `find_steps` | `SafetyNet` |
| `SafetyNet` | `safety_net` | `ChooseAction`（Choice） |
| `PrepareUpdate` | `prepare_update` | `PublishBatch` |
| `PublishBatch` | `publish_batch` | `UpdateAliases` |
| `UpdateAliases` | `update_aliases` | `Succeeded`（Succeed） |
| `RetireTutorials` | `retire` | `Succeeded`（Succeed） |

三個細節來自官方文件而不是猜測：

- **Choice 沒有 Retry／Catch。** catcher 只存在於 `Task`、`Parallel`、`Map`；`Choice` 也不支援 `End`，`Next` 只能寫在 `Choices` 裡面。所以 Phase 29 的 `assert_safe_asl` 只對 `Task` 要求 Retry／Catch，`ChooseAction` 沒有 `Retry` 是正確的，不是漏寫。
- **`Default` 必須存在。** 沒有 Choice Rule 成立又沒有 `Default` 時，執行會因「無法離開該狀態」報錯。KEEP 是合法業務結果（設計 §7.4「補漏無任何可確認命中時，記錄未命中並 KEEP」），所以必須有 `RecordKeep`；`action` 只會是 `UPDATE`／`RETIRE`／`KEEP`，把它正規化成 `KEEP` 是業務結果，不是吞掉錯誤。
- **`States.ALL` 只能單獨出現在最後一個 catcher，且抓不到 `States.Runtime` 與 `States.DataLimitExceeded`。** 因此 payload 只放 ID 與 S3 key，避免撞到資料大小上限。

`RetireTutorials` 直接接 `Succeeded`，**不經過 `PublishBatch`**：退役不產生新版本，也沒有東西要發布。`UpdateAliases` 排在 `PublishBatch` 之後，因為設計 §7.4 要求「寫下一版、diff、reason，完成後更新 aliases」；`kind=changed` 時這個 Task 原樣回傳 state，不呼叫 `update_feature_aliases`。部署前先用 Phase 29 的 `save_asl_snapshot`（內部是 `put_object(..., if_none_match=True)`）把**與部署完全相同的 bytes** 存成 `stepfunctions/release-update/v1.json`（設計 §9.3、RUN Rule 10）。

雲端驗收要留下的證據格式如下。這是**預計取得**的清單，尚未執行：

| 證據 | 取得方式 | 必須看到 |
|---|---|---|
| 執行 ARN 與歷史 | `aws stepfunctions describe-execution` / `get-execution-history` | 一個 `SUCCEEDED`、一個注入故障後的 `FAILED`；每個 Task 的 `TaskStateEntered`，失敗終點是 `PipelineFailed`。 |
| ASL 快照 | `aws s3api head-object --key stepfunctions/release-update/v1.json` | 與部署中的 definition 相同；同內容重送冪等，改內容要升成 `v2.json`。 |
| 資料結果 | `aws dynamodb get-item --consistent-read`（A／B／C／`FEATURE#Prepare`） | A 切到 v3；B、C 的 `current_version` 不變；Feature PK 不變。 |
| 公開頁 | `curl http://<bucket>.s3-website-<region>.amazonaws.com/site/tutorials/prepare-meeting/v3.html` | A 第 3 步是新文字、第 1／2／4 步逐字相同；B、C 無新版。 |
| 模型呼叫數 | 逐次 `CallTrace` 紀錄 | 與該次執行的 attempt 數相符，含 retry 與每個 embedding（F45）。 |

## 7. TDD Tasks

### Task 1：removed 走 RETIRE，successor 只來自維護者

- [ ] **Step 1：建立失敗測試**（`tests/unit/test_release_retire.py`）

```python
def test_removed_retires_each_hit_tutorial(repo, removed_release, hits_two_tutorials):
    retired = retire_for_release(removed_release, hits_two_tutorials, repository=repo,
                                 successor_by_slug={"prepare-meeting": "share-summary"}, now=NOW)
    assert retired == ("notification-settings", "prepare-meeting")        # slug 升序
    assert repo.get_tutorial("prepare-meeting").status == TutorialStatus.RETIRED
    assert repo.get_tutorial("prepare-meeting").successor == "share-summary"
    assert repo.get_tutorial("notification-settings").successor is None   # 未指定仍完成退役（F19）

def test_successor_is_never_taken_from_the_release(repo, removed_release, hits_step3):
    tainted = removed_release.model_copy(update={"evidence": "successor: share-summary"})
    retire_for_release(tainted, hits_step3, repository=repo, successor_by_slug={}, now=NOW)
    assert repo.get_tutorial("prepare-meeting").successor is None

def test_retire_task_writes_the_operation_record(repo, local_deps, retire_state):
    result = task_retire(retire_state, local_deps)
    body = json.loads(repo.get_object("operations/op-release-r_43/retire.json").decode("utf-8"))
    assert body == [{"slug": "prepare-meeting", "reason": "release:r_43",
                     "retired_at": "2026-09-13T00:00:00Z", "successor": "share-summary"}]
    assert result["result_ref"] == "operations/op-release-r_43/retire.json"
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/test_release_retire.py -q` 確認紅燈。** 預期 FAIL，訊號包含 `cannot import name 'retire_for_release'`。
- [ ] **Step 3：建立最小實作**

```python
# src/training_kb/pipelines/release.py
def retire_for_release(release, hits, *, repository, successor_by_slug, now):
    if release.kind != ReleaseKind.REMOVED:
        raise PermanentError(f"retire_for_release 只處理 removed，收到 {release.kind}")
    retired = []
    for slug in sorted({hit.slug for hit in hits}):
        retire_tutorial(slug, reason=f"release:{release.id}",
                        successor=successor_by_slug.get(slug),
                        repository=repository, now=now)
        retired.append(slug)
    return tuple(retired)

def task_retire(state, deps):
    if state.get("action") != "RETIRE":
        return dict(state)                       # 不適用就原樣回傳
    repository, operation_id = deps.need_repository(), str(state["operation_id"])
    release = _load_release(state, repository)
    successors = _load_json(repository, operation_ref(operation_id, "successors")) or {}
    now = deps.now()
    slugs = retire_for_release(release, _hits(state), repository=repository,
                               successor_by_slug=successors, now=now)
    ref = operation_ref(operation_id, "retire")
    if repository.get_object(ref) is None:       # 重送不重寫，也不丟 ObjectAlreadyExists
        body = [{"slug": slug, "reason": f"release:{release.id}", "retired_at": to_iso(now),
                 "successor": successors.get(slug)} for slug in slugs]
        repository.put_object(ref, json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                              "application/json", if_none_match=True)
    return {**state, "result_ref": ref}
```

`successor` 的唯一來源是維護者事先寫進 `operations/<operation_id>/successors.json` 的 `{slug: successor_slug}`，讀不到就是空 dict（F54）。合法性檢查（存在、非自身、不形成循環）由 Phase 26 的 `resolve_successor` 負責，本 Phase 不重寫一份。`_hits(state)` 從 `hit_refs` 的 `"<version_id>#<number>"` 還原 `StepHit`，slug 用 Phase 20 的 `parse_version_id(version_id)[0]`。

- [ ] **Step 4：跑 `uv run pytest tests/unit/test_release_retire.py -q` 確認綠燈。** 另補三個案例：`kind="renamed"` 呼叫本函式丟 `PermanentError`；退役後該篇既有版本與回饋仍可讀取（設計 §8.4）；同 `operation_id` 重送時 `retire.json` 內容不變且沒有第二次寫入。
- [ ] **Step 5：提交** `git add src/training_kb/pipelines/release.py tests/unit/test_release_retire.py`，再 `git commit -m "feat(release): 依改版退役受影響教學"`。

### Task 2：建立 ASL 與 state machine，鎖定失敗語意

- [ ] **Step 1：建立失敗測試**（`tests/unit/test_release_asl.py`）

```python
ASL_PATH = Path("infra/stepfunctions/release-update/v1.json")
TASK_STATES = ("LocateFeature", "FindSteps", "SafetyNet", "PrepareUpdate",
               "PublishBatch", "UpdateAliases", "RetireTutorials")

@pytest.fixture
def asl():
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))

def test_every_task_has_the_shared_retry_and_catch(asl):
    assert_safe_asl(asl)                                   # Phase 29 的遞迴檢查
    for name in TASK_STATES:
        state = asl["States"][name]
        # JSON 讀回來的是 list，Phase 29 的常數是 tuple，所以先轉成同一種形狀再比較
        assert (state["Retry"], state["Catch"], state["TimeoutSeconds"]) == (list(RETRY), list(CATCH), 120), name
    assert asl["States"]["PipelineFailed"]["Type"] == "Fail"

def test_asl_task_names_match_python_tasks(asl):
    parameters = [asl["States"][name]["Parameters"] for name in TASK_STATES]
    assert {p["task"] for p in parameters} == {task_name(task) for task in RELEASE_UPDATE_TASKS}
    assert {p["pipeline"] for p in parameters} == {"release-update"}
    assert all(p["state.$"] == "$" and "Payload" not in p for p in parameters)
    assert {s["Resource"] for s in (asl["States"][n] for n in TASK_STATES)} == {"${PipelineTaskFunctionArn}"}

def test_choice_has_default_and_no_retry(asl):
    choice = asl["States"]["ChooseAction"]
    assert choice["Default"] == "RecordKeep"
    assert "Retry" not in choice and "Catch" not in choice and "End" not in choice
    assert asl["States"]["RetireTutorials"]["Next"] == "Succeeded"      # RETIRE 不經 PublishBatch
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/test_release_asl.py -q` 確認紅燈。** 預期 FAIL：`infra/stepfunctions/release-update/v1.json` 尚未存在。
- [ ] **Step 3：建立 §6 的 ASL 與 CDK 資源**

```python
# infra/training_kb_stack.py：沿用 Phase 41 建好的 task_fn 與 log_group，不再建第二個 Lambda
release_machine = sfn.StateMachine(
    self, "ReleaseUpdate", state_machine_name="training-kb-release-update",
    state_machine_type=sfn.StateMachineType.STANDARD,
    definition_body=sfn.DefinitionBody.from_file("infra/stepfunctions/release-update/v1.json"),
    definition_substitutions={"PipelineTaskFunctionArn": task_fn.function_arn},
    logs=sfn.LogOptions(destination=log_group, level=sfn.LogLevel.ALL),
    timeout=Duration.minutes(15),
)
task_fn.grant_invoke(release_machine)        # 只授權這一支函式，不給萬用字元
release_machine.grant_start_execution(webhook_fn)   # Phase 30 的 webhook 收到 Release 事件要能啟動這條流程
release_machine.grant_start_execution(import_fn)    # Phase 42 的受控匯入走同一條流程（Phase 60 IAM 核對表：兩條 state machine）
```

ASL 的 `RETRY`／`CATCH` 直接引用 Phase 29 的常數產生（`from training_kb.pipelines.asl import CATCH, RETRY, assert_safe_asl, task_state`），不在本檔另寫一份字面值；若 Phase 29 還停在單一 retrier，**先回頭改 Phase 29**（D-53），不要在本 Phase 放寬檢查。

- [ ] **Step 4：存快照、合成並檢查**

```bash
uv run pytest tests/unit/test_release_asl.py -q
cdk synth --quiet
```

`cdk` 是 Node.js 套件，指令**不加** `uv run`（00A §3.1、D-22）。預期：測試 PASS；template 中恰有一個新增的 `AWS::StepFunctions::StateMachine`（`StateMachineType: STANDARD`、`StateMachineName: training-kb-release-update`），沒有新的 `AWS::Lambda::Function`，也沒有第四條 pipeline。刪掉任何一個 `Catch` 後測試必須轉紅。若 Phase 09／41 的 CDK 環境尚未建立，先完成前置再跑，不把目前缺指令寫成已通過。

- [ ] **Step 5：提交** `git add infra/stepfunctions/release-update/v1.json infra/training_kb_stack.py tests/unit/test_release_asl.py`，再 `git commit -m "feat(infra): 建立 release-update 流程定義"`。

### Task 3：串接三個分支並完成雲端驗收

- [ ] **Step 1：建立失敗測試**（`tests/unit/test_release_asl.py` 同檔，本機序列部分）

```python
ORDER = ["locate_feature", "find_steps", "safety_net", "prepare_update",
         "publish_batch", "update_aliases", "retire"]

def test_release_update_task_order_and_names():
    assert [task_name(task) for task in RELEASE_UPDATE_TASKS] == ORDER

def test_zero_hits_ends_as_keep(local_deps, keep_state):
    result = run_release_update(keep_state, local_deps)          # 反查零命中且 safety_net 零確認
    assert (result["action"], result["prepared_version_ids"]) == ("KEEP", [])
    assert local_deps.repository.published_version_ids == []

def test_renamed_run_keeps_state_small(local_deps, renamed_state):
    result = run_release_update(renamed_state, local_deps)
    assert (result["action"], result["prepared_version_ids"]) == ("UPDATE", ["prepare-meeting@v3"])
    assert set(result) <= set(RELEASE_STATE_FIELDS)              # 沒有全文、evidence 或向量
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/test_release_asl.py -q` 確認紅燈。** 預期 FAIL，訊號包含 `cannot import name 'RELEASE_UPDATE_TASKS'`。
- [ ] **Step 3：建立最小實作**

```python
RELEASE_STATE_FIELDS = ("operation_id", "project_id", "input_ref", "release_id", "feature_id",
                        "action", "hit_refs", "prepared_version_ids", "publish_request_ref",
                        "alias_update", "result_ref")

def task_prepare_update(state, deps):
    if state.get("action") != "UPDATE":
        return dict(state)
    repository = deps.need_repository()
    plans = prepare_update(_load_release(state, repository), _hits(state), repository=repository,
                           writer=deps.need_writer(), operations=deps.operations,
                           operation_id=str(state["operation_id"]))
    return {**state, "prepared_version_ids": [plan.version_id for plan in plans]}

RELEASE_UPDATE_TASKS = (task_locate_feature, task_find_steps, task_safety_net,
                        task_prepare_update, task_publish_batch, task_update_aliases, task_retire)
_TASK_BY_NAME = {task_name(task): task for task in RELEASE_UPDATE_TASKS}
_DEPS: "Deps | None" = None

def run_release_update(state, deps):
    return run_sequence("release-update", state, RELEASE_UPDATE_TASKS, deps)

def release_update_handler(event, context):
    global _DEPS
    task = _TASK_BY_NAME.get(str(event.get("task")))
    if task is None:
        raise PermanentError(f"release-update 沒有名為 {event.get('task')!r} 的 task")
    if _DEPS is None:
        _DEPS = build_deps(load_settings(os.environ))
    return task(dict(event.get("state") or {}), _DEPS)
```

`task_prepare_update` 傳進去的是**這次 Release 的** `operation_id`；命中多篇教學時，[Phase 51](51-Phase51-Release-UPDATE精準改寫.md) 的 `prepare_update` 會在內部替每篇各開一筆 `op-release-update-<release_id>--<slug>` 子 operation 去配版號（00A D-59：`allocate_version` 以 `operation_id` 為唯一鍵，一個 operation 只對應一篇教學的一個版本），所以本 Phase **不**自己拆 operation，也不改傳別的 ID；`state` 仍然只留 `prepared_version_ids` 這一個小清單。

其餘六個 task 照同一形狀：先檢查前置條件，不適用就 `return dict(state)`，適用才呼叫 Phase 49–51 或 Phase 25 的函式，再把小型結果併回 state。`task_safety_net` 在直接反查為零或 `needs_safety_net(...)` 成立時才呼叫 Phase 50 的 `safety_net`，最後決定 `action`：`removed` → `RETIRE`；有命中且 `renamed`／`changed` → `UPDATE`；其餘 → `KEEP`（F18）。`task_publish_batch` 把 `prepared_version_ids` 包成一個 `PublishRequest` 交 `Publisher.prepare/inspect/commit`，整批全有或全無（F49）。`RELEASE_UPDATE_TASKS` 的順序是本機序列版本，雲端由 `ChooseAction` 跳過不適用的節點，兩邊語意相同。handler 不寫 try／except：`TransientError` 要讓 Retry 抓到，`PermanentError` 要讓 Catch 抓到。

- [ ] **Step 4：部署、跑 S5 主案例並注入故障**

```bash
cdk deploy TrainingKbApp --require-approval never
aws stepfunctions start-execution --state-machine-arn "$TKB_RELEASE_SM_ARN" --name "op-release-r_42" \
  --input '{"operation_id":"op-release-r_42","project_id":"demo","input_ref":"operations/op-release-r_42/release.json"}'
aws stepfunctions get-execution-history --execution-arn "$ARN" --max-results 200 \
  --query "events[?type=='TaskStateEntered'].stateEnteredEventDetails.name" --output text
diff <(aws s3 cp s3://<bucket>/tutorials/prepare-meeting/v2.md -) \
     <(aws s3 cp s3://<bucket>/tutorials/prepare-meeting/v3.md -)
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_release_update_state_machine.py -q
```

預期：`diff` 只出現第 3 步那兩行，B、C 沒有 `v2.md`；依 §6 證據表逐列保存輸出。接著讓 `PublishBatch` 必定丟 `TransientError` 後換 execution name 重跑：執行以 `FAILED` 結束、終點是 `PipelineFailed`、A 的 `current_version` 仍是 v2、公開頁仍是舊內容；移除故障後以**同一個** `operation_id` 重送，取回同一個 `prepare-meeting@v3`，不得出現 v4。

- [ ] **Step 5：保存證據並提交**

若 O3 協定無法保證「整批舊或整批新」，本 Phase 停在 FAIL，保留限制與決策出口，不新增 CloudFront、公開讀取 API，也不放寬 F49；O2／O5／O6 任一未通過時整個雲端驗收記為 BLOCKED。把兩個 execution ARN 與 §6 證據表寫進證據索引後，`git add tests/integration/test_release_update_state_machine.py src/training_kb/pipelines/release.py`，再 `git commit -m "test(release): 驗收 release-update 雲端流程"`。

## 8. 驗收矩陣

| 路徑 | 刺激 | 預期資料結果 |
|---|---|---|
| Happy | `r_42` renamed 命中 A 第 3 步 | A 切到 v3 且只有第 3 步不同；B、C 無新版；`FEATURE#Prepare` 的 PK 不變、name 變 Prepare。 |
| Happy | `kind=removed` 命中 A | A `status=retired`、`successor` 依 `successors.json`；歷史原文保留；`retire.json` 記下這一筆。 |
| Boundary | removed 但維護者未指定 successor | 仍完成退役，`successor` 為 `None`（F19）。 |
| Boundary | 零命中且 safety_net 零確認，或只命中歷史／未發布版步驟 | `action="KEEP"`，走 `RecordKeep`，執行 `SUCCEEDED` 且 `prepared_version_ids` 為空（F17、F18）。 |
| Failure | 任一 Task 的 Retry 耗盡 | execution `FAILED`，終點 `PipelineFailed`，零新版本公開（F49）。 |
| Failure | alias 撞名 | `UpdateAliases` 以 `PermanentError` 失敗；不降級成 KEEP（D07）。 |
| Idempotency | 同 `operation_id` 重送 | 同一個 `version_id`，沒有 v4，`retire.json` 不重寫，沒有重複退役。 |

人工驗收：在 Step Functions console 打開一個成功與一個失敗執行，逐一檢視每個 Task 的輸入輸出；再用瀏覽器打開 A、B、C 的公開頁與 A 的退役頁，確認退役頁顯示過期說明、原文與後繼連結，且不能送出新回饋。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| Choice 被加上 Retry 後 synth 失敗，或零命中時執行報錯 | 誤以為所有節點都要 Retry；Choice 缺 `Default` | 只有 Task／Parallel／Map 支援 Retry；補 `RecordKeep`，KEEP 是合法結果不是錯誤。 |
| Retry 永遠沒命中 | `ErrorEquals` 寫成 `TrainingKB.TransientError` | 改回 Phase 29 的 `RETRY`（`TransientError` 加 Lambda 服務層那條，D-53），並用 `get-execution-history` 實證。 |
| 部署出現第二個 Lambda | 每條 pipeline 各建一支函式 | 只用 Phase 41 的 `training-kb-pipeline-task`，state machine 才叫 `training-kb-release-update`（D-23）。 |
| Catch 之後走到 `Succeeded`，或 A 已公開但第二篇失敗 | 把失敗包成回傳值；在分支內逐篇 publish | Catch 必須到 `Fail`；整組交 Phase 25 一次提交，整次失敗且不發布（F49）。 |
| 退役教學仍收得到新回饋 | 沒呼叫 Phase 26 的檢查 | 回 Phase 26／42 補 `assert_accepts_feedback`。 |
| successor 由 PR 內容決定 | 把 evidence 當設定 | 只讀維護者寫的 `successors.json`（F54）。 |
| ASL 快照被覆寫 | 沒用條件寫入 | 走 `save_asl_snapshot`（內部 `if_none_match=True`）；改內容要升 `v2.json`。 |

## 10. 來源與 Rule 對照

- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature)
  - Rule 9「kind 為 removed 的改版動作為 RETIRE」（primary）→ `tests/unit/test_release_retire.py::test_removed_retires_each_hit_tutorial` 與 ASL `ChooseAction` 的 `RETIRE` 分支直接斷言。
  - Rule 12「未引用改版 Feature 的教學維持 KEEP」→ 相關（primary Phase 50）：本 Phase 在流程層再驗一次，§8 Happy 案例斷言 B、C 的 `current_version` 不變、`action="KEEP"` 走 `RecordKeep`。
  - Rule 16「RETIRE 將受影響教學標記為過期」→ 相關（primary Phase 26）：本 Phase 只在 `release-update` 流程中呼叫 `retire_tutorial`，`status == "retired"` 的權威斷言在 `tests/unit/test_retire_tutorial.py`。
  - Rule 17「RETIRE 的教學導向後繼 Tutorial」→ 相關（primary Phase 26）：本 Phase 斷言 successor 只來自維護者的 `successors.json`，未指定時為 `None`（F19、F54）。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature)
  - Rule 2「教學 pipeline 依 Step Functions 預定義節點執行」→ 相關（primary Phase 29）：`test_asl_task_names_match_python_tasks` 在本條 pipeline 再驗固定節點名稱。
  - Rule 6「每個 Step Functions Task 設定 Retry」、Rule 7「每個 Step Functions Task 設定 Catch」→ 相關（primary Phase 29）：`test_every_task_has_the_shared_retry_and_catch` 逐一斷言七個 Task。
  - Rule 10「Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json`」→ 相關（primary Phase 29）：Task 2 Step 4 用 `save_asl_snapshot` 的條件寫入取得同一份 bytes。
- Supporting：F17（只處理目前已發布版本）、F18（未命中即 KEEP）、F19／F54（successor 由維護者選定，沒有也完成退役）、F45（呼叫數含 retry）、F49（整次失敗不發布）、D07（alias 撞名拒絕）、D21（資料狀態只用 `retired`）。設計 §8.4（退役畫面與資料）、§16 S5（PR #42 只改 A 第 3 步、removed 呈現退役、B 與 C 不變）。
- [Step Functions 錯誤處理](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)：`Retry`／`Catch` 只存在於 `Task`、`Parallel`、`Map`；`States.ALL` 必須單獨且放最後，抓不到 `States.Runtime` 與 `States.DataLimitExceeded`。[Choice 節點](https://docs.aws.amazon.com/step-functions/latest/dg/state-choice.html)：`Choices` 必填、沒有相符規則又沒有 `Default` 時執行會報錯，Choice 不支援 `End`。
- [Lambda 整合](https://docs.aws.amazon.com/step-functions/latest/dg/connect-lambda.html)：直接函式 ARN 的 task result 就是函式輸出，沒有 `Payload` 外層。[StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)：同名執行的冪等有狀態與保留期限制，`ExecutionAlreadyExists` 不能直接當成功，仍要查 operation 紀錄。

## 11. 完成清單

- [ ] `retire_for_release`、`RELEASE_UPDATE_TASKS`、`run_release_update`、`release_update_handler` 的名稱與簽名符合本文件與 00A；handler 在 `pipelines/release.py`（D-25）。
- [ ] removed 分支對每篇命中教學退役，successor 只來自維護者的 `successors.json`，未指定仍完成退役；`Retire` task 寫出 `operations/<operation_id>/retire.json`。
- [ ] `infra/stepfunctions/release-update/v1.json` 的七個 Task 都用 `${PipelineTaskFunctionArn}`、`Parameters` 帶 `pipeline`／`task`／`state.$`，Retry 是 Phase 29 的兩個 retrier、Catch 導向 `PipelineFailed`，Choice 有 `Default`，RETIRE 分支不經 `PublishBatch`。
- [ ] `training-kb-release-update` 只授權給 `training-kb-webhook` 與 `training-kb-import` 兩支函式啟動（`grant_start_execution`），對齊 Phase 60 的 IAM 核對表。
- [ ] `task_prepare_update` 只傳這次 Release 的 `operation_id`，per-slug 子 operation 由 Phase 51 的 `prepare_update` 內部產生（D-59），本 Phase 沒有第二份取號邏輯。
- [ ] state machine 名為 `training-kb-release-update`、沒有新增第二個 Lambda、`cdk` 指令沒有加 `uv run`；ASL 快照經 `save_asl_snapshot` 條件寫入 `stepfunctions/release-update/v1.json`，不同內容不覆寫。
- [ ] 雲端驗收保存成功與失敗各一個 execution ARN 並附 §6 證據表每一列；A 只改第 3 步且第 1、2、4 步逐字相同，B、C 無新版，歷史或未發布步驟不觸發改寫。
- [ ] REL Rule 9 有 primary assertion；REL Rule 12／16／17 與 RUN Rule 2／6／7／10 寫成「相關」並指出 primary Phase（50、26、29）；O2／O3／O5／O6 任一未通過時雲端驗收標為 BLOCKED，沒有宣稱流程已完成或已核定。
