# Phase 59：失敗復原與重送驗收實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **（a）已存在、可直接重用（file:function）**
> - `src/training_kb/publishing.py`：`Publisher.prepare/inspect/commit`、`promote_site_objects(prepared, *, repository)`、`public_site_keys(version_ids)`、`site_key`／`tutorial_index_key`／`site_index_key`、`PENDING_PROMOTE_NAME`、`PENDING_PROMOTE_CONTENT_TYPE`、`UNPUBLISHED_MARKER`、`assert_batch_publishable`、`build_commit_transaction`、`MAX_BATCH_VERSIONS`。
> - `src/training_kb/content.py`：`allocate_version`、`create_version`、`verify_version_complete`、`PUBLIC_SITE_PREFIX`（**在 `content.py`，不是 `publishing.py`**）、`markdown_key`／`diff_key`。
> - `src/training_kb/ingress.py`：`_accept`／`_accept_detailed`／`_start_once` 的續跑分支（D-45：`input_ref`／`execution_arn` 是事實欄位，`duplicate` 但未啟動是合法續跑）。
> - `src/training_kb/operations.py`：`OperationCoordinator.load/record_version/record_model_output/record_proc_sample/complete/fail/acquire_lease/next_sequence`；`record_version` write-once（同值 no-op、換值 `CoordinationError`），`record_proc_sample` 第一次 `True` 之後一律 `False`。
> - `src/training_kb/pipelines/asl.py`：`RETRY`（**已是 D-53 的兩條**）、`CATCH`、`FAIL_STATE_NAME = "PipelineFailed"`、`assert_safe_asl(definition) -> None`（不合格丟 `PermanentError`，已遞迴 `Map.ItemProcessor`／`Iterator` 與 `Parallel.Branches`）、`ASL_LOCAL_PATH = "infra/stepfunctions/{pipeline}/v{number}.json"`。
> - 既有可沿用的測試資產：`tests/integration/test_publish_cutpoints.py`（P24 單篇三切點）、`tests/integration/test_batch_publish_cutpoints.py`（P25 五切點，含 `SiteReader.report()`、`aws_publisher`／`site_reader` fixture 與「同 operation 重送只補公開物件」的案例）、`tests/integration/test_start_execution_idempotency.py`、`tests/integration/test_operations_ledger.py`。**這些是別的 Phase 的測試檔，本 Phase 只讀不改**（R3.6）。
>
> **（b）因上一批裁決／實作而修正的點**
> 1. `PUBLIC_SITE_PREFIX` 定義在 `training_kb.content`（§5 原寫 Phase 24／22 的 `publishing`）。`site_diff_key(version_id)` 的 owner 是 **P57**、落在 `src/training_kb/site.py`（P57 §4），本 Phase 開工時它才剛建立；**更穩的作法是直接用 `publishing.public_site_keys((version_id,))`**——它就是 `pending-promote.json` 裡 `site_keys` 的唯一算法，也正是 `promote_site_objects` 的回傳值，`resume_publish` 用它比自己拼「版本頁 + 差異檔」安全。
> 2. **`pending-promote.json` 只有多篇（`len(version_ids) >= 2`）才寫**（`Publisher._record_pending_promote`，00A §6.7）；單篇靠 `OPS#<op>.version_id`（`_after_transaction` 先 `record_version` 再寫 `site/`）。§6 已寫對，§7 的程式片段要照這個順序實作。
> 3. **切點 4 的例外型別會被轉換。** `Publisher._after_transaction` 把交易之後的任何例外一律轉成 `PublishError`（設計 §8.3、P24 review Important 2），而 `PublishError` 繼承 `Exception`，**不是** `TransientError`。所以 `maybe_fail("publish_after_transact_before_site")` 丟出的 `InjectedFault` 會以 `PublishError`（訊息含切點代號 `a2_after_transact_before_site`／`a3_after_first_site_before_second`）現身。§7 Task 2 的測試已據此改成 `pytest.raises((TransientError, PublishError))`，**不得為了讓型別一致而改掉 `_after_transaction` 的轉型**。
> 4. **`resume_publish` 的 `a2` 復原必須先重跑 `Publisher.prepare` 再 `promote_site_objects`**（00A §6.7、上一批 REP §8 第 9 項）：切點前留下的 staging 是交易**前**渲染的，帶著 `UNPUBLISHED_MARKER`（`data-published="false"`），promote-only 會被 `_put_public_object` 的 runtime 守門擋下。§6 與 §7 Task 2 已寫成明確步驟。
> 5. `create_version` 的真實簽名是 `create_version(plan: VersionPlan, content: TutorialContent, repository: Repository) -> TutorialVersion`；`allocate_version` 的簽名與 §5 相符。`RETRY` 已含 D-53 的第二條 retrier，所以 §9 最後一列的停止條件在現況下不會觸發（保留當回歸守門）。
> 6. `infra/stepfunctions/<pipeline>/v1.json` 三份定義**由 P41（ticket-analysis）、P48（feedback-review）、P52（release-update）建立**，本 Phase 開工前目錄還不存在；`check_asl.py` 的預設 glob 要能在缺檔時給出明確訊息，而不是靜靜回 0。
> 7. `infra/scripts/` 沒有 `__init__.py`（namespace package），`infra/__init__.py` 存在，所以 `from infra.scripts.check_asl import ...` 與 `uv run python -m infra.scripts.check_asl` 都成立（既有 `infra/scripts/check_models.py` 就是這樣被 `tests/unit/test_check_models.py` 使用）。**`pyproject.toml` 的 mypy `files = ["src", "infra"]` 且 `strict = true`**，所以本 Phase 新增的 `check_asl.py` 與 `publishing.resume_publish` 都要完整型別註記；§7 的程式片段為了易讀省略了註記，實作時必須補上。
>
> **（c）gate 現況對本 Phase 的影響**
> - **O3 = FAIL**（P12，報告 `docs/plan/report/o3-20260914t181109z.md`；P24／P25 已依協定 A 在 moto 重現切點）。切點 4 的 partial **已經在 moto 重現**（`tests/integration/test_batch_publish_cutpoints.py::test_batch_cutpoint_5_partial_is_observed_not_accepted`），本 Phase 只能**原樣記錄真實 AWS 的觀察**，不得宣稱通過、不得放寬 F49、不得刪除已 promote 的頁面充當回滾。
> - **O2 = PASS**（P11）：永久去重與同版號可以依賴。
> - **O5 = BLOCKED**（重 probe 報告 `docs/plan/report/o5-20260915T030245Z.md`，Titan／Claude 都仍 `ValidationException: Operation not allowed`）。真實 AWS 執行時，需要模型的節點會走 `PermanentError → Catch → PipelineFailed`——**這是 BLOCKED 證據，不是 bug，也不是通過**。本 Phase 的復原證據因此要分兩類：不需要模型的切點（3、4、5 與 publish 復原）可在真實 AWS 實證；需要模型的端到端重跑（切點 1、2 經由 pipeline 觸發）在真實 AWS 上只能記 BLOCKED，程式面改由 moto 直接呼叫 `create_version` 驗證。
> - **O6 有 4 列待維護者核定**（11 個 `xfail(strict=True)` 站崗）：Release 完全走不進 Rote，所以真實 AWS 的「Release → pipeline」端到端**不可用**；切點 5 的真實驗證改用可走通的 Ticket 路徑，或直接呼叫 `ingress.accept_ticket`。
> - **O1 provisionally accepted、O4／O7 未到**，與本 Phase 無關。
>
> **（d）適用的 controller 裁決（`.superpowers/sdd/phase0914-2/COMMON.md`）**
> - **R1 這一批真的接 AWS**：本 Phase 要真的部署與執行並保存證據（execution ARN、`describe-execution`、`get-execution-history`、CloudWatch、website endpoint 的 HTTP 回應）。做不到的部分標 BLOCKED 並附實際錯誤原文。全案固定 `us-east-1`，CLI 一律帶 `--region us-east-1`。
> - **R3 同檔併行**：`publishing.py`／`content.py`／`ingress.py` 是共用檔，本 Phase 在 W4（P41／P48／P52／P57 之後），理論上沒有人同時改，但仍**只用 Edit、不用 Write**，新增的東西放在 `# ---- Phase 59 ----` 區段，`git add` 只加自己的檔案路徑。
> - **R5 名稱契約以 00A ＋ 既有程式為準**；**R10 需要維護者決定的事自己裁決並標「本計畫選擇」**。
> - **若 P41 為了雲端失敗路徑實證已經先建了 `src/training_kb/faults.py` 的最小第一片，本 Phase 擴充它、不重建**（Task 1 Step 3 改成補齊缺的切點名稱與 `active_fault`／`maybe_fail`，紅燈訊號改成 `ImportError: cannot import name ...`）。截至 W0，P41 文件 §4 的預計檔案**沒有**列 `faults.py`。

**目標：** 用可控的 `TKB_FAULT` 開關在儲存、發布與接入的五個切點注入失敗，證明讀者看到的永遠是整批舊狀態，而且同一個 operation 重送會沿用原版號與原模型輸出把東西補齊。

**架構：** `training_kb/faults.py` 提供五個固定切點與只在非正式環境生效的開關；`content.py`、`publishing.py`、`ingress.py` 各在真實路徑上呼叫 `maybe_fail`。整合測試在每個切點注入後核對 DynamoDB 與 `site/` 的對外可見狀態，再清掉開關以同一個 `operation_id` 重送。`infra/scripts/check_asl.py` 包裝 Phase 29 的 `assert_safe_asl`，靜態檢查三份 ASL 的兩條 Retry 與 Catch。真實 AWS 驗收另標 `aws` marker，證據寫成固定格式。

**技術：** Python 3.12、pytest（`aws` marker）、moto、boto3、AWS Step Functions Standard。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§8.3、§14.1、§14.2、§15、§16（S3／S8）、§18 O2／O3](../../design/training-kb.md)。
- 前置為 [Phase 58：Demo 控制台與規則開關預覽](./58-Phase58-Demo控制台與規則開關預覽.md)；另需 [Phase 01](./01-Phase01-專案骨架與離線品質門檻.md) 在 `pyproject.toml` 註冊的 `aws` marker、[Phase 11](./11-Phase11-O2接受順序與重啟整合驗證.md) 的 lease 與 `accept_seq`、[Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的 O3 切點命名、[Phase 20](./20-Phase20-版本分配與重試重用.md) 的版號重用、[Phase 23](./23-Phase23-未發布版本與關係完整寫入.md) 的建版、[Phase 24](./24-Phase24-單篇教學發布提交.md)／[Phase 25](./25-Phase25-多篇教學整批發布.md) 的 `Publisher` 與 `pending-promote.json`、[Phase 29](./29-Phase29-共用Pipeline執行器與ASL失敗語意.md) 依裁決 D-53 固定的兩條 retrier、[Phase 32](./32-Phase32-事件接受去重與流程啟動.md) 的去重與啟動、[Phase 35](./35-Phase35-PROC成功失敗與退役生命週期.md) 的 PROC 樣本。前置未通過時停止。
- **本批次（Phase 41–60）的實際排程把本 Phase 放在 W4**（現況核對 2026-09-14）：真正擋住本 Phase 的是 [Phase 41](./41-Phase41-Ticket-Analysis雲端流程驗收.md)（Lambda／state machine 部署、`infra/stepfunctions/ticket-analysis/v1.json`、相依打包 R2）、[Phase 48](./48-Phase48-Feedback-Review排程流程.md) 與 [Phase 52](./52-Phase52-Release-RETIRE與流程驗收.md)（另兩份 ASL 快照）、[Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md)（`site_diff_key`、公開站與 bucket policy）。這四個沒完成，Task 3 的三份 ASL 檢查與真實 AWS 驗收都做不了。
- 下一階段是 [Phase 60：安全檢查與端到端完成證據](./60-Phase60-安全檢查與端到端完成證據.md)。
- 本階段不做：不為了取得綠燈修改業務契約；不新增 CloudFront、公開讀取 API 或待審佇列；不放寬 F49 的「整次失敗不發布」；不把注入開關帶進正式環境；不改 Phase 12 與本 Phase 任何一套切點名稱。
- 與本 Phase 有關的 O1–O7 gate 狀態（**2026-09-14 現況，不是「待驗證」**）：**O2 = PASS**（P11）；**O3 = FAIL**（P12，報告 `docs/plan/report/o3-20260914t181109z.md`，決策出口仍在維護者手上，見 00A D-80）；**O5 = BLOCKED**（報告 `docs/plan/report/o5-20260915T030245Z.md`，Titan／Claude 都仍 `ValidationException: Operation not allowed`）；**O6 有 4 列待核定**（11 個 `xfail(strict=True)` 站崗，Release 走不進 Rote）；O1 provisionally accepted（D-71）；O4／O7 未到。這是 O2 與 O3 的追驗階段。切點 `publish_after_transact_before_site` 正是設計 §18 O3 明說的缺口，**此階段完成前不可宣稱 publish 故障驗收已通過**。只要出現對外可見的 partial publish、新版號、新模型輸出或重複樣本，就保留 FAIL 並停止依賴路徑。
- **真實 AWS 這一批要接（controller R1）**：本 Phase 的切點證據要真的在 `us-east-1` 跑出來並保存（execution ARN、`describe-execution`、`get-execution-history`、CloudWatch、公開 website endpoint 的 HTTP 回應）。**與 Phase 41 的分工**：P41 負責「部署本身與正常流程的雲端證據」，本 Phase 負責「各切點的重啟／同 operation 復原證據」。因為 O5 BLOCKED，需要模型的節點在真實 AWS 一定走 `PermanentError → Catch → PipelineFailed`；那是 BLOCKED 證據，**照實記錄、不改寫成通過、也不當 bug 修**。
- **承接 [Phase 24](./24-Phase24-單篇教學發布提交.md)／[Phase 25](./25-Phase25-多篇教學整批發布.md) 標「延後至 P41／P59」的項目**（controller 2026-09-14 裁決）：P24 §11 的「真實 AWS 上重跑三個切點與 website endpoint 人工驗收」與 P25 §11 的「在真實 AWS 上重跑五個切點，並用公開 website endpoint 的 HTTP 回應做人工驗收」，由本 Phase 的 **Task 3 Step 4A**（見 §7）承接並逐項留證；P41 不重複做發布切點，只做部署與正常流程。
- 本 Phase 沒有 primary Rule：[00B 需求覆蓋對照](./00B-需求覆蓋對照.md) 把 P25、P41、P59、P60 列為驗收型，第 10 節的 Rule 一律是「相關」，直接斷言在各自的 primary Phase。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
一次 Release 事件從接入到公開的真實路徑與五個注入切點（五個都在同一條線上）

ingress.accept_release（Phase 32）
  保存 RELEASE -> [5 start_execution] -> starter.start("release-update", ...)
              |
              v
content.create_version（Phase 20–23）
  allocate_version -> validate_content -> put_object(v2.md) -> [1 s3_after_md]
     -> put_object(v2.diff) -> put_meta(VERSION) -> [2 ddb_after_version]
     -> put STEP/REFERENCES -> put SUPERSEDES/APPLIED_TO -> verify_version_complete
              |
              v
publishing.Publisher.commit（Phase 24／25）
  prepare -> inspect -> [3 publish_before_transact]
     -> transact(published_at + current_version)
     -> put_object(operations/<op>/pending-promote.json)（多篇整批才寫，Phase 25）
     -> [4 publish_after_transact_before_site] -> promote_site_objects
     -> site/tutorials/prepare-meeting/v2.html

[你在這裡] Phase 59：逐一注入 -> 核對對外可見狀態 -> 清掉開關 -> 同 operation 重送
```

## 2. 完成後看得到什麼

以 Release `r_42` 讓 `prepare-meeting` 從 v1 更新到 v2 為例（`operation_id` = `op-release-r_42`）；每個切點注入後外部可見狀態必須是下表，任何一格對不上就是 FAIL。

```text
切點                                 current_   v2 的         私有產物       site/ 有
                                     version    published_at  (md/diff)      v2 頁？
-----------------------------------  ---------  ------------  -------------  --------
1 s3_after_md                        v1 不變    VERSION 未建   md 有 diff 無  沒有
2 ddb_after_version                  v1 不變    None           齊全           沒有
3 publish_before_transact            v1 不變    None           齊全           沒有
4 publish_after_transact_before_site v2 已切換  有值           齊全           沒有 <- O3 缺口
5 start_execution                    v1 不變    不適用         不適用         沒有
-----------------------------------  ---------  ------------  -------------  --------
共同不變量：任一切點後打開公開站讀到的都仍是 v1 全文；
  site/tutorials/prepare-meeting/v2.html 不存在，index.html 也沒有指向 v2 的連結。
```

清掉開關後以同一個 `operation_id` 重送，五個切點都收斂到同一個結果：版號仍是 `prepare-meeting@v2`、模型輸出沿用既有 `model_output_refs`、`site/tutorials/prepare-meeting/v2.html` 出現、回饋樣本與 PROC 成功樣本各自沒有增加。切點 4 的重送只讀 `operations/op-release-r_42/pending-promote.json` 的 `site_keys` 補寫公開物件，不再跑一次條件交易。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 切點 | 程式裡一個明確位置，注入開關可以讓它在那裡丟例外。 |
| `InjectedFault` | 人工注入的暫時錯誤，會先被 ASL 的 Retry 攔到，重試耗盡才進 Catch。 |
| lease | 同篇教學同時只有一個寫入者的短期租約；租約不等於接受順序，TTL 也不保證準時解鎖。 |
| closed execution | 同名 Step Functions 執行已經結束；再啟動會得到 `ExecutionAlreadyExists`。 |
| partial publish | 多篇一起發布時 A 已公開、B 還沒，對外看得到不一致；F49 禁止。 |
| 補償重送 | 交易已提交但公開物件未寫時，重送只補寫它們，不再跑一次條件交易。 |
| `pending-promote.json` | Phase 25 在交易成功後寫進私有操作紀錄的待補公開 key 清單，重送照它補齊。 |
| `aws` marker | pytest 標籤；標它的測試需要真實 AWS 帳號，由 Phase 01 在 `pyproject.toml` 註冊。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/faults.py` | 五個切點名稱、`InjectedFault`、`active_fault`、`maybe_fail`。 |
| 修改 | `src/training_kb/content.py` | 切點 1、2：寫完 `v<n>.md` 之後、寫完 VERSION metadata 之後各一次。 |
| 修改 | `src/training_kb/publishing.py` | 切點 3、4：交易之前、交易之後而未 promote 之前（多篇整批時就在寫完 `pending-promote.json` 之後）；另加 `resume_publish`。 |
| 修改 | `src/training_kb/ingress.py` | 切點 5：`starter.start(...)` 之前。 |
| 建立 | `infra/scripts/check_asl.py` | 包裝 `assert_safe_asl`，另外核對兩條 retrier 與 `PipelineFailed` 終點。 |
| 測試 | `tests/unit/test_faults.py`、`tests/unit/test_check_asl.py` | 開關與 ASL 靜態檢查。 |
| 測試 | `tests/integration/test_recovery.py` | 主戰場：切點矩陣、重送、串行與真 AWS 驗收。 |
| 產出 | `docs/plan/report/recovery-<YYYYMMDD-HHMM>.md` | 可追溯的驗收紀錄與 execution ARN。 |

## 5. 固定介面

### Consumes

```text
TransientError / PermanentError / CoordinationError                    # Phase 02
Repository.get_tutorial / get_version / get_proc                       # Phase 06
Repository.put_object / get_object / object_exists / scan_entity       # Phase 07、08
OperationCoordinator.accept / load / record_model_output / record_version /
    record_proc_sample / complete / fail ; operation_ref(op_id, name)  # Phase 10
acquire_lease(scope, owner, *, ttl_seconds, now) / release_lease /
    next_sequence(scope)                                               # Phase 11
O3CutPoint 的五個名稱（只做對照，不改名）                               # Phase 12
allocate_version(tutorial_id, operation_id, operations, *, repository,
    reason, rules_applied) -> VersionPlan                              # Phase 20
create_version(plan, content, repository) -> TutorialVersion ;
    verify_version_complete(version_id, repository) -> bool            # Phase 23
PUBLIC_SITE_PREFIX = "site/"（在 training_kb.content）                  # Phase 22
PublishRequest / PreparedPublish / PublishResult ;
    Publisher.prepare / inspect / commit ; site_key(version_id)（相對 key）;
    public_site_keys(version_ids) -> tuple[str, ...]（含 site/ 前綴）    # Phase 24
promote_site_objects(prepared, *, repository) -> tuple[str, ...] ;
    PENDING_PROMOTE_NAME = "pending-promote" ; UNPUBLISHED_MARKER      # Phase 25
site_diff_key(version_id)（相對 key，在 site.py）                        # Phase 57
RETRY（兩條，D-53）/ CATCH / FAIL_STATE_NAME = "PipelineFailed" /
    assert_safe_asl(definition) -> None（不合格丟 PermanentError）/
    ASL_LOCAL_PATH = "infra/stepfunctions/{pipeline}/v{number}.json"    # Phase 29
PipelineStarter.start(pipeline, execution_name, input) -> str ;
    ingress._accept_detailed(obj, *, deadline)（續跑事實，D-45）;
    on_new_success(proc, operation_id, operations, now)                 # Phase 32、35
```

（現況核對 2026-09-14：原寫 `PUBLIC_SITE_PREFIX` 屬 Phase 24／22，實際定義在 `training_kb.content`；原缺 `public_site_keys`／`PENDING_PROMOTE_NAME`／`UNPUBLISHED_MARKER`／`ASL_LOCAL_PATH`；`create_version` 的實際簽名是三個位置參數。）

### Produces

```python
FAULT_POINTS = ("s3_after_md", "ddb_after_version", "publish_before_transact",
                "publish_after_transact_before_site", "start_execution")

class InjectedFault(TransientError):
    point: str

def active_fault(env: Mapping[str, str] | None = None) -> str | None: ...
def maybe_fail(point: str, env: Mapping[str, str] | None = None) -> None: ...
def resume_publish(operation_id: str, *, operations, repository,
                   publisher, now: datetime) -> PublishResult: ...

LAMBDA_SERVICE_ERRORS: list[str]

def iter_task_states(states: Mapping[str, Any],
                     prefix: str = "") -> Iterator[tuple[str, dict]]: ...
def check_asl_document(doc: Mapping[str, Any], *,
                       fail_state: str = "PipelineFailed") -> list[str]: ...
def main(argv: list[str] | None = None) -> int: ...
```

`InjectedFault` 繼承 `TransientError`，注入的失敗才會走完 Retry 再進 Catch，把設計 §14.2 的整條失敗路徑走一次（00A 第 4.1 節同一句）。

## 6. 設計細節

`active_fault` 有兩道保險：`TKB_ENV` 是 `prod` 時一律回 `None`，不論 `TKB_FAULT` 設什麼；切點名稱不在 `FAULT_POINTS` 時立刻丟 `ValueError`，讓打錯字變成明確錯誤而不是安靜地不生效。`maybe_fail` 進入前也先檢查名稱，所以就算沒啟用，寫錯的切點名也會在第一次執行被抓到。

[Phase 12](./12-Phase12-O3發布切換整合驗證.md) spike 的切點與本 Phase 的注入開關是**兩套名稱**，兩邊都不改名，對照關係固定如下：

| Phase 59 `FAULT_POINTS`（注入） | Phase 12 `O3CutPoint`（觀察） | 對應說明 |
|---|---|---|
| `publish_before_transact` | `a1_before_transact` | 交易前中斷，全舊，私有 staging 不對外。 |
| `publish_after_transact_before_site` | `a2_after_transact_before_site` | 交易後未寫公開物件，就是 O3 缺口。 |
| Task 2 的多篇整批案例 | `a3_after_first_site_before_second` | A 新 B 舊，違反 F49。 |
| 不注入（先 DB 後 site、不做事後刪除） | `b1_after_site_before_transact`、`c1_after_delete_site` | 先寫 site 再交易一律禁止、刪除不消除先前曝光，兩者只在 Phase 12 觀察。 |
| `s3_after_md`、`ddb_after_version`、`start_execution` | 無對應 | 建版與接入層切點，Phase 12 的 spike 不涵蓋。 |

同一個 operation 重送的流程固定如下：

```text
同一事件第二次送達 -> 同一 canonical_id -> 同一 operation_id
      |
      v
OperationCoordinator.accept(...) 條件寫入 OPS#<id>
      |
      +-- "accepted"  -> 新事件，照正常流程
      +-- "duplicate" -> 讀既有 OperationRecord
             +-- status == "done" -> 取既有結果；不新增版本／回饋樣本／PROC 樣本
             +-- 其他狀態         -> 沿用 version_id 與 model_output_refs，
                                     只補齊缺的產物再發布
```

切點 4 是本 Phase 唯一需要補償的路徑。DynamoDB 交易無法連同 S3 的公開切換一起提交（設計 §8.3、§18 O3），交易已提交後條件 `current_version == supersedes` 已不成立，重送不能再跑一次條件交易。**本計畫選擇：** 重送先讀該版本的 `published_at`，有值就只補寫公開物件，清單以 [Phase 25](./25-Phase25-多篇教學整批發布.md) 寫在 `operations/<operation_id>/pending-promote.json` 的 `site_keys` 為準；連這份清單都不存在時（**單篇發布本來就不寫它**），用 operation 紀錄的 `version_id` 配 `public_site_keys((version_id,))` 重算同一份。

**`a2` 的復原順序是硬性的（00A §6.7、上一批 REP §8 第 9 項）：先重跑 `Publisher.prepare`，再 `promote_site_objects`。** 切點 4 之前留下的 staging 是**交易前**渲染的，那時 `published_at` 還是 `None`，頁面帶著 `UNPUBLISHED_MARKER`（`data-published="false"`）；直接 promote 會被 `publishing._put_public_object` 的 runtime 守門擋下並丟 `PublishError`——擋得好，但那代表**復原失敗**而不是成功。重跑 `prepare` 時表裡的 `published_at` 已經有值，重新渲染出來的 staging 才是 `data-published="true"`，promote 出去的 bytes 才合法。復原路徑**不得**再呼叫 `Publisher.commit`（`inspect` 會以「版本已發布」擋下）、**不得**刪除既有公開物件、**不得**重新 `allocate_version`。

**切點 4 的例外型別**（現況核對 2026-09-14）：`Publisher._after_transaction` 把交易之後的任何例外一律轉成 `PublishError`（設計 §8.3），而 `training_kb.errors.PublishError` 繼承 `Exception`、**不是** `TransientError`。所以 `maybe_fail("publish_after_transact_before_site")` 丟出的 `InjectedFault` 對呼叫端而言是 `PublishError`，訊息會帶 `_cut_point` 算出的切點代號（單篇 `a2_after_transact_before_site`、多篇 `a3_after_first_site_before_second`）。這是刻意的設計，**不得為了讓五個切點的例外型別一致而改掉它**；測試改成接受 `(TransientError, PublishError)`，並對切點 4 額外斷言訊息含切點代號。這讓讀者只會短暫看到舊版，不會看到半完成的新版，也不會卡在永遠無法發布的狀態；但這是補償不是原子性，所以在 Phase 12 的 O3 協定被接受之前，本 Phase 只能記錄「補償有效」，不能寫成「發布故障驗收通過」。多篇整批的不變量更嚴格：任何切點失敗後 A 與 B 必須同時是舊狀態或同時是新狀態，出現 A 新 B 舊就停止，不得描述成「整次沒有發布」。

## 7. TDD Tasks

### Task 1：`faults.py` 的五個切點與環境限制

- [ ] **Step 1：建立失敗測試**

```python
# tests/unit/test_faults.py
import pytest
from training_kb.errors import TransientError
from training_kb.faults import InjectedFault, active_fault, maybe_fail

def test_unknown_fault_point_fails_immediately():
    with pytest.raises(ValueError, match="未知的失敗切點"):
        maybe_fail("s3_after_mdx", {"TKB_FAULT": "s3_after_md"})

def test_prod_never_injects():
    env = {"TKB_ENV": "prod", "TKB_FAULT": "s3_after_md"}
    assert active_fault(env) is None
    maybe_fail("s3_after_md", env)

def test_active_point_raises_transient_injected_fault():
    env = {"TKB_ENV": "dev", "TKB_FAULT": "publish_before_transact"}
    with pytest.raises(InjectedFault) as caught:
        maybe_fail("publish_before_transact", env)
    assert isinstance(caught.value, TransientError)
    assert caught.value.point == "publish_before_transact"
    maybe_fail("s3_after_md", env)
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_faults.py -q
```

預期：FAIL，訊號包含 `No module named 'training_kb.faults'`。

- [ ] **Step 3：建立最小實作**

```python
# src/training_kb/faults.py
import os
from collections.abc import Mapping

from training_kb.errors import TransientError

FAULT_POINTS = ("s3_after_md", "ddb_after_version", "publish_before_transact",
                "publish_after_transact_before_site", "start_execution")

class InjectedFault(TransientError):
    def __init__(self, point: str) -> None:
        super().__init__(f"注入失敗切點：{point}")
        self.point = point

def _check_point(point: str) -> None:
    if point not in FAULT_POINTS:
        raise ValueError(f"未知的失敗切點：{point}；可用：{'、'.join(FAULT_POINTS)}")

def active_fault(env: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if env is None else env
    if source.get("TKB_ENV", "dev").strip().lower() == "prod":
        return None
    point = source.get("TKB_FAULT", "").strip()
    if point:
        _check_point(point)
    return point or None

def maybe_fail(point: str, env: Mapping[str, str] | None = None) -> None:
    _check_point(point)
    if active_fault(env) == point:
        raise InjectedFault(point)
```

- [ ] **Step 4：把五個切點接進程式並跑綠燈**

`content.py` 在寫完 `v<n>.md` 之後、寫完 VERSION metadata 之後各插一次；`publishing.py` 的 `Publisher.commit` 在交易之前、以及交易之後而尚未 `promote_site_objects` 之前各插一次（多篇整批時後者就落在寫完 `pending-promote.json` 之後；單篇發布本來就不寫這份清單，見 §6）；`ingress.py` 在保存 TICKET／RELEASE 之後、`starter.start` 之前插一次。再加一個測試讀這三個檔的原始碼，斷言 `FAULT_POINTS` 的每個名稱都恰好出現一次 `maybe_fail(...)` 呼叫。執行 `uv run pytest tests/unit/test_faults.py -q`，預期整個檔案全綠。

**五個插入點對應到現有程式的確切位置**（現況核對 2026-09-14，逐個核過真實程式）：

| 切點 | 檔案:函式 | 插在哪一行之後 | 插在這裡的理由 |
|---|---|---|---|
| 1 `s3_after_md` | `content.py:create_version` | `put_private_artifact(repository, md_key, current_md, MARKDOWN_CONTENT_TYPE)` 之後、寫 `diff_key(...)` 之前 | 對應矩陣「md 有、diff 無」。 |
| 2 `ddb_after_version` | `content.py:create_version` | `if existing is None: repository.put_meta(planned)` 這個 `if` 區塊**之後**、`_write_edges(...)` 之前 | `put_meta` 只在首次執行；插在 `if` 之後，重送時切點照樣生效，且矩陣「私有產物齊全、沒有 STEP 邊」成立。 |
| 3 `publish_before_transact` | `publishing.py:Publisher.commit` | `inspect` 通過、`build_commit_transaction(...)` 之前（**在 `_after_transaction` 的 try 之外**） | 例外原樣是 `InjectedFault`（`TransientError`），對應矩陣「全舊」。 |
| 4 `publish_after_transact_before_site` | `publishing.py:Publisher._publish_site` | `self._record_pending_promote(prepared)` 之後、第一次 `_restage` 之前 | 單篇的 `record_version` 已在 `_after_transaction` 先跑完、多篇的 `pending-promote.json` 已寫好，**兩種復原輸入都在**；再往前插就會讓復原沒有輸入（P25 review 必修 A1）。例外會被 `_after_transaction` 轉成 `PublishError`（見 §6）。 |
| 5 `start_execution` | `ingress.py:_accept` | `assert_time_left(deadline, step="start-execution")` 之後、`_start_once(...)` 之前 | **本計畫選擇：插在 `_accept` 而不是 `_start_once` 內部。** 插在 `_start_once` 裡會被它的 `except Exception` 攔到並先 `operations.fail(...)` 把 ledger 標成 `failed`；插在外面則 ledger 維持 `accepted`、`input_ref` 已寫、`execution_arn` 仍空，重送剛好走 P32 設計好的續跑分支（D-45），不換名重跑也不建第二筆 operation。 |

型別註記不可省：`pyproject.toml` 的 mypy 是 `strict = true` 且 `files = ["src", "infra"]`。

- [ ] **Step 5：提交** — `git add src/training_kb/faults.py src/training_kb/content.py src/training_kb/publishing.py src/training_kb/ingress.py tests/unit/test_faults.py` 後 `git commit -m "feat(faults): 以 TKB_FAULT 在五個切點注入失敗"`。

### Task 2：切點矩陣、整批不切換與同 operation 重送

- [ ] **Step 1：建立失敗測試**

```python
# tests/integration/test_recovery.py
import pytest
from training_kb.errors import PublishError, TransientError
from training_kb.faults import FAULT_POINTS

@pytest.mark.parametrize("point", FAULT_POINTS)
def test_no_public_change_after_injected_fault(point, world, monkeypatch):
    monkeypatch.setenv("TKB_ENV", "dev")
    monkeypatch.setenv("TKB_FAULT", point)
    # 現況核對 2026-09-14：切點 4 的 InjectedFault 會被 Publisher._after_transaction
    # 轉成 PublishError（設計 §8.3），所以這裡收兩種型別，另在下面單獨斷言切點代號。
    with pytest.raises((TransientError, PublishError)) as caught:
        world.deliver_release("r_42")
    if point == "publish_after_transact_before_site":
        assert "a2_after_transact_before_site" in str(caught.value)
    assert world.public_html("prepare-meeting@v1") == world.v1_html
    assert not world.object_exists(world.public_key("prepare-meeting@v2"))
    assert "v2.html" not in world.tutorial_index("prepare-meeting")
    if point != "publish_after_transact_before_site":
        assert world.tutorial().current_version == "prepare-meeting@v1"

def test_batch_publish_is_all_or_nothing(world, monkeypatch):
    monkeypatch.setenv("TKB_ENV", "dev")
    monkeypatch.setenv("TKB_FAULT", "publish_before_transact")
    with pytest.raises(TransientError):      # 切點 3 在 try 之外，型別不變
        world.publish_batch(["prepare-meeting@v2", "share-summary@v2"])
    for version_id in ("prepare-meeting@v2", "share-summary@v2"):
        assert world.tutorial(version_id.split("@")[0]).current_version.endswith("@v1")
        assert not world.object_exists(world.public_key(version_id))

def test_resend_reuses_version_and_model_output(world, monkeypatch):
    monkeypatch.setenv("TKB_ENV", "dev")
    monkeypatch.setenv("TKB_FAULT", "publish_after_transact_before_site")
    with pytest.raises(PublishError):        # 切點 4 被 _after_transaction 轉型
        world.deliver_release("r_42")
    first = world.operation("op-release-r_42")
    monkeypatch.delenv("TKB_FAULT")
    world.resume("op-release-r_42")
    again = world.operation("op-release-r_42")
    assert again.version_id == first.version_id == "prepare-meeting@v2"
    assert again.model_output_refs == first.model_output_refs
    assert world.model_calls_during_resend == 0
    assert world.object_exists("site/tutorials/prepare-meeting/v2.html")

def test_same_event_resend_adds_no_samples(world):
    world.deliver_release("r_42")
    before = world.counters()
    world.deliver_release("r_42")
    assert world.counters() == before
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_recovery.py -q
```

預期：FAIL，訊號包含 `fixture 'world' not found`；補上 fixture 後會變成 `cannot import name 'resume_publish'`。

- [ ] **Step 3：建立最小實作**

```python
# tests/integration/test_recovery.py（接在測試上方）
from training_kb.publishing import site_key
from training_kb.site import site_diff_key          # Phase 57

PUBLIC, SLUG = "site/", "prepare-meeting"

class World:
    """把 Phase 20→25 的真實路徑包成測試門面，不繞過 Publisher 另接發布路徑。"""

    def public_key(self, version_id: str) -> str:
        return PUBLIC + site_key(version_id)

    def public_html(self, version_id: str) -> str:
        return (self.repository.get_object(self.public_key(version_id)) or b"").decode()

    def tutorial_index(self, slug: str) -> str:
        body = self.repository.get_object(f"{PUBLIC}tutorials/{slug}/index.html")
        return (body or b"").decode()

    def counters(self) -> tuple[int, int, int]:
        return (len(self.repository.scan_entity("VERSION")),
                len(self.repository.scan_entity("FEEDBACK")),
                self.repository.get_proc(self.signature).success_count)
```

```python
# src/training_kb/publishing.py（在 Phase 24 的模組追加，放在 `# ---- Phase 59 ----` 區段）
import json
from training_kb.errors import CoordinationError
from training_kb.keys import operation_ref

def resume_publish(operation_id, *, operations, repository, publisher, now):
    """同 operation 重送：沿用原版號；交易已提交時只補公開物件。

    **順序是硬性的（00A §6.7、REP §8 第 9 項）：先 `prepare` 再 `promote_site_objects`。**
    切點 4 之前留下的 staging 是交易「前」渲染的，帶著 UNPUBLISHED_MARKER，
    promote-only 會被 `_put_public_object` 擋下 —— 那是復原失敗，不是成功。
    """
    record = operations.load(operation_id)
    if record is None or record.version_id is None:
        raise CoordinationError(f"沒有可沿用的操作紀錄：{operation_id}")
    version = repository.get_version(record.version_id)
    if version is None:
        raise CoordinationError(f"操作紀錄指向不存在的版本：{record.version_id}")
    request = PublishRequest(version_ids=(record.version_id,), operation_id=operation_id)
    # published_at 已有值時這一步是「重新渲染成 data-published=true」，不是重新發布。
    prepared = publisher.prepare(request, now=now)
    if version.published_at is None:
        return publisher.commit(prepared, now=now)          # 切點 1、2、3：照正常路徑走完
    body = repository.get_object(operation_ref(operation_id, PENDING_PROMOTE_NAME))
    expected = (list(json.loads(body)["site_keys"]) if body           # 多篇：P25 的待補清單
                else list(public_site_keys((record.version_id,))))    # 單篇：版本頁 + 差異檔
    if list(promote_site_objects(prepared, repository=repository)) != expected:
        raise CoordinationError(f"補寫的公開 key 與待補清單不一致：{operation_id}")
    return PublishResult(published=(record.version_id,), failed=None, reasons=())
```

（現況核對 2026-09-14：原片段用 `operation_ref(operation_id, "pending-promote")` 的字面值與 `PUBLIC_SITE_PREFIX + site_key(...) / site_diff_key(...)` 自行拼清單，改成既有的 `PENDING_PROMOTE_NAME` 與 `public_site_keys(...)`——後者就是 `pending-promote.json` 裡 `site_keys` 的唯一算法，也正是 `promote_site_objects` 的回傳值，兩邊不可能分岔，也不必等 P57 的 `site_diff_key`。整批復原要復原**多篇**時，`request` 的 `version_ids` 改成 `pending-promote.json` 的 `version_ids`，父 operation 依 D-59 不持有版號。實作時要補完整型別註記：mypy `strict` 涵蓋 `src`。）

`World` 的 `__init__` 收下 `repository`、`operations`、`publisher`、PROC `signature`，並把已發布 v1 的公開頁 bytes 存進 `v1_html`、`model_calls_during_resend` 起始為 0；`object_exists`／`tutorial`／`operation` 直接轉呼 `Repository.object_exists`、`Repository.get_tutorial`、`OperationCoordinator.load`。`deliver_release(release_id)` 是唯一的端到端驅動：走 Phase 32 的接受與啟動、在本機用 `run_sequence` 跑 release-update、再走 Phase 20→23→24 建版與發布，所以五個切點都在它的路徑上（`start_execution` 在最前面，失敗時連版本都還沒建）。`publish_batch` 走 Phase 25 的 `prepare`／`inspect`／`commit`，`resume` 呼叫 `resume_publish`。`world` fixture 用 moto 建好 `training_kb` 表與 bucket 並載入已發布的 v1。重送一律先讀 `OperationCoordinator.load`：有 `version_id` 就重用，有 `model_output_refs` 就從私有 S3 讀回，不再呼叫 `Writer`。`counters()` 的 `success_count` 只有在 [Phase 35](./35-Phase35-PROC成功失敗與退役生命週期.md) 的 `on_new_success` 拿到 `record_proc_sample(...)` 回 `True` 這份永久證據時才會加，所以同事件重送三種樣本都不變。

- [ ] **Step 4：補切點 4、串行與 closed execution 案例並跑綠燈**

切點 4 允許 `current_version` 已切換，但仍必須滿足「`site/tutorials/prepare-meeting/v2.html` 不存在、教學索引沒有 v2 連結」，測試對它單獨斷言並在報告標成 O3 缺口，不得改成寬鬆通過。同篇的 Release 與 Feedback 交錯送達時以 `acquire_lease` 串行，兩者依 `next_sequence` 取得的接受順序各產生一版，版號不重疊也不跳過；測試明確寫出「lease 不等於接受順序、TTL 不保證準時解鎖」。`start_execution` 切點清掉後重送，若 Step Functions 回 `ExecutionAlreadyExists`，必須先用 `describe_execution` 讀回原執行狀態並核對 operation 紀錄：`status == "done"` 才沿用既有結果，否則依 [Phase 32](./32-Phase32-事件接受去重與流程啟動.md) 回 `CoordinationError`，不可直接當成功，也不可換名重跑。執行 `uv run pytest tests/integration/test_recovery.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交** — `git add src/training_kb/publishing.py tests/integration/test_recovery.py` 後 `git commit -m "test(recovery): 切點注入與同 operation 重送"`。

### Task 3：ASL 靜態檢查與真實 AWS 驗收證據

- [ ] **Step 1：建立失敗測試**

```python
# tests/unit/test_check_asl.py
from infra.scripts.check_asl import check_asl_document
from training_kb.pipelines.asl import CATCH, RETRY

ARN = "arn:aws:lambda:ap-northeast-1:123456789012:function:training-kb-pipeline-task"

def _document() -> dict:
    inner = {"Inner": {"Type": "Task", "Resource": ARN, "End": True}}
    return {"StartAt": "Work", "States": {
        "PipelineFailed": {"Type": "Fail", "Error": "PipelineFailed"},
        "Work": {"Type": "Task", "Resource": ARN, "End": True, "Retry": [dict(RETRY[0])]},
        "Fan": {"Type": "Map", "Next": "Work",
                "ItemProcessor": {"StartAt": "Inner", "States": inner}}}}

def test_missing_catch_and_second_retrier_are_reported():
    problems = check_asl_document(_document())
    assert any("Work" in item and "Catch" in item for item in problems)
    assert any(item.startswith("Task Fan.ItemProcessor.Inner") for item in problems)
    assert any("Lambda.ServiceException" in item for item in problems)
    assert any(item.startswith("assert_safe_asl") for item in problems)

def test_complete_document_has_no_problems():
    doc = _document()
    del doc["States"]["Fan"]
    doc["States"]["Work"]["Retry"] = [dict(item) for item in RETRY]
    doc["States"]["Work"]["Catch"] = [dict(item) for item in CATCH]
    assert check_asl_document(doc) == []
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_check_asl.py -q
```

預期：FAIL，訊號包含 `No module named 'infra.scripts.check_asl'`。

- [ ] **Step 3：建立最小實作**

```python
# infra/scripts/check_asl.py
import json
import sys
from pathlib import Path

from training_kb.errors import PermanentError
from training_kb.pipelines.asl import CATCH, FAIL_STATE_NAME, RETRY, assert_safe_asl

ASL_ROOT = Path("infra/stepfunctions")
LAMBDA_SERVICE_ERRORS = ["Lambda.ServiceException", "Lambda.AWSLambdaException",
                         "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]

def iter_task_states(states, prefix=""):
    for name in sorted(states):
        state, where = states[name], f"{prefix}{name}"
        if state.get("Type") == "Task":
            yield where, state
        for key in ("ItemProcessor", "Iterator"):
            if isinstance(state.get(key), dict):
                yield from iter_task_states(state[key].get("States", {}), f"{where}.{key}.")
        for index, branch in enumerate(state.get("Branches") or []):
            yield from iter_task_states(branch.get("States", {}), f"{where}.Branches[{index}].")

def check_asl_document(doc, *, fail_state=FAIL_STATE_NAME):
    problems, states = [], doc.get("States") or {}
    for where, state in iter_task_states(states):
        retries, catches = state.get("Retry") or [], state.get("Catch") or []
        if retries[: len(RETRY)] != [dict(item) for item in RETRY]:
            problems.append(f"Task {where} 的前 {len(RETRY)} 條 Retry 與 Phase 29 的 RETRY 不同")
        if not any(item.get("ErrorEquals") == LAMBDA_SERVICE_ERRORS for item in retries):
            problems.append(f"Task {where} 缺少涵蓋 Lambda.ServiceException 的 retrier")
        if catches != [dict(item) for item in CATCH] or catches[0].get("Next") != fail_state:
            problems.append(f"Task {where} 的 Catch 沒有把 States.ALL 導向 {fail_state}")
    if states.get(fail_state, {}).get("Type") != "Fail":
        problems.append(f"缺少 Type=Fail 的 {fail_state} 終點")
    try:
        assert_safe_asl(doc)
    except PermanentError as error:
        problems.append(f"assert_safe_asl：{error}")
    return problems

def main(argv=None):
    paths = [Path(item) for item in argv] if argv else sorted(ASL_ROOT.glob("*/v*.json"))
    found = {path: check_asl_document(json.loads(path.read_text())) for path in paths}
    for path, problems in found.items():
        print(f"[{'通過' if not problems else '不通過'}] {path}")
        print(*(f"  - {item}" for item in problems), sep="\n")
    return 1 if any(found.values()) else 0

if __name__ == "__main__":
    sys.exit(main())
```

`check_asl_document` 自己走完所有 Task（含 `Map` 的 `ItemProcessor`／`Iterator` 與 `Parallel` 的 `Branches`）收齊全部問題，再**包裝** Phase 29 的 `assert_safe_asl`：後者在第一個問題就丟 `PermanentError`，所以只把它的訊息當最後一筆追加，`StartAt`、`Choice` 的 `Default`、同層 `Fail` 這些結構規則不必重寫一次。`LAMBDA_SERVICE_ERRORS` 逐字對應裁決 D-53 的第二條 retrier；Phase 29 的 `RETRY` 依 D-53 已含兩條時本檢查等於只比對它，常數存在是為了讓「第二條不見了」有明確訊息。

- [ ] **Step 4：對三份 ASL 執行並準備真 AWS 驗收**

三份定義由 P41（`ticket-analysis`）、P48（`feedback-review`）、P52（`release-update`）建立，路徑樣板就是 Phase 29 的 `ASL_LOCAL_PATH`（`infra/stepfunctions/{pipeline}/v{number}.json`）；**掃不到任何檔案時 `main` 要印「找不到 ASL 定義」並回非 0，不得靜靜回 0**（現況核對 2026-09-14：本 Phase 開工前這個目錄還不存在）。從 repo 根目錄執行 `uv run python -m infra.scripts.check_asl`，它會掃 `infra/stepfunctions/<pipeline>/v<n>.json` 三份定義並全部印 `[通過]`；真 AWS 案例以 `TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_recovery.py -m aws -q` 單獨執行。真 AWS 案例標 `@pytest.mark.aws`（marker 由 Phase 01 在 `pyproject.toml` 註冊），Phase 01 的 conftest 在 `TKB_RUN_AWS_INTEGRATION` 未設時自動 skip，一般開發不必加 `-m` 參數。每跑一次就把證據寫進 `docs/plan/report/recovery-<YYYYMMDD-HHMM>.md`，固定欄位為：切點名稱、注入方式、`execution_arn`、`describe_execution` 的 `status`／`error`／`cause` 與讀取時間、注入後的 `current_version` 與 `site/` 清單、重送後的 `version_id` 與 `site/` 清單、模型呼叫數差值、結論（PASS／FAIL／O3 缺口）。沒有這份紀錄就不算完成。

- [ ] **Step 4A：承接 Phase 24／25「延後至 P41／P59」的真實 AWS 驗收**（新增，controller 2026-09-14 裁決 R1）

這一步只做**發布切點的重跑與復原**，部署與正常流程的雲端證據歸 Phase 41，不重做。全部指令帶 `--region us-east-1`。逐項留證，做不到的標 BLOCKED 並附錯誤原文：

1. **真實 S3／DynamoDB 上重跑切點 3 與切點 4（單篇）** —— 直接呼叫 `Publisher.prepare`／`commit` 並用 `TKB_FAULT` 注入，不需要模型，**不受 O5 BLOCKED 影響**。每次記下：注入前後的 `TUTORIAL.current_version`、`VERSION.published_at`（`get-item --consistent-read`）、`aws s3api list-objects-v2 --prefix site/tutorials/<slug>/` 的清單。
2. **真實 S3 上重跑多篇切點（對應 Phase 12 的 `a3_after_first_site_before_second`）** —— 承接 P25 §11 那一列。**預期會重現 partial（A 新 B 舊）**：O3 是 FAIL，這裡只記錄觀察，不得改寫成通過、不得刪頁回滾、不得放寬 F49。
3. **website endpoint 人工驗收**（承接 P24 §8／§11 與 P25 §8／§11）—— 注入當下用 `curl -i http://<bucket>.s3-website-us-east-1.amazonaws.com/tutorials/<slug>/v<n>.html` 讀舊版頁與（應該不存在的）新版頁，把兩個 HTTP 狀態碼與 body 前幾行、以及同一時刻的 `TUTORIAL` item 一起存進報告。**S3 website endpoint 只有 HTTP，報告不得寫成 HTTPS。**
4. **`resume_publish` 的真實 AWS 復原** —— 清掉 `TKB_FAULT`、以同一個 `operation_id` 呼叫 `resume_publish`，證明 `site/` 補齊、版號不變、`OPS#` 的 `model_output_refs` 不變。
5. **切點 5（`start_execution`）的真實 state machine 續跑** —— 用 Ticket 路徑（**Release 走不進 Rote：O6 有 4 列未核定**）。注入後確認沒有 execution；清掉開關重送，確認沿用同一個 execution name、`describe-execution` 的 `status` 與 `executionArn` 已留存。若 execution 進到需要模型的節點，**必然**因 O5 BLOCKED 走 `PermanentError → Catch → PipelineFailed`：用 `get-execution-history` 抓出那一段的 `error`／`cause` 原文貼進報告，標 **BLOCKED（O5）**，不標 FAIL、也不標 PASS。
6. **Step Functions console 人工驗收** —— 打開一個 FAILED 與一個重送後 SUCCEEDED（或 BLOCKED 時：兩個 FAILED，並註明原因不同）的執行，ARN 對照 `recovery-<YYYYMMDD-HHMM>.md`。

- [ ] **Step 5：提交** — `git add infra/scripts/check_asl.py tests/unit/test_check_asl.py` 後 `git commit -m "feat(infra): 檢查 ASL 的兩條 Retry 與 Catch"`。

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 無注入的建版與發布 | v2 發布成功，`site/tutorials/prepare-meeting/v2.html` 存在，`current_version` 指向 v2。 |
| Failure | 五個切點逐一注入 | 公開站仍讀到 v1；沒有 v2 公開物件；切點 1、2、3、5 的 `current_version` 不變。 |
| Failure | 多篇整批在任一切點失敗 | 兩篇同時維持舊狀態；不得出現 A 新 B 舊。 |
| Boundary | 切點 4 注入 | `current_version` 已切換但公開物件未寫；標為 O3 缺口，重送只依 `pending-promote.json` 補寫。 |
| Boundary | 同 operation 重送 | 同一版號、同一模型輸出 ref、重送期間模型呼叫數為 0。 |
| Boundary | 同一事件重送（同 `operation_id`） | 版本數、回饋樣本數、PROC `success_count` 三者都不變。 |
| Boundary | 同名 execution 已結束 | 先 `describe_execution` 並核對 operation 紀錄，`status == "done"` 才沿用，否則 `CoordinationError`。 |

**這張矩陣的每一列都分成兩類判定**（現況核對 2026-09-14，依 controller R1 與 gate 現況）：

| 類別 | 哪些列 | 怎麼判 |
|---|---|---|
| **可實證** | 上表 Happy、Failure 前兩列、Boundary 的同 operation 重送／同事件重送／closed execution；以及 §7 Task 3 Step 4A 的第 1、3、4、6 項 | 在 moto **與** 真實 `us-east-1` 各跑一次都成立才算過；證據就是 `recovery-<YYYYMMDD-HHMM>.md` 的欄位。 |
| **BLOCKED／FAIL 如實記錄** | 切點 4 那一列（O3 缺口）、多篇整批的真實 AWS 重跑（`a3` partial，**O3 = FAIL**）、任何進到模型節點的雲端執行（**O5 = BLOCKED**）、Release 端到端（**O6 4 列未核定**） | **照實記錄觀察到的結果與錯誤原文**，不得改寫成通過、不得放寬 F49、不得刪頁回滾、不得填猜測的 model ID。報告在該列寫 `FAIL（O3）`／`BLOCKED（O5）`／`BLOCKED（O6）`，並附 gate 報告路徑。 |

人工驗收：在 Step Functions console 打開一個 FAILED 與一個重送後 SUCCEEDED 的執行（O5 BLOCKED 時退化成兩個 FAILED，並註明失敗原因不同），對照 `recovery-<YYYYMMDD-HHMM>.md` 的 ARN；同時用瀏覽器打開公開站（**HTTP** website endpoint，S3 website 沒有 HTTPS）確認注入期間讀到的是舊版。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 重送後出現 v3 | 重送重新配置版號 | 停止；改為從 operation 紀錄讀回 `version_id`。 |
| 重送時模型被再呼叫一次 | 沒有重用 `model_output_refs` | 停止；儲存階段重試必須重用既有輸出。 |
| A 已公開、B 失敗卻宣稱整次未發布 | 在 Map 內逐篇 publish | 停止；改成全部 prepare／inspect 後整批 commit，保留 FAIL。 |
| 切點 4 被寫成「已通過」 | 把補償當成原子性 | 改寫成 O3 缺口與補償結果；Phase 12 未 PASS 前不得宣稱通過。 |
| 正式環境仍會注入失敗 | 沒設 `TKB_ENV=prod` 或忘了清 `TKB_FAULT` | 停止部署；部署清單必須包含這兩項檢查。 |
| `ExecutionAlreadyExists` 直接當成功 | 誤把冪等當結果 | 先 `describe_execution` 並核對 operation 紀錄再判定。 |
| `check_asl_document` 對正確的 ASL 也報錯 | Phase 29 的 `RETRY` 還只有一條 retrier | 回 Phase 29 補上裁決 D-53 的第二條，不在本 Phase 放寬檢查。 |

## 10. 來源與 Rule 對照

本 Phase 是驗收型，沒有 primary Rule；下列都是「相關」，直接斷言由括號內的 primary Phase 負責，本 Phase 只在失敗復原情境下再驗一次（[00B](./00B-需求覆蓋對照.md) 第 2、3.2 節）。

- [接入來源事件.feature](../../spec/features/接入來源事件.feature) Rule 30：「同一正規化事件重送時只處理一次」→ 相關（primary Phase 10）；Task 2 斷言重送後版本數、回饋樣本數與 PROC `success_count` 都不變。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature) Rule 2：「任一 pipeline 修改既有教學時使用該篇的下一個版本號」→ 相關（primary Phase 20）；Task 2 斷言同 operation 重送沿用同一 `version_id`，並以 lease 串行同篇的 Release 與 Feedback。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature)：Rule 2「教學 pipeline 依 Step Functions 預定義節點執行」、Rule 6「每個 Step Functions Task 設定 Retry」、Rule 7「每個 Step Functions Task 設定 Catch」、Rule 10「Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json`」→ 四條都是相關（primary Phase 29）；Task 3 的 `check_asl_document` 只檢查既有三份 `infra/stepfunctions/<pipeline>/v<n>.json`，不新增節點也不改快照契約。
- [發布教學版本.feature](../../spec/features/發布教學版本.feature) Rule 4：「Tutorial 的 current_version 指向目前教學版本」、Rule 5：「已上架的版本具有 published_at」→ 相關（primary Phase 24）；Task 2 的切點矩陣直接觀察這兩個欄位。
- 設計 §8.3（發布與併發界線、多篇整批不得部分發布）、§14.1（S3／DynamoDB 部分寫入時保留不可公開的未完成版本）、§14.2（重試不是重新抽一次文字、`ExecutionAlreadyExists` 不等於成功）、§15（版本與發布、接入去重、呼叫與失敗三列驗收）、§16（S3「中途失敗仍讀舊版」、S8「一次儲存失敗復原」）、§18 O2／O3。
- [Step Functions StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)：同名同 input 的冪等只涵蓋仍在執行的案例。
- [describe_execution（boto3）](https://docs.aws.amazon.com/boto3/latest/reference/services/stepfunctions/client/describe_execution.html)：回傳 `status`、`error`、`cause`，且是最終一致讀取，證據要記下讀取時間。
- [Step Functions 錯誤處理](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)：`States.ALL` 並非涵蓋所有終止錯誤。

## 11. 完成清單

- [ ] `FAULT_POINTS` 恰為五個名稱，打錯字立刻報錯，`TKB_ENV=prod` 一律不注入。
- [ ] 五個切點分別落在 `content.py`、`publishing.py`、`ingress.py` 的真實路徑上，且各被呼叫一次。
- [ ] 每個切點注入後公開站仍讀到舊版，`site/tutorials/<slug>/` 沒有新版本頁、索引也沒有新連結。
- [ ] 多篇整批失敗時兩篇同時維持舊狀態，沒有 partial publish。
- [ ] 同 operation 重送沿用原版號與原模型輸出，重送期間模型呼叫數為 0；切點 4 依 `pending-promote.json` 補寫，單篇發布沒有這份清單時改用 operation 紀錄的 `version_id` 與 `site_key(...)` 重算同一份。
- [ ] 同事件重送不新增版本、回饋樣本或 PROC 成功樣本；closed execution 先核對 `status == "done"` 再判定。
- [ ] `check_asl.py` 包裝 `assert_safe_asl`，對三份 ASL 全部 `[通過]`，刻意刪掉一個 Catch 或第二條 retrier 時會失敗。
- [ ] Phase 12 與本 Phase 的兩套切點名稱有對照表，兩邊都沒有改名。
- [ ] `recovery-<YYYYMMDD-HHMM>.md` 有 execution ARN 與前後狀態；未完成前不宣稱 publish 故障驗收已通過。
- [ ] **（承接 Phase 24 §11）真實 AWS 上重跑單篇三個切點，並用公開 website endpoint（HTTP）做人工驗收**，證據在 `recovery-<YYYYMMDD-HHMM>.md`。
- [ ] **（承接 Phase 25 §11）真實 AWS 上重跑多篇五個切點，用公開 website endpoint 的 HTTP 回應同時讀 A 與 B 兩頁存證**；出現 partial 就標 `FAIL（O3）`，不改寫成通過。
- [ ] `resume_publish` 的 `a2` 復原在真實 AWS 上驗過：**先 `Publisher.prepare` 再 `promote_site_objects`**，補齊後 `site/` 頁面不含 `data-published="false"`。
- [ ] 需要模型的雲端節點在報告中標 `BLOCKED（O5）` 並附 `get-execution-history` 的 `error`／`cause` 原文；Release 端到端標 `BLOCKED（O6）`。未執行的項目一律不標 green。
