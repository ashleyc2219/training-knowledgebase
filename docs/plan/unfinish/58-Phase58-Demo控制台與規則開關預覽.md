# Phase 58：Demo 控制台與規則開關預覽實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **（a）已存在、可直接用的東西**
>
> - `src/training_kb/config.py`：`load_settings(env=None) -> Settings`、`Settings(... project_id=DEFAULT_PROJECT_ID)`、`DEFAULT_PROJECT_ID = "demo"`、`Thresholds`。
> - `src/training_kb/errors.py`：`ObjectAlreadyExists`（**是** `PermanentError` 的子類）、`PermanentError`、`TransientError`。
> - `src/training_kb/repository.py`：`put_object(key, body, content_type, *, if_none_match)`（**`if_none_match` 沒有預設值，必須明寫**）、`list_rules(status=None)`、`list_versions_of_tutorial(slug)`、`list_feedback_of_version`／`list_views_of_version`／`list_tickets`、`get_object`、`object_exists`、`scan_entity`。
> - `src/training_kb/writing/client.py`：`Writer.generate_json(system, user, schema, *, operation_id, node) -> dict`（`node` 必填、原樣寫進 trace）、`CallTrace.to_json()`、`TRACE_FIELDS = ("operation_id", "node", "model", "attempt", "kind", "started_at", "outcome")`（七欄，不多不少）。
> - `src/training_kb/rules.py`：`render_rules_block(rules)`、`applied_rule_ids(rules)`、`select_active_rules(...)`、`rules_for_content(...)`。
> - `src/training_kb/content.py`：`render_markdown(content)`、`diff_key(slug, number)`、`markdown_key(slug, number)`、`parse_version_id`。
> - **`operation_id_for(kind, canonical_id)` 與 `execution_name(operation_id)` 在 `src/training_kb/ingress.py`**（不是獨立模組）；`OperationKind` 在 `src/training_kb/operations.py`，值含 `"feedback-review"`，所以 `operation_id_for("feedback-review", ...)` 型別上合法。
> - `infra/training_kb_data_stack.py`：**`PRIVATE_PREFIXES` 已經包含 `"demo/previews/"`**，所以 `PREVIEW_PREFIX` 天生落在私有前綴裡，`site/*` 的 bucket policy 不會公開它（§5 的說法成立，且已經是既成事實）。
> - `tests/unit/conftest.py`：`RecordingWriter`（`generate_json` 依 `replies` 佇列回 dict、記 `calls`／`request_attempts`）、`fake_writer` fixture、`FIXED_EMBEDDING`。
> - `tests/conftest.py`：`MemoryRepository`（記憶體版，有 `put_object` 的 `if_none_match` 行為）與 `aws` marker 的自動 skip。
>
> **（b）文件因上一批裁決／實作而修正的點（逐條）**
>
> 1. **§5 Consumes 裡大半的名稱在本批還不存在**（實測 grep `src/` 全無）：`import_feedback`／`import_view`（P42，W2）、`approved_categories`（P43，W3）、`ReviewMode`（P44，W1）、`average_rating`／`negative_feedback_ids`／`format_average`（P53，W1）、`version_metrics`／`reopen_stats`／`rule_counts`／`applied_count`／`bedrock_call_count`（P54，W2）、`load_seed`／`verify_recipe`／`apply_seed`（P56，W1）。**本 Phase 在 W3，上述全部都在它之前**，所以這些相依在排程上都成立——這是本組三份文件裡唯一沒有缺件問題的 Phase。模組落點依 00A §3.2 已補進 §5。
> 2. **`streamlit` 目前沒有安裝**（`uv run python -c "import streamlit"` → `ModuleNotFoundError`）。加進 `[dependency-groups] dev` 之後 **`uv.lock` 必須一起 `git add`**（00A §3.2 的根目錄表）。`pyproject.toml` 是共用檔（P56 可能也要改），只用 Edit、只加自己那一行（R3）。
> 3. **`demo/` 目前不存在，而且 pytest 執行時專案根目錄不在 `sys.path`**（實測 `import demo` → `ModuleNotFoundError`；`[tool.setuptools.packages.find] where = ["src"]` 只安裝 `training_kb`）。P56 在 §4 已經裁決「在 `[tool.pytest.ini_options]` 加 `pythonpath = ["."]`」——本 Phase 在 W3，**P56 已經做完，直接沿用，不要再做一次**；若 P56 最後沒做，本 Phase 補上同一行。
> 4. **`demo/` 是本機原始碼目錄，`demo/previews/` 是 S3 key 前綴**，兩者同名但不同層；`PREVIEW_PREFIX` 指的是後者，任何程式都不得用它去組本機路徑。
> 5. `Repository.put_object` 的 `if_none_match` **沒有預設值**，§6 的 `put_object(..., if_none_match=True)` 寫法正確，照抄即可。
> 6. `CallTrace` 的 record 只有 `TRACE_FIELDS` 七欄，`kind` 只允許 `embedding`／`generation`／`tool_use`，`outcome` 只允許 `success`／`transient_error`／`permanent_error`（00A §6.4）——`call_breakdown` 依 `node` 分組、數 `attempt >= 2`，欄位名照這七個。
> 7. §4 表把 `DASHBOARD_BLOCKS`／`SYNTHETIC_NOTICE` 放在 `view_model.py`、`PREVIEW_PREFIX` 放在 `preview.py`，與 00A §3.2 的 `demo/` 表逐字一致（四支檔不得互相搬名稱）；§5 的 Produces 區塊把它們混在一起列，**以 00A ＋ §4 為準**。
>
> **（c）gate 現況對本 Phase 的影響**（COMMON.md §2）
>
> - **O5 BLOCKED**（Titan／Claude 皆 `ValidationException: Operation not allowed`；報告 `docs/plan/report/o5-20260915T030245Z.md`）→ **Task 2 的規則開關預覽在真實 AWS 上跑不出兩份 Markdown**（`Writer.generate_json` 會 `PermanentError`）。moto ＋ `RecordingWriter` 的測試照做、照綠；**真實現場演練記 BLOCKED 並附錯誤原文**，不得用預先產好的 `off.md`／`on.md` 冒充本次成功（設計 §11.5 的「預先執行結果」必須標示，`Banner.fallback_reason` 就是為此存在）。`trigger-ticket` 觸發的正式 Ticket Analysis（D-68 的 R-007 套到 B v1）同理：真實 AWS 上會在模型節點走 Catch → PipelineFailed，那是 BLOCKED 證據不是 bug。
> - **O7 未到**（P56 首驗，而且 P56 這一批因 O5 只能留「待核定」）→ Dashboard 的文案固定「待維護者核定」，**不得**出現「O7 已通過」；`missing_approvals` 非空時不得宣稱通過。
> - **O4 未到**（P54 首驗）→ 重開票率的 14 天窗口端點未核定，區塊 3 除了分子分母與 proxy 說明，還要能承受「窗口定義之後改」而不必改公式（一律轉呼 `reopen_stats`）。
> - **O3 FAIL** → 本 Phase 不寫 `site/`；只要確認預覽跑完 `site/` 前綴物件數不變即可，**不得**因此對 O3 下任何結論。
> - O1 provisionally accepted、O6 待核定：與本 Phase 無直接相依。
>
> **（d）適用的 controller 裁決（COMMON.md §3）**
>
> - **R1 真實 AWS**：本 Phase 不在 R1 的六個 Phase 名單內（P41／P48／P52／P57／P59／P60）。`trigger-*` 子命令**要能真的送出**，但實機演練與證據收在 P60 的證據索引（本文件 §6 已寫 `V4` 那一列）。本 Phase 只保證 CLI 送出去的 payload 與 execution name 逐字正確（用假 client 斷言）。
> - **R3 同檔併行**：`demo/cli.py`／`preview.py`／`view_model.py`／`dashboard.py` 只有本 Phase 動；`pyproject.toml` 是共用檔（只用 Edit）。W3 同波的 P43／P48／P52／P55 不碰 `demo/`。
> - **R5**：本文件的程式碼片段是示意，00A ＋ 既有程式是契約。
> - **R6**：逐 Task 先紅燈再綠燈。**R9**：不派 subagent。
> - **R11 安全**：Demo 指標要明示是合成資料；不嵌金鑰；`PREVIEW_PREFIX` 是私有前綴。

**目標：** 做出維護者本機用的 Demo 控制台：一支 CLI 觸發六種操作、一個 Streamlit dashboard 顯示四個固定區塊，並用同一批 B 工單產生「規則關／開」兩份完全隔離的預覽。

**架構：** 控制台不直接寫 DynamoDB 業務資料；所有寫入都走 `lambda:invoke` 或 `states:StartExecution`，唯二例外是受控的 `seed` 匯入與隔離預覽，而預覽只寫私有 S3 `demo/previews/<run_id>/`。Dashboard 是唯讀的 view model 加 Streamlit 畫面，指標數值全部由 Phase 53／54 的函式從原始資料重算。

**技術：** Python 3.12、argparse、boto3、Streamlit、pytest、moto。

## 全域限制

- 唯一主來源是 [Training KB 設計 §11.4、§11.5、§12.1、§12.3、§13](../../design/training-kb.md)。
- 前置為 [Phase 57：S3 靜態教學站與回饋下載](./57-Phase57-S3靜態教學站與回饋下載.md)；另需 [Phase 53](./53-Phase53-評分與負面回饋指標.md)、[Phase 54](./54-Phase54-重開票與呼叫規則指標.md) 的指標函式、[Phase 55](./55-Phase55-規則驗證與狀態轉移.md) 的規則狀態與 [Phase 56](./56-Phase56-O7核定Demo種子資料.md) 的種子。前置未通過時停止。下一階段是 [Phase 59：失敗復原與重送驗收](./59-Phase59-失敗復原與重送驗收.md)。
- 本階段不做：不建立第四條 pipeline；不讓 CLI 或 Dashboard 直接寫入 DynamoDB 業務 item；不把 AWS 憑證嵌進頁面或種子檔；不改正式門檻；不自行計算指標公式（一律呼叫 Phase 53／54）；不重算或重新核定種子（屬 [Phase 56](./56-Phase56-O7核定Demo種子資料.md)）。
- 與本 Phase 有關的 O1–O7 gate 狀態（O1–O7 是設計 §18 的七個待確認事項編號）：**O7 未到**（首驗在 Phase 56，而且 P56 這一批因 O5 只能留「待核定」），Dashboard 只能顯示批次名稱並標「待維護者核定」，**不得把「程式重算成功」寫成「維護者已核定」**；**O4 未到**（首驗在 P54），窗口端點仍待核定，重開票率必須同時顯示分子、分母與 proxy 說明，零分母顯示 N/A 與樣本不足；**O5 BLOCKED**（現況核對 2026-09-14 新增：Titan／Claude 皆 `ValidationException: Operation not allowed`，報告 `docs/plan/report/o5-20260915T030245Z.md`）→ 規則開關預覽與 `trigger-ticket` 的正式套用在真實 AWS 上跑不到模型，moto ＋ 假 writer 的測試照做，現場演練記 BLOCKED 並用 `Banner.fallback_reason` 明示；**O3 FAIL**（報告 `docs/plan/report/o3-20260914t181109z.md`）→ 本 Phase 不寫 `site/`，只斷言預覽不動它，不對 O3 下結論。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
[你在這裡] 維護者終端機           維護者瀏覽器（localhost）
   demo/cli.py                        demo/dashboard.py
      |                                     |
      |                          唯讀 Repository 讀取（不寫）
      +-- seed ---------> apply_seed（受控匯入，唯一直接寫入）
      +-- trigger-ticket ----+
      +-- trigger-release ---+--> lambda:invoke --> ingress handler
      +-- import -----------+---> lambda:invoke --> import handler（逐筆）
      +-- metrics ----------> lambda:invoke --> analytics handler
      +-- trigger-review ---> states:StartExecution --> feedback-review
                                            |
   demo/preview.py -------------------------+--> Bedrock 兩次寫作呼叫
      |
      +--> 私有 S3 demo/previews/<run_id>/off.md、on.md（不寫 DynamoDB）
```

所有箭頭都用「維護者本機 AWS 登入」的身分；程式裡沒有任何金鑰字串。資源名稱與區域由 [Phase 02](./02-Phase02-設定時間與錯誤契約.md) 的 `load_settings()` 從 `TKB_TABLE_NAME`、`TKB_CONTENT_BUCKET`、`TKB_AWS_REGION`、`TKB_PROJECT_ID` 取得，不自訂短名。下一階段 [Phase 59](./59-Phase59-失敗復原與重送驗收.md) 才驗收失敗復原。

## 2. 完成後看得到什麼

```text
$ uv run python -m demo.cli trigger-review --mode demo
input={"mode": "demo"}
operation_id=op-feedback-review-demo-2026-09-13
execution_arn=arn:aws:states:...:execution:training-kb-feedback-review:op-feedback-review-demo-2026-09-13
$ uv run python -m demo.cli metrics --version prepare-meeting@v1
avg=2.875（顯示 2.9） n=8 negative=8 reopen 筆數=7 分子=7 分母=10 rate=0.7（proxy，定義見說明）
$ uv run streamlit run demo/dashboard.py
橫幅：【合成資料示範】｜批次：demo-seed-01｜時間標示：即時執行
```

規則開關預覽跑完後，S3 只多出私有的 `demo/previews/run-01/off.md` 與 `demo/previews/run-01/on.md` 兩個 key；DynamoDB 整張表的內容與跑之前 byte-for-byte 相同，公開的 `site/` 前綴一個字也沒動。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| Streamlit | 用純 Python 寫網頁介面的套件；`streamlit run <檔案>` 會在本機開一個網站。 |
| 子命令 | 一支工具底下的多個動作，像 `git commit` 的 `commit`。本案有六個。 |
| `start_execution` | 啟動一條 Step Functions 流程，回傳這次執行的唯一 ARN。 |
| 隔離預覽 | 用同一批輸入跑兩次（規則關／開），兩份結果都只寫展示用的私有前綴，不進正式資料。 |
| proxy | 不是直接量到的數字，而是用別的資料推估的近似值；重開票率就是教學成效的 proxy。 |
| 預先執行結果 | 展示前先跑好、現場當備援用的結果；必須標示，不能說成本次成功。 |
| attempt | 一次真的送到 Bedrock 的請求；第二次重試是第二個 attempt，不是同一個。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `demo/cli.py` | 六個子命令與參數驗證；只透過 invoke／StartExecution／`apply_seed` 寫入。 |
| 建立 | `demo/preview.py` | `run_rule_toggle_preview`，只寫 `demo/previews/<run_id>/`。 |
| 建立 | `demo/view_model.py` | 四區塊的純計算 view model、`Banner`、`call_breakdown`。 |
| 建立 | `demo/dashboard.py` | Streamlit 畫面；唯讀、不嵌金鑰。 |
| 修改 | `pyproject.toml` ＋ `uv.lock` | 把 `streamlit` 加進 `[dependency-groups] dev`（沿用 Phase 01 的相依管理方式）。（現況核對 2026-09-14：`streamlit` 目前**沒有安裝**；`uv.lock` **必須一起 `git add`**，00A §3.2 根目錄表明文。`pyproject.toml` 是共用檔，只用 Edit、只加自己那一行，R3。） |
| （沿用） | `pyproject.toml` 的 `[tool.pytest.ini_options] pythonpath = ["."]` | 讓 `from demo.cli import ...` 能 import。（現況核對 2026-09-14：實測 pytest 執行時專案根目錄**不在** `sys.path`。這一行由 **P56（W1）** 加，本 Phase 在 W3 直接沿用；若 P56 最後沒做，本 Phase 補。） |
| 測試 | `tests/unit/test_demo_cli.py`、`tests/unit/test_demo_view_model.py` | 參數、寫入路徑與 view model。 |
| 測試 | `tests/unit/test_demo_dashboard_guard.py` | 原始碼守門：不寫 DynamoDB、不含金鑰。 |
| 測試 | `tests/integration/test_demo_preview.py` | moto 下比對預覽前後整張表。 |

## 5. 固定介面

### Consumes

```text
# 已存在（可直接 import）
training_kb.config      load_settings(env=None) -> Settings                       # P02
                        （table_name / content_bucket / aws_region / project_id）
                        DEFAULT_PROJECT_ID = "demo"
training_kb.errors      ObjectAlreadyExists（PermanentError 子類）                 # P07
training_kb.repository  Repository.put_object(key, body, content_type, *,         # P07
                                              if_none_match)  ← 無預設值，必須明寫
                        Repository.list_rules(status=None)                        # P08
                        Repository.list_versions_of_tutorial(slug)                # P27
training_kb.writing     Writer.generate_json(system, user, schema, *,             # P15
                                             operation_id, node) -> dict
                        CallTrace.to_json() -> str（逐筆 node／attempt 的唯一讀法）
                        TRACE_FIELDS 七欄：operation_id / node / model / attempt /
                                           kind / started_at / outcome
training_kb.rules       render_rules_block(rules: Sequence[AuthoringRule]) -> str  # P19
training_kb.content     render_markdown(content: TutorialContent) -> str          # P22
                        diff_key(slug, n) / markdown_key(slug, n) / parse_version_id
training_kb.ingress     operation_id_for(kind, canonical_id)                      # P32
                        execution_name(operation_id)
                        ← 現況核對 2026-09-14：這兩個在 ingress.py，沒有獨立模組
training_kb.operations  OperationKind（含 "feedback-review"）                      # P10
infra.training_kb_data_stack
                        PRIVATE_PREFIXES 已含 "demo/previews/"                     # P09

# 本批較早的波次產出（本 Phase 在 W3，下列全部在它之前落地）
training_kb.ingress     import_feedback / import_view（由 import handler 逐筆呼叫） # P42（W2）
                        approved_categories(repository) -> frozenset[str]          # P43（W3，同波）
training_kb.pipelines.feedback
                        ReviewMode = Literal["formal", "demo"]                     # P44（W1）
training_kb.analytics.ratings
                        average_rating(feedback) / negative_feedback_ids(feedback,
                                                                         approved)
                        format_average(value) -> str                               # P53（W1）
training_kb.analytics.version
                        version_metrics(version_id, *, repository, approved,
                                        project_id) -> VersionMetrics              # P54（W2）
training_kb.analytics.reopen
                        reopen_stats(views, tickets, *, cluster_id,
                                     published_at) -> ReopenStats(count,
                                     reopen_users, viewers, rate)                  # P54（W2）
training_kb.analytics.rules_metrics
                        rule_counts(rules) / applied_count(versions, rule_id)
                        bedrock_call_count(trace, *, operation_id=None) -> int     # P54（W2）
demo.seed_loader        load_seed(directory: Path) -> SeedBundle
                        verify_recipe(bundle) -> RecipeReport
                        apply_seed(bundle, *, repository, now) -> tuple[str, ...]  # P56（W1）
```

**（現況核對 2026-09-14：`approved_categories` 的 owner P43 與本 Phase 同在 W3。）** 若 P43 尚未落地就先做 `dashboard_view`，`approved` 一律由**呼叫端傳進來**（它已經是 `dashboard_view(*, repository, approved, project_id, batch)` 的必填 keyword），測試傳 `frozenset({"找不到按鈕", "缺少資訊"})` 即可；`view_model.py` 裡**一個字都不寫類別清單**。

### Produces

```python
SUBCOMMANDS = ("seed", "trigger-ticket", "trigger-release", "trigger-review",
               "import", "metrics")
DASHBOARD_BLOCKS = ("最新教學與版本差異", "每版評分與回饋數",
                    "重開票筆數與分子分母", "規則狀態與來源證據")
PREVIEW_PREFIX = "demo/previews/"
SYNTHETIC_NOTICE = "合成資料示範"

def build_parser() -> argparse.ArgumentParser: ...
def main(argv: Sequence[str] | None = None) -> int: ...

@dataclass(frozen=True)
class PreviewResult:
    run_id: str
    rule_id: str
    off_key: str
    on_key: str
    model_calls: int

def run_rule_toggle_preview(tickets, *, rule, repository, writer,
                            run_id: str) -> PreviewResult: ...

@dataclass(frozen=True)
class Banner:
    batch: str
    time_mode: Literal["live", "simulated"]
    fallback_reason: str | None

@dataclass(frozen=True)
class CallBreakdown:
    total: int
    retries: int
    by_node: tuple[tuple[str, int], ...]

def render_banner(banner: Banner) -> str: ...
def call_breakdown(trace) -> CallBreakdown: ...
def dashboard_view(*, repository, approved, project_id, batch) -> dict: ...
```

`dashboard_view` 的 key 就是 `DASHBOARD_BLOCKS` 的四個名稱，Streamlit 只負責畫出來，不做任何計算。`PREVIEW_PREFIX` 落在 Phase 09 的 `PRIVATE_PREFIXES` 裡，永遠不會被 `site/*` 的 bucket policy 公開。

## 6. 設計細節

隔離預覽的寫入界線是本 Phase 唯一不能妥協的東西（設計 §11.4 與 §19.2 的決策 F47：兩份都只是隔離的 Demo 產物，不寫入正式教學、回饋與規則效果統計）：

```text
        同一批 B（分享摘要）的工單文字
                     |
       +-------------+--------------+
       v                            v
  規則區塊 = 空白              規則區塊 = render_rules_block([R-007])
       |                            |
  writer.generate_json         writer.generate_json
       |                            |
  render_markdown              render_markdown
       |                            |
       v                            v
  demo/previews/<run_id>/off.md  demo/previews/<run_id>/on.md
       |                            |
       +-------------+--------------+
                     |
      可以寫的只有上面兩個私有 S3 key；以下一律不寫：
      TUTORIAL item / VERSION item / rules_applied / FEEDBACK / 效果統計
```

`run_id` 由呼叫端提供並寫進檔頭，兩份檔案第一行固定是「合成資料示範｜隔離預覽｜不寫入正式教學與統計」。兩個 key 一律用 `put_object(..., if_none_match=True)` 寫入，同一個 `run_id` 重跑會拿到 `ObjectAlreadyExists`（Phase 07 的 `PermanentError` 子類）而中止，避免蓋掉現場已經展示過的對照檔；要重跑就換 `run_id`。若現場另外展示正常 Ticket Analysis 建立 B v1，那是獨立流程，畫面上要與這兩份預覽分開標示（設計 §11.4：不能把 B 的兩份預覽算進 R-007 的三次套用）。

**R-007 轉 active 之後的正式套用由本 Phase 觸發（00A D-68）。** 設計 §11.4 要求示範「規則真的被用到正式教學上」：種子（[Phase 56](./56-Phase56-O7核定Demo種子資料.md)）只把 `R-007` 放成 candidate，[Phase 55](./55-Phase55-規則驗證與狀態轉移.md) 的 `validate_rules` 把它轉成 active 之後，維護者在本 Phase 用 `uv run python -m demo.cli trigger-ticket --ticket-id <一張 B 類工單>` 跑一次**正常的** Ticket Analysis，產出 `share-summary@v1` 並讓該版的 `rules_applied == ["R-007"]`。這條路徑走的是正式 pipeline（`lambda:invoke` → ingress handler），不是上面的隔離預覽，所以它會寫 VERSION item、也會被 Phase 54 的 `applied_count` 算進去；證據由 [Phase 60](./60-Phase60-安全檢查與端到端完成證據.md) 證據索引的 `V4`（已驗證規則用到另一篇教學）那一列收下，實機演練排在它的 rehearse 步驟；本 Phase 只負責提供觸發入口與畫面上的區分標示。

> **（現況核對 2026-09-14）O5 BLOCKED，這條路在真實 AWS 上跑不完。** Ticket Analysis 要呼叫 Titan（embedding）與 Claude（draft），兩者目前都回 `ValidationException: Operation not allowed`（報告 `docs/plan/report/o5-20260915T030245Z.md`），所以真實執行會在模型節點走 `PermanentError → Catch → PipelineFailed`。**那是 BLOCKED 證據，不是 bug，也不是通過**（COMMON.md §2 O5 列）。本 Phase 的責任邊界因此縮成：
>
> 1. `trigger-ticket` 的**送出內容**正確（`lambda.invoke` 的 payload、function 名稱來自 `load_settings()`），用假 client 斷言——本波可驗、必須綠。
> 2. 「`share-summary@v1` 的 `rules_applied == ["R-007"]`」這條**在 moto ＋ `RecordingWriter`** 下驗（P40／P46 的既有做法），證明串接對了。
> 3. **真實 AWS 的那一次**由 P60 的 rehearse 收；若 O5 屆時仍 BLOCKED，P60 照實記 BLOCKED，本 Phase §11 的對應列維持未勾並註明「等 O5」。

四個 Dashboard 區塊與資料來源固定如下，其他欄位不加：

```text
  區塊                       來源                              顯示規則
  -------------------------  --------------------------------  ----------------
  1 最新教學與版本差異        VERSION + 私有 tutorials/*.diff   顯示 reason 與完整 diff
  2 每版評分與回饋數          version_metrics（Phase 54）       無評分顯示「尚無評分」
  3 重開票筆數與分子／分母    reopen_stats（Phase 54）          分母 0 顯示 N/A 與樣本不足
  4 規則狀態與來源證據        list_rules + evidence/derived_from candidate 不寫成已有效
  -------------------------  --------------------------------  ----------------
  另加：B 隔離對照、當次真實模型呼叫數（含 embedding、Rote、Map、重試）
```

區塊 1 讀的是**私有**的 `tutorials/<slug>/v<n>.diff`，不是 Phase 57 的公開副本；Dashboard 是維護者本機唯讀工具，所以這裡可以顯示 `reason`，但同一個字串不得出現在公開頁（00A §3.3）。區塊 3 必須同時印出「筆數、分子、分母、率」與一句 proxy 說明：率是「窗口內先瀏覽後同群開票的不同使用者數／窗口內不同瀏覽者數」，不是直接量測的教學成效；筆數 7 與 2 是筆數，不是百分比。

顯示與判斷分開：門檻用未四捨五入的值，畫面用 Phase 53 的 `format_average` 顯示一位小數（2.875 顯示 2.9）。橫幅固定含「合成資料示範」與批次名稱；`time_mode="live"` 的即時執行時間與 `time_mode="simulated"` 的模擬歷史時間分成兩張表，不合併成同一組使用者成效（設計 §11.5）；`fallback_reason` 非空時橫幅改成「目前顯示預先執行結果」並同時印出本次現場失敗原因。

呼叫數以「每次實際送出的嘗試」計算：`total` 一律轉呼 Phase 54 的 `bedrock_call_count(trace)`，逐筆的 `node` 與 `attempt` 用 `json.loads(trace.to_json())` 讀（Phase 15 指定的唯一讀法，不碰私有清單），`retries` 是 `attempt >= 2` 的紀錄筆數；記憶體重用不算新呼叫。實際三次就顯示三次，不為了對齊展示表格刪掉 embedding 或重試（設計 §12.3）。

## 7. TDD Tasks

### Task 1：六個子命令與唯一的寫入路徑

- [ ] **Step 1：建立失敗測試**

```python
import pytest

from demo.cli import SUBCOMMANDS, build_parser

def test_parser_has_exactly_six_subcommands():
    parser = build_parser()
    actions = [a for a in parser._actions if a.dest == "command"]
    assert set(actions[0].choices) == set(SUBCOMMANDS)

@pytest.mark.parametrize("mode", ["formal", "demo"])
def test_trigger_review_accepts_only_known_modes(mode):
    assert build_parser().parse_args(["trigger-review", "--mode", mode]).mode == mode

def test_trigger_review_rejects_unknown_mode():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["trigger-review", "--mode", "loose"])
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_demo_cli.py -q
```

預期：FAIL，訊號包含 `cannot import name 'build_parser'`。

- [ ] **Step 3：建立最小實作**

`build_parser()` 用 `argparse.ArgumentParser` 加一個 `add_subparsers(dest="command", required=True)`，六個子命令逐一註冊：`seed`（`--dir`，預設 `demo/seed`）、`trigger-ticket`（`--ticket-id`）、`trigger-release`（`--release-id`）、`trigger-review`（`--mode`，`choices=("formal", "demo")`，型別對應 Phase 44 的 `ReviewMode`）、`import`（`--file`、`--kind`，`choices=("feedback", "view")`）、`metrics`（`--version`）。`main()` 依 `command` 分派，每個 handler 回傳 0 或非 0 的退出碼；AWS client 一律 `boto3.client(..., region_name=load_settings().aws_region)`，不寫死區域也不接受金鑰參數。

- [ ] **Step 4：補寫入路徑測試並跑綠燈**

用假的 boto3 client 斷言四件事：`trigger-ticket`、`trigger-release`、`metrics` 只呼叫 `lambda.invoke`；`import` 讀進 Phase 57 widget 的 `{kind, source, generated_at, note, items}` 封套後，**每個 item 各送一次 `lambda.invoke`**（`items` 只放一筆，對應 Phase 42 的一次 `import_feedback`／`import_view` 與一個 `ImportResult`），並逐筆印出 `saved`／`duplicate`／`rejected`；`trigger-review` 只呼叫 `stepfunctions.start_execution`，input **逐字**是 `{"mode": "demo"}`——**只有 `mode` 一個欄位**，沒有 `project_id`，也沒有任何「排程時刻」欄位（時間一律由 Phase 48 的 `deps.now()` 決定，`project_id` 缺值時用 `Settings.project_id`），與 EventBridge Scheduler 送給同一條 state machine 的形狀完全相同（00A §7、D-61）；execution name 是 `execution_name(operation_id_for("feedback-review", f"{project_id}-{date}"))`，其中 `project_id = load_settings().project_id`、`date` 是當日 UTC 日期（`datetime.now(UTC).date().isoformat()`），所以 demo 專案在 2026-09-13 得到 `op-feedback-review-demo-2026-09-13`——與 Phase 48 `review_operation_id` 的算式逐字相同（canonical id 中間用 `-` 不用 `#`），同一天重送才會落在同一筆 operation 紀錄；以上四者都沒有呼叫任何 `dynamodb` 方法。`seed` 是唯一例外，只呼叫 `load_seed` → `verify_recipe` → `apply_seed`，且 `verify_recipe` 的 `o7_ready` 為假時印出 `missing_approvals` 並回非 0，不寫入任何資料。執行 `uv run pytest tests/unit/test_demo_cli.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add demo/cli.py tests/unit/test_demo_cli.py pyproject.toml
git commit -m "feat(demo): 建立控制台六個子命令"
```

### Task 2：B 規則開關的隔離預覽

- [ ] **Step 1：建立失敗測試**（`dump_table` 把整張表的 item 依 PK／SK 排序後轉成 list，`written_keys` 回 moto bucket 內全部 key）

```python
from demo.preview import run_rule_toggle_preview

def test_rule_toggle_preview_writes_only_two_keys(repository, fake_writer, tickets, rule):
    before = dump_table(repository)
    result = run_rule_toggle_preview(tickets, rule=rule, repository=repository,
                                     writer=fake_writer, run_id="run-01")
    assert result.off_key == "demo/previews/run-01/off.md"
    assert result.on_key == "demo/previews/run-01/on.md"
    assert sorted(written_keys(repository)) == [result.off_key, result.on_key]
    assert dump_table(repository) == before
    assert result.model_calls == 2 and result.rule_id == rule.rule_id
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_demo_preview.py -q
```

預期：FAIL，訊號包含 `cannot import name 'run_rule_toggle_preview'`。

- [ ] **Step 3：建立最小實作**

同一批 `tickets` 各跑一次 `Writer.generate_json`：第一次規則區塊傳空字串，第二次傳 `render_rules_block([rule])`；兩份輸出各自 `TutorialContent.model_validate(...)` 後經 `render_markdown` 轉成 Markdown，前面加上固定檔頭（`SYNTHETIC_NOTICE`、`run_id`、規則開關狀態），再用 `Repository.put_object(key, body.encode("utf-8"), "text/markdown; charset=utf-8", if_none_match=True)` 寫到 `PREVIEW_PREFIX + run_id + "/off.md"` 與 `"/on.md"`。函式全程不呼叫 `put_meta`、`put_edge`、`update_meta`、`allocate_version`、`create_version`，也不回傳任何 `version_id`。

（現況核對 2026-09-14：`Writer.generate_json` 的 `node` 是**必填** keyword，`generate_json` 會把它原樣寫進 `CallTrace`，所以兩次呼叫要傳**不同**的 node 名（例如 `preview-off`／`preview-on`），`call_breakdown` 才分得開。測試用 `tests/unit/conftest.py` 的 `RecordingWriter`，`replies` 先排好兩個 `TutorialContent` 形狀的 dict。**O5 BLOCKED** → 真實 Bedrock 上這兩次呼叫會 `PermanentError`；本 Task 的綠燈全部在 moto ＋ `RecordingWriter` 上取得，現場演練的失敗照實記 BLOCKED 並用 `Banner.fallback_reason` 標示「目前顯示預先執行結果」。）

- [ ] **Step 4：補污染防護測試並跑綠燈**

加入四個案例：同一個 `run_id` 重跑丟 `ObjectAlreadyExists`、且第二次沒有任何新寫入；預覽跑完後 `list_rules()` 每條規則的 `applied_to` 長度不變；預覽跑完後同一版的 `version_metrics` 結果與跑前逐欄位相同；`site/` 前綴的物件數量不變。執行 `uv run pytest tests/integration/test_demo_preview.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add demo/preview.py tests/integration/test_demo_preview.py
git commit -m "feat(demo): 隔離的規則開關預覽"
```

### Task 3：四個區塊的 view model 與真實呼叫數

- [ ] **Step 1：建立失敗測試**

```python
from demo.view_model import DASHBOARD_BLOCKS, call_breakdown, dashboard_view

def test_dashboard_view_has_exactly_four_blocks(repository):
    view = dashboard_view(repository=repository, approved=APPROVED,
                          project_id="demo", batch="demo-seed-01")
    assert tuple(view) == DASHBOARD_BLOCKS
    reopen = view["重開票筆數與分子分母"]["prepare-meeting@v1"]
    assert reopen["count"] == 7 and reopen["numerator"] == 7
    assert reopen["denominator"] == 10 and reopen["rate"] == 0.7
    assert "proxy" in reopen["note"]

def test_call_breakdown_counts_every_attempt(trace):
    result = call_breakdown(trace)
    assert result.total == 5 and result.retries == 1
    assert dict(result.by_node)["embed"] == 1
```

`trace` fixture 用 Phase 15 的 `CallTrace`，塞入五筆紀錄：`embed` 一筆、`draft` 兩筆（`attempt` 1 與 2）、`name-gap` 一筆、Rote 節點一筆。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_demo_view_model.py -q
```

預期：FAIL，訊號包含 `cannot import name 'dashboard_view'`。

- [ ] **Step 3：建立最小實作**

`dashboard_view` 逐一呼叫 Phase 53／54 的函式填四個 key，不自己寫任何平均或比例公式：區塊 2 用 `version_metrics(...)` 的 `average`／`sample_size`／`negative_ids`，區塊 3 把同一個結果的 `reopen.count`／`reopen_users`／`viewers`／`rate` 映成 `count`／`numerator`／`denominator`／`rate` 並固定附上 proxy 說明的 `note`，區塊 4 用 `rule_counts` 與 `applied_count`。零評分填 `None` 並附「尚無評分」，零分母（`rate is None`）填 `None` 並附「N/A：樣本不足」。`call_breakdown` 的 `total` 直接用 `bedrock_call_count(trace)`，再以 `json.loads(trace.to_json())` 依 `node` 分組、數 `attempt >= 2` 的筆數當 `retries`。

- [ ] **Step 4：補邊界案例並跑綠燈**

加入零評分版本、零瀏覽版本、candidate 與 active 混合的規則清單三個案例，斷言畫面不會出現 0 分或 0%，且 candidate 的筆數與 active 分開列出、不寫成已有效。執行 `uv run pytest tests/unit/test_demo_view_model.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add demo/view_model.py tests/unit/test_demo_view_model.py
git commit -m "feat(demo): 四區塊 view model 與呼叫數"
```

### Task 4：標示護欄與 Dashboard 原始碼守門

- [ ] **Step 1：建立失敗測試**

```python
from pathlib import Path

from demo.view_model import Banner, render_banner

def test_banner_always_marks_synthetic_and_batch():
    text = render_banner(Banner(batch="demo-seed-01", time_mode="live",
                                fallback_reason=None))
    assert "合成資料示範" in text and "demo-seed-01" in text and "即時執行" in text
    fallback = render_banner(Banner(batch="demo-seed-01", time_mode="live",
                                    fallback_reason="Bedrock 逾時"))
    assert "預先執行結果" in fallback and "Bedrock 逾時" in fallback

def test_dashboard_never_writes_dynamodb_or_embeds_keys():
    source = Path("demo/dashboard.py").read_text(encoding="utf-8")
    for banned in ("put_item", "update_item", "transact_write_items", "put_meta",
                   "put_edge", "delete_item", "aws_secret", "AKIA"):
        assert banned not in source
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_demo_dashboard_guard.py -q
```

預期：FAIL，`demo/dashboard.py` 與 `render_banner` 都還不存在。

- [ ] **Step 3：建立最小實作**

`render_banner` 固定輸出「【合成資料示範】｜批次：<batch>｜時間標示：即時執行／模擬時間」，`fallback_reason` 非空時追加「｜目前顯示預先執行結果；本次現場失敗原因：<reason>」。`demo/dashboard.py` 只 import `demo.view_model` 與 `streamlit`，用 `st.session_state` 保存批次與備援選項，用 `boto3` 預設憑證鏈建立**唯讀**的 Repository 取資料，不建立任何 DynamoDB 寫入 client，也不呼叫 `apply_seed`。

- [ ] **Step 4：補時間分離測試並跑綠燈**

斷言即時執行與模擬歷史資料分別放在兩個 key、view model 不提供把兩者相加的欄位，並斷言畫面文案出現「待維護者核定」而非「O7 已通過」；再以 `uv run streamlit run demo/dashboard.py` 人工開一次，確認橫幅永遠在最上方。執行 `uv run pytest tests/unit/test_demo_dashboard_guard.py tests/unit/test_demo_view_model.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add demo/dashboard.py demo/view_model.py tests/unit/test_demo_dashboard_guard.py
git commit -m "feat(demo): Dashboard 標示與唯讀守門"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 | 本批（2026-09-14）實際可驗到哪 |
|---|---|---|---|
| Happy | `trigger-review --mode demo` | 回傳 execution ARN，名稱來自 `execution_name(operation_id_for(...))`；沒有任何 DynamoDB 直接寫入。 | 可驗（假 boto3 client 斷言 payload 與 execution name 逐字）。真實送出的實機證據在 P60。 |
| Happy | 同一批 B 工單跑預覽 | 只新增 `off.md`、`on.md` 兩個私有 key；整張表與 `site/` 不變。 | 可驗（moto ＋ `RecordingWriter`）。**真實 Bedrock 不行**（O5 BLOCKED）。 |
| Failure | `--mode loose` | `SystemExit`；不啟動任何流程。 | 可驗。 |
| Failure | 同一個 `run_id` 重跑預覽，或 Dashboard 原始碼含寫入呼叫／金鑰字面值 | 前者丟 `ObjectAlreadyExists` 且不覆寫；後者守門測試 FAIL，不得展示。 | 可驗。 |
| Boundary | 版本零評分、零瀏覽 | 顯示「尚無評分」與「N/A：樣本不足」，不顯示 0 分或 0%。 | 可驗。 |
| Boundary | 一次執行含 embedding 與一次重試 | 呼叫數 `total` 含全部嘗試，`retries` 只數 `attempt >= 2` 的紀錄。 | 可驗（`CallTrace` 是純記錄物件，不需要真模型）。 |
| （新增）Blocked | 真實 AWS 上跑預覽或 `trigger-ticket` | 模型節點 `ValidationException: Operation not allowed` → `PermanentError` → Catch → PipelineFailed；報告記 **BLOCKED ＋ 錯誤原文逐字**，`Banner.fallback_reason` 標「目前顯示預先執行結果」。**不得**把預先產好的檔案說成本次成功（設計 §11.5）。 | 本批要留的證據形狀（實機由 P60 收）。 |
| （新增）Gate | Dashboard 文案 | 固定「待維護者核定」；`missing_approvals` 非空時不得出現「O7 已通過」「雲端驗收已通過」。 | 可驗（Task 4 的守門測試 ＋ 報告措辭檢查）。 |

人工驗收：開一次 Dashboard，逐格核對區塊 2 的 2.9／4.4 與區塊 3 的 7／2、0.7／0.2 能由 Phase 56 的種子原始資料重算；再打開 `off.md` 與 `on.md` 並排讀，確認兩份都標示為隔離預覽。不能只看測試顯示 PASS。（現況核對 2026-09-14：`off.md`／`on.md` 這一批只能是 moto ＋ 假 writer 產生的；人工驗收時要能一眼看出它們是**假模型輸出**，檔頭除了 `SYNTHETIC_NOTICE` 與 `run_id`，建議一併寫上 writer 類別名——這樣「隔離預覽」與「模型未開通」兩件事在紙面上分得開。）

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 預覽跑完後 `rules_applied` 多了一筆 | 預覽走了正式建版路徑 | 停止展示；預覽只能 `put_object` 兩個私有 key。 |
| 重開票率顯示 70% 卻沒有分子分母 | 只印比例 | 補印筆數、分子、分母與 proxy 說明。 |
| 零瀏覽版本顯示 0% | 把零分母當成 0 | 改為 N/A 與樣本不足。 |
| 呼叫數少算 embedding 或重試 | 自建計數器或為了對齊展示表格刪減 | 一律轉呼 `bedrock_call_count`；設計 §12.3 明文禁止刪掉。 |
| Dashboard 直接改資料 | 展示頁繞過流程 | 停止；所有寫入走 invoke 或 StartExecution，`seed` 之外沒有例外。 |
| 把重算成功說成 O7 已核定 | 混淆程式驗證與人工核定 | 畫面與報告都標「待維護者核定」；`missing_approvals` 非空時不得宣稱通過。 |
| 預覽的 `reason` 或 diff 出現在公開站 | 把 Dashboard 的私有內容複製到 `site/` | 停止：`reason` 與私有 diff 只在本機唯讀畫面（00A §3.3）。 |

## 10. 來源與 Rule 對照

- [檢視學習指標.feature](../../spec/features/檢視學習指標.feature)
  - Rule 11：「Demo 對同題重開票率標明 proxy 與精確定義」→ **primary 在本 Phase**；`tests/unit/test_demo_view_model.py::test_dashboard_view_has_exactly_four_blocks` 直接斷言區塊 3 同時有 `count == 7`、`numerator == 7`、`denominator == 10`、`rate == 0.7` 與 `"proxy" in note`（Task 3）。
  - Rule 12：「Demo 以同一批 Ticket 並排展示規則關閉與開啟產生的 Tutorial B」→ **primary 在本 Phase**；`tests/integration/test_demo_preview.py::test_rule_toggle_preview_writes_only_two_keys` 直接斷言同一批 `tickets` 產生 `off.md` 與 `on.md` 兩個 key、`model_calls == 2`，且 `dump_table(repository) == before`（Task 2）。
  - Rule 9：「每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫」→ **相關（primary 在 [Phase 54](./54-Phase54-重開票與呼叫規則指標.md)）**；本 Phase 只做顯示，`total` 轉呼 `bedrock_call_count`（Task 3）。
  - Rule 10：「Demo 指標以 seeded data 展示」→ **相關（primary 在 [Phase 56](./56-Phase56-O7核定Demo種子資料.md)）**；本 Phase 只重算與顯示已核定批次的數值（Task 3）。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature) Rule 1：「缺少原始 Example 時可用明示合成且經確認的驗收資料」→ **相關（primary 在 Phase 56）**；本 Phase 只斷言橫幅固定標示合成資料與批次（Task 4），「經確認」的核定紀錄是 Phase 56 的交付物。
- [套用教學規則.feature](../../spec/features/套用教學規則.feature) Rule 5：「既有教學衍生的適用規則可用於不同主題新教學的第一版」→ **相關（primary 在 [Phase 19](./19-Phase19-Active規則選取與注入.md)）**；本 Phase 的 on／off 預覽只是把同一條規則用在 B 的畫面對照，不是選取邏輯（Task 2）。
- 設計 §11.4（兩份預覽都不寫正式資料）、§11.5（合成標示、即時與模擬時間不合併、備援標示）、§12.1（指標公式與空資料）、§12.3（呼叫數照實顯示）、§13（四個區塊、展示頁不直接寫 DynamoDB、瀏覽器不嵌金鑰）、§19.2 的決策 F47。
- [Streamlit session state](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)：`st.session_state` 是唯一能跨 rerun 保留選項的機制。
- [Step Functions describe_execution](https://docs.aws.amazon.com/boto3/latest/reference/services/stepfunctions/client/describe_execution.html)：`status` 為 `RUNNING`／`SUCCEEDED`／`FAILED`／`TIMED_OUT`／`ABORTED`／`PENDING_REDRIVE`，且是最終一致讀取，Dashboard 要能顯示 `RUNNING`。

## 11. 完成清單

- [ ] 六個子命令齊全，`--mode` 只接受 `formal` 與 `demo`，環境設定一律走 `load_settings()` 與 `TKB_` 長名。
- [ ] `trigger-review` 的 input 逐字只有 `{"mode": <mode>}`，execution name 來自 `execution_name(operation_id_for("feedback-review", f"{project_id}-{date}"))`，與 Phase 48 的排程與 `review_operation_id` 完全一致（D-61）。
- [ ] `trigger-ticket` 能在 `R-007` 轉 active 後跑出正式的 B v1 且 `rules_applied == ["R-007"]`，並在畫面上與隔離預覽分開標示（D-68）。
- [ ] CLI 與 Dashboard 都沒有直接寫入 DynamoDB 業務 item，也沒有金鑰字面值；`import` 逐筆呼叫 Phase 42 的單筆匯入。
- [ ] 規則開關預覽只寫私有 `demo/previews/<run_id>/off.md` 與 `on.md`，整張表與 `site/` 不變，同 `run_id` 重跑會被擋下。
- [ ] 四個區塊名稱與 `DASHBOARD_BLOCKS` 一致，數值全部由 Phase 53／54 重算，公式沒有第二份實作。
- [ ] 重開票率同時顯示筆數、分子、分母與 proxy 說明；零分母顯示 N/A。
- [ ] 呼叫數含 embedding、Rote、Map 與重試，來源是 `bedrock_call_count` 與 `trace.to_json()`。
- [ ] 橫幅固定顯示合成資料與批次；即時與模擬時間分開；備援標為「預先執行結果」。
- [ ] 未把程式重算成功寫成 O7 已核定或雲端驗收已通過。
- [ ] **`streamlit` 進 `[dependency-groups] dev` 且 `uv.lock` 一起提交**（現況核對 2026-09-14 新增；`streamlit` 目前沒有安裝）。
- [ ] **`from demo.cli import ...` 在 `uv run pytest` 下 import 得到**（`pythonpath = ["."]` 由 P56 加；本 Phase 只確認它還在，現況核對 2026-09-14 新增）。

**（現況核對 2026-09-14）本批注定勾不起來的一列，以及它的解除條件：**

| 完成清單的列 | 為什麼本批勾不起來 | 解除條件 |
|---|---|---|
| `trigger-ticket` 能在 `R-007` 轉 active 後跑出**真實的** B v1 且 `rules_applied == ["R-007"]`（D-68） | **O5 BLOCKED**：真實 Ticket Analysis 會在 Titan／Claude 節點 `ValidationException: Operation not allowed` | 維護者送出 Bedrock model access 表單並核准（REP §8 第 1 項）；實機那一次由 P60 的 rehearse 收 |

本批可以且必須勾完的替代證據：同一條串接在 **moto ＋ `RecordingWriter`** 下綠燈（證明串接對了），以及 `trigger-ticket` 送出的 payload／function 名稱由假 client 斷言逐字正確。兩者都**不等於** O5 通過，報告要分開寫。
