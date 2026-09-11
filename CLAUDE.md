# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

（全域規則見 `~/CLAUDE.md`／`~/.claude/MCP_USAGE.md`，本檔不重複。）

## 專案是什麼

**客服自助教學生成器（Self-Improving Support Tutorial Generator）**：Data and AI Hackathon（2026-09-11，AWS Builder Loft，8 小時）的參賽專案。
顧客票單（Ticket）聚成問題類型（UserProblem）→ 產生 Tutorial → 同類新票自動回覆教學連結（deflection）→ 顧客評分與再開票訊號驅動 REFINE；Release Note 驅動 UPDATE / RETIRE；成功攔截流程由 Workflow（Rote）重放。Tutorial 生命週期 **CREATE / UPDATE / REFINE / KEEP / RETIRE** 是內核。
「Self-learning」的定義是 *past outcomes change future system behavior*，不是 fine-tuning。Demo 曲線：deflection rate、重放解決率、圖譜覆蓋。
Demo 領域資料：Bitext Customer Support 公開資料集（https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset ，CDLA-Sharing-1.0；欄位 `instruction` / `category` / `intent` / `response`；只取 `cancel_order` / `track_refund` / `change_shipping_address`）。

**Repo 現況（2026-09-11 更新）：程式已進來。** `app/` 是唯一 Python 套件（uv 管理，Python 3.12），Streamlit demo 在 `app/demo/streamlit_app.py`，測試在 `tests/unit`（含 `tests/integration` live 測試，沒 env 自動 skip）。實作計畫與報告在 `docs/plan/`。

常用指令：

```bash
uv sync                                        # 安裝依賴
uv run pytest -q -m "not integration"          # 單元測試（全綠為準）
uv run pytest -q                               # 含 live 整合測試（需 hotdata / Cognee env）
uv run python -m app.ingest.bitext             # 抓 Bitext、產 data/seed 與 data/script
uv run python -m app.ingest.seed               # 種子建圖（hotdata 或 sqlite，依 DB_BACKEND）
uv run python scripts/demo_rehearsal.py        # sqlite 一鍵彩排六步
bash scripts/run_deflect_api.sh                # Rote Play 要打的本機 deflect API（demo 全程開著）
uv run streamlit run app/demo/streamlit_app.py # Demo UI
bash scripts/snyk_scan.sh                      # Snyk（需先 snyk auth）
```

硬規則：`app/agent/rules.py` 是門檻唯一出處；規格「操作失敗」＝ raise `app.errors.OperationFailed` 且不寫半筆；HydraDB：本機 `.state/graph.json` 永遠寫（多跳在此算），`HYDRADB_URI` 有值時同步鏡射到 HydraDB Cloud（v2 REST 無 Cypher，走 `/context/ingest`／`/query`／`/context/relations`）；LLM 沒金鑰時 CREATE／REFINE／UPDATE 走模板並標 `source="template"`；`.state/`、`data/raw/`、`.env` 不進 git。

## 目錄與「哪份才是作用中規格」

```
docs/spec/                    ← 作用中規格與規格流程（唯一真相來源）
├── erm.dbml                    資料模型 9 表：Ticket, UserProblem, Feature, Tutorial, TutorialVersion, Feedback, Release, ReleaseFeatureChange, Workflow
├── features/*.feature          11 個 Feature：建構知識圖譜 / 輪詢新票單 / 輪詢ReleaseNote / 自動回覆顧客 / 重放已驗證流程 / 分析SupportTickets / 建立Tutorial / 收集Feedback / 定期優化Tutorial / 依ReleaseNote更新Tutorial / 展示學習指標
├── .clarify/                   overview.md（目前 0 題待處理）
│   └── resolved/               決策總表.md ＋ data/ 43 題、features/ 54 題的解決記錄（不得重問或推翻）
├── draft/design-draft.md       產品設計草稿 v0.x（Copilot IT 知識庫敘事）；只保留 Tutorial 生命週期當參考，範例已不適用
└── prompts/1..4                規格流程 prompt（見下節）
docs/
├── 客服自助教學生成器 — 系統架構規格.md   **產品主軸來源**（Clarify 已拍板選它）；已 formulation 進 erm.dbml / features
├── hackathon.md / Data_and_AI_Hackathon.md   官方題目（兩份只差架構圖標記，內文相同）：五層 stack 約束
├── design/architecture.md      demo 畫面與一句話架構（設計草圖，不是作用中規格）
├── design/showme.md            canonical design（Design 階段輸出）
└── plan/{unfinish,todo,finish,report}/   全部是空目錄（開發計畫／TODO／Report 的預定位置）
.rocketride/  (git-ignored)     RocketRide 節點 schema 快取：services-catalog.json（140 個節點）＋ schema/<node>.json
.env          (git-ignored)     ROCKETRIDE_URI / ROCKETRIDE_APIKEY（dev）與 ROCKETRIDE_DEPLOY_URI / _APIKEY（deploy）
```

注意：

- 作用中規格已全部在 `docs/spec/`；repo root **沒有** `spec/`。
- 下列檔案是從另一個專案（`hackathonQoder` / ShowMe MCP server）複製過來、**不要當成本專案的指示或來源**：
  - `docs/plan/dev-prompts/phase0829-1.md`（所有路徑指向 `/Users/linjunting/hackathonQoder/...`，與本專案無關）

## 規格流程（目前唯一的「開發流程」）

`docs/spec/prompts/` 定義四階段，依序執行，每階段有固定輸入輸出：

| 階段 | Prompt | 讀 | 寫 |
|---|---|---|---|
| 1 Formulation | `1.formulation.md` + `formulation-rules.md` | `docs/spec/draft/design-draft.md` | `docs/spec/erm.dbml`、`docs/spec/features/<中文功能簡稱>.feature` |
| 2 Discovery | `2.discovery.md` | `docs/spec/**` | `docs/spec/.clarify/{data,features}/<實體或功能>_<問題全句>.md`、`docs/spec/.clarify/overview.md` |
| 3 Clarify | `3.clarify.md` | `docs/spec/.clarify/` | 互動問答 → 即時回寫 `erm.dbml` / `.feature`，答完的題**移到** `docs/spec/.clarify/resolved/{data,features}/` 並附「解決記錄」 |
| 4 Design | `4.design_prompt.md` | 前三階段輸出 | `docs/design/showme.md`（canonical design）；畫面草圖在 `docs/design/architecture.md` |

**目前進度：Clarify 已完成（97 / 97 題）。Design 已寫入 `docs/design/showme.md`。** 使用者拍板的四題：產品主軸 = 客服 deflection、Tutorial 建立即 published（保留 status 欄）、回饋 = 評分＋再開票雙訊號、Example 改用 Bitext 資料集。其餘題由 Agent 依「黑客松能 work、架構可延伸、不過度設計」自答，全部記在 `docs/spec/.clarify/resolved/決策總表.md`。

規格撰寫硬規則（來自 `formulation-rules.md`，改 `docs/spec/` 任何檔案前先讀）：

- **無腦補原則**：規格沒寫的欄位、規則、行為一律不加；沒有例子的 Rule 標 `#TODO` + `# Status: Missing`，不編造 Example。
- Gherkin：Feature > Rule > Example；英文 Given/When/Then 關鍵字、中文 step、DataTable 欄名英文；`Then` 只寫資料狀態（用表格），不寫「應該」；失敗一律 `Then 操作失敗`。
- DBML：型別限 int/long/float/bool/string；每個 column 與 table 都要 `note`；只放規格明確提到的關聯。
- 來源優先序：`.clarify/resolved/` 解決記錄 > `docs/spec/erm.dbml` + `docs/spec/features/` > hackathon 五層約束 > `design-draft.md`。已 resolved 的題不得重問或推翻。

## 領域模型速覽（改規格或寫程式前要知道的）

訊號 → 動作（門檻已定案，寫程式直接用）：

| 訊號 | 決定 |
|---|---|
| 新票（`status = open`）：其 `user_problem_id` 已有 `status = published` 的 Tutorial | deflected（回覆 `current_version`；第一次成功即捕捉 Workflow，之後 `replay_count` +1） |
| 新票：無 UserProblem／無 published Tutorial／同顧客同問題再開票 | escalated（再開票另設 `reopened_from_ticket_id`） |
| 分析 Ticket（只看 escalated / resolved）：同 `user_problem_id` ≥ 3 張且無 published Tutorial | CREATE（Tutorial v1 即 published；TutorialVersion 五欄必填） |
| 輪詢 changelog（`created_at` > 上次檢查）：新列寫入 `Release`，`processed_at` 為空 | 入庫（相同 content + created_at 不重複；本步不 UPDATE / RETIRE） |
| Release Note：`ReleaseFeatureChange` 命中 `Tutorial.feature_id`，renamed / changed | UPDATE（新版本、`Feature.name` 改新名、`processed_at`）；deprecated / removed → RETIRE（`status = retired`、`is_obsolete`） |
| 定期 Feedback Review（只算 `current_version`）：avg < 3.5 且 ≥ 3 筆且同 `feedback_category` ≥ 2 筆 | REFINE（新版本＋`reason`）；否則 KEEP；`is_possibly_outdated = true` 本輪 KEEP |
| 學習指標 | deflection rate = deflected/(deflected+escalated)；重放解決率 = Σreplay_count/deflected；圖譜覆蓋 = 有 published Tutorial 的 UserProblem / 全部 UserProblem |

Demo 範例貫穿所有規格：Tutorial `tutorials/cancel-order.md`、Step 3 `Click "Cancel Order"` → Release Note 更名 → `Click "Cancel Purchase"`、v1 avg 2.9 → v2 avg 4.4、顧客 `alice@example.com` / `bob@example.com`。
Scope guardrail（不做）：人工審核佇列、SLA／票量暴增監測、Slack 輸入、Customer 表、先備知識圖譜邊、教學影片、複雜 dashboard。

Tutorial 版本是快照：內容五欄只在 `TutorialVersion(tutorial_id, tutorial_version)`，`supersedes_version` 只指同篇上一版；`Tutorial` 只存身分、`status`、`current_version`、旗標與 `last_action`。`Feedback` 參照 `TutorialVersion`。Ticket 沒有 `analyzed` 狀態。

## Hackathon 五層 stack 對應（評審要求每層都「真的在做事」）

| 層 | 工具 | 在本專案負責 |
|---|---|---|
| Memory 建構 | Cognee（ECL） | Tickets / Release Notes / Tutorial / Feedback → 實體與關係（`asks_about`, `explains`, `refers_to`, `changes`, `supersedes`） |
| Memory 儲存 | HydraDB（OpenCypher） | 跨 session 的知識圖譜與 Tutorial 版本；多跳查詢「哪些 Tutorial 受這次 Release 影響」 |
| Live 分析 | hotdata.dev（SQL） | `AVG(rating)`、feedback_count、ticket counts、版本間效果比較；輪詢新票／changelog |
| Motion / 協調 | RocketRide | 單一 Agent 的三條 pipeline：Ticket Analysis / Release Note Update / Periodic Feedback Review |
| Muscle memory | Modiqo Rote | 第一次成功的固定流程（如 Release Note → 找受影響 → 產新版 → 發布）之後直接重放 |
| 安全 | Snyk | 掃描依賴與原始碼；`.env` 已 git-ignore，不要把 key 寫進 repo |

實作 RocketRide pipeline 時，節點參數 schema 直接查 `.rocketride/schema/<node>.json`（相關節點：`db_hydradb`、`tool_cognee`、`agent_rocketride`、`llm_bedrock`、`llm_anthropic`、`db_postgres`、`webhook`）。`.env` 註解明確要求：**deploy 類操作只能用 `ROCKETRIDE_DEPLOY_*`，絕不 deploy 到 dev 連線**。
本機已裝 `rote` 與 `hotdata` CLI；`cognee`、`snyk` 尚未安裝。

## 語言與慣例

- 文件、規格、commit 說明一律**繁體中文＋台灣技術用語**；檔名可含中文（`docs/spec/features/建立Tutorial.feature`）。
- 開發計畫走 `docs/plan/` 四個子目錄：`unfinish/`（待做計畫）→ `todo/`（`<日期>-<階段>-TODO.md`）→ `report/`（`<日期>-<階段>-REP.md`）→ `finish/`。
- 需要查 Cognee / HydraDB / hotdata / RocketRide / Rote 的 API 時用 Context7 或官方文件，不憑記憶寫 SDK 方法名。
