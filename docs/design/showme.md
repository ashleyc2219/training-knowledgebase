# 客服自助教學生成器 — Canonical Design

- **讀者：** 8 小時黑客松開發者與評審
- **用途：** 把已 Clarify 的規格收成可拆實作切片、可寫驗收測試的設計
- **狀態：** Design（2026-09-11）。程式尚未實作。本檔的目錄、ASCII 圖、pipeline 名稱都是規劃，不是已上線系統。
- **畫面草圖：** `docs/design/architecture.md`（FigJam 需先選 team；目前 Figma seat 是 View）
- **作用中規格：** `docs/spec/erm.dbml`、`docs/spec/features/*.feature`、`docs/spec/.clarify/resolved/`
- **本檔不是規格。** 不新增 Feature、不改門檻、不發明第 10 張業務表。

---

## 1. 文件目的與狀態

把 Formulation → Discovery → Clarify 的輸出，收成一份 hackathon-scoped application design。

完成條件：一條可 demo 的學習迴圈——種子建圖 → 餵票 → 無教學則 escalated／達門檻 CREATE → 同類新票 deflected → Rote 重放 → Feedback／Release 觸發 REFINE 或 UPDATE／RETIRE → 三條學習指標上升。

產品形態（clarified + 2026-09-11 定案）：**單一 Agent 的客服 deflection 教學生成器**。不是 MCP server、不是 multi-agent platform、不是客服總機。

三層不要混：

| 畫面 | 做什麼 | 不做什麼 |
|---|---|---|
| 左 | 假裝進資料：餵票 **或** 貼 changelog | 不在 UI 決定 CREATE／擋票／UPDATE |
| 中 | Agent 寫／改教學文件（含 Release 後的 Step 3 diff） | 沒有教學人員清單；真人不填五欄 |
| 下 | 曲線證明它有變聰明 | 不做複雜 dashboard |

擋票發生在文件寫好**之後**、下一張票進來時。中間只有「Agent 產 docs」。

**Release Note 怎麼辦：** 不另開頁、不發明 RocketRide `release` node。左欄貼一則 changelog（與 hotdata 輪詢同一功能）→ 寫入 `Release` 表（`processed_at` 空）→ 同一 Agent 的 Release Note Update pipeline 決定 UPDATE／RETIRE → 中欄顯示 `.md` diff。完整契約見 §7.3。

---

## 2. Source of Truth 與衝突裁決

衝突時依序採用（`docs/spec/prompts/4.design_prompt.md` §3）：

1. `.clarify/resolved/` 解決記錄（★ 使用者拍板優先）
2. `docs/spec/erm.dbml` + `docs/spec/features/*.feature`
3. 黑客松五層約束（與 1、2 衝突時標在本檔，不默改規格）
4. `docs/客服自助教學生成器 — 系統架構規格.md` 未被推翻的五層職責
5. `docs/spec/draft/design-draft.md` 只保留 Tutorial 生命週期
6. 本檔 §5 的 design decision

`docs/design/architecture.md` 是 demo 畫面草圖，可當 design decision 參考，**不是**作用中規格。

截至 2026-09-11：`.clarify/data/` 與 `.clarify/features/` 為空，**0 題待處理**。本檔沒有把已定案重寫成未定。

---

## 3. 產品範圍

### Goals

- 顧客票聚成 `UserProblem` → 產生 Tutorial → 同類新票自動回教學連結。
- Tutorial 生命週期：CREATE / UPDATE / REFINE / KEEP / RETIRE。
- Self-learning = past outcomes change future system behavior（不是 fine-tuning）。
- Demo 看得見：deflection rate、重放解決率、圖譜覆蓋。
- 五層都重複做事：Cognee / HydraDB / hotdata / RocketRide / Rote；Snyk 掃依賴與原始碼。

### Non-Goals（Clarified，不做）

人工審核佇列、SLA／票量暴增監測、Slack 輸入、Customer 表、先備知識圖譜邊、教學影片、複雜 dashboard、ShowMe／MCP overlay、multi-agent、K8s／message queue、必須操作真實產品 UI、Release Note 觸發 CREATE、Rote 重放解票步驟。

---

## 4. 現況基線

**程式碼觀察（2026-09-11 實查）：**

| 項目 | 狀態 |
|---|---|
| `package.json` / `pyproject.toml` / 測試目錄 | 不存在 |
| `tutorials/` | 不存在 |
| 應用 entry point | 不存在 |
| `docs/spec/**` | 作用中規格（9 表、11 Feature、58 Rule、81 Example） |
| `docs/design/architecture.md` | 畫面草圖，已寫 |
| `docs/design/showme.md` | 本檔 |
| `.rocketride/schema/` | 存在（git-ignored 快取，140 個節點） |
| `.env` | git-ignored；本檔不引用真實金鑰 |
| git commit | 尚未建立 |

不得寫成「已可 `uv run` / `npm start`」。下列目錄是規劃，撰寫時不存在：`app/`、`tutorials/`、`tests/`。

---

## 5. 目標架構與相依方向

### 5.1 一句話

```
票單 / 回饋 / Release Note
              |
              v
         hotdata 輪詢、算數字
              |
              v
     +-------- 單一 Agent (RocketRide + LLM) --------+
     | 沒教學 → 轉真人 → 確認解法                      |
     |          同類 >= 3 → CREATE .md v1             |
     | 有教學 → 回連結 (deflect)                       |
     |          第一次 Rote 記住，下次重放              |
     | 回饋差 → REFINE     Release → UPDATE / RETIRE  |
     +------------------+----------------------------+
                        |
           Cognee 建圖 --+--> HydraDB 記住
                        |
                        v
              中：教學 / diff     下：曲線
```

### 5.2 規劃中的模組（尚未存在）

單一行程、單一 repo，不拆微服務。

```text
AWS-Hackathon/
├── docs/spec/                  規格（已存在）
├── docs/design/                architecture.md + 本檔
├── app/                        規劃：唯一 Python 套件
│   ├── demo/                   Streamlit：只觸發、只展示
│   ├── ingest/                 種子匯入、輪詢 cursor
│   ├── agent/                  RocketRide 三條 pipeline + 即時路徑
│   ├── memory/                 Cognee remember／recall、HydraDB 寫回
│   ├── analytics/              hotdata SQL（輪詢與三條指標）
│   └── muscle/                 Rote workspace → Play → 重放
├── tutorials/                  規劃：產出的 .md（cancel-order.md）
└── tests/                      規劃：對齊 11 份 .feature
```

**Design decision：** 用一個 Python 應用包住五層呼叫，不用第二個 controller process。理由：8 小時內評審要看到迴圈，不是平台。

### 5.3 資料流（單向為主，學習寫回）

```text
種子／新票／Release／Feedback
        → Cognee remember（ECL：add + cognify）
        → HydraDB 持久化圖譜與 Tutorial 版本
        → hotdata 輪詢與算指標
        → RocketRide 決策（CREATE / UPDATE / REFINE / KEEP / RETIRE / deflect / escalate）
        → 成功攔截由 Rote 捕捉為 Play；下次重放
        → 新學習寫回 HydraDB 與 ERM 對應欄位（hotdata）
```

Snyk 不在這條迴圈：開發過程掃程式與依賴。

### 5.4 RocketRide 節點（只用不發明）

查過 `.rocketride/schema/`。本專案實際接線：

| 節點 | 用途 |
|---|---|
| `agent_rocketride` | 唯一 Agent；`instructions` 寫三條 pipeline + 即時路徑規則 |
| `llm_bedrock` | 把 `resolution_steps` 收成五欄；UPDATE／REFINE 改 steps |
| `tool_cognee` | remember／recall；dataset 固定（預設 `main`，不開 per-call override） |
| `db_hydradb` | 跨 session 圖譜與 Tutorial 對應；`recall_memory` + OpenCypher |
| `webhook` | Demo「餵下一張票／貼 changelog／按 Review」打進同一 Agent |

**不接：** `mcp_client`、第二個 `agent_*`、`tool_slack`。catalog 沒有 hotdata／Rote 節點——這兩層用本機 CLI，不發明 `db_hotdata` 或 `tool_rote`。

**Design decision：** `db_postgres` 不當業務庫。9 表的即時列與聚合走 hotdata SQL（官方定位是即席查詢層）。若 hackathon 當日 hotdata 不可用，降級把同一份 SQL 打到本機 Postgres，**表形狀仍是 9 表**，不是第 10 表。

### 5.5 官方 API 對齊（查證過，不捏造）

| 層 | 來源 | 本專案怎麼呼叫 |
|---|---|---|
| Cognee | [docs.cognee.ai](https://docs.cognee.ai/core-concepts/data-flows)：`remember(data)` = Add + Cognify；[python-api/cognify](https://docs.cognee.ai/python-api/cognify)；REST `POST /api/v1/remember` | 種子票、新 TutorialVersion、Feedback、Release 本文各呼叫一次 remember。查詢用 RocketRide `tool_cognee` 的 recall（`search_type` 預設 `GRAPH_COMPLETION_DECOMPOSITION`） |
| HydraDB | 黑客松指南：OpenCypher 多跳；RocketRide `db_hydradb`：`store` / `recall_memory` | 建圖結果寫入；問「這 UserProblem 有沒有 published Tutorial」「這次 Release 影響哪些 Tutorial」 |
| Rote | [modiqo.ai/docs](https://www.modiqo.ai/docs)、[FAQ](https://www.modiqo.ai/faq) | 第一次成功攔截在 rote workspace 跑完 → crystallize 成 Play → 同類票 `rote play run` 帶新 `ticket_id`。Play 重的是方法，不是舊答案 |
| hotdata | 黑客松指南：即席 SQL | `WHERE created_at > :last_checked`；三條指標的 COUNT／SUM／AVG |
| RocketRide | `.rocketride/schema/agent_rocketride.json` | 單一 `agent_rocketride`，`max_waves` 維持預設 10 |

---

## 6. 端到端流程

時間序（Demo 當日）：

1. **建構知識圖譜** — 匯入 Bitext 歷史列。Ticket `status = resolved`，`resolution_steps` 有值。建立／重用 UserProblem（topic = intent）與 Feature。Cognee remember，HydraDB 存圖譜。
2. **輪詢新票單** — hotdata 取 `created_at > 上次檢查` 且 `status = open` 的票。Cursor 存在 demo session／本機檔，不落第 10 表。
3. **自動回覆顧客** — HydraDB／hotdata 查該 `user_problem_id` 是否有 `status = published` 的 Tutorial。有 → deflected（回 `current_version` 連結）。無／retired／`user_problem_id` 空／同顧客再開票 → escalated。
4. **轉真人（Demo UI）** — 中欄出現解法框，預填 Bitext `response`。確認後寫 `resolution_steps`，`status = resolved`。真人不填教學五欄。
5. **分析 Ticket** — 只看 `escalated`／`resolved`。同 `user_problem_id` ≥ 3 且無 published Tutorial → Knowledge Gap → 動作 CREATE；已有教學 → KEEP。
6. **建立 Tutorial** — LLM 讀多張 `resolution_steps`，產出五欄；寫 `tutorials/cancel-order.md`；`status = published`，`current_version = v1`，`last_action = CREATE`。Cognee remember 新教學；HydraDB 連 `explains`／`UserProblem`。
7. **下一張同類票** — 才 deflect。第一次成功 → Rote 捕捉 Workflow（`replay_count = 0`）。之後同 UserProblem → 重放，`replay_count + 1`。
8. **收集 Feedback** — 顧客對 `TutorialVersion` 評 1–5。種子可預置 v1 低分（avg 2.9）。
9. **定期 Feedback Review** — demo 手動按一次。avg < 3.5 且 ≥ 3 筆且同 category ≥ 2 → REFINE 新版；否則 KEEP。`is_possibly_outdated = true` 本輪 KEEP。
10. **輪詢 Release Note** — changelog 新列寫入 `Release`，`processed_at` 空。相同 content + created_at 不重複。
11. **依 Release Note 更新** — 處理所有 `processed_at` 空的列。renamed／changed → UPDATE；deprecated／removed → RETIRE；new feature 無 Tutorial → 只記 `processed_at`。與 REFINE 同時命中先 UPDATE。
12. **展示學習指標** — hotdata 算三條，Streamlit 下欄畫曲線。

---

## 7. Pipeline 契約

單一 `agent_rocketride`。UI 只送「發生了什麼」，決策在 Agent。

### 7.1 即時路徑：輪詢新票 → 自動回覆

| 項 | 契約 |
|---|---|
| 觸發 | Streamlit「餵下一張票」或 hotdata 輪詢到新 open 票 |
| 讀 | Ticket（open、`created_at`）、UserProblem、Tutorial（published + current_version）、Workflow |
| 寫 | Ticket.status = deflected｜escalated；deflected 時填 `deflected_tutorial_id/version`；再開票填 `reopened_from_ticket_id` |
| 成功 | Then 表與 `自動回覆顧客.feature` 一致 |
| 失敗 | 無法讀 Tutorial／HydraDB → `操作失敗`，票維持 open，本輪不分析 |
| Rote | 見 §7.5；escalated 不建 Workflow |

### 7.2 Ticket Analysis → CREATE

| 項 | 契約 |
|---|---|
| 觸發 | 有新的 escalated／resolved，或 demo 按「分析」 |
| 讀 | Ticket（只 `escalated`／`resolved`）、UserProblem、Tutorial |
| 決定 | 同 topic ≥ 3 且無 published Tutorial → CREATE；已有 → KEEP；聚不起來 → 空結果 |
| 寫（CREATE） | Tutorial + TutorialVersion v1 五欄；`path`；`last_action = CREATE`；Cognee remember；HydraDB `explains` |
| 失敗 | 缺五欄任一、無 Knowledge Gap、無 Feature → `操作失敗`，不寫半篇 Tutorial |
| LLM | 只成型五欄。聚集 topic 在 demo 用 Bitext `intent`，規格不驗演算法 |

### 7.3 Release Note（入庫 ≠ 處理；不是獨立 node）

RocketRide catalog **沒有** `release` 節點。Release 是：

1. hotdata 的 `Release` **表**（demo 的模擬 changelog 就是這張表，一列一則）；
2. HydraDB 的 `Release` **圖譜節點**（Cognee `remember` 本文後寫入，邊 `changes` → Feature）；
3. 同一 `agent_rocketride` 的一條 pipeline（跟 Ticket Analysis、Feedback Review 並列）。

不要為它加第四欄畫面、第二個 Agent、或自造 `tool_release`。

```
左：[貼 changelog]
        |
        v
hotdata 輪詢 created_at > 上次檢查
        |
        v
Release 列入庫（processed_at 空）     ← Feature：輪詢ReleaseNote
        |
        v
同一 Agent 處理所有 processed_at 空的列
        |
        +-- renamed / changed --> UPDATE 教學 vN+1、Feature.name、中欄 Step 3 diff
        +-- deprecated / removed --> RETIRE（retired + is_obsolete）
        +-- new feature 且無 Tutorial --> 只寫 processed_at，不 CREATE
        |
        v
Cognee remember 本文 → HydraDB (Release)-[:changes]->(Feature)<-[:explains]-(Tutorial)
```

Demo 貫穿列：`Cancel Order has been renamed to Cancel Purchase.` → `tutorials/cancel-order.md` Step 3 從 `Click "Cancel Order"` 改成 `Click "Cancel Purchase"`。

| 項 | 契約 |
|---|---|
| 觸發 | 左欄「貼 changelog」或 hotdata 輪詢到新列（同一功能，資料來源不同） |
| 入庫 | `輪詢ReleaseNote`：`created_at > 上次檢查` 寫入 Release，`processed_at` 空；content+created_at 已存在則不新增 |
| 處理 | `依ReleaseNote更新Tutorial`：所有 `processed_at` 空的列一次處理 |
| 讀 | Release、Feature、Tutorial；HydraDB 多跳 `(Release)-[:changes]->(Feature)<-[:explains]-(Tutorial)` |
| 寫 | ReleaseFeatureChange；renamed／changed → 新 TutorialVersion、`Feature.name`、`last_action = UPDATE`、`processed_at`；deprecated／removed → `retired`／`is_obsolete`／`RETIRE` |
| 不寫 | CREATE。new feature 無 Tutorial 只記 `processed_at` |
| 畫面 | 中欄 Tutorial diff；下欄曲線不因入庫本身改變（要等下一張票才可能反映） |
| 失敗 | 擷取不到 change_type → `操作失敗`，`processed_at` 保持空，下輪可重跑 |

### 7.4 Periodic Feedback Review

| 項 | 契約 |
|---|---|
| 觸發 | demo 手動「Review」；不規定週期 |
| 讀 | Tutorial.current_version 的 Feedback；`AVG(rating)`、count、同 category count |
| 決定 | avg < 3.5 **且** count ≥ 3 **且** 同 category ≥ 2 → REFINE；否則 KEEP。`is_possibly_outdated` → KEEP |
| 寫 | 新版本 + `reason` + `supersedes_version` + `last_action`；Cognee remember 新版 |
| 再開票 | `reopened_from_ticket_id` 只進指標，本輪不直接 REFINE |
| 衝突 | 與 UPDATE 同時：先 UPDATE，REFINE 等下一輪 |

### 7.5 Rote（肌肉記憶）

| 項 | 契約 |
|---|---|
| 捕捉 | 某 UserProblem **第一次** deflected 成功 |
| Play 步驟 | 匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket |
| 寫 | Workflow 一列，`replay_count = 0`，`captured_at` = 系統目前時間 |
| 重放 | 已有 Workflow 且再次 deflected → 跑同一 Play（新 ticket_id）→ `replay_count + 1` |
| 不做 | 不重放 `resolution_steps`、不產影片、escalated 不捕捉 |

---

## 8. Tutorial 生命週期狀態機

```
（無 Tutorial）
      |
      | 分析：同 topic >= 3 且無 published
      v
   CREATE  -->  status=published, current_version=v1, last_action=CREATE
      |
      +-- Feedback Review 三條件成立 --> REFINE --> vN+1, last_action=REFINE
      +-- Feedback 未達門檻         --> KEEP   --> last_action=KEEP
      +-- Release renamed/changed   --> UPDATE --> vN+1, last_action=UPDATE
      +-- Release deprecated/removed--> RETIRE --> status=retired, is_obsolete=true
      +-- is_possibly_outdated      --> 本輪 KEEP（等 UPDATE 做完）
```

`status` 值：draft / published / retired。黑客松建立即 published；draft 留欄位，不建審核佇列。

不變條件（clarified）：

- `is_obsolete = true` ⇒ `is_possibly_outdated = false`、`status = retired`、`last_action = RETIRE`
- `status = published` ⇒ `current_version` 有值
- `last_action = CREATE` ⇒ `current_version = v1`
- 內容五欄只在 `TutorialVersion`；`supersedes_version` 只指同篇上一版；v1 必空

---

## 9. 資料模型對應

9 表是邏輯模型。不發明第 10 張業務表。

| 表 | hotdata（SQL） | HydraDB（圖譜） |
|---|---|---|
| Ticket | 列與 status、輪詢 `created_at` | 節點 Ticket，邊 `asks_about` → Feature |
| UserProblem | topic 唯一、計數 | 節點 UserProblem |
| Feature | name／status | 節點 Feature |
| Tutorial | status、current_version、旗標、last_action | 節點 Tutorial，邊 `explains` → Feature |
| TutorialVersion | 五欄快照 | 節點 TutorialVersion，邊 `supersedes` |
| Feedback | rating、category；AVG 只算 current_version | 節點 Feedback，邊 `refers_to` |
| Release | content、created_at、processed_at | 節點 Release |
| ReleaseFeatureChange | change_type、from_name、to_name | 邊 `changes`（Release → Feature） |
| Workflow | steps、replay_count | 可省略節點；重放率用 SQL |

**Design decision：** `上次檢查時間` 存在 demo session（或本機 cursor 檔），不是業務表。理由：規格把它當 Given，不是 column。

**Design decision：** `.md` 檔是 Tutorial.path 的展示副本；權威內容在 TutorialVersion。Agent 寫檔與寫表同一成功邊界：五欄缺一則兩者都不寫。

---

## 10. 圖譜關係與多跳查詢

Cognee 從票／教學／回饋／Release 抽出實體後，HydraDB 至少要能回答這些邊：

| 邊 | 從 → 到 | 何時寫 |
|---|---|---|
| `asks_about` | Ticket → Feature | 匯入或分析填了 feature_id |
| `explains` | Tutorial → Feature | CREATE／UPDATE |
| `refers_to` | Feedback → TutorialVersion | 收集 Feedback |
| `changes` | Release → Feature | 處理 Release 寫出 ReleaseFeatureChange |
| `supersedes` | TutorialVersion → 上一版 | UPDATE／REFINE |

多跳（評審會問「哪些教學受這次 Release 影響」）：

```text
(Release)-[:changes]->(Feature)<-[:explains]-(Tutorial)
WHERE Release.processed_at IS NULL
```

不建先備知識邊。`prerequisites` 是自由文字。

---

## 11. Demo 資料策略

資料集：[bitext/Bitext-customer-support-llm-chatbot-training-dataset](https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset)（`instruction` / `category` / `intent` / `response`；CDLA-Sharing-1.0）。

主打三個 topic：`cancel_order`、`track_refund`、`change_shipping_address`。

貫穿檔：`tutorials/cancel-order.md`。Step 3 `Click "Cancel Order"` → Release「Cancel Order has been renamed to Cancel Purchase.」→ `Click "Cancel Purchase"`。

顧客：`alice@example.com`、`bob@example.com`。

**Design decision：** 種子用每類 2 張歷史 resolved（建 UserProblem／Feature，不到 CREATE 門檻）。現場再餵第 3 張 → 轉真人 → CREATE v1 → 第 4 張 deflect。Feedback v1 avg 2.9 可種子預置，Review 時 REFINE 到 4.4。三到五類每類兩到三筆不是硬規則（Clarify）。

現場餵票與 hotdata 輪詢是同一功能，只是資料來源不同。現場貼 changelog 與 hotdata 輪詢 Release 也是同一功能。

---

## 12. 學習指標

全部由 hotdata 算，不落欄。Streamlit 下欄展示。

| 指標 | 分子 | 分母 | 公式 |
|---|---|---|---|
| deflection rate | `status = deflected` | deflected + escalated | 2/4 = 0.5（Example） |
| 重放解決率 | `SUM(Workflow.replay_count)` | deflected 票數 | 2/4 = 0.5 |
| 圖譜覆蓋 | 有 published Tutorial 的 UserProblem | UserProblem 總數 | 1/2 = 0.5 |

open／resolved 不進 deflection 分母。

畫面「兩條曲線」= deflection rate 上升 + 平均 rating 2.9 → 4.4。重放解決率與圖譜覆蓋用同一下欄的數字／小圖，不另開 dashboard。

Self-learning 的可觀察點：第 4 張票從 escalated 變成 deflected；Rote `replay_count` 增加；REFINE 後均分上升；Release 後 Step 3 文字改變。

---

## 13. Demo UI 邊界

一個 Streamlit 分頁（`docs/design/architecture.md`）。

| 區 | 觸發 | 展示 |
|---|---|---|
| 左 | 餵下一張票、貼 changelog | 顧客原文、系統回的教學連結 |
| 中 | 確認解法（預填 Bitext）、按分析／Review | deflected／轉真人、`.md`、Release 後 Step 3 diff |
| 下 | 無（只讀） | deflection rate、均分、重放率、覆蓋 |

UI **不**計算門檻、**不**決定 CREATE／擋票、**不**列出教學人員待辦。

---

## 14. 錯誤與異常語意

規格失敗一律 `Then 操作失敗`。本檔不發明錯誤碼表。

| 情境 | 負責層 | 可見結果 |
|---|---|---|
| rating 非 1–5、缺 tutorial_id／timestamp、無對應 TutorialVersion | Demo／hotdata 寫入前檢查 | 操作失敗，Feedback 不入庫 |
| 建立時缺五欄、無 Knowledge Gap、無 Feature | RocketRide 建立路徑 | 操作失敗，Tutorial 不出現 |
| HydraDB／Cognee／hotdata 讀寫失敗 | 該層 adapter | 操作失敗；票維持原 status；Release `processed_at` 保持空 |
| Rote Play 重放失敗 | muscle | 本張票改走 Agent 即時路徑（仍可 deflected）；不把失敗寫成 replay_count+1 |
| 已處理的 Release 再跑 | Release pipeline | 不改 Tutorial（Rule 已有） |

---

## 15. 測試策略

驗收來源只有十一份 `.feature` 的 Example。不發明例子當需求。

| 層級 | 測什麼 | 對齊 |
|---|---|---|
| 單元 | 門檻函式：≥3、avg < 3.5、category ≥ 2、content+created_at 去重 | 各 Rule 的臨界 Example |
| 契約 | Given 表 → When → Then 表 | 11 個 Feature 的 step 句型 |
| 手動 demo | §16 切片結束時的畫面 | architecture.md 左中下 |

規劃位置（尚未存在）：單元 `tests/unit`，整合 `tests/integration`。本階段不寫測試碼。

統計（2026-09-11 對 `docs/spec/features/*.feature` 實數）：**58 Rule、81 Example、0 條 `#TODO`**。每條 Rule 的負責層見 §19.1。

---

## 16. 交付切片（約 8 小時）

每一片結束都要能手動驗證。不先做 stretch。

| 片 | 結束時可看到 | 依賴 |
|---|---|---|
| A 種子建圖 | hotdata 有 resolved Ticket、UserProblem、Feature；Cognee／HydraDB 能 recall cancel_order | 帳號、Bitext 列 |
| B 餵票轉真人 | 第 1–2 張 cancel_order → escalated；確認框寫入 resolution_steps | A |
| C CREATE v1 | 第 3 張湊滿 → `tutorials/cancel-order.md` published v1 | B |
| D deflect + Rote | 第 4 張回連結；Workflow 出現；第 5 張 replay_count=1 | C |
| E 指標 + REFINE | 下欄 deflection 上升；種子低分 Review → v2，均分 2.9→4.4 | D |
| F Release UPDATE | 入庫一則更名 → Step 3 diff「Cancel Purchase」；Snyk 掃過本次程式 | E |

---

## 17. Demo 當日風險（不是規格 open question）

| 風險 | 訊號 | 降級 |
|---|---|---|
| RocketRide／Bedrock 連不上 | Agent 無回應 | 本機用同一套門檻函式跑完迴圈，評審仍看 Then 表與曲線；五層改口頭對應 |
| Cognee／HydraDB 未就緒 | remember／Cypher 失敗 | ERM 仍寫 hotdata；圖譜改事後補 remember，demo 先秀 SQL 覆蓋 |
| hotdata 不可用 | 輪詢／AVG 失敗 | 同一 SQL 打本機 Postgres，表仍是 9 張 |
| Rote 未暖機 | 無 Play | 第一次仍 Agent deflect；Workflow.replay_count 用本機計數，並標「Play 未捕捉」 |
| Snyk 太晚 | 評審查安全層 | 切片 F 之前掃；`.env` 不進 repo |
| FigJam 生不出圖 | Figma seat = View | 用 `architecture.md` ASCII |

deploy 只用 `ROCKETRIDE_DEPLOY_*`，不把 pipeline deploy 到 dev 連線。本階段不安裝套件、不 deploy。

---

## 18. 假設、限制與 open questions

### 假設（design decision，可改但須標）

1. 單一 RocketRide Agent，三條 pipeline + 即時路徑。否決 multi-agent：8 小時控不了兩個 controller。
2. Demo UI = 一個 Streamlit 分頁。否決多頁 dashboard。
3. LLM 只成型五欄；topic 用 Bitext intent。否決現場 embedding 聚類（規格不驗演算法）。
4. 輪詢週期不規定，demo 手動觸發。
5. Cognee dataset 固定、不開 per-call override。
6. 9 表即時列在 hotdata；HydraDB 存圖譜與版本關係。

### 限制

- Repo 目前沒有可執行碼。
- Bitext 沒有可操作產品，教學來源只能是 `resolution_steps`。
- `docs/客服自助教學生成器 — 系統架構規格.md` 仍含已被推翻的句子（審核佇列、操作產品、Slack、影片、SLA）；以 `docs/spec/` 為準。
- 未實測 Cognee → HydraDB 的 `graph_db_config` 當日是否可直連；切片 A 要先做一次 remember + Cypher 煙測。

### Open questions

**無新發現。** Clarify 0 題待處理。未 resolved 的 clarify 項：無。

---

## 19. Source inventory 與規則覆蓋

### 19.1 Spec-to-Design（58 Rule，無人落空）

| Feature | Rule 數 | 負責層 |
|---|---|---|
| 建構知識圖譜 | 5 | Cognee remember + HydraDB 節點 + hotdata 寫 Ticket／UserProblem／Feature；RocketRide 只當匯入觸發 |
| 輪詢新票單 | 1 | hotdata SQL；下一步進即時路徑 |
| 輪詢ReleaseNote | 3 | hotdata 寫 Release（processed_at 空） |
| 自動回覆顧客 | 5 | RocketRide 即時路徑 + HydraDB「有無 published」 |
| 重放已驗證流程 | 3 | Rote Play + hotdata Workflow |
| 分析SupportTickets | 9 | RocketRide Ticket Analysis + hotdata 計數 |
| 建立Tutorial | 5 | RocketRide + `llm_bedrock` 五欄 + 寫 `.md` + Cognee／HydraDB |
| 收集Feedback | 7 | Streamlit 表單 + hotdata Feedback + Cognee remember |
| 定期優化Tutorial | 10 | RocketRide Periodic Review + hotdata AVG／COUNT |
| 依ReleaseNote更新Tutorial | 7 | RocketRide Release Update + HydraDB 多跳 + hotdata processed_at |
| 展示學習指標 | 3 | hotdata 三條公式；Streamlit 下欄展示 |
| **合計** | **58** | |

### 19.2 現況 vs 目標

| 目標 | 現況 |
|---|---|
| 五層接線 | 僅有 schema 快取與規格；程式不存在 |
| 11 Feature 行為 | 僅有 `.feature` |
| Demo UI | 僅有 architecture.md 草圖 |
| tutorials/*.md | 不存在 |
| 測試 | 不存在 |
| Implementation plan | 本階段不寫；切片只在 §16 |

### 19.3 約束衝突稽核

本檔沒有：ShowMe／MCP overlay、第二個 Agent、審核佇列、SLA、Slack、Customer 表、先備邊、教學影片、Release CREATE、Rote 重放解票、必須操作產品 UI、Copilot／Meeting 範例、`hackathonQoder`、錯誤碼表。

草稿已脫鉤：產品主軸是顧客 deflection；建立即 published；教學來源是 `resolution_steps`。

### 19.4 實際讀取

**完整讀：**

- `docs/spec/prompts/4.design_prompt.md`
- `docs/spec/erm.dbml`
- `docs/spec/features/` 十一份（含 `輪詢ReleaseNote.feature`）
- `docs/spec/.clarify/overview.md`、`resolved/決策總表.md`
- `docs/design/architecture.md`
- `docs/客服自助教學生成器 — 系統架構規格.md`
- `docs/Data_and_AI_Hackathon.md`
- `CLAUDE.md`
- `.rocketride/schema/{tool_cognee,db_hydradb,agent_rocketride,llm_bedrock,db_postgres}.json`

**抽查／目錄：** `.clarify/data/` 與 `.clarify/features/`（空）；repo root 無 `package.json`／`pyproject.toml`；`.rocketride/schema/` 141 檔。

**未逐字重讀：** `resolved/data/` 與 `resolved/features/` 的 97 份個別檔（以決策總表 + 作用中 erm／feature 為準；與總表衝突時以解決記錄為準，本次未發現衝突）。

**官方文件：**

- Cognee：https://docs.cognee.ai/core-concepts/data-flows 、https://docs.cognee.ai/python-api/cognify 、https://docs.cognee.ai/api-reference/introduction
- Rote：https://www.modiqo.ai/docs 、https://www.modiqo.ai/faq
- HydraDB／RocketRide 節點：`.rocketride/schema/` + 黑客松指南

**未當來源：** `design-draft.md` 的 Copilot 敘事、`phase0829-1.md`、舊 ShowMe prompt 殘留。
