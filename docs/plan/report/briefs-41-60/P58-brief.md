# P58 brief — Demo 控制台與規則開關預覽

文件：`docs/plan/unfinish/58-Phase58-Demo控制台與規則開關預覽.md`（W0 已更新，commit `137352f`）。波次 **W3**（需要 P54 的指標與 P56 的種子）。

## 1. 單一交付物與停止點
- **交付物：** 維護者本機的 Demo 控制台——`demo/cli.py` 六個子命令、`demo/preview.py` 的隔離規則開關預覽、`demo/view_model.py` 的四區純計算 view model、`demo/dashboard.py` 的 Streamlit 畫面。
- **停止點：** 寫入界線。除了受控的 `seed` 匯入與只寫 `demo/previews/<run_id>/` 兩個私有 key 的預覽之外，**所有寫入都走 `lambda:invoke` 或 `states:StartExecution`**；Dashboard 唯讀、不嵌金鑰；指標公式不得有第二份實作。

## 2. 已存在、直接重用
| file:name | 用途／注意 |
|---|---|
| `src/training_kb/config.py:load_settings(env=None)->Settings`／`DEFAULT_PROJECT_ID="demo"` | `table_name`／`content_bucket`／`aws_region`／`project_id`；不寫死區域 |
| `src/training_kb/errors.py:ObjectAlreadyExists` | `PermanentError` 子類；同 `run_id` 重跑就靠它擋 |
| `src/training_kb/repository.py:put_object(key, body, content_type, *, if_none_match)` | **`if_none_match` 沒有預設值，必須明寫 `if_none_match=True`** |
| `src/training_kb/repository.py:list_rules(status=None)`／`list_versions_of_tutorial(slug)`／`list_feedback_of_version`／`list_views_of_version`／`list_tickets` | 唯讀取數 |
| `src/training_kb/writing/client.py:Writer.generate_json(system,user,schema,*,operation_id,node)->dict` | `node` **必填**、原樣進 trace；回 dict，呼叫端自己 `model_validate` |
| `src/training_kb/writing/client.py:CallTrace.to_json()`／`TRACE_FIELDS` | 七欄：`operation_id`／`node`／`model`／`attempt`／`kind`／`started_at`／`outcome`。`kind` ∈ `embedding`／`generation`／`tool_use` |
| `src/training_kb/rules.py:render_rules_block(rules)` | 規則注入區塊（P19） |
| `src/training_kb/content.py:render_markdown(content)`／`diff_key(slug,n)`／`parse_version_id` | Markdown 產出 |
| **`src/training_kb/ingress.py`**`:operation_id_for(kind, canonical_id)`／`execution_name(operation_id)` | **不是獨立模組**；`OperationKind`（`operations.py`）含 `"feedback-review"` |
| `infra/training_kb_data_stack.py:PRIVATE_PREFIXES` | **已含 `"demo/previews/"`** → `PREVIEW_PREFIX` 天生私有 |
| `tests/unit/conftest.py:RecordingWriter`／`fake_writer` | `generate_json` 依 `replies` 佇列回 dict，記 `calls`／`request_attempts` |
| `tests/conftest.py:MemoryRepository` | 記憶體 Repository，`put_object` 有 `if_none_match` 行為 |

**本 Phase 在 W3，上游相依全部在它之前落地**（P42 W2、P44 W1、P53 W1、P54 W2、P56 W1；P43 同波 W3）——這是 G6 三份裡唯一沒有缺件問題的。

## 3. 要新增／修改的東西（分工不得互搬，00A §3.2 `demo/` 表）
| 檔 | 名稱 |
|---|---|
| `demo/cli.py` | `SUBCOMMANDS = ("seed","trigger-ticket","trigger-release","trigger-review","import","metrics")`、`build_parser()->argparse.ArgumentParser`、`main(argv=None)->int` |
| `demo/preview.py` | `PREVIEW_PREFIX = "demo/previews/"`、`PreviewResult(run_id, rule_id, off_key, on_key, model_calls)`、`run_rule_toggle_preview(tickets,*,rule,repository,writer,run_id)->PreviewResult` |
| `demo/view_model.py` | `DASHBOARD_BLOCKS`（四個中文區塊名）、`SYNTHETIC_NOTICE = "合成資料示範"`、`Banner(batch,time_mode,fallback_reason)`、`render_banner(banner)->str`、`CallBreakdown(total,retries,by_node)`、`call_breakdown(trace)`、`dashboard_view(*,repository,approved,project_id,batch)->dict` |
| `demo/dashboard.py` | 只 import `demo.view_model` ＋ `streamlit`；唯讀 |
| `pyproject.toml` ＋ **`uv.lock`** | `streamlit` 進 `[dependency-groups] dev`；`uv.lock` **必須一起 `git add`** |
| 測試 | `tests/unit/test_demo_cli.py`、`test_demo_view_model.py`、`test_demo_dashboard_guard.py`、`tests/integration/test_demo_preview.py` |

同波（W3）併行的是 P43／P48／P52／P55，**都不碰 `demo/`**；唯一共用檔是 `pyproject.toml`（只用 Edit、只加自己那一行，R3）。

## 4. Task 順序與紅燈訊號
```bash
# Task 1 RED
uv run pytest tests/unit/test_demo_cli.py -q            # cannot import name 'build_parser'
# Task 2 RED
uv run pytest tests/integration/test_demo_preview.py -q # cannot import name 'run_rule_toggle_preview'
# Task 3 RED
uv run pytest tests/unit/test_demo_view_model.py -q     # cannot import name 'dashboard_view'
# Task 4 RED
uv run pytest tests/unit/test_demo_dashboard_guard.py -q  # demo/dashboard.py / render_banner 不存在
# 安裝 streamlit
uv add --dev streamlit    # 或手改 pyproject 後 uv sync；記得 git add uv.lock
# 人工
uv run streamlit run demo/dashboard.py                  # 確認橫幅永遠在最上方
# 全套
uv run pytest tests -q -W error && uv run ruff check src tests infra && uv run mypy
```
若 `import demo` 失敗 → 檢查 `pyproject.toml` 的 `[tool.pytest.ini_options] pythonpath = ["."]`（由 P56 在 W1 加；沒有就補）。

## 5. 00B primary Rule ＋ 測試
| Rule | 出處 | 對應測試 |
|---|---|---|
| `MET` Rule 11 Demo 對同題重開票率標明 proxy 與精確定義 | 檢視學習指標.feature | `tests/unit/test_demo_view_model.py::test_dashboard_view_has_exactly_four_blocks` — 斷言區塊 3 同時有 `count == 7`、`numerator == 7`、`denominator == 10`、`rate == 0.7` 與 `"proxy" in note` |
| `MET` Rule 12 Demo 以同一批 Ticket 並排展示規則關閉與開啟產生的 Tutorial B | 檢視學習指標.feature | `tests/integration/test_demo_preview.py::test_rule_toggle_preview_writes_only_two_keys` — 兩個 key、`model_calls == 2`、`dump_table(repository) == before` |

相關（primary 在別份）：`MET` 9／10（P54／P56）、`RUN` 1（P56）、`APL` 5（P19）、`VAL` 7（P55）。文件 §10 已對齊 00B，無缺漏。

## 6. 風險與陷阱
1. **O5 BLOCKED**：`run_rule_toggle_preview` 的兩次 `generate_json` 與 `trigger-ticket` 觸發的正式 Ticket Analysis 在真實 AWS 上都會 `ValidationException: Operation not allowed` → `PermanentError` → Catch → PipelineFailed。moto ＋ `RecordingWriter` 照綠；現場演練記 BLOCKED ＋ 錯誤原文，並用 `Banner.fallback_reason` 標「目前顯示預先執行結果」。**不得**把預先產好的 `off.md`／`on.md` 說成本次成功（設計 §11.5）。
2. **兩次 `generate_json` 要傳不同的 `node`**（例如 `preview-off`／`preview-on`），否則 `call_breakdown` 的 `by_node` 分不開。
3. **`trigger-review` 的 input 逐字只有 `{"mode": <mode>}`** — 沒有 `project_id`、沒有排程時刻（00A §7、D-61）。execution name ＝ `execution_name(operation_id_for("feedback-review", f"{project_id}-{date}"))`，`date = datetime.now(UTC).date().isoformat()`，canonical id 中間用 `-` 不用 `#` → `op-feedback-review-demo-2026-09-13`。必須與 P48 的 `review_operation_id` **逐字相同**。
4. **`import` 每個 item 各送一次 `lambda.invoke`**（對應 P42 的一次 `import_feedback`／`import_view` 與一個 `ImportResult`），逐筆印 `saved`／`duplicate`／`rejected`。
5. **`seed` 是唯一直接寫入**：`load_seed` → `verify_recipe` → `apply_seed`；`o7_ready` 為假時印 `missing_approvals` 並回非 0，**不寫入任何資料**。→ P56 這一批 `o7_ready` 必為 `False`（O7 未核定 ＋ 重開票 check 待 P54），所以 `seed` 子命令在 Demo 上會直接拒絕。**這是正確行為**，但要在 CLI 的說明文字講清楚，否則現場會以為壞了。
6. **`dashboard_view` 不得自己寫任何平均／比例公式** — 一律轉呼 P53／P54。守門：`rg -n "days=14|sum\(.*\)/len\(" demo/` 應無命中。
7. **零值處理**：零評分 → `None` ＋「尚無評分」；`reopen_stats` 的 `viewers == 0` → `rate is None` → `None` ＋「N/A：樣本不足」。**不得顯示 0 分或 0%。**
8. **`demo/`（本機原始碼目錄）與 `demo/previews/`（S3 key 前綴）同名不同層** — 任何程式都不得用 `PREVIEW_PREFIX` 組本機路徑。
9. **`streamlit` 目前沒安裝**；`uv.lock` 要一起提交（00A §3.2 根目錄表）。Streamlit 本身可能帶進一批 transitive deps，注意 `uv run pytest tests -q -W error` **不得有任何 warning**（COMMON.md gate）——若 streamlit 的 import 產生 DeprecationWarning，只在 `dashboard.py` 裡 import 它（`view_model.py` 一律不 import streamlit，`test_demo_dashboard_guard.py` 的分工守門就是為此）。
10. **`test_demo_dashboard_guard.py` 是原始碼字串守門**：`put_item`／`update_item`／`transact_write_items`／`put_meta`／`put_edge`／`delete_item`／`aws_secret`／`AKIA` 都不得出現在 `demo/dashboard.py`。寫註解時別不小心提到這些字。
11. **O7／O4 措辭**：畫面與報告固定「待維護者核定」；區塊 3 除了 rate 還要印筆數、分子、分母與 proxy 說明（O4 窗口端點未核定）。

## 7. 需要裁決的點 → 建議裁決
1. **`demo` 可 import 怎麼做？** → 沿用 P56 在 W1 加的 `[tool.pytest.ini_options] pythonpath = ["."]`。不要另立一套（別用測試檔頂端的 `sys.path` 插入樣板）。
2. **`demo/` 要不要進 setuptools packages？** → **不要**；`where = ["src"]` 維持不動。`streamlit run demo/dashboard.py` 與 `python -m demo.cli` 從專案根跑本來就成立。
3. **mypy 要不要含 `demo`？** → 跟隨 P56 的裁決（建議 `files = ["src", "infra", "demo"]`）。`dashboard.py` 若因 streamlit 沒有 stub 而 strict 紅燈，就在 `pyproject.toml` 加一段 `[[tool.mypy.overrides]] module = "streamlit.*"` / `ignore_missing_imports = true`（只針對 streamlit，不放寬全域 strict）。
4. **`o7_ready` 為假時 `seed` 怎麼辦？** → 依文件：印 `missing_approvals` 並回非 0、不寫入。**不加 `--force`**。現場要塞資料就直接呼叫 `apply_seed`（那是寫程式的人的事，不是 CLI 的出口）。
5. **`approved` 從哪來？** → 一律由呼叫端傳進 `dashboard_view(..., approved=...)`；P43 同波，若尚未落地就在測試傳 `frozenset({"找不到按鈕","缺少資訊"})`，`view_model.py` 一個字都不寫類別清單。
6. **預覽檔頭要寫什麼？** → `SYNTHETIC_NOTICE` ＋ `run_id` ＋ 規則開關狀態 ＋ **writer 類別名**（建議加）。理由：O5 BLOCKED 時兩份預覽是假 writer 產的，人工驗收要能一眼分辨「隔離預覽」與「模型未開通」。
7. **`trigger-ticket` 的 D-68 正式套用怎麼驗？** → 本波在 moto ＋ `RecordingWriter` 下驗 `rules_applied == ["R-007"]`（證明串接對了）＋ 用假 client 斷言送出的 payload；真實那一次由 **P60 的 rehearse** 收，O5 仍 BLOCKED 就照實記。§11 對應列維持未勾。

## 8. 對 AWS 的實際操作
- **本 Phase 不在 R1 的六個實機名單內**（P41／P48／P52／P57／P59／P60），**不部署任何資源**。
- CLI 的 AWS client 一律 `boto3.client(..., region_name=load_settings().aws_region)`（全案固定 `us-east-1`），**不寫死區域、不接受金鑰參數**；身分走維護者本機 AWS 登入（帳號 `123456789012`，IAM user `tkb-deploy-admin`）。
- 本波的 AWS 驗證全部用**假 boto3 client**：斷言 `lambda.invoke`／`stepfunctions.start_execution` 被呼叫幾次、payload 逐字、execution name 逐字，以及「四個 trigger／metrics 子命令都沒有呼叫任何 `dynamodb` 方法」。
- 隔離預覽的 S3 驗證用 **moto**（`tests/integration/test_demo_preview.py`）：`dump_table` 前後相同、`written_keys` 只有兩個 `demo/previews/<run_id>/*.md`、`site/` 前綴物件數不變、同 `run_id` 重跑丟 `ObjectAlreadyExists` 且無新寫入。
- 實機證據（`describe-execution`、`get-execution-history`、CloudWatch）由 **P60** 的證據索引 `V4` 那一列收；本 Phase 只在報告 §7 寫明「觸發入口已備妥、實機演練排在 P60」。
- 不把任何金鑰、帳號憑證、bucket 內容寫進 repo（R11）。
