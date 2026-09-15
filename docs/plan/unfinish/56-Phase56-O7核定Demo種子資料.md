# Phase 56：O7 核定 Demo 種子資料實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **（a）已存在、可直接用的東西**
>
> - `src/training_kb/pipelines/ticket.py`：`ensure_embedding(ticket, *, writer, repository, operation_id) -> Ticket`、`assign_cluster(ticket, *, repository) -> str`、`new_cluster_id(existing)`、`CLUSTER_COSINE_THRESHOLD`（＝`Thresholds().cosine_match`，不是第二份字面值）。`src/training_kb/vectors.py`：`cosine`、`centroid`。
> - `src/training_kb/content.py`：`verify_version_complete(version_id, repository) -> bool`（P23）、`parse_version_id`、`render_markdown`、`make_diff`、`markdown_key`、`diff_key`、`put_private_artifact`。
> - `src/training_kb/keys.py`：`view_pk(tutorial_version, user, ts)` **已經實作了設計 §9.1 的正規化 SHA-256**，`apply_seed` 不必自己算；另有 `tutorial_pk`／`version_pk`／`feature_pk`／`ticket_pk`／`release_pk`／`feedback_pk`／`rule_pk`／`step_pk`／`edge_sk`／`RELATIONS`。
> - `src/training_kb/repository.py`：`put_meta`、`put_edge`、`put_object`、`get_steps`、`list_feedback_of_version`／`list_views_of_version`／`list_tickets`／`list_rules`、`list_versions_of_tutorial`。
> - `src/training_kb/models.py` 的十個模型都是 `StrictModel`（`extra="forbid"`）：`Ticket.cluster_id`／`embedding` 預設 `None`、`embedding` 必須是 **1024 個有限數**；`Feedback.rating` 是 `mode="before"` 的 strict int 1–5（`True`／`"4"` 一律拒絕）；`Feedback` **沒有** `project_id`；`TutorialView` **只有** `tutorial_version`／`user`／`ts` 三欄；`AuthoringRule.evidence` 需要 **至少 5 個不同** Feedback ID。種子 JSON 多帶任何欄位都會被 `extra="forbid"` 擋下。
> - `tests/unit/conftest.py`：`RecordingWriter`（`embed` 回 `FIXED_EMBEDDING`、記 `calls`／`request_attempts`）、`fake_writer` fixture、`FIXED_EMBEDDING = [0.001] * 1024`。
> - `src/training_kb/config.py`：`DEFAULT_PROJECT_ID = "demo"`、`load_settings()`。
>
> **（b）文件因上一批裁決／實作而修正的點**
>
> 1. **§5 Consumes 裡 P43／P53／P54／P55 的名稱在本批都還不存在**（實測 grep `src/` 全無）：`DEFAULT_FEEDBACK_CATEGORIES`（P43）、`average_rating`／`negative_feedback_ids`／`format_average`（P53）、`reopen_stats`／`version_metrics`（P54）、`SeedBatch`／`evaluate_batch`／`next_status`（P55）。模組落點依 00A §3.2：`analytics/ratings.py`（P53）、`analytics/reopen.py`＋`analytics/version.py`（P54）、`analytics/validation.py`（P55）、`ingress.py`＋`config` 的類別表（P43）。
> 2. **波次順序（controller ledger）是 W1：P53 ∥ P56；W2：P54；W3：P43 ∥ P55。** 本 Phase 在 W1 時 `reopen_stats`（P54）、`SeedBatch`（P55）、`DEFAULT_FEEDBACK_CATEGORIES`（P43）都還沒有人寫出來 → §7 已加「Task 排序與缺件處理」，八個目標數字裡的四個（reopen count／rate）與 `batches.json` 的型別化必須依序處理，不得自己另寫一份公式（違反 00A §6.9 的單一實作原則）。
> 3. **`demo/` 目前不存在**，而且不是可 import 的位置：`pyproject.toml` 的 `[tool.setuptools.packages.find] where = ["src"]` 不涵蓋它、`mypy` 的 `files = ["src", "infra"]` 不含它、COMMON.md 的 `ruff check src tests infra` 也不含它。**實測：pytest 執行時專案根目錄不在 `sys.path`，`import demo` 直接 `ModuleNotFoundError`。** §4 與 §7 Task 1 已補上處理方式。
> 4. **`tests/unit/conftest.py` 這一批只有 P55 可以動**（COMMON.md R3.6）→ §7 Task 1 Step 1 的 `seed_dir` 系列 fixture 改放在 `tests/unit/test_seed_recipe.py` 自己檔案裡（與 P23／P24／P26 把共用器材留在使用它的測試檔的既有做法一致）。
> 5. `Release.source_event_id` 用**簡寫** `gh-pr-42`，**不套** P13 的 `github_source_event_id`（00A §6.7「種子配方固定值」列已明文；同 D-47 的精神，合成與真實各自成套）。
> 6. `Writer.embed(text, *, operation_id, node) -> list[float]` 的 `node` 是**必填** keyword；`CallTrace` 的 record 欄位固定是 `TRACE_FIELDS` 七欄。
>
> **（c）gate 現況對本 Phase 的影響**（COMMON.md §2）
>
> - **O5 BLOCKED**（2026-09-14 20:0x 重 probe，Titan 與 Claude 都回 `ValidationException: Operation not allowed`；報告 `docs/plan/report/o5-20260915T030245Z.md`）→ **§6.7 的「20 筆真實 Titan embedding 分群」這一批做不出來。** 處理方式見 §6.7 與 §7 Task 3 的改寫：schema／重算／守門測試用 `RecordingWriter`＋`FIXED_EMBEDDING` 完成，`cluster_demo_tickets.py` 保留真實呼叫路徑但執行結果記 **BLOCKED（附實際錯誤原文）**，`clustering_report.json` 的 `observed` 區塊留空並註明原因；**不得**回退成預填 `cluster_id`，也**不得**把 skip 當 PASS。
> - **O7 未到，本 Phase 是首驗 Phase。** 程式綠燈只能關掉 schema 與重算兩條；`approvals/*.json` 的四個維護者欄位一律留空，報告收在「O7 = 未完成（缺維護者核定）」。
> - **O4 未到**（P54 首驗）：`reopen_stats` 的 UTC `[p, p+14 days)` 端點尚未核定，重算出的 0.7／0.2 帶著未定狀態，報告不得宣稱重開票率已有規格答案。
> - O3 FAIL、O6 待核定、O1 provisionally accepted：與本 Phase 沒有直接相依（種子不發布、不走 Rote、不碰 `approved-sources.json`）。
>
> **（d）適用的 controller 裁決（COMMON.md §3）**
>
> - **R1**：本 Phase 唯一的真實 AWS 是 Bedrock Titan，O5 BLOCKED 時照實記 BLOCKED，不填猜測值、不假裝通過。
> - **R3**：`demo/` 下 P56 與 P58 的檔案不重疊（00A §3.2）；但 `pyproject.toml` 是共用檔（P58 要加 `streamlit`），只用 Edit、各自區段、`git add` 只加自己的路徑。
> - **R5**：本文件的程式碼片段是示意，00A ＋ 既有程式是契約，衝突時以後者為準。
> - **R6**：逐 Task 先紅燈再綠燈，報告要有 RED／GREEN 的指令與輸出。
> - **R10**：需要維護者決定的事自己裁決、標「本計畫選擇」寫進文件與報告，繼續做。

**目標：** 把設計 §11 的 Demo 配方展開成可載入、可重算、可核定的種子資料，並留下維護者核定紀錄，讓 O7 的三個條件各自有獨立證據。

**架構：** `demo/seed/*.json` 是純資料；`demo/seed_loader.py` 負責 schema 驗證與寫入；`verify_recipe()` 用 Phase 53／54 的函式重算八個目標數字；`demo/scripts/cluster_demo_tickets.py` 用**真實 Titan embedding** 對二十筆工單分群。程式只能完成 schema 與重算，維護者核定必須由真人簽署。

**技術：** Python 3.12、Pydantic v2、JSON、Amazon Bedrock Titan Text Embeddings V2、pytest。

## 全域限制

- 唯一主來源是 [Training KB 設計 §11.1–§11.5、§12.2、§12.3、§18 O7](../../design/training-kb.md)。`O5`、`O7` 是設計 §18「待確認事項」的編號（O5 = 模型與參數驗證，O7 = 核定種子與外部設定）。
- 前置為 [Phase 55：規則驗證與狀態轉移](./55-Phase55-規則驗證與狀態轉移.md)；真實 embedding 另需 [Phase 14](./14-Phase14-O5模型可用性與參數驗證.md) 的 O5 gate 與 [Phase 38](./38-Phase38-Ticket-Embedding與群中心分群.md) 的分群函式。下一階段是 [Phase 57：S3 靜態教學站與回饋下載](./57-Phase57-S3靜態教學站與回饋下載.md)。（現況核對 2026-09-14：本批的實作波次是 **W1：P53 ∥ P56**、W2：P54、W3：P43 ∥ P55，所以「前置為 P55」在排程上**不成立**；P38 已完成可直接用，P43／P53／P54／P55 的名稱在 W1 時還不存在，缺件處理見 §7 開頭的「Task 排序與缺件處理」。）
- **gate 現況（2026-09-14，取代本文件原本的「待驗證」措辭）：O5 BLOCKED**（Titan／Claude 皆 `ValidationException: Operation not allowed`，報告 `docs/plan/report/o5-20260915T030245Z.md`）→ 真實 embedding 分群做不出來，照 §6.7／§7 Task 3 記 BLOCKED；**O7 未到**，本 Phase 首驗，程式只能關 schema 與重算兩條；**O4 未到**（P54 首驗），14 天窗口端點未核定；O3 FAIL、O6 待核定與本 Phase 無直接相依。
- **O7 的三個條件是 schema 通過、重算通過、維護者核定；三者分開記錄，缺一即 O7 未完成。** 程式綠燈只能關閉前兩個；核定欄位由程式自動填入即視為造假。
- 所有種子都是**明示合成資料**：每個檔案帶 `"synthetic": true`，畫面固定標「合成資料示範」與資料批次；不得描述成原始觀測、實測結果或真實使用者成效。設計 §12.3：重算出的評分差與重開票率差只是觀察結果，不宣稱因果、不當成實測成效。
- 模擬 `published_at` 只用於歷史回放，不套在本次真實發布上；即時操作使用真實執行時間。
- 所有使用者一律 `u_01` 這種形狀（D-47：真實 GitHub 的 `u_gh-<id>` 不進本批資料，也不建對照表）；`project_id` 一律 `demo`（D-34 的 `DEFAULT_PROJECT_ID`）。
- 二十筆建立教學用工單的 `cluster_id` **必須**由真實 Titan embedding 產生；不可全部預填。九筆重開票工單的 `cluster_id = c12` 是設計 §11.3 明列的固定同題對應，屬配方數值，不由 embedding 決定。
- 本階段不做：不部署 AWS 資源、不公開任何內容、不建立正式 Tutorial、不改規則狀態（那是 Phase 55 的 `apply_rule_status`）、不做 B 的規則開關預覽（Phase 58）。
- 以下程式檔與資料檔均是實作時預計建立；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
設計 §11 配方（文字） --> +------------------------------------------------+
                         | [你在這裡] demo/seed/*.json                    |
                         |  load_seed            -> schema 通過           |
                         |  verify_recipe        -> 2.875/4.4/8/2/7/2/    |
                         |                          0.7/0.2               |
                         |  cluster_demo_tickets -> 20 筆真實 Titan 分群  |
                         |  approvals/*.json     -> 維護者簽署（不能代簽）|
                         +------------------------------------------------+
                              |              |                 |
                              v              v                 v
                         Phase 55 批次  Phase 57 站台資料  Phase 58 預覽
三個條件都成立 -> O7 完成；任一缺 -> O7 未完成
```

## 2. 完成後看得到什麼

```text
$ uv run python -m demo.seed_loader verify demo/seed
[合成資料示範] batch=demo-seed-01 synthetic=true
  A v1 average        expected 2.875  actual 2.875  OK  | A v2 average       4.4  4.4  OK
  A v1 negative count expected 8      actual 8      OK  | A v2 negative count 2    2    OK
  A v1 reopen count   expected 7      actual 7      OK  | A v2 reopen count   2    2    OK
  A v1 reopen rate    expected 0.7    actual 0.7    OK  | A v2 reopen rate    0.2  0.2  OK
schema=PASS  recompute=PASS  approvals=MISSING(R007-B1, R012-B1, R012-B2)
O7 = 未完成（缺維護者核定）
```

維護者簽好 `demo/seed/approvals/*.json` 後，最後兩行才會變成 `approvals=PASS` 與 `O7 = 三條件齊備`。程式永遠不會自己把 `approvals` 變成 PASS。

（**實作核對 2026-09-15，取代上一行的 W0 註記：上面就是實際輸出**——八個數值、`schema=PASS  recompute=PASS  approvals=MISSING(...)` 與最後一行都相符（只有右欄的空白寬度略有不同）。P54 的 `reopen_stats` 已經落地，所以八項全部算得出來、`recompute=PASS`。W0 當時預期的 `actual=n/a` 與 `recompute=PARTIAL` **沒有發生**。最後一行仍然是 `O7 = 未完成（缺維護者核定）`，因為三批核定全缺；輸出存在 `demo/seed/recipe-report.txt`。）

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 種子（seed） | 事先準備好的合成資料，用來讓流程與指標有東西可算。 |
| 配方（recipe） | 設計 §11 規定這些資料該長什麼樣、該算出哪些數字。 |
| 重算 | 不用預存數字，直接把原始回饋／瀏覽／工單餵進 Phase 53／54 的函式再算一次。 |
| 核定批次 | 一次規則驗證所需的完整前後資料，外加維護者簽名；簽名一定要真人做，程式不能代簽。 |
| 真實分群 | 二十筆工單各自送 Titan 取得 1024 維向量，再依 cosine 分群，而不是把答案寫死。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `demo/seed/` 下的 `features.json`、`tutorials.json`、`versions.json`、`steps.json`、`releases.json`、`feedback.json`、`views.json`、`tickets.json` | 產品功能、四篇教學與版本內容、`r_42`、回饋、瀏覽、工單。 |
| 新增 | `demo/seed/rules.json`、`batches.json`、`approvals/<batch_id>.json` | `R-007`、`R-012` 與維護者核定紀錄。 |
| 新增 | `demo/seed_loader.py` | `SeedBundle`、`load_seed`、`verify_recipe`、`apply_seed`。 |
| 新增 | `demo/scripts/cluster_demo_tickets.py` | 二十筆工單的真實 Titan embedding 分群。 |
| 新增 | `demo/__init__.py`、`demo/scripts/__init__.py` | （現況核對 2026-09-14 補）`demo/` 目前不存在，而且測試 `from demo.seed_loader import ...` 需要它是可 import 的套件。 |
| 測試 | `tests/unit/test_seed_recipe.py` | schema、重算八個數字、核定缺漏。**`seed_dir` 系列 fixture 放這一檔**（不動 `tests/unit/conftest.py`，那支這一批只有 P55 能改，COMMON.md R3.6）。 |
| 測試 | `tests/integration/test_demo_clustering.py` | O5 通過後的真實 embedding 分群證據；O5 BLOCKED 時 `@pytest.mark.aws` 自動 skip。 |

**（現況核對 2026-09-14）讓 `demo` 可以被 import。** 實測：`uv run pytest` 時專案根目錄**不在** `sys.path`（`pyproject.toml` 的 `[tool.setuptools.packages.find] where = ["src"]` 只安裝 `training_kb`），所以 `import demo` 會 `ModuleNotFoundError`。既有專案對 `infra/` 的做法是在測試檔頂端手動插路徑（`tests/unit/test_data_stack.py`、`tests/unit/test_check_models.py`）。**本計畫選擇：** 在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 加一行 `pythonpath = ["."]`（pytest 8 內建支援，不需要外掛），讓 `demo` 與 `infra` 一起變成可 import；理由是本 Phase 與 P58 共七支測試檔都要 import `demo`，逐檔複製 `sys.path` 樣板會讓同一段程式碼出現七次。`pyproject.toml` 是共用檔，只用 Edit、只加這一行（R3）。同時把 `demo` 加進 `mypy` 的 `files`（`files = ["src", "infra", "demo"]`）與 lint 指令（`uv run ruff check src tests infra demo`），理由是 `demo/seed_loader.py` 會被 P58 的 `cli.py` import，是實際執行路徑，不是一次性腳本；若 W1 時 mypy 對 `demo` 紅燈且不是本 Phase 造成的，改為維持 `files = ["src", "infra"]` 並在報告寫明（COMMON.md R10）。

**（實作核對 2026-09-15）§4 與 §5 與實作的七處差異，都是「本計畫選擇（2026-09-14）」：**

1. **`SeedBundle` 多一個 `contents: tuple[TutorialContent, ...]` 欄位。** §5 的 Produces 草圖只列了九個實體與 `batches`，但每個版本的 Title／Problem／Prerequisites／Expected Outcome 是**種子資料**，不能由程式生成——那等於把配方藏進程式碼，維護者就無法逐檔核對（§8 的人工驗收）。落點：四段文字放 `versions.json` 的 `content` 區塊、步驟放 `steps.json`，`load_seed` 合成 `TutorialContent`。00A §6.9 只訂 `verify_recipe(bundle) -> RecipeReport` 的簽名，沒有訂 `SeedBundle` 的欄位，所以這不違反契約。
2. **`versions.json` 的每一筆是 `{"version": {...}, "content": {...}}`**，不是攤平的欄位：`TutorialVersion` 是 `extra="forbid"`，攤平就得在解析前先 pop 四個鍵，不如把兩者分開放得明白。
3. **`batches.json` 的 `approved_by`／`approved_at` 是空字串，`load_seed` 把它們讀成 `None`。** §6.6 要求留空字串，但 `SeedBatch.approved_by` 的型別是 `str | None`，而 `evaluate_batch` 判「已核定」看的是 `is not None`——空字串會讓未核定的批次被判成已核定。所以批次的核定值**只從 `approvals/<batch_id>.json` 讀**：四個欄位都非空且 `seed_commit` 等於目前十份種子檔的 SHA-256 才填進 `SeedBatch`，否則兩個欄位都是 `None`。
4. **`clustering_report.json` 比 §6.7 的樣板多四個欄位**：`_notice`（合成聲明，與十份種子檔一致）、`operation_id`、`model_id`（人工核對時要知道打的是哪一顆模型），以及 `upstream`——記 botocore `ClientError` 的訊息原文。產品程式（`BedrockWriter`）刻意只保留錯誤碼（message 可能回聲使用者輸入），但 §6.7 要求 BLOCKED 報告帶錯誤原文，而這支腳本的輸入是版控在 repo 裡的合成工單文字、沒有使用者資料，所以在腳本端從例外鏈補記一次。
5. **`tests/integration/test_demo_clustering.py` 同時放 moto 與 `aws` 兩段。** 00A §3.3 只配給本 Phase 一個整合測試檔名，而 `apply_seed` 需要真的 `Repository`（`verify_version_complete` 要查基表與 S3）。上半段是 moto、不標 marker；下半段標 `@pytest.mark.aws`。
6. **兩個真實 Titan 測試另外標 `xfail(strict=False)`。** 只標 `aws` 的話，設了 `TKB_RUN_AWS_INTEGRATION=1` 的人會看到「測試失敗」而不是「O5 BLOCKED」；`strict=False` 讓它在 O5 開通後 xpass，提醒把標記拿掉。**skip 與 xfail 都不等於 PASS。**
7. **`apply_seed` 補寫 `FEEDBACK#<id> --REFERS_TO--> VERSION#<version_id>` 邊，並用 `now` 擋未來時間。** 前者是 `Repository.list_feedback_of_version` 的唯一索引（與 `ingress._complete_feedback` 同一條邊），少了它指標一筆都掃不到；後者把 §全域限制的「模擬 `published_at` 只用於歷史回放」變成可執行的檢查——晚於載入時間的版本一律 `ContentError`。

**本計畫選擇（2026-09-14）：不把種子施作到真實 `training_kb` 表。** 理由三條：（a）本 Phase 不在 controller R1 的六個實機 Phase 名單內，§全域限制也明寫「不部署 AWS 資源」；（b）種子含一條 `status=active` 的 `R-012` 與四篇 `published_at` 非空的教學，寫進共用表會改變 P59／P60 真實執行時 `rules_for_content` 取到的規則集合，也可能讓 P57 的站台索引重建把合成教學放上公開 `site/`；（c）`TrainingKbData` 的 data role 只允許 `SK begins_with APPLIED_TO#` 的 `DeleteItem`（D-79），約 180 筆 item 無法用產品路徑清理。P58 的 dashboard 不需要真實表——它 import `demo/seed_loader.py`，`load_seed` ＋ `verify_recipe` 就拿得到全部數字；真的要真實資料時，一行 `apply_seed(load_seed(Path("demo/seed")), repository=..., now=clock.now_utc())` 即可，風險與清理成本由維護者決定。

## 5. 固定介面

### Consumes

```text
# 已存在（可直接 import）
training_kb.models       Feature / Tutorial / TutorialVersion / TutorialStep / Release /
                         Feedback / TutorialView / Ticket / AuthoringRule（全是 StrictModel）
training_kb.repository   Repository.put_meta / put_object / put_edge / get_steps / list_*
training_kb.keys         view_pk(tutorial_version, user, ts)  ← 設計 §9.1 的 SHA-256 已實作
training_kb.content      verify_version_complete(version_id, repository) -> bool      # P23
                         parse_version_id / render_markdown / make_diff / markdown_key / diff_key
training_kb.pipelines.ticket
                         ensure_embedding(ticket, *, writer, repository, operation_id) -> Ticket
                         assign_cluster(ticket, *, repository) -> str                 # P38
                         new_cluster_id(existing) / CLUSTER_COSINE_THRESHOLD
training_kb.writing      Writer.embed(text, *, operation_id, node) -> list[float]     # P15/16
training_kb.config       DEFAULT_PROJECT_ID = "demo" / load_settings()                # P02
tests/unit/conftest.py   RecordingWriter / fake_writer / FIXED_EMBEDDING（1024 個 0.001）

# 本批才會出現（現況核對 2026-09-14：目前 src/ 裡一個都沒有，模組落點依 00A §3.2）
training_kb.analytics.ratings     average_rating(feedback) -> float | None
                                  negative_feedback_ids(feedback, approved) -> ...     # P53（W1）
training_kb.analytics.reopen      reopen_stats(views, tickets, *, cluster_id,
                                               published_at) -> ReopenStats            # P54（W2）
training_kb.analytics.version     version_metrics(version_id, *, repository,
                                               approved, project_id) -> VersionMetrics # P54（W2）
training_kb.analytics.validation  SeedBatch / evaluate_batch / next_status             # P55（W3）
training_kb.<P43 的落點>          DEFAULT_FEEDBACK_CATEGORIES
                                  = frozenset({"找不到按鈕", "缺少資訊"})              # P43（W3）
```

### Produces

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

@dataclass(frozen=True)
class SeedBundle:
    batch_label: str
    synthetic: bool
    features: tuple["Feature", ...]
    tutorials: tuple["Tutorial", ...]
    versions: tuple["TutorialVersion", ...]
    steps: tuple["TutorialStep", ...]
    releases: tuple["Release", ...]
    feedback: tuple["Feedback", ...]
    views: tuple["TutorialView", ...]
    tickets: tuple["Ticket", ...]
    rules: tuple["AuthoringRule", ...]
    batches: tuple["SeedBatch", ...]

@dataclass(frozen=True)
class RecipeCheck:
    name: str
    expected: float
    actual: float | None
    ok: bool

@dataclass(frozen=True)
class RecipeReport:
    checks: tuple[RecipeCheck, ...]
    schema_ok: bool
    recompute_ok: bool
    approved_batch_ids: tuple[str, ...]
    missing_approvals: tuple[str, ...]
    o7_ready: bool   # schema_ok and recompute_ok and not missing_approvals

def load_seed(directory: Path) -> SeedBundle: ...
def verify_recipe(bundle: SeedBundle) -> RecipeReport: ...
def apply_seed(bundle: SeedBundle, *, repository: "Repository", now: datetime) -> tuple[str, ...]: ...
def cluster_demo_tickets(
    bundle: SeedBundle, *, writer: "Writer", repository: "Repository", operation_id: str
) -> dict[str, str]: ...
```

`o7_ready` 是三個布林的 `and`，不是別名；任何一個為假時 `o7_ready` 必須為假，且 `missing_approvals` 要列出缺哪一批。

## 6. 種子配方

以下表格的欄位與數值可直接展開成 JSON。所有時間為 UTC，`synthetic` 一律 `true`。

### 6.1 Feature（`features.json`）

`FEATURE` 的 PK 在第一次建立時固定，改名只改 `name` 與 `aliases`（D06）。

| `feature_id`（PK 後綴） | 種子載入時 `name` | `aliases` | 用在哪 |
|---|---|---|---|
| `Prepare` | `Meeting Summary` | `[]` | A 第 3 步；PR #42 改名對象 |
| `Open Meeting`／`Meeting List` | 同名 | `[]` | A 第 1、2 步（`Open Meeting` 也是 B 第 1 步） |
| `Share Link`／`Share Summary` | 同名 | `[]` | B 第 2、3 步 |
| `Settings Page`／`Notification Settings`／`Notification Channel` | 同名 | `[]` | C 第 1、2、3 步 |
| `Export Notes` | 同名 | `[]` | A／B／C 第 4 步 |
| `Weekly Digest` | 同名 | `[]` | D 各版第 3 步（R-012 證據） |

`first_seen` 一律 `2026-07-01T00:00:00Z`。PR #42 流程執行後，`Prepare` 的 `name` 變成 `Prepare`、`aliases` 變成 `["Meeting Summary"]`，PK 不動。**本計畫選擇：** 設計 §9.1 說 Feature PK 用「建立時名稱」，但 §9.2、§10、§11.1 的具名例子一律寫 `FEATURE#Prepare`；本配方依後者固定 PK 後綴為 `Prepare`，並在改名測試中不從 PK 反推顯示名稱。

### 6.2 Tutorial 與版本（`tutorials.json`、`versions.json`、`steps.json`）

| slug | topic | `cluster_id` | `current_version` | `status` |
|---|---|---|---|---|
| `prepare-meeting` | 準備會議 | `c12` | `prepare-meeting@v2` | active |
| `share-summary` | 分享摘要 | `c31` | `share-summary@v1` | active |
| `notification-settings` | 設定通知 | `c47` | `notification-settings@v1` | active |
| `weekly-digest` | 每週摘要 | `c58` | `weekly-digest@v4` | active |

| `version_id` | `supersedes` | `reason` | `rules_applied` | 模擬 `published_at` |
|---|---|---|---|---|
| `prepare-meeting@v1` | null | `gap:c12` | `[]` | 2026-08-01T00:00:00Z |
| `prepare-meeting@v2` | `prepare-meeting@v1` | `feedback:8 則 找不到按鈕` | `["R-007"]` | 2026-08-20T00:00:00Z |
| `share-summary@v1` | null | `gap:c31` | `[]` | 2026-07-20T00:00:00Z |
| `notification-settings@v1` | null | `gap:c47` | `[]` | 2026-07-20T00:00:00Z |
| `weekly-digest@v1`～`@v4` | 逐版鏈接 | v1 `gap:c58`；v2～v4 `feedback:5 則 缺少資訊` | v2、v4 為 `["R-012"]` | 2026-06-01／06-20／07-01／07-20 |

`reason` 只有 00A 規定的三種形狀，`feedback:<n> 則 <category>` 的 `<n>` 是去重後的證據筆數。每個版本都是四步五段（Title／Problem／Prerequisites／Steps／Expected Outcome），每步**恰一個** Feature，`s3_key` 為 `tutorials/<slug>/v<n>.md`。A 的四步依序引用 `Open Meeting`、`Meeting List`、`Prepare`、`Export Notes`；B 引用 `Open Meeting`、`Share Link`、`Share Summary`、`Export Notes`；C 引用 `Settings Page`、`Notification Settings`、`Notification Channel`、`Export Notes`。**B 與 C 都不引用 `Prepare`**，這是 PR #42 只改 A 第 3 步的驗收前提。`prepare-meeting@v1` 是 `v1.diff` 為空的首版。

**本計畫選擇：** `share-summary@v1` 的 `rules_applied` 在種子中是 `[]`，因為載入當下 `R-007` 仍是 `candidate`；設計 §11.4 所說「後續正式 B v1 可採用規則」的那一次套用，由 Phase 58 在 `R-007` 轉 `active` 後跑正常 Ticket Analysis 產生**新的** B 版本並寫入 `rules_applied=["R-007"]`。種子不預寫，否則會在規則仍是 candidate 時就宣稱已套用，違反 §11.4 的順序。[檢視學習指標.feature](../../spec/features/檢視學習指標.feature) 中 `applied_to` 為三筆的 Example 是 `applied_count` 的計算輸入，Phase 54 已直接斷言，不要求種子長成那樣。

### 6.3 Release（`releases.json`）

只有一筆：`id` = `r_42`（合成上游 ID，與人看的 PR #42 分開）、`source_event_id` = `gh-pr-42`、`source` = `github_pr`、`kind` = `renamed`、`feature` = `Prepare`、`old_name` = `Meeting Summary`、`new_name` = `Prepare`、`evidence` = 「PR #42：將 Meeting Summary 改名為 Prepare」、`ts` = `2026-09-01T00:00:00Z`。

### 6.4 回饋與瀏覽（`feedback.json`、`views.json`）

完全照設計 §11.2、§11.3 展開。A v1 每筆 `comment` 為「第三步沒有指出按鈕在哪一頁與位置」；A v2 的 `f_101`／`f_102` 為「資訊仍不夠完整」，其餘 `comment` 為空。

| 版本 | Feedback ID | user | rating | category | `ts` |
|---|---|---|---:|---|---|
| A v1 | `f_12`／`f_15` | `u_01`／`u_02` | 2 | 找不到按鈕 | 2026-08-02T00:00:00Z |
| A v1 | `f_19`、`f_23`、`f_27`、`f_31`、`f_34` | `u_03`～`u_07` | 3 | 找不到按鈕 | 同上 |
| A v1 | `f_40` | `u_08` | 4 | 找不到按鈕 | 同上 |
| A v2 | `f_101`／`f_102` | `u_01`／`u_02` | 2 | 缺少資訊 | 2026-08-21T00:00:00Z |
| A v2 | `f_103`～`f_110` | `u_03`～`u_10` | 5 | 空 | 同上 |

| 項目 | A v1 | A v2 |
|---|---|---|
| 瀏覽 | `u_01`～`u_10` 各一筆，`2026-08-02T09:00:00Z` | 同十人各一筆，`2026-08-21T09:00:00Z` |
| 重開票 | `t_2001`～`t_2007` 由 `u_01`～`u_07`，`2026-08-03T10:00:00Z` | `t_2101`／`t_2102` 由 `u_01`／`u_02`，`2026-08-22T10:00:00Z` |

`TUTORIAL_VIEW` 的 PK 依設計 §9.1，為正規化 `[tutorial_version, user, ts]` 固定 JSON 編碼的 SHA-256。九筆重開票工單的 `source` 為 `email`、`project_id` 為 `demo`、`author` 依表中使用者、`text` 為「看過準備會議教學後，仍找不到第三步的按鈕」、`cluster_id` 為 `c12`。

### 6.5 建立教學用的二十筆工單（`tickets.json`）

`id` 是 `t_1001`～`t_1020`、`author` 是 `u_11`～`u_30` 一對一、`project_id` 都是 `demo`；`source` 為 `email`（`t_1001`～`t_1014`）與 `discord`（`t_1015`～`t_1020`）；`ts` 平均散布於執行當日及前十三個 UTC 日期，每日一到兩筆；`text` 是同一功能的二十種不同問法（例如「會前摘要在哪裡開啟？」「如何看到開會前整理的重點？」「準備會議的摘要按鈕找不到」）；`cluster_id` 與 `embedding` 兩者皆 **`null`**，由 §6.7 的分群腳本用真實 embedding 填入。

### 6.6 規則與核定批次（`rules.json`、`batches.json`）

`applies_when` 存的是 `StepType` 的值（`click_ui`／`read`），不是 `"step.type == click_ui"` 這種條件字串（D-10）。

| `rule_id` | `rule` | `applies_when` | `status` | `evidence` | `derived_from` |
|---|---|---|---|---|---|
| `R-007` | click_ui 步驟要指出頁面與控制項位置 | `click_ui` | `candidate` | `f_12`～`f_40` 八筆 | `prepare-meeting@v1` |
| `R-012` | 每步不超過兩句 | `read` | `active` | `f_301`～`f_305` | `weekly-digest@v1` |

`batches.json` 的每一筆逐欄對應 Phase 55 的 `SeedBatch`：`slug`、`cluster_id`（A 為 `c12`、D 為 `c58`）、`project_id="demo"`、`synthetic=true` 都要寫出；`approved_by`／`approved_at` **留空字串**，由 `approvals/<batch_id>.json` 的維護者欄位填。

| `batch_id` | `rule_id` | before → after | 重算結果 | 預期 verdict |
|---|---|---|---|---|
| `R007-B1` | `R-007` | `prepare-meeting@v1` → `@v2` | 平均 2.875→4.4、rate 0.7→0.2 | `improved` |
| `R012-B1` | `R-012` | `weekly-digest@v1` → `@v2` | 平均 3.8→3.8（持平）、rate 0.4→0.3 | `not_improved` |
| `R012-B2` | `R-012` | `weekly-digest@v3` → `@v4` | 平均 3.5→3.9、rate 0.3→0.35（上升） | `not_improved` |

`R012-B1` 與 `R012-B2` 不共用任何 `version_id`，因此是設計 §12.2 要求的「兩個不重疊核定批次」。兩批的回饋、瀏覽與工單同樣展開成原始資料，`cluster_id` 一律 `c58`：`f_301`～`f_340` 各版十筆（v1 總分 38、v2 總分 38、v3 總分 35、v4 總分 39）；瀏覽者 v1～v3 各 10 人（`u_01`～`u_10`）、v4 為 20 人（`u_01`～`u_20`）；重開票工單 `t_3001`～`t_3017` 依序對應 v1 四人、v2 三人、v3 三人、v4 七人。每版的 View 固定在該版模擬 `published_at` 之後的 `T09:00:00Z`、Ticket 在同日 `T10:00:00Z`（v1 06-02、v2 06-21、v3 07-05、v4 07-21），讓每筆 Ticket 只落在自己那一版的十四天窗口內，四個 rate 才會剛好是 0.4／0.3／0.3／0.35。

### 6.7 分群腳本與核定紀錄

```text
demo/scripts/cluster_demo_tickets.py
  | 每筆 text -> Writer.embed -> Titan amazon.titan-embed-text-v2:0
  |   request {"inputText": ..., "dimensions": 1024, "normalize": true}
  v Ticket.embedding（1024 維）-> assign_cluster：cosine >= 0.85 取最高、同分 id 升序
  +-> demo/seed/tickets_clustered.json + clustering_report.json
        （每筆列出 ticket_id、cluster_id、最高 cosine、呼叫 attempt 序號）
```

腳本**必須**實際呼叫 Bedrock；`TKB_RUN_AWS_INTEGRATION` 未設為 `1` 或 Phase 14 的 O5 未通過時，輸出 `BLOCKED` 報告並讓 O7 保持未完成，不得回退成預填 `cluster_id`。二十筆的分群結果是觀察值：可能不是單一群，報告要照實列出實際群數與每群成員，不為了讓畫面好看而改文字。

> **現況核對（2026-09-14）：O5 BLOCKED，這一批拿不到真實 embedding。** 2026-09-14 20:0x 的重 probe 顯示 Titan（`amazon.titan-embed-text-v2:0`）與 Claude 都回 `ValidationException: Operation not allowed`（報告 `docs/plan/report/o5-20260915T030245Z.md`）。**本計畫選擇**（COMMON.md R1／R10）：
>
> 1. `demo/scripts/cluster_demo_tickets.py` 與 `demo/seed_loader.cluster_demo_tickets(...)` **照設計寫完整條真實呼叫路徑**（逐筆 `ensure_embedding` → `assign_cluster`），不加任何「模型不可用就預填」的分支。
> 2. 種子的二十筆 `cluster_id`／`embedding` 維持 `null`，`tickets_clustered.json` **不產生**（沒有觀察值就沒有檔案，空檔比沒有檔更容易被誤讀成「跑過了」）。
> 3. `clustering_report.json` 產生，但只寫 `{"synthetic": true, "status": "BLOCKED", "reason": "<Bedrock 回的錯誤原文逐字>", "probed_at": "<UTC>", "observed": null, "tickets": []}`；`observed` 是 `null` 而不是 `{}`。
> 4. `verify_recipe` 的 `o7_ready` 不受影響（它只看 schema／重算／核定三條）；**分群 BLOCKED 這件事單獨記在 §7 Task 3 與 Phase 報告，不併進 `RecipeReport`**，因為 00A §8 的 O7 定義就是那三條，硬塞第四條會讓 P58 的 dashboard 讀到不存在的欄位。
> 5. 單元層的 schema、重算與「不可全部預填」守門測試**用 `RecordingWriter`／`FIXED_EMBEDDING` 完成**（P38 的既有做法），這些測試證明的是「路徑接對了」，**不是** O5 通過；`tests/integration/test_demo_clustering.py` 照 D-41 標 `@pytest.mark.aws`，在沒有 `TKB_RUN_AWS_INTEGRATION=1` 時由 `tests/conftest.py` 自動 skip，**skip 不算 PASS**。
> 6. `demo/seed/approvals/*.json` 三份全部留「待核定」（四個維護者欄位空字串），`recipe-report.txt` 最後一行固定是「O7 = 未完成（缺維護者核定）」。

核定紀錄 `demo/seed/approvals/<batch_id>.json` 的固定欄位：

```json
{
  "batch_id": "R007-B1",
  "rule_id": "R-007",
  "before_version_id": "prepare-meeting@v1",
  "after_version_id": "prepare-meeting@v2",
  "synthetic": true,
  "recomputed": {"before_average": 2.875, "after_average": 4.4, "before_rate": 0.7, "after_rate": 0.2},
  "recipe_report_sha256": "",
  "seed_commit": "",
  "approved_by": "",
  "approved_at": "",
  "statement": "我已核對本批次為合成資料、數值可由 demo/seed 重算，同意作為 O7 驗證批次。"
}
```

`approved_by`、`approved_at`、`seed_commit`、`recipe_report_sha256` 四個欄位**只能由維護者填寫**。`load_seed` 只驗證欄位存在且 `seed_commit` 與目前種子一致；任何自動填值的程式碼都視為造假並停止。

## 7. TDD Tasks

> **Task 排序與缺件處理（現況核對 2026-09-14 新增）**
>
> **（實作核對 2026-09-15）下面整張「缺件處理」表已經不適用。** 實際排程把本 Phase 放在
> P43／P53／P54／P55 **之後**，四份模組都已經在 `src/` 裡，所以：八個 `RecipeCheck` 全部算得出來
> （**沒有** `xfail` 佔位）、`batches.json` 直接載成 P55 的 `SeedBatch`（**不是**暫時性的 `dict`）、
> `negative_feedback_ids` 的 `approved` 直接
> `from training_kb.ingress import DEFAULT_FEEDBACK_CATEGORIES`（**沒有**模組層常數 `_SEED_CATEGORIES`）。
> 唯一仍然成立的是那句紅字：`demo/` 底下不得有第二份平均或十四天窗口——守門
> `rg -n "days=14|timedelta" demo/` 實測**無命中**。
>
> 本 Phase 原排在 **W1**，而 §5 Consumes 裡 P43／P53／P54／P55 的名稱分別落在 W1／W2／W3。實作時依下列順序處理，**不得自己另寫一份平均或重開票公式**（00A §6.9：同一個指標只能有一份實作；P44 的例外是 00A D-44 明文授權的，本 Phase 沒有這個授權）：
>
> | 缺件 | 誰產出 | 波次 | Task 1–2 的處理 |
> |---|---|---|---|
> | `average_rating`、`negative_feedback_ids` | P53 | **W1（同波）** | 同波產出。先做 Task 1（schema 與載入，不需要它們），`verify_recipe` 的四個評分類 check 等 `analytics/ratings.py` 落地後再補；若 W1 結束時仍不存在，Task 2 的那四項標 `actual=None`／`ok=False` 並在報告寫明「等 P53」。 |
> | `reopen_stats` | P54 | **W2（本 Phase 之後）** | 八個目標裡的四個（reopen count／rate）**在 W1 做不完**。Task 2 只完成評分類四項；重開票四項**留成失敗的 `RecipeCheck`（`actual=None`、`ok=False`）** 並在 §11 完成清單維持未勾、報告寫明「待 P54」。**不得**在 `demo/seed_loader.py` 裡自己算 14 天窗口。 |
> | `SeedBatch`、`evaluate_batch`、`next_status` | P55 | **W3（本 Phase 之後）** | `batches.json` 這一批**照 §6.6 的欄位原樣寫成 JSON 並驗 schema**，但 `SeedBundle.batches` 暫時是 `tuple[dict[str, object], ...]` 而不是 `tuple[SeedBatch, ...]`，`load_seed` 只做欄位存在與「兩批不重疊」檢查。P55 落地後由 **P55 自己**把型別換成 `SeedBatch`（它是 `batches.json` 的唯一消費者，00A §6.9 P55 列）。差異在本 Phase 報告 §7 記一行。 |
> | `DEFAULT_FEEDBACK_CATEGORIES` | P43 | **W3（本 Phase 之後）** | `negative_feedback_ids(feedback, approved)` 的 `approved` 參數在 W1 先由 `verify_recipe` 用**模組層常數** `_SEED_CATEGORIES = frozenset({"找不到按鈕", "缺少資訊"})` 傳入，並在該常數旁加 `# TODO(P43)：改成 import DEFAULT_FEEDBACK_CATEGORIES`。它是**呼叫端傳進去的參數值**，不是第二份分類邏輯，所以不違反單一實作原則。 |
>
> 三處「待後續 Phase」都要同時出現在：程式註解、`§11 完成清單`（維持未勾）、Phase 報告 §9。

### Task 1：種子 schema 與載入

- [x] **Step 1：建立失敗測試**

在 **`tests/unit/test_seed_recipe.py` 自己檔案裡**（現況核對 2026-09-14：原寫「`tests/unit/conftest.py` 追加」，但那支檔這一批只有 P55 可以動，COMMON.md R3.6；P23／P24／P26 都是把共用器材留在使用它的測試檔）加 `seed_dir` fixture：把 `demo/seed/` 整個 `shutil.copytree` 到 `tmp_path`，回傳那份副本；另外三個 `seed_dir_with_*` fixture 各自在副本上改一個欄位（兩個 Feature、`f_19` 的 rating 改 4、兩批共用 `version_id`），正本永遠不被測試改動。

```python
import pytest

from demo.seed_loader import load_seed
from training_kb.errors import ContentError

def test_load_seed_reads_all_entities_and_marks_synthetic(seed_dir):
    bundle = load_seed(seed_dir)
    assert bundle.synthetic is True
    assert len(bundle.feedback) == 18 + 40     # A 的 18 筆 + weekly-digest 的 40 筆
    assert len(bundle.views) == 20 + 50
    assert {t.id for t in bundle.tickets} >= {"t_1001", "t_2001", "t_2101", "t_3001"}
    assert {r.rule_id for r in bundle.rules} == {"R-007", "R-012"}

def test_load_seed_rejects_step_without_exactly_one_feature(seed_dir_with_two_features):
    with pytest.raises(ContentError):
        load_seed(seed_dir_with_two_features)
```

- [x] **Step 2：執行並確認紅燈**

執行 `uv run pytest tests/unit/test_seed_recipe.py -q`，預期 FAIL。（現況核對 2026-09-14：`demo/` 目前整個不存在，所以第一次的紅燈訊號是 **`ModuleNotFoundError: No module named 'demo'`**，不是 `cannot import name 'load_seed'`；先做 §4 的「讓 `demo` 可以被 import」與空的 `demo/__init__.py`，第二次才會變成 `cannot import name 'load_seed'`。兩次都要記進報告的 RED 證據。）

- [x] **Step 3：建立最小實作**

用 Phase 03／04 的 Pydantic 模型逐檔解析，不另寫寬鬆 parser。載入順序固定為 features → tutorials → versions → steps → releases → feedback → views → tickets → rules → batches → approvals；後面的檔案可引用前面的 ID，引用不存在的 ID 直接丟 `ContentError`。

`apply_seed(bundle, *, repository, now)` 寫入時，**VERSION 與 STEP item 只帶模型欄位**（D-40：item 屬性 = 模型欄位 + `RESERVED_ATTRS`，沒有第三類；`synthetic`、`batch_label` 只留在 JSON 檔與報告，不寫進 item）；每個版本除了 `put_meta` 之外還要寫 `tutorials/<slug>/v<n>.md` 全文、`.diff`（v1 為空）與 `REFERENCES`／`SUPERSEDES` 邊，寫完逐一呼叫 Phase 23 的 `verify_version_complete(version_id, repository)`，任一個回 `False` 就丟 `ContentError` 並停止，不留半套版本。回傳值是這次實際寫入的 PK 清單。

- [x] **Step 4：補四個 schema 失敗案例、跑綠燈並提交**

依序加入：步驟零個或兩個 Feature、Feedback 指向不存在版本、`R-012` 兩批共用 `version_id`、核定檔缺 `approved_by`。前三個丟 `ContentError`；第四個不丟錯，但要出現在 `missing_approvals`。

```bash
uv run pytest tests/unit/test_seed_recipe.py -q
git add demo/seed demo/seed_loader.py tests/unit/test_seed_recipe.py
git commit -m "feat(demo): 建立可載入的合成種子資料"
```

### Task 2：verify_recipe 重算八個數字

- [x] **Step 1：建立失敗測試**

```python
from demo.seed_loader import load_seed, verify_recipe

EXPECTED = {
    "A v1 average": 2.875, "A v2 average": 4.4,
    "A v1 negative count": 8, "A v2 negative count": 2,
    "A v1 reopen count": 7, "A v2 reopen count": 2,
    "A v1 reopen rate": 0.7, "A v2 reopen rate": 0.2,
}

def test_verify_recipe_recomputes_all_eight_targets(seed_dir):
    report = verify_recipe(load_seed(seed_dir))
    assert {c.name: c.expected for c in report.checks} == EXPECTED
    assert all(c.ok for c in report.checks)
    assert report.recompute_ok is True

def test_verify_recipe_fails_when_one_feedback_is_edited(seed_dir_with_wrong_rating):
    report = verify_recipe(load_seed(seed_dir_with_wrong_rating))
    assert report.recompute_ok is False
    assert [c.name for c in report.checks if not c.ok] == ["A v1 average"]
```

- [x] **Step 2：確認紅燈**

執行 `uv run pytest tests/unit/test_seed_recipe.py -q`，預期 FAIL 且訊號為 `cannot import name 'verify_recipe'`。

- [x] **Step 3：實作重算**

`verify_recipe` 只能呼叫 Phase 53 的 `average_rating`、`negative_feedback_ids` 與 Phase 54 的 `reopen_stats`，不得在種子檔或程式裡預存這八個數字當來源。`negative_feedback_ids` 的 `approved` 參數用 Phase 43 的 `DEFAULT_FEEDBACK_CATEGORIES`（`找不到按鈕`、`缺少資訊`），不另外定義一份類別表。期望值寫在 `verify_recipe` 內的常數表，實際值一律從 `bundle` 的原始資料算出來。

（現況核對 2026-09-14：依 §7 開頭的缺件表，W1 時 `reopen_stats`（P54）與 `DEFAULT_FEEDBACK_CATEGORIES`（P43）都還不存在。**`approved` 先傳模組層常數 `_SEED_CATEGORIES`**，那是參數值不是第二份邏輯；**重開票四項留成 `actual=None`／`ok=False` 的 `RecipeCheck`**，`recompute_ok` 因此為 `False`、`o7_ready` 為 `False`，這是誠實的中間狀態，不是綠燈。`test_verify_recipe_recomputes_all_eight_targets` 在 W1 用 `xfail(strict=True)` 標住四項重開票，P54 落地後由本 Phase 的補做或 P54 自己把 xfail 拿掉——**不得**為了讓它綠而在 `seed_loader.py` 裡自己算窗口。）

- [x] **Step 4：加入 O7 三條件測試、跑綠燈並提交**

斷言四種情形：schema 失敗、重算失敗、核定缺漏，三者各自讓 `o7_ready is False`；三者皆成立時 `o7_ready is True`。

```bash
uv run pytest tests/unit/test_seed_recipe.py -q
git add demo/seed_loader.py tests/unit/test_seed_recipe.py
git commit -m "feat(demo): 由原始資料重算配方目標數字"
```

### Task 3：二十筆工單的真實 Titan embedding 分群

- [x] **Step 1：先寫「不可全部預填」的守門測試**

```python
def test_seed_tickets_for_creation_have_no_precomputed_cluster(seed_dir):
    bundle = load_seed(seed_dir)
    creation = [t for t in bundle.tickets if t.id.startswith("t_10")]
    assert len(creation) == 20
    assert all(t.cluster_id is None and t.embedding is None for t in creation)
    reopen = [t for t in bundle.tickets if t.id.startswith("t_2")]
    assert all(t.cluster_id == "c12" for t in reopen)          # A 的九筆同題重開票
    assert all(t.cluster_id == "c58"                            # weekly-digest 的十七筆
               for t in bundle.tickets if t.id.startswith("t_3"))
```

- [x] **Step 2：確認紅燈後建立腳本骨架**

`cluster_demo_tickets(bundle, *, writer, repository, operation_id)` 逐筆呼叫 Phase 38 的 `ensure_embedding` 與 `assign_cluster`，回傳 `{ticket_id: cluster_id}`，並寫出 `tickets_clustered.json` 與 `clustering_report.json`。

- [x] **Step 3：建立整合測試**

測試檔放 `tests/integration/`、每個測試標 `@pytest.mark.aws`（marker 由 Phase 59 定義、Phase 01 的 `pyproject.toml` 註冊；`TKB_RUN_AWS_INTEGRATION` 未設時 conftest 自動 skip）：

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_demo_clustering.py -q -m aws
```

測試內容：二十筆各產生一個 1024 維向量；`CallTrace` 的 attempt 數等於實際 request 數；報告列出每筆的最高 cosine；同一筆重跑不重新計算 embedding。Phase 14 的 O5 未通過或無權限時，整合測試 `skip`，腳本輸出 `BLOCKED`，**且不得把 skip 當成 PASS**。

（現況核對 2026-09-14：**O5 就是 BLOCKED**，所以這條指令這一批一定是 `skip`。marker `aws` 已由 **P01 的 `pyproject.toml` 註冊**、自動 skip 由 **`tests/conftest.py` 的 `pytest_collection_modifyitems`** 提供，**都已存在**——原文寫「marker 由 Phase 59 定義」是錯的（現況核對 2026-09-14：實際 owner 是 P01＋既有 `tests/conftest.py`，00A D-41）。另外**補一組不依賴 Bedrock 的單元測試**放在 `tests/unit/test_seed_recipe.py`：用 `RecordingWriter`（`embed` 回 `FIXED_EMBEDDING`）跑 `cluster_demo_tickets(...)`，斷言二十筆都被呼叫一次、回傳 dict 有二十個 key、`repository` 沒有被寫進 `cluster_id` 以外的東西。這證明「路徑接對了」，**不證明** O5 通過。）

- [x] **Step 4：核對分群結果是觀察值並提交**

把報告中的實際群數與每群成員抄進 `demo/seed/clustering_report.json` 的 `observed` 區塊。若二十筆沒有落在同一群，照實記錄並在 Demo 畫面說明，不回頭改寫工單文字硬湊單一群。

（現況核對 2026-09-14：O5 BLOCKED → 沒有觀察值可抄。依 §6.7 的「本計畫選擇」，`clustering_report.json` 寫 `status: "BLOCKED"` ＋ Bedrock 回的錯誤原文逐字 ＋ `observed: null`，`tickets_clustered.json` **不產生**；Phase 報告 §7 記「O7 的分群條件未取得證據，原因 O5 BLOCKED」，`§11 完成清單`的對應列**維持未勾**。）

```bash
git add demo/scripts/cluster_demo_tickets.py tests/integration/test_demo_clustering.py demo/seed/
git commit -m "feat(demo): 以真實 Titan embedding 分群展示工單"
```

### Task 4：維護者核定紀錄與 O7 報告

- [x] **Step 1：建立失敗測試**

```python
def test_o7_is_not_ready_until_a_human_signs_every_batch(seed_dir):
    report = verify_recipe(load_seed(seed_dir))
    assert report.schema_ok and report.recompute_ok
    assert report.o7_ready is False
    assert set(report.missing_approvals) == {"R007-B1", "R012-B1", "R012-B2"}

def test_approval_file_keeps_the_four_human_fields(seed_dir):
    for path in (seed_dir / "approvals").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        assert set(record) >= {"approved_by", "approved_at", "seed_commit",
                               "recipe_report_sha256", "statement"}
        assert record["synthetic"] is True
```

- [x] **Step 2：確認紅燈並實作核定檢查**

`load_seed` 讀 `approvals/`，把四個維護者欄位為空字串的批次列入 `missing_approvals`；`seed_commit` 與目前種子檔案雜湊不符時，同樣列為缺核定並在報告寫明原因（種子改過、需重新核定）。

- [x] **Step 3：加入 grep 守門**

```bash
uv run pytest tests/unit/test_seed_recipe.py -q
rg -n "approved_by|approved_at" demo/ src/ --glob '!demo/seed/approvals/*'
```

預期：測試 PASS；`rg` 只應命中讀取與驗證的程式碼，不得出現任何賦值。

- [x] **Step 4：產出 O7 報告並提交**

執行 `uv run python -m demo.seed_loader verify demo/seed`，把輸出存成 `demo/seed/recipe-report.txt`。報告最後一行只能是「O7 = 未完成（缺維護者核定）」或「O7 = 三條件齊備」，不得出現「O7 已通過」等結論式措辭。

```bash
git add demo/seed_loader.py demo/seed/ tests/unit/test_seed_recipe.py
git commit -m "feat(demo): 加入維護者核定紀錄與 O7 報告"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 | 本批（2026-09-14）實際可驗到哪 |
|---|---|---|---|
| Happy | 完整種子目錄；維護者簽完三個批次 | schema PASS、八個 check 全 OK、`missing_approvals == ()`、`o7_ready is True`。 | **驗不到**：維護者未簽（O7 未到）＋ 重開票四項待 P54。可驗的是 schema PASS 與評分類四項 OK。 |
| Failure | 把 `f_19` 的 rating 改成 4 | `A v1 average` 這一個 check 失敗，`o7_ready is False`。 | 可驗（只用 P53 的 `average_rating`）。 |
| Failure | 步驟引用零個或兩個 Feature | `load_seed` 丟 `ContentError`，不產生 bundle。 | 可驗。 |
| Failure | `R012-B1` 與 `R012-B2` 共用 `weekly-digest@v2` | `ContentError`：兩批重疊，不能當連續兩批證據。 | 可驗（`load_seed` 自己的欄位檢查，不需要 P55 的 `SeedBatch`）。 |
| Boundary | 核定檔存在但 `approved_by` 為空；種子改過但 `seed_commit` 未更新 | 都列入 `missing_approvals`，`o7_ready is False`。 | 可驗。 |
| Boundary | 無 Bedrock 權限 | 分群腳本輸出 `BLOCKED`，整合測試 skip，O7 保持未完成。 | **這就是本批的實際狀態**（O5 BLOCKED）：`clustering_report.json` 的 `status` 是 `BLOCKED` ＋ 錯誤原文逐字，`tests/integration/test_demo_clustering.py` 全部 skip。 |
| Security | 二十筆工單預填 `cluster_id` | Task 3 Step 1 的守門測試失敗。 | 可驗（純資料斷言，不碰模型）。 |
| （新增）Blocked | O5 未開通時跑 `cluster_demo_tickets` | 真實呼叫路徑走到 Bedrock 回 `ValidationException: Operation not allowed` → `PermanentError`；報告記 BLOCKED。**不回退成預填、不吞例外、不當成通過。** | 本批要留的證據。 |
| （新增）Interim | W1 時 `reopen_stats`（P54）不存在 | 四個重開票 check 是 `actual=None`／`ok=False`，`recompute_ok is False`、`o7_ready is False`；`seed_loader.py` 裡**沒有**第二份 14 天窗口公式。 | 可驗（`rg -n "timedelta\(days=14\)|days=14" demo/` 應無命中）。 |

人工驗收：維護者逐一打開 `demo/seed/feedback.json`、`views.json`、`tickets.json`，親手核對八筆與十筆回饋、二十筆瀏覽與九筆重開票工單，確認它們就是設計 §11.2、§11.3 的配方；再看 `clustering_report.json` 的實際 cosine 值。只看 `recompute_ok is True` 不算核定。（現況核對 2026-09-14：本批 `clustering_report.json` 沒有 cosine 值可看，只有 BLOCKED 與錯誤原文；O5 開通後要重跑腳本再請維護者看這一項。）

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 報告說「O7 已通過」 | 把程式綠燈當維護者核定 | 改回三條件分列；`o7_ready` 只在三者皆真時為真。 |
| 二十筆 `cluster_id` 全是 `c12` | 為了畫面好看預填 | 停止；設計 §11.1 明寫要驗證實際 embedding 分群。 |
| 平均算出 2.9 而不是 2.875 | 把顯示值存回種子 | 種子只存原始 rating；顯示在最外層格式化。 |
| 模擬發布時間被當成真實發布 | 歷史資料與即時執行混用 | 畫面分開標示；設計 §11.5 要求兩者不得合併。 |
| `R-012` 只用一批就退役 | 少做「不重疊」檢查 | 兩批必須不共用 `version_id`；否則只算一批。 |
| 種子改過卻沿用舊核定 | `seed_commit` 沒更新 | 視同缺核定，請維護者重新核對並簽名。 |
| 合成資料被說成實測 | 文案沒標示 | 每個檔案帶 `synthetic: true`，畫面固定標「合成資料示範」。 |

## 10. 來源與 Rule 對照

「D 開頭」是[設計 §19.1](../../design/training-kb.md) 的資料決策編號、「F 開頭」是 §19.2 的功能決策編號；`D-nn` 則是 [00A 共用契約與名詞](00A-共用契約與名詞.md)第 8 節的裁決編號。

- [執行教學流程.feature](../../spec/features/執行教學流程.feature) RUN Rule 1「缺少原始 Example 時可用明示合成且經確認的驗收資料」→ **本 Phase 是 primary**；Task 1 斷言每個種子檔帶 `synthetic: true`，Task 4 斷言核定紀錄的 `statement` 明寫合成，不描述成原始觀測（決策 F01）。
- [檢視學習指標.feature](../../spec/features/檢視學習指標.feature)
  - MET Rule 10「Demo 指標以 seeded data 展示」→ **本 Phase 是 primary**；Task 2 的 `test_verify_recipe_recomputes_all_eight_targets` 直接由原始資料重算 2.875／4.4／8／2／7／2／0.7／0.2（決策 F46）。
  - MET Rule 11「Demo 對同題重開票率標明 proxy 與精確定義」→ 相關（primary 在 [Phase 58](58-Phase58-Demo控制台與規則開關預覽.md)）；本 Phase 只負責讓報告同時輸出筆數與比率，畫面文案由 Phase 58 的 dashboard 負責。
  - MET Rule 12「Demo 以同一批 Ticket 並排展示規則關閉與開啟產生的 Tutorial B」→ 相關（primary 在 Phase 58）；本 Phase 只提供那批 Ticket 與規則資料，兩份隔離預覽在 Phase 58，且不寫正式 Tutorial 與統計。
- [驗證教學規則.feature](../../spec/features/驗證教學規則.feature)
  - VAL Rule 3「未載入完整核定種子驗證批次時不改變規則狀態」→ 相關（primary 在 [Phase 55](55-Phase55-規則驗證與狀態轉移.md)）；本 Phase 交付的是核定批次本身，Task 4 的 `test_o7_is_not_ready_until_a_human_signs_every_batch` 證明缺簽名時批次不完整。
  - VAL Rule 6「驗證無效的規則從可使用規則中退役」→ 相關（primary 在 Phase 55）；本 Phase 只提供 `R012-B1`／`R012-B2` 兩批不重疊的完整證據，判定與寫狀態都在 Phase 55。
- [分析工單.feature](../../spec/features/分析工單.feature) TIC Rule 1「每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding」與 Rule 2「demo 分群以 cosine 至少 0.85 為同群門檻」→ 相關（primary 在 [Phase 38](38-Phase38-Ticket-Embedding與群中心分群.md)）；Task 3 以真實 embedding 呼叫 Phase 38 的 `ensure_embedding`／`assign_cluster`，不預填結果。
- 設計 §11.1（配方清單與二十筆不同問法）、§11.2／§11.3（可重算的評分、負面、瀏覽與重開票）、§11.4（R-007 轉移順序與 R-012 兩批退役）、§11.5（合成與即時分開標示）、§12.2（完整核定批次）、§12.3（觀察結果不等於因果）、§18 O7；決策 D06、D29、F01、F32、F46。
- 00A 裁決：D-10（`applies_when` 存 `StepType` 的值）、D-34（`project_id` 預設 `demo`）、D-40（item 只有模型欄位）、D-41（真實 AWS 測試放 `tests/integration/` 並標 `@pytest.mark.aws`）、D-47（Demo 使用者用 `u_01` 形狀）。
- [Amazon Titan Text Embeddings 模型說明](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)（2026-09-13 查證）：model ID `amazon.titan-embed-text-v2:0`，預設輸出 1024 維（另支援 512／256），且**不支援** `maxTokenCount`、`topP` 等生成參數。
- [Titan Embeddings 請求與回應格式](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html)：V2 request 欄位為 `inputText`（必填）、`dimensions`、`normalize`、`embeddingTypes`；response 為 `embedding`、`inputTextTokenCount`、`embeddingsByType`。本配方固定送 `{"inputText": ..., "dimensions": 1024, "normalize": true}`，與 Phase 16 的 payload 一致。

## 11. 完成清單

- [x] `demo/seed/*.json` 依 §6 展開完整，每個檔案帶 `synthetic: true`。
- [x] `load_seed` 用 Phase 03／04 模型驗證；步驟零或多 Feature、引用不存在 ID 都丟 `ContentError`。
- [x] `verify_recipe` 由原始資料重算並斷言 2.875、4.4、8、2、7、2、0.7、0.2 共八項。
- [ ] 二十筆建立教學用工單的 `cluster_id`／`embedding` 在種子中為 `null`，由真實 Titan 呼叫填入且有守門測試；九筆重開票工單維持 `cluster_id = c12` 的固定同題對應。（**未完成**：種子中的 `null`、九筆 `c12`／十七筆 `c58` 與守門測試都已完成，但「由真實 Titan 呼叫填入」因 **O5 BLOCKED** 取不到觀察值——2026-09-15 實跑 `demo/scripts/cluster_demo_tickets.py` 得 `ValidationException: Operation not allowed`，證據在 `demo/seed/clustering_report.json`。）
- [x] `R-007` 一批、`R-012` 兩批不重疊的核定批次都有完整前後對照與原始資料；核定欄位只由維護者填寫，程式碼沒有任何賦值路徑，`rg` 檢查已執行。
- [x] `o7_ready` 只在 schema、重算、核定三者皆成立時為真；報告不出現「O7 已通過」。

**（實作核對 2026-09-15，取代上面 W0 寫的「注定勾不起來的三列」）**

W0 那份表是在 P43／P53／P54／P55 都還沒落地時寫的。實際排程改成本 Phase 最後做，
`analytics/ratings.py`（P53）、`analytics/reopen.py`（P54）、`analytics/validation.py`（P55）、
`ingress.DEFAULT_FEEDBACK_CATEGORIES`（P43）**都已經在 `src/` 裡**，所以：

| 完成清單的列 | 實際結果 | 解除條件 |
|---|---|---|
| `verify_recipe` 重算並斷言八項 | **已完成**：八項全部由原始資料算出（`recipe-report.txt` 的 `recompute=PASS`）。`reopen_stats` 直接 import P54 的那一份，`demo/` 下沒有第二份十四天窗口（`rg -n "days=14" demo/` 無命中） | — |
| 二十筆由真實 Titan 呼叫填入 `cluster_id` | **未完成**：O5 BLOCKED。2026-09-15 06:46Z 實跑 `demo/scripts/cluster_demo_tickets.py` 打到 `us-east-1` 的 Bedrock，得 `An error occurred (ValidationException) when calling the InvokeModel operation: Operation not allowed`，逐字記在 `demo/seed/clustering_report.json` 的 `upstream`；`observed` 是 `null`、**沒有**產生 `tickets_clustered.json` | 維護者送出 Bedrock model access 表單並核准，再重跑腳本（REP §8 第 1 項） |
| `o7_ready` 為真 | **未完成**：schema 與重算都通過，三批核定全缺 | 維護者在 `demo/seed/approvals/<batch_id>.json` 填四個欄位並簽名 |

**本計畫選擇（2026-09-14）：** 因為三個缺件都已落地，`batches.json` **直接**載成 P55 的
`SeedBatch`（不是 W0 brief 說的暫時性 `dict`），八個 `RecipeCheck` 也**沒有** xfail 佔位——
留佔位會讓報告看起來比實際狀況差。

其餘各列（種子展開、`ContentError` 驗證、守門測試、核定欄位無賦值路徑＋`rg` 檢查、報告措辭）已全部勾完。
