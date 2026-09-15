# Phase 52：Release RETIRE 與流程驗收實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **（a）已存在、直接重用（file:function）**
> - `src/training_kb/pipelines/asl.py`：`RETRY`（**已經是 D-53 的兩條 retrier tuple**）、`CATCH`、`FAIL_STATE_NAME = "PipelineFailed"`、`TASK_TIMEOUT_SECONDS = 120`、`task_state(resource_arn, next_state)`、`assert_safe_asl`（**已檢查 Choice 必須有 `Default`**、Task 前兩條 retrier 逐字相同、`Catch` 單一 `States.ALL` 導向同層 `Fail`）、`canonical_json`、`save_asl_snapshot(repository, pipeline, number, body) -> str`（同 bytes 冪等、不同 bytes 丟 `PermanentError`）、`ASL_LOCAL_PATH = "infra/stepfunctions/{pipeline}/v{number}.json"`、`ASL_SNAPSHOT_KEY = "stepfunctions/{pipeline}/v{number}.json"`。
> - `src/training_kb/pipelines/common.py`：`Deps(operations, now, repository=None, writer=None, settings=None)` 與 `need_repository`／`need_writer`／`need_settings`、`run_sequence(pipeline, payload, tasks, deps)`（失敗時 `operations.fail(...)` 後**原樣 re-raise**）、`PIPELINE_NAMES`。
> - `src/training_kb/content.py:retire_tutorial(slug, *, reason, successor, repository, now) -> Tutorial`（**在 `content.py`，不是 `publishing.py`**；只改 `status`／`successor` 兩個欄位、`successor` 只在目前為空時寫入、revision 不符轉 `TransientError`、`reason`／`now` 只驗證不寫 item）、`resolve_successor(slug, successor, *, repository)`、`RETIRED_NOTICE`、`parse_version_id`。
> - `src/training_kb/publishing.py`：`Publisher(repository, renderer, operations)` 與 `prepare`／`inspect`／`commit`、`PublishRequest(version_ids, operation_id)`、`tutorial_index_key(slug)`、`Publisher._write_tutorial_index(slug)`（用 `list_versions_of_tutorial` 重建，走 `_put_index` → `_put_public_object(..., if_none_match=False)`，**索引頁可覆寫**）。
> - `src/training_kb/site.py:SiteRenderer.render_tutorial_index(tutorial, versions)` — **退役區塊與後繼連結已於修正波實作（commit `f1ef75a`）**，`_retired_block` 依 `Tutorial.status`／`successor` 產生。
> - `src/training_kb/ingress.py:validate_release`／`operation_id_for`／`execution_name`、`src/training_kb/keys.py:operation_ref`、`src/training_kb/clock.py:to_iso`／`now_utc`、`src/training_kb/models.py:ReleaseKind.REMOVED`／`TutorialStatus.RETIRED`。
>
> **（b）因上一批裁決／實作而修正的點**
> 1. **§4 的兩個 infra 檔目前都不存在**：`infra/` 只有 `__init__.py`、`app.py`、`training_kb_data_stack.py`、`scripts/`。`infra/training_kb_stack.py` 與 `infra/stepfunctions/` 目錄**由 P41 建立**（COMMON.md R2、00A D-23）；本 Phase 只追加第二條 state machine 與 `infra/stepfunctions/release-update/v1.json`。開工前先確認 P41 已提交。
> 2. **`task_name`／`build_deps`／`pipeline_task_handler` 目前都不存在**（`pipelines/common.py` 只有 `Deps`／`run_sequence`／`PIPELINE_NAMES`），owner 是 **P41**（00A §6.9、D-24）。本 Phase 不得自己補一份。
> 3. **`RETRY` 已經是兩條 retrier**（`pipelines/asl.py:33`，D-53 已落地）。§7 Task 2 Step 3 的「若 Phase 29 還停在單一 retrier，先回頭改 Phase 29」已成為歷史備註，不需要執行。`assert_safe_asl` 也已經檢查 `Choice` 的 `Default`，所以 §7 的 `test_choice_has_default_and_no_retry` 是額外保險而非唯一防線。
> 4. §7 的 `TimeoutSeconds` 與 Fail state 名稱請 **import 常數**（`TASK_TIMEOUT_SECONDS`、`FAIL_STATE_NAME`），不要在測試裡硬寫 `120` 與 `"PipelineFailed"`（與 §11「不另寫一份字面值」同一個理由）。
> 5. **`cdk` 指令要照 COMMON.md 改寫**：本機互動 shell 把 `node` 定成會拒絕的 function，**一律 `command npx aws-cdk@2 <子命令>`**，並帶 `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1`；`--outputs-file` 指到 scratchpad，**不提交 `cdk.out/`**。全案固定 `us-east-1`（`aws configure` 預設是 ap-northeast-1，所以每條 `aws` CLI 都要 `--region us-east-1`）。
> 6. §7 Task 3 Step 4 寫 `cdk deploy TrainingKbApp`：**stack id 以 P41 實際建立的為準**（目前已部署的只有 `TrainingKbData`）。deploy 前先看 `infra/app.py` 裡 P41 加的 stack id，不要照抄一個不存在的名字。
> 7. **D-83 要在本 Phase 寫程式**（00A D-83、上一批 REP §8）：`retire_tutorial` 之後要呼叫 `Publisher` **重寫該篇教學索引頁**（只有索引頁，不重發版本頁）。§7 Task 1 已補上 **Step 3b** 明確步驟，§8 驗收矩陣與 §11 完成清單各補一列。
> 8. `retire_for_release` 的實作片段用 `release.kind != ReleaseKind.REMOVED` — 正確（`ReleaseKind` 是 `StrEnum`，與字串也相等，但用 enum 比較較清楚）。`successor_by_slug.get(slug)` 回 `None` 時 `retire_tutorial` 照常退役（F19）——與 `content.py` 現況一致。
> 9. §5 Consumes 的 `retire_tutorial(...)` 標「Phase 26」正確，但模組路徑是 **`training_kb.content`**，不是 `publishing`。
>
> **（c）gate 現況對本 Phase 的影響**（COMMON.md §2）——**本 Phase 是 G4 唯一真的上 AWS 的 Phase（R1）**
> - **O6 尚未核定 `github.com/pull_request`**（`tests/fixtures/o6/approved-sources.json` 該列 `approved_by`／`approved_at` 皆為空字串；`tests/integration/test_o6_github_mapping.py`、`test_release_extraction.py`、`test_adapter_fixtures.py`、`test_rote_commit.py` 都有 `xfail(strict=True)` 站崗）→ **Release 事件走不進 Rote／webhook 路徑**。所以雲端驗收**不能**從 GitHub webhook 觸發，只能用 `aws stepfunctions start-execution` 直接餵 §2 那三欄 input；而且 `operation_id` 對應的 **operation ledger（`OPS#` item）與 `operations/<op>/release.json` 必須先手動備好**，否則 `run_sequence`／`allocate_version` 會在第一步就 `CoordinationError`。這條 webhook 路徑記 **BLOCKED**，附 `approved-sources.json` 的原文，不得補臨時 mapping、不得改那個 fixture。
> - **O5 BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`：Titan／Claude 都 `ValidationException: Operation not allowed`）→ 真實 AWS 執行時，**`LocateFeature` 的語意層、`SafetyNet`、`PrepareUpdate` 三個需要模型的節點會走 `PermanentError → Catch → PipelineFailed`**。那是**要保存的 BLOCKED 證據**（execution ARN + `get-execution-history` 裡的 `TaskFailed` 原文），不是 bug，**也不是通過**。能真的跑完的雲端路徑只有「字串層命中 + 零命中 KEEP」與「removed → RETIRE」。
> - **O3 FAIL**（`docs/plan/report/o3-20260914t181109z.md`）→ `PublishBatch` 依協定 A 實作與驗證，跑到發布切點就把觀察到的結果原樣記錄；**不得宣稱 O3 PASS、不得放寬 F49**，決策出口仍在維護者手上（D-80）。
> - **O2 PASS**（P11）：同 `operation_id` 重送取回同一 `version_id` 可以依賴。
> - 前置：P01–P40 完成；**同批的 P41（Lambda／stack／`pipeline_task_handler`）、P49／P50／P51 必須全部先落地**。
>
> **（d）適用的 controller 裁決**：R1（真的部署與執行、做不到的標 BLOCKED 附錯誤原文）、R2（沿用 P41 的相依 layer／bundling，**不各自再做一套**）、R3（`pipelines/release.py`、`infra/training_kb_stack.py` 共用檔只 Edit、只 `git add` 自己的檔）、R5、R6、R7（`docs/plan/report/phases/2026-09-14-Phase52-REP.md`）、R8（**絕不 push**）、R10、R11（最小權限、不把憑證寫進 repo）。
>
> **實作波次**：W1（P49 ∥ P50）→ W2（P51）→ **W3（P52，本 Phase）**。

> **實作後修正（2026-09-14，Phase 52 實作者）——本計畫選擇：**
>
> 1. **雲端 KEEP 撞 O5，不是可實證路徑。** 零命中必然讓 `task_safety_net` 呼叫 Phase 50 的
>    `safety_net`，而它第一件事就是 `writer.embed(...)`，所以 §6／§8 原本標「可實證」的 KEEP
>    那一列改標 BLOCKED 並附實際執行 `op-release-p52k20260915` 的原文。**雲端唯一跑得到
>    `SUCCEEDED` 的是 RETIRE**（字串層命中 → `needs_safety_net` 為 `False` → `retire_tutorial`
>    → 索引頁重寫，全程零模型）。本機／moto 的 KEEP 仍然必做且已綠。
> 2. **`removed` 即使零命中也回 `RETIRE`**（`_release_action`）：REL Rule 9 是依 `kind` 決定
>    動作，不是依命中數；零命中時退役零篇、`retire.json` 是空陣列，追溯得到「這則 removed
>    沒有命中任何教學」。
> 3. **`task_locate_feature` 順手把 `hit_refs` 與 `prepared_version_ids` 設成空值。** 雲端的
>    KEEP 與 RETIRE 兩條分支都跳過 `PrepareUpdate`，在第一個節點給定初值，三條分支的輸出形狀
>    才一致（§2 要求成功輸出列得出這幾個欄位）。
> 4. **不對 `training-kb-import` 再呼叫一次 `grant_start_execution`。** Phase 42 已用名稱組
>    ARN 一次授權 `ticket-analysis` 與 `release-update`（controller 2026-09-14），本 Phase 只
>    grant webhook，並補上 webhook 對 `release-update` execution 的 `states:DescribeExecution`
>    （P41 `_grant_execution_lookup` 留的缺口 3 第二半）。
> 5. **測試檔落點**：ASL 結構與本機三分支序列在 `tests/unit/test_release_asl.py`（文件 §4 指定
>    的路徑）；CDK `Template` 斷言另開 `tests/unit/infra/test_release_machine.py`，因為共用的
>    `fake_layer` fixture 在 `tests/unit/infra/conftest.py`，`tests/unit/` 吃不到，複製一份會分岔。
> 6. **順手改了兩處別人的 `resource_count_is`**（P41 `test_ticket_asl.py` 的 state machine 與
>    log group 數量、P54 `test_analytics_stack.py` 的 state machine 數量）：本 Phase 與 P48 各加
>    一條 state machine 與一個 log group，固定數量的斷言必然轉紅。改成包含關係／名稱判斷，
>    與同一支檔既有的「Lambda 用包含關係」註解同一個理由。
> 7. **UPDATE 分支的本機全序列測試不做**（改用 task 層與既有 Phase 的測試涵蓋）：
>    `task_publish_batch` 要走 `Repository.transact_write`，記憶體假表沒有 `meta.client`，
>    做不到；`prepare_update` 由 P51 `tests/unit/test_release_update.py`、整批發布由 P25
>    `tests/integration/test_batch_publish_cutpoints.py`（moto）涵蓋，雲端則被 O5／O3 擋住。
>    本 Phase 在 `tests/unit/test_release_retire.py` 斷言 `task_safety_net` 選 UPDATE 且零模型
>    呼叫，並在 `tests/unit/test_release_asl.py` 斷言三個 UPDATE 專用 Task 在別的分支是 no-op。

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
- O1–O7 狀態（現況核對 2026-09-14，見 COMMON.md §2）：**O2 PASS**；**O3 FAIL** → 停止公開發布路徑、保留可追溯 FAIL，不得放寬 F49；**O5 BLOCKED** → 三個需要模型的節點在真實 AWS 會走 Catch，保存 BLOCKED 證據；**O6 尚未核定 `github.com/pull_request`** → Release 事件走不進 webhook／Rote，雲端驗收改用 `start-execution` 直接餵 input。**雲端驗收因此分成「可實證路徑」與「BLOCKED 路徑」兩欄（§6、§8），不得把文件、CDK synth 或 mock 綠燈寫成雲端流程已通過。**
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
| 建立 | `infra/stepfunctions/release-update/v1.json` | 固定 Standard ASL 定義（00A D-14；路徑樣板是 `asl.ASL_LOCAL_PATH`）。 |
| 修改 | `infra/training_kb_stack.py` | 第二條 state machine 與最小執行角色（Lambda 與 log group 沿用 Phase 41 的）。（現況核對 2026-09-14：這支檔與 `infra/stepfunctions/` 目錄**目前都不存在**，由 P41 建立；開工前先確認 P41 已提交。） |
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
retire_tutorial(slug, *, reason, successor, repository, now) -> Tutorial         # Phase 26，在 content.py
Publisher._write_tutorial_index(slug) -> None ; SiteRenderer.render_tutorial_index  # Phase 24/26，D-83 索引重寫
Publisher.prepare / inspect / commit ; PublishRequest(version_ids, operation_id) # Phase 24/25
run_sequence(pipeline, payload, tasks, deps) -> dict ; RETRY / CATCH / task_state /
    assert_safe_asl / canonical_json / save_asl_snapshot /
    FAIL_STATE_NAME / TASK_TIMEOUT_SECONDS / ASL_LOCAL_PATH / ASL_SNAPSHOT_KEY   # Phase 29
task_name(task) / build_deps(settings) / pipeline_task_handler(event, context)   # Phase 41（現況：尚未存在，等 P41）
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

雲端驗收要留下的證據格式如下。這是**預計取得**的清單，尚未執行。**所有 `aws` CLI 一律帶 `--region us-east-1`**（COMMON.md §1：`aws configure` 預設是 ap-northeast-1）。現況核對 2026-09-14：依 COMMON.md §2 拆成**可實證路徑**與 **BLOCKED 路徑**兩張表。

**可實證路徑（本 Phase 一定要做到並保存證據）**

| 證據 | 取得方式 | 必須看到 |
|---|---|---|
| ASL 快照 | `aws s3api head-object --region us-east-1 --bucket <content bucket> --key stepfunctions/release-update/v1.json` | 與部署中的 definition 相同 bytes；同內容重送冪等（`save_asl_snapshot` 撞 key 會先比對 bytes），改內容要升成 `v2.json`。 |
| state machine 存在與定義 | `aws stepfunctions describe-state-machine --region us-east-1 --state-machine-arn "$TKB_RELEASE_SM_ARN"` | `name` 是 `training-kb-release-update`、`type` 是 `STANDARD`、`definition` 的七個 `Resource` 都是 P41 那支共用 Lambda 的 ARN。 |
| ~~KEEP 路徑執行~~ → **移到 BLOCKED 表**（實作後修正 2026-09-14） | `start-execution`（零命中的 Release input） | **取不到 `SUCCEEDED`**：零命中必然讓 `task_safety_net` 呼叫 Phase 50 的 `safety_net`，而它第一件事就是 `writer.embed(...)` → Titan → **O5** `ValidationException`。原本這一列寫的前提（「`locate_feature` 在字串層命中或回 `None` 就不進語意層」）只擋得住定位那一層，擋不住補漏那一層。實際執行 `op-release-p52k20260915` 的原文見 BLOCKED 表。本機／moto 的 KEEP 仍然必做且已綠（`tests/unit/test_release_asl.py::test_zero_hits_ends_as_keep`）。 |
| RETIRE 路徑執行 | `start-execution`（`kind=removed`，`operations/<op>/successors.json` 先放好）→ `get-execution-history` | `SUCCEEDED`；終點 `Succeeded`；`RetireTutorials` **不經** `PublishBatch`。 |
| 退役資料結果 | `aws dynamodb get-item --region us-east-1 --consistent-read --table-name training_kb --key '{"PK":{"S":"TUTORIAL#prepare-meeting"},"SK":{"S":"META"}}'` | `status=retired`、`successor` 依 `successors.json`；`current_version`、`VERSION`／`STEP`、S3 `.md`／`.diff` 全部保留。 |
| 退役紀錄 | `aws s3 cp s3://<bucket>/operations/<op>/retire.json -` | JSON 陣列，每篇一筆 `{"slug", "reason", "retired_at", "successor"}`；同 `operation_id` 重送內容不變。 |
| **退役索引頁（D-83）** | `aws s3 cp s3://<bucket>/site/tutorials/prepare-meeting/index.html -`（key 以 `tutorial_index_key(slug)` 為準） | 含 `RETIRED_NOTICE` 與後繼連結；版本清單仍列已發布版；**版本頁 `v2.html` 的 bytes 完全未變**。 |
| 失敗語意 | 注入 `TransientError` 後換 execution name 重跑 → `get-execution-history` | `FAILED`、終點 `PipelineFailed`、`Retry` 真的重試兩次（`TaskScheduled` 出現三次）；A 的 `current_version` 不變、`site/` 無新檔。 |
| 模型呼叫數 | 逐次 `CallTrace` 紀錄 | 與該次執行的 attempt 數相符，含 retry 與每個 embedding（F45）。 |

**BLOCKED 路徑（照跑、原樣記錄觀察到的結果，不得寫成通過）**

| 路徑 | 為什麼 blocked | 要保存什麼 |
|---|---|---|
| 從 GitHub webhook 觸發 release-update | **O6 未核定 `github.com/pull_request`**（`tests/fixtures/o6/approved-sources.json` 的 `approved_by` 為空） | `approved-sources.json` 該列原文 ＋ 「本 Phase 改用 `start-execution` 直接餵 input、operation ledger 先手動備好」的說明。**不得**補臨時 mapping、不得改那個 fixture。 |
| `LocateFeature` 語意層／`SafetyNet`（含**零命中的 KEEP**）／`PrepareUpdate` | **O5 BLOCKED**（Titan／Claude 都 `ValidationException: Operation not allowed`） | 執行 ARN ＋ `get-execution-history` 裡的 `error`／`cause` 原文（`PermanentError` → `Catch` → `PipelineFailed`）＋ `docs/plan/report/o5-20260915T030245Z.md`。**欄位是 `lambdaFunctionFailedEventDetails`，不是 `taskFailedEventDetails`**（直接函式 ARN，Phase 41 已實證）。這是 **BLOCKED 證據，不是 bug，也不是通過**。 |
| `PublishBatch` 的「整批舊或整批新」 | **O3 FAIL**（`docs/plan/report/o3-20260914t181109z.md`、D-80） | 跑到發布切點時觀察到的 DynamoDB 與 `site/` 實際狀態，原樣記錄；決策出口留給維護者。不得宣稱 O3 PASS、不得放寬 F49。 |
| A 切到 v3 的公開頁 `curl http://<bucket>.s3-website-<region>.amazonaws.com/site/tutorials/prepare-meeting/v3.html` | 需要 `PrepareUpdate`（O5）與 `PublishBatch`（O3）都成功 | 若因上兩列取不到，記 BLOCKED 並指向該列；不得用 moto 綠燈或本機渲染的 HTML 頂替。 |

## 7. TDD Tasks

### Task 1：removed 走 RETIRE，successor 只來自維護者

- [x] **Step 1：建立失敗測試**（`tests/unit/test_release_retire.py`）

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

- [x] **Step 2：執行 `uv run pytest tests/unit/test_release_retire.py -q` 確認紅燈。** 預期 FAIL，訊號包含 `cannot import name 'retire_for_release'`。
- [x] **Step 3：建立最小實作**

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

- [x] **Step 3b：退役之後重寫該篇的教學索引頁（00A D-83，本批必做）**

這是上一批最終 review 裁決、留給本 Phase 寫程式的事（`docs/plan/report/2026-09-14-Phase21-40實作-REP.md` §8、00A D-83）。背景：協定 A 下**已發布的版本頁不可覆寫**（`Publisher._version_problems` 擋已發布版、`_put_public_object` 會比對 bytes），所以退役提示寫不進既有的 `v<n>.html`。出口 c 是把提示掛在**可覆寫**的教學索引頁。

- renderer 那一半**已經完成**：`src/training_kb/site.py:SiteRenderer.render_tutorial_index` 已經輸出退役區塊與後繼連結（修正波 commit `f1ef75a`，`_retired_block` 讀 `Tutorial.status`／`successor`）。本 Phase **不改 renderer**。
- 本 Phase 要做的是「何時寫」：`task_retire` 在 `retire_for_release(...)` **回來之後**，對每一個退役成功的 slug 各呼叫一次 `Publisher._write_tutorial_index(slug)`。順序不可顛倒——索引頁的內容取自 `repository.get_tutorial(slug)`，`status` 還沒變成 `retired` 就寫不出退役區塊。
- **只寫索引頁**：不呼叫 `Publisher.prepare`／`inspect`／`commit`，不重發版本頁，不碰 `render_version_page`，不建立任何新版本。`_write_tutorial_index` 走 `_put_index` → `_put_public_object(..., if_none_match=False)`，本來就是可覆寫的投影。
- **本計畫選擇**：直接呼叫既有的 `Publisher._write_tutorial_index`（雖然是私有方法），**不**在本 Phase 複製一份索引渲染邏輯、也不為此改 `publishing.py` 的公開介面（兩份排序邏輯遲早分岔；ruff 的 `select` 只有 `E`／`F`／`I`／`UP`，不會擋私有存取）。若 P57 之後把它改成公開方法，本 Phase 只要改呼叫點。`Publisher` 由 `Publisher(repository, SiteRenderer(), operations)` 建出來（`renderer` 的實作 P57 才會換）。
- **`retire_tutorial` 自己仍然不寫任何 `site/` 物件**（D-83 明訂），寫入點只有這裡。

補兩個測試到 `tests/unit/test_release_retire.py`：

```python
def test_retire_rewrites_only_the_tutorial_index(repo, local_deps, retire_state):
    before = repo.get_object("site/tutorials/prepare-meeting/v2.html")
    task_retire(retire_state, local_deps)
    index = repo.get_object(tutorial_index_key("prepare-meeting")).decode("utf-8")
    assert RETIRED_NOTICE in index and "share-summary" in index
    assert repo.get_object("site/tutorials/prepare-meeting/v2.html") == before   # 版本頁 bytes 未變
    assert repo.published_version_ids == []                                      # 沒有新版本被發布

def test_index_rewrite_happens_after_status_is_retired(repo, local_deps, retire_state):
    task_retire(retire_state, local_deps)
    assert repo.get_tutorial("prepare-meeting").status == TutorialStatus.RETIRED
    assert 'class="tutorial-index"' in repo.get_object(
        tutorial_index_key("prepare-meeting")).decode("utf-8")
```

（公開 key 以 `publishing.tutorial_index_key(slug)` 為準，不要自己拼字串。）

- [x] **Step 4：跑 `uv run pytest tests/unit/test_release_retire.py -q` 確認綠燈。** 另補三個案例：`kind="renamed"` 呼叫本函式丟 `PermanentError`；退役後該篇既有版本與回饋仍可讀取（設計 §8.4）；同 `operation_id` 重送時 `retire.json` 內容不變且沒有第二次寫入。
- [x] **Step 5：提交** `git add src/training_kb/pipelines/release.py tests/unit/test_release_retire.py`，再 `git commit -m "feat(release): 依改版退役受影響教學"`。（只 `git add` 自己的檔案路徑，不用 `git add -A`；COMMON.md R3.3。）

### Task 2：建立 ASL 與 state machine，鎖定失敗語意

- [x] **Step 1：建立失敗測試**（`tests/unit/test_release_asl.py`）

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

- [x] **Step 2：執行 `uv run pytest tests/unit/test_release_asl.py -q` 確認紅燈。** 預期 FAIL：`infra/stepfunctions/release-update/v1.json` 尚未存在。
- [x] **Step 3：建立 §6 的 ASL 與 CDK 資源**

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

ASL 的 `RETRY`／`CATCH` 直接引用 Phase 29 的常數產生（`from training_kb.pipelines.asl import CATCH, FAIL_STATE_NAME, RETRY, TASK_TIMEOUT_SECONDS, assert_safe_asl, task_state`），不在本檔另寫一份字面值。（現況核對 2026-09-14：原寫「若 Phase 29 還停在單一 retrier，先回頭改 Phase 29」——**`RETRY` 已經是 D-53 的兩條 retrier tuple**（`pipelines/asl.py:33`），這句已成歷史備註，不需要執行；`assert_safe_asl` 也已經檢查 `Choice` 必須有 `Default`。）

- [x] **Step 4：存快照、合成並檢查**

```bash
uv run pytest tests/unit/test_release_asl.py -q
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet
```

`cdk` 是 Node.js 套件，指令**不加** `uv run`（00A §3.1、D-22）。（現況核對 2026-09-14，COMMON.md §1：本機互動 shell 把 `node` 定成會拒絕的 function，所以**一律用 `command npx aws-cdk@2 <子命令>`**，並帶 `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1`；`--outputs-file` 指到 scratchpad，**不要提交 `cdk.out/`**。`jsii` 在 `uv run pytest` 下正常，所以 `Template.from_stack` 的單元斷言可用。）預期：測試 PASS；template 中恰有一個新增的 `AWS::StepFunctions::StateMachine`（`StateMachineType: STANDARD`、`StateMachineName: training-kb-release-update`），沒有新的 `AWS::Lambda::Function`，也沒有第四條 pipeline。刪掉任何一個 `Catch` 後測試必須轉紅。若 Phase 09／41 的 CDK 環境尚未建立，先完成前置再跑，不把目前缺指令寫成已通過。

- [x] **Step 5：提交** `git add infra/stepfunctions/release-update/v1.json infra/training_kb_stack.py tests/unit/test_release_asl.py`，再 `git commit -m "feat(infra): 建立 release-update 流程定義"`。

### Task 3：串接三個分支並完成雲端驗收

- [x] **Step 1：建立失敗測試**（`tests/unit/test_release_asl.py` 同檔，本機序列部分）

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

- [x] **Step 2：執行 `uv run pytest tests/unit/test_release_asl.py -q` 確認紅燈。** 預期 FAIL，訊號包含 `cannot import name 'RELEASE_UPDATE_TASKS'`。
- [x] **Step 3：建立最小實作**

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

- [x] **Step 4：部署、跑 S5 主案例並注入故障**

```bash
# 0) 部署（stack id 以 P41 在 infra/app.py 建立的為準；COMMON.md §1）
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 \
  command npx aws-cdk@2 deploy <P41 的 stack id> --require-approval never \
  --outputs-file "$SCRATCH/cdk-outputs.json"

# 1) 先備好 operation ledger 與輸入（O6 未核定 pull_request，走不進 webhook，
#    所以 OPS# item 與 operations/<op>/release.json 必須先手動寫好）
aws s3 cp ./release-r_42.json s3://<bucket>/operations/op-release-r_42/release.json --region us-east-1
#    OPS# item 用一小段 uv run python 呼叫 OperationCoordinator.accept(AcceptOperation(...)) 寫入，
#    不要手拼 DynamoDB item（欄位形狀由 operations.py 的 codec 決定）。

# 2) 直接餵 input 啟動（不經 PipelineStarter／webhook）
aws stepfunctions start-execution --region us-east-1 --state-machine-arn "$TKB_RELEASE_SM_ARN" \
  --name "op-release-r_42" \
  --input '{"operation_id":"op-release-r_42","project_id":"demo","input_ref":"operations/op-release-r_42/release.json"}'

aws stepfunctions get-execution-history --region us-east-1 --execution-arn "$ARN" --max-results 200 \
  --query "events[?type=='TaskStateEntered'].stateEnteredEventDetails.name" --output text

# 3) 可實證的資料比對
diff <(aws s3 cp s3://<bucket>/tutorials/prepare-meeting/v2.md - --region us-east-1) \
     <(aws s3 cp s3://<bucket>/tutorials/prepare-meeting/v3.md - --region us-east-1)

TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_release_update_state_machine.py -q
```

（現況核對 2026-09-14：三處改寫——`cdk` 換成 `command npx aws-cdk@2` 並固定 `us-east-1`；stack id 不寫死 `TrainingKbApp`，以 P41 實際建立的為準；**加上第 1 步**，因為 **O6 未核定 `github.com/pull_request`**，Release 事件走不進 webhook／Rote，`operation_id` 對應的 `OPS#` 紀錄與 `release.json` 必須先手動備好，否則 `run_sequence` 第一步就 `CoordinationError`。）

預期（**照 §6 的兩張表分別記錄**）：

- **可實證**：RETIRE 與 KEEP 兩條路徑各一個 `SUCCEEDED` execution；`retire.json`、退役索引頁（D-83）、`status=retired` 與 `successor` 都對得上；注入 `TransientError` 後換 execution name 重跑，執行以 `FAILED` 結束、終點是 `PipelineFailed`、A 的 `current_version` 不變、`site/` 沒有新檔；移除故障後以**同一個** `operation_id` 重送，`retire.json` 不重寫、沒有重複退役。
- **BLOCKED**：`renamed` 主案例會在 `SafetyNet`／`PrepareUpdate` 撞 **O5**（`ValidationException: Operation not allowed` → `PermanentError` → Catch → `PipelineFailed`），所以上面第 3 步的 `diff`（`v3.md`）與 `PublishBatch` 的整批切換（**O3 FAIL**）**取不到**。把 execution ARN、`get-execution-history` 的 `TaskFailed` 原文與兩份 gate 報告路徑（`o5-20260915T030245Z.md`、`o3-20260914t181109z.md`）原樣存進證據索引，**不得**用 moto 綠燈或本機渲染頂替，也不得宣稱流程已通過。

- [x] **Step 5：保存證據並提交**

若 O3 協定無法保證「整批舊或整批新」，本 Phase 停在 FAIL，保留限制與決策出口，不新增 CloudFront、公開讀取 API，也不放寬 F49；O2／O5／O6 任一未通過時整個雲端驗收記為 BLOCKED。把兩個 execution ARN 與 §6 證據表寫進證據索引後，`git add tests/integration/test_release_update_state_machine.py src/training_kb/pipelines/release.py`，再 `git commit -m "test(release): 驗收 release-update 雲端流程"`。

## 8. 驗收矩陣

現況核對 2026-09-14（COMMON.md §2）：每一列都標明它在**本機／moto 單元測試**是可實證的，還是在**真實 AWS** 上被 gate 擋住。**本機那一欄全部都要做到**；真實 AWS 那一欄做不到的列 BLOCKED 並附錯誤原文。

| 路徑 | 刺激 | 預期資料結果 | 本機／moto | 真實 AWS |
|---|---|---|---|---|
| Happy | `kind=removed` 命中 A | A `status=retired`、`successor` 依 `successors.json`；歷史原文保留；`retire.json` 記下這一筆。 | ✅ 必做 | ✅ **可實證**（不需要模型） |
| Happy（D-83） | 同上 | A 的教學索引頁 `tutorial_index_key("prepare-meeting")` 被重寫，含 `RETIRED_NOTICE` 與後繼連結；**版本頁 bytes 未變**、沒有新版本被發布。 | ✅ 必做 | ✅ **可實證** |
| Boundary | removed 但維護者未指定 successor | 仍完成退役，`successor` 為 `None`（F19）。 | ✅ 必做 | ✅ 可實證 |
| Boundary | 零命中且 safety_net 零確認，或只命中歷史／未發布版步驟 | `action="KEEP"`，走 `RecordKeep`，執行 `SUCCEEDED` 且 `prepared_version_ids` 為空（F17、F18）。 | ✅ 必做（已綠） | ⛔ **BLOCKED：O5**（實作後修正 2026-09-14）——零命中必然觸發 `safety_net`，它的第一個動作就是 `embed`。證據 `op-release-p52k20260915` |
| Failure | 任一 Task 的 Retry 耗盡 | execution `FAILED`，終點 `PipelineFailed`，零新版本公開（F49）。 | ✅ 必做 | ✅ 可實證（注入 `TransientError`） |
| Idempotency | 同 `operation_id` 重送 | 同一個 `version_id`，沒有 v4，`retire.json` 不重寫，沒有重複退役。 | ✅ 必做 | ✅ 可實證（RETIRE／KEEP 這兩條） |
| Happy | `r_42` renamed 命中 A 第 3 步 | A 切到 v3 且只有第 3 步不同；B、C 無新版；`FEATURE#Prepare` 的 PK 不變、name 變 Prepare。 | ✅ 必做（假 writer） | ⛔ **BLOCKED**：`PrepareUpdate` 撞 **O5**、`PublishBatch` 撞 **O3 FAIL** |
| Failure | alias 撞名 | `UpdateAliases` 以 `PermanentError` 失敗；不降級成 KEEP（D07）。 | ✅ 必做 | ⛔ BLOCKED（走不到 `UpdateAliases`，它排在 `PublishBatch` 之後） |
| Entry | 由 GitHub `pull_request` webhook 觸發整條流程 | `training-kb-webhook` 啟動 `training-kb-release-update`。 | — | ⛔ **BLOCKED**：**O6 未核定 `github.com/pull_request`**；改用 `start-execution` 直接餵 input，operation ledger 先手動備好 |

人工驗收（分兩條路徑）：

- **可實證**：在 Step Functions console 打開一個成功（RETIRE 或 KEEP）與一個失敗（注入 `TransientError`）的執行，逐一檢視每個 Task 的輸入輸出；再用瀏覽器打開 A 的**教學索引頁**（D-83 重寫的那一頁），確認顯示過期說明與後繼連結；並確認退役後送新回饋會被 Phase 26 的 `assert_accepts_feedback` 擋下。不能只看測試顯示 PASS。
- **BLOCKED**：A 切到 v3 的版本頁 `site/tutorials/prepare-meeting/v3.html` 取不到（O5／O3），記 BLOCKED 並附 execution ARN 與 `TaskFailed` 原文。

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
| 退役後讀者看不到過期說明 | 只改了 DynamoDB，沒重寫教學索引頁 | 依 D-83 在 `retire_tutorial` 之後呼叫 `Publisher._write_tutorial_index(slug)`；**只有索引頁**，不重發版本頁（已發布版本頁的 bytes 不可覆寫）。 |
| 想把退役提示寫回 `v<n>.html` | 沒注意協定 A 下已發布版本頁不可覆寫 | 停止：`_version_problems` 會擋、`_put_public_object` 會比對 bytes；出口 c 就是索引頁（D-83）。 |
| 雲端驗收卡在 webhook 進不來 | 以為 Release 事件能從 GitHub webhook 觸發 | **O6 未核定 `github.com/pull_request`**：改用 `start-execution` 直接餵 input，`OPS#` 與 `release.json` 先手動備好；webhook 那條記 BLOCKED，不補臨時 mapping。 |

## 10. 來源與 Rule 對照

- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature)
  - Rule 9「kind 為 removed 的改版動作為 RETIRE」（primary）→ `tests/unit/test_release_retire.py::test_removed_retires_each_hit_tutorial` 與 ASL `ChooseAction` 的 `RETIRE` 分支直接斷言。
  - Rule 12「未引用改版 Feature 的教學維持 KEEP」→ 相關（primary Phase 50）：本 Phase 在流程層再驗一次，§8 Happy 案例斷言 B、C 的 `current_version` 不變、`action="KEEP"` 走 `RecordKeep`。
  - Rule 16「RETIRE 將受影響教學標記為過期」→ 相關（primary Phase 26）：本 Phase 只在 `release-update` 流程中呼叫 `retire_tutorial`，`status == "retired"` 的權威斷言在 `tests/unit/test_retire_tutorial.py`。**讀者真的看得到過期說明，靠的是本 Phase 的 D-83 索引頁重寫**（Task 1 Step 3b）——renderer 已於修正波完成（`f1ef75a`），寫入時機是本 Phase 的交付物。
  - Rule 17「RETIRE 的教學導向後繼 Tutorial」→ 相關（primary Phase 26）：本 Phase 斷言 successor 只來自維護者的 `successors.json`，未指定時為 `None`（F19、F54）。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature)
  - Rule 2「教學 pipeline 依 Step Functions 預定義節點執行」→ 相關（primary Phase 29）：`test_asl_task_names_match_python_tasks` 在本條 pipeline 再驗固定節點名稱。
  - Rule 6「每個 Step Functions Task 設定 Retry」、Rule 7「每個 Step Functions Task 設定 Catch」→ 相關（primary Phase 29）：`test_every_task_has_the_shared_retry_and_catch` 逐一斷言七個 Task。
  - Rule 10「Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json`」→ 相關（primary Phase 29）：Task 2 Step 4 用 `save_asl_snapshot` 的條件寫入取得同一份 bytes。
- Supporting：F17（只處理目前已發布版本）、F18（未命中即 KEEP）、F19／F54（successor 由維護者選定，沒有也完成退役）、F45（呼叫數含 retry）、F49（整次失敗不發布）、D07（alias 撞名拒絕）、D21（資料狀態只用 `retired`）。設計 §8.4（退役畫面與資料）、§16 S5（PR #42 只改 A 第 3 步、removed 呈現退役、B 與 C 不變）。
- [Step Functions 錯誤處理](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)：`Retry`／`Catch` 只存在於 `Task`、`Parallel`、`Map`；`States.ALL` 必須單獨且放最後，抓不到 `States.Runtime` 與 `States.DataLimitExceeded`。[Choice 節點](https://docs.aws.amazon.com/step-functions/latest/dg/state-choice.html)：`Choices` 必填、沒有相符規則又沒有 `Default` 時執行會報錯，Choice 不支援 `End`。
- [Lambda 整合](https://docs.aws.amazon.com/step-functions/latest/dg/connect-lambda.html)：直接函式 ARN 的 task result 就是函式輸出，沒有 `Payload` 外層。[StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)：同名執行的冪等有狀態與保留期限制，`ExecutionAlreadyExists` 不能直接當成功，仍要查 operation 紀錄。

## 11. 完成清單

- [x] `retire_for_release`、`RELEASE_UPDATE_TASKS`、`run_release_update`、`release_update_handler` 的名稱與簽名符合本文件與 00A；handler 在 `pipelines/release.py`（D-25）。
- [x] removed 分支對每篇命中教學退役，successor 只來自維護者的 `successors.json`，未指定仍完成退役；`Retire` task 寫出 `operations/<operation_id>/retire.json`。
- [x] `infra/stepfunctions/release-update/v1.json` 的七個 Task 都用 `${PipelineTaskFunctionArn}`、`Parameters` 帶 `pipeline`／`task`／`state.$`，Retry 是 Phase 29 的兩個 retrier、Catch 導向 `PipelineFailed`，Choice 有 `Default`，RETIRE 分支不經 `PublishBatch`。
- [x] `training-kb-release-update` 只授權給 `training-kb-webhook` 與 `training-kb-import` 兩支函式啟動（`grant_start_execution`），對齊 Phase 60 的 IAM 核對表。
- [x] `task_prepare_update` 只傳這次 Release 的 `operation_id`，per-slug 子 operation 由 Phase 51 的 `prepare_update` 內部產生（D-59），本 Phase 沒有第二份取號邏輯。
- [x] state machine 名為 `training-kb-release-update`、沒有新增第二個 Lambda、`cdk` 指令沒有加 `uv run`（用 `command npx aws-cdk@2`，帶 `AWS_REGION=us-east-1`，不提交 `cdk.out/`）；ASL 快照經 `save_asl_snapshot` 條件寫入 `stepfunctions/release-update/v1.json`，不同內容不覆寫。
- [x] **D-83：`task_retire` 在 `retire_for_release` 之後，對每個退役成功的 slug 呼叫 `Publisher._write_tutorial_index(slug)`；只重寫索引頁、不重發版本頁、不建立新版本，且版本頁 bytes 未變有直接 assertion。**
- [ ] 雲端驗收依 §6 的兩張表分別保存：**可實證路徑**（RETIRE／KEEP 各一個 `SUCCEEDED`、一個注入故障後的 `FAILED`、ASL 快照、`retire.json`、退役索引頁）與 **BLOCKED 路徑**（webhook 入口 O6、`SafetyNet`／`PrepareUpdate` O5、`PublishBatch` O3），每一列都附取得方式與原始輸出或錯誤原文。
  - **未完全達成的只有「KEEP 的 `SUCCEEDED`」**（實作後修正 2026-09-14）：零命中必然走 `safety_net` → `embed` → **O5**，所以雲端 KEEP 只留得到 BLOCKED 證據（`op-release-p52k20260915`）。其餘全部取得：RETIRE 一個 `SUCCEEDED`（`op-release-p52r20260915`）、重送冪等一個 `SUCCEEDED`、注入 `TransientError` 一個 `FAILED`（三次 attempt）、ASL 快照 `head-object`、`retire.json`、退役索引頁的 HTTP 回應。
- [x] REL Rule 9 有 primary assertion；REL Rule 12／16／17 與 RUN Rule 2／6／7／10 寫成「相關」並指出 primary Phase（50、26、29）；O2／O3／O5／O6 任一未通過時雲端驗收標為 BLOCKED，沒有宣稱流程已完成或已核定。
