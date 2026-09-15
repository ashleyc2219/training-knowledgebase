# P56 brief — O7 核定 Demo 種子資料

文件：`docs/plan/unfinish/56-Phase56-O7核定Demo種子資料.md`（W0 已更新，commit `c44428b`）。波次 **W1**。

## 1. 單一交付物與停止點
- **交付物：** 一份可載入、可由原始資料重算、可被維護者核定的 Demo 種子（`demo/seed/*.json` 十份 ＋ `approvals/<batch_id>.json`）與 `demo/seed_loader.py`。
- **停止點：** `o7_ready` 只在 schema／重算／維護者核定三者皆真時為真；程式綠燈只能關前兩條，核定欄位程式碼**沒有任何賦值路徑**。

## 2. 已存在、直接重用
| file:name | 用途 |
|---|---|
| `src/training_kb/pipelines/ticket.py:ensure_embedding(ticket,*,writer,repository,operation_id)->Ticket` | 缺向量才呼叫 Titan，叫完寫回（P38） |
| `src/training_kb/pipelines/ticket.py:assign_cluster(ticket,*,repository)->str` | cosine≥0.85 取最高、同分 id 升序、無命中開新群 |
| `src/training_kb/pipelines/ticket.py:new_cluster_id`／`CLUSTER_COSINE_THRESHOLD` | `c<n>` 編號；門檻是 `Thresholds().cosine_match` 的別名 |
| `src/training_kb/vectors.py:cosine`／`centroid` | 向量運算，不要重寫 |
| `src/training_kb/keys.py:view_pk(tutorial_version,user,ts)` | **設計 §9.1 的正規化 SHA-256 已實作**，`apply_seed` 直接用 |
| `src/training_kb/keys.py:` `tutorial_pk`／`version_pk`／`feature_pk`／`ticket_pk`／`release_pk`／`feedback_pk`／`rule_pk`／`step_pk`／`edge_sk`／`RELATIONS` | 全部 PK／SK 組法 |
| `src/training_kb/content.py:verify_version_complete(version_id, repository)->bool` | P23，`apply_seed` 每寫完一版就呼叫 |
| `src/training_kb/content.py:` `parse_version_id`／`render_markdown`／`make_diff`／`markdown_key`／`diff_key`／`put_private_artifact` | 版號與 Markdown／diff 產物 |
| `src/training_kb/repository.py:` `put_meta`／`put_edge`／`put_object`／`get_steps`／`list_*` | 寫入原語 |
| `src/training_kb/models.py` 十個 `StrictModel` | `extra="forbid"`：種子 JSON 多一個欄位就爆 |
| `tests/unit/conftest.py:RecordingWriter`／`fake_writer`／`FIXED_EMBEDDING`（`[0.001]*1024`） | O5 BLOCKED 時的假 writer（**不可改這支檔**，只有 P55 能動） |
| `src/training_kb/config.py:DEFAULT_PROJECT_ID = "demo"` | `project_id` 一律用它 |

模型硬約束（直接決定種子 JSON 長相）：`Ticket.embedding` 必須是 **1024 個有限數**或 `None`；`Feedback.rating` 是 `mode="before"` 的 strict int 1–5（`True`／`"4"` 一律拒）；`Feedback` **沒有** `project_id`；`TutorialView` **只有** `tutorial_version`／`user`／`ts`；`AuthoringRule.evidence` 需要 **≥5 個不同** ID；`Ticket.feature_ids` 長度 0..1。

## 3. 要新增／修改的東西
| 檔 | 名稱／內容 | 備註 |
|---|---|---|
| `demo/__init__.py`、`demo/scripts/__init__.py` | 空套件標記 | `demo/` 目前完全不存在 |
| `demo/seed/*.json`（十份）＋ `approvals/<batch_id>.json`（三份） | 依文件 §6 展開 | 每檔 `"synthetic": true` |
| `demo/seed_loader.py` | `SeedBundle`／`RecipeCheck`／`RecipeReport`／`load_seed(dir)`／`verify_recipe(bundle)`／`apply_seed(bundle,*,repository,now)`／`cluster_demo_tickets(bundle,*,writer,repository,operation_id)` | 00A §6.9 P56 列；`o7_ready` 是三個布林的 `and` |
| `demo/scripts/cluster_demo_tickets.py` | 真實 Titan 分群腳本 | 不加「模型不可用就預填」的分支 |
| `pyproject.toml` | `[tool.pytest.ini_options]` 加 `pythonpath = ["."]`；`mypy files` 加 `"demo"` | **共用檔，只用 Edit**（P58 也要改它加 `streamlit`；R3） |
| `tests/unit/test_seed_recipe.py` | 全部測試 ＋ `seed_dir` 系列 fixture | **fixture 放這裡，不要動 `tests/unit/conftest.py`**（只有 P55 能改，R3.6） |
| `tests/integration/test_demo_clustering.py` | `@pytest.mark.aws` | O5 BLOCKED → 全 skip |

同波次可能有別人在改：`pyproject.toml`（P58 在 W3，時間上不重疊，但仍只用 Edit）。`demo/` 其餘檔案只有 P58 動，不重疊。

## 4. Task 順序與紅燈訊號
```bash
# Task 1 RED-1（demo/ 還不存在）
uv run pytest tests/unit/test_seed_recipe.py -q        # ModuleNotFoundError: No module named 'demo'
# 建 demo/__init__.py + pyproject pythonpath 後
# Task 1 RED-2
uv run pytest tests/unit/test_seed_recipe.py -q        # cannot import name 'load_seed'
# Task 2 RED
uv run pytest tests/unit/test_seed_recipe.py -q        # cannot import name 'verify_recipe'
# Task 3 RED（守門）
uv run pytest tests/unit/test_seed_recipe.py -q -k precomputed_cluster
# Task 3 整合（一定 skip）
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_demo_clustering.py -q -m aws
# Task 4 RED + grep 守門
uv run pytest tests/unit/test_seed_recipe.py -q
rg -n "approved_by|approved_at" demo/ src/ --glob '!demo/seed/approvals/*'   # 只能命中讀取端
# 全套
uv run pytest tests -q -W error && uv run ruff check src tests infra demo && uv run mypy
```
**兩次 RED 都要進報告**（`ModuleNotFoundError` 那次也算）。

## 5. 00B primary Rule ＋ 測試
| Rule | 出處 | 對應測試 |
|---|---|---|
| `RUN` Rule 1 缺原始 Example 時可用明示合成且經確認的驗收資料 | 執行教學流程.feature | `tests/unit/test_seed_recipe.py` 斷言每檔 `synthetic: true`、核定 `statement` 明寫合成 |
| `MET` Rule 10 Demo 指標以 seeded data 展示 | 檢視學習指標.feature | `test_verify_recipe_recomputes_all_eight_targets` |

相關（primary 在別份）：`MET` 11／12（P58）、`VAL` 3／6（P55）、`TIC` 1／2（P38）。文件 §10 已對齊 00B，無缺漏。

## 6. 風險與陷阱
1. **W1 缺件（最大風險）。** `reopen_stats`（P54，**W2**）、`SeedBatch`（P55，**W3**）、`DEFAULT_FEEDBACK_CATEGORIES`（P43，**W3**）都在本 Phase 之後；`average_rating`／`negative_feedback_ids`（P53）同波。照文件 §7 開頭新增的「Task 排序與缺件處理」表做：重開票四項留 `actual=None`／`ok=False`（`xfail(strict=True)`）、`batches.json` 暫時是 dict、`approved` 傳模組層常數。**絕不自己寫第二份 14 天窗口或平均公式。** 守門：`rg -n "days=14" demo/` 必須無命中。
2. **`import demo` 在 pytest 下不成立**（實測）。專案根不在 `sys.path`；既有 `infra` 是靠測試檔頂端手動插路徑（`tests/unit/test_data_stack.py`）。裁決見 §7。
3. **`tests/unit/conftest.py` 不能碰**（R3.6，只有 P55 能改）。
4. **O5 BLOCKED** → 20 筆真實 embedding 拿不到。`clustering_report.json` 寫 `status: "BLOCKED"` ＋ 錯誤原文 ＋ `observed: null`；`tickets_clustered.json` **不產生**；不得預填 `cluster_id`；skip ≠ PASS。
5. **`StrictModel` 的 `extra="forbid"`**：`synthetic`／`batch_label` 只能留在 JSON 檔與報告，**不得**寫進 item（D-40）。
6. `Release.source_event_id` 用簡寫 `gh-pr-42`，**不套** P13 的 `github_source_event_id`（00A §6.7 種子配方固定值列）。
7. 配方數字已自洽（v1 38/10=3.8、v2 38/10=3.8、v3 35/10=3.5、v4 39/10=3.9；rate 4/10、3/10、3/10、7/20）；feedback 18+40=58、views 20+50=70、reopen tickets 17=4+3+3+7。照抄即可。
8. 文件原寫「`aws` marker 由 Phase 59 定義」是錯的——marker 由 **P01 的 `pyproject.toml`** 註冊、自動 skip 在 **`tests/conftest.py`**，都已存在。

## 7. 需要裁決的點 → 建議裁決
1. **怎麼讓 `demo` 可 import？** → 在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 加 `pythonpath = ["."]`（pytest 8 內建，不需外掛）。理由：P56＋P58 共七支測試檔都要 import `demo`，逐檔複製 `sys.path` 樣板會出現七次。
2. **`demo/` 要不要進 setuptools packages？** → **不要**。`where = ["src"]` 維持不動；`demo/` 是本機工具與資料，不是要安裝的套件；`python -m demo.seed_loader` 從專案根跑本來就成立。
3. **mypy 要不要加 `demo`？** → **要**（`files = ["src", "infra", "demo"]`）。`demo/seed_loader.py` 會被 P58 的 `cli.py` import，是實際執行路徑。若 strict 下紅燈太多且非本 Phase 造成，回退成 `["src", "infra"]` 並在報告寫明。lint 同步改成 `ruff check src tests infra demo`。
4. **O5 BLOCKED 下 20 筆分群怎麼辦？** → seed／recipe／schema／重算驗證用 `RecordingWriter`＋`FIXED_EMBEDDING` 完成；`cluster_demo_tickets.py` 保留真實呼叫路徑但執行結果記 BLOCKED（附錯誤原文逐字）；`approvals/` 三份全留「待核定」。
5. **`batches.json` 在 P55 之前是什麼型別？** → `tuple[dict[str, object], ...]`，`load_seed` 只驗欄位存在與「兩批不重疊」；P55 落地後由 **P55 自己**換成 `SeedBatch`（它是唯一消費者）。
6. **分群 BLOCKED 要不要進 `RecipeReport`？** → **不要**。00A §8 的 O7 定義就是三條，加第四個欄位會讓 P58 的 dashboard 讀到不存在的 key。BLOCKED 記在報告與 `clustering_report.json`。

## 8. 對 AWS 的實際操作
- 只有 Bedrock Titan（`amazon.titan-embed-text-v2:0`），region **`us-east-1`**，payload `{"inputText": ..., "dimensions": 1024, "normalize": true}`（與 P16 一致）。
- 執行：`TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_demo_clustering.py -q -m aws` — **預期 skip**（未設環境變數時由 `tests/conftest.py` 自動 skip；設了也會因 O5 BLOCKED 而 `PermanentError`）。
- 證據放 Phase 報告 §4／§9，錯誤原文逐字；`demo/seed/clustering_report.json` 寫 `status: "BLOCKED"`。**不寫任何憑證、帳號、bucket 內容進 repo**（R11）。
- 本 Phase **不在** R1 的六個實機 Phase 名單內（P41／P48／P52／P57／P59／P60），不部署任何資源。
