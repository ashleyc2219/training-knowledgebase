# Phase 2 — 餵票、即時路徑、轉真人、分析、CREATE v1

- **對應設計：** `docs/design/showme.md` §16 切片 B＋C、§7.1（即時路徑）、§7.2（Ticket Analysis → CREATE）；畫面對應 `docs/design/architecture.md` §1（左／中欄）、§4（轉真人 → Tutorial）
- **對應規格：** `docs/spec/features/輪詢新票單.feature`、`自動回覆顧客.feature`、`分析SupportTickets.feature`、`建立Tutorial.feature`（共 20 條 Rule）
- **狀態：** 規劃文件，**尚未實作**。Phase 0／1 由別的 agent 同時進行，撰寫當下（2026-09-11）已落地骨架：`app/{errors,config}.py`、`app/analytics/{sql,local_db,hotdata_client,metrics,db}.py`、`app/agent/rules.py`（純函式已寫齊）、`app/agent/{realtime,analysis,create_tutorial,rocketride_client,feedback_review,release_update}.py`（**只有 docstring ＋ `TODO(Phase 2)`，函式尚未實作**）、`app/ingest/poll.py`、`app/memory/*`、`data/script/demo_tickets.json`、`tutorials/.gitkeep`（空目錄）。本檔的工作就是把那些 TODO 填掉。不要把本檔任何一段當成「已實作」。
- **⚠️ 與既有骨架的差異：** 下文的程式碼片段是**目標形狀**，不是要覆蓋既有檔案。碰到既有檔案時一律「補實作」而不是「重寫」，且沿用既有命名（例如常數是 `rules.RECURRING_MIN`，不是 `RECURRING_MIN_TICKETS`）。三處已知落差見步驟 2.0／2.1。
- **預估時間：** 約 150 分鐘（2.5 小時）
  | 段 | 內容 | 分鐘 |
  |---|---|---|
  | 2.0 | 前置檢查與劇本資料 | 15 |
  | 2.1–2.3 | rules / poll / realtime ＋ 單元測試 | 40 |
  | 2.4–2.5 | Streamlit 左欄餵票、中欄轉真人 | 25 |
  | 2.6–2.7 | analysis ＋ create_tutorial ＋ 單元測試 | 45 |
  | 2.8–2.9 | rocketride_client ＋ pipeline.json ＋ instructions | 20 |
  | 2.10 | 🖐️ 手動 deploy ＋ 走一次完整驗收 | 5 |

## 前置：Phase 1 驗收通過（具體條件）

Phase 2 開工前，下列每一條都要能在終端機驗證。任一條不成立就先回頭補 Phase 0／1，不要在本 Phase 補建表或補種子。

| # | 條件 | 怎麼驗 |
|---|---|---|
| P1 | `uv run python -c "import app"` 成功，`app/errors.py` 有 `OperationFailed` | `uv run python -c "from app.errors import OperationFailed; print(OperationFailed)"` |
| P2 | 9 表 schema 已建（Ticket / UserProblem / Feature / Tutorial / TutorialVersion / Feedback / Release / ReleaseFeatureChange / Workflow），欄位與 `docs/spec/erm.dbml` 一致 | `uv run python -c "from app.analytics.hotdata_client import run_sql; print(run_sql('SELECT COUNT(*) FROM Ticket'))"` |
| P3 | `app/analytics/hotdata_client.run_sql()` 可讀可寫；hotdata 不通時自動落到 `app/analytics/local_db.py`，**表形狀仍是 9 張** | 同上；再跑一次 INSERT/DELETE 的煙測 |
| P4 | 三個 topic 的 `UserProblem` 與 `Feature` 已存在：`cancel_order`／`Cancel Order`、`track_refund`／`Track Refund`、`change_shipping_address`／`Change Shipping Address`，且 `UserProblem.feature_id` 已填 | `SELECT id, topic, feature_id FROM UserProblem` 回 3 列且 feature_id 非空 |
| P5 | `app/memory/cognee_client.py` 的 `remember()/recall()` 與 `app/memory/hydradb_client.py` 的 `upsert_node/upsert_edge/cypher` 可呼叫；不通時丟明確例外而不是靜默 | Phase 1 的煙測腳本 |
| P6 | `app/demo/streamlit_app.py` 空殼可 `uv run streamlit run app/demo/streamlit_app.py` 起得來，左／中／下三區塊佔位已在 | 瀏覽器打開看到三欄 |
| P7 | `.env` 由 Phase 0 載入機制讀得到 `ROCKETRIDE_URI` / `ROCKETRIDE_APIKEY` / `ROCKETRIDE_DEPLOY_URI` / `ROCKETRIDE_DEPLOY_APIKEY`；`.env` 仍在 `.gitignore` | `git check-ignore -v .env` 有輸出 |
| P8 | **cancel_order 目前沒有任何 `status IN ('escalated','resolved')` 的 Ticket** | 見下方「⚠️ 交界處理」 |

### ⚠️ 交界處理：cancel_order 的種子票

`showme.md` §11 的種子策略是「每類 2 張歷史 resolved」。但本 Phase 的驗收要求是**第 1、2、3 張 cancel_order 都在台上餵進去**，第 3 張 resolved 後按分析才 CREATE。若 Phase 1 已為 cancel_order 種了 2 張 resolved，餵第 1 張時就湊滿 3 張，CREATE 會提早一張發生，劇本節奏會亂。

**Design decision（本 Phase）：** `cancel_order` 的種子計數歸零，`track_refund` 與 `change_shipping_address` 維持每類 2 張 resolved（圖譜覆蓋分母仍是 3 個 UserProblem，§12 的指標不受影響）。

```sql
-- Phase 2 開工前跑一次；把 cancel_order 的種子票移出分析母體（不是刪票，保留原文給 LLM 當素材）
UPDATE Ticket
   SET status = 'open'
 WHERE user_problem_id = (SELECT id FROM UserProblem WHERE topic = 'cancel_order')
   AND status IN ('escalated', 'resolved');
-- 驗收：下面這句必須回 0
SELECT COUNT(*) FROM Ticket
 WHERE user_problem_id = (SELECT id FROM UserProblem WHERE topic = 'cancel_order')
   AND status IN ('escalated', 'resolved');
```

> 把它們改成 `open` 而不是刪掉，是因為 `輪詢新票單.feature` 的 Rule 只處理 `created_at > 上次檢查時間` 的票——這些舊票 `created_at` 早於 cursor，會維持 `open` 不被處理，剛好符合該 Rule 的 Example（ticket 1、2 維持 open）。

## 產出

`[改]` = 檔案已存在，補實作；`[新]` = 本 Phase 新建；`[生]` = 執行後自動產生。

```
[改] app/agent/rules.py              只修 classify_ticket 的判斷順序（見步驟 2.1）
[改] app/agent/realtime.py           填掉 TODO(Phase 2)：handle_open_ticket
[改] app/agent/analysis.py           填掉 TODO：analyze_tickets / knowledge_gaps
[改] app/agent/create_tutorial.py    填掉 TODO：create_tutorial（LLM 五欄 → 兩表 ＋ .md）
[改] app/agent/rocketride_client.py  填掉 TODO：run_agent / call_llm / deploy_pipeline
[改] app/ingest/poll.py              填掉 TODO：poll_new_tickets ＋ .state/last_checked.json cursor
[改] app/analytics/sql.py            追加本 Phase 的具名 SQL 常數（不動既有常數）
[改] app/demo/streamlit_app.py       左欄「餵下一張票」、中欄決策卡＋解法確認框＋.md 檢視、按「分析」
[改] data/script/demo_tickets.json   補 bitext_response 欄 ＋ 追加一筆 intent 為 null 的票
[新] app/agent/pipeline.json         RocketRide pipeline 定義（含 instructions 全文）
[生] tutorials/cancel-order.md       CREATE 跑完後產生（不是手寫，目前只有 .gitkeep）
[改] tests/unit/test_rules.py        新增 test_reopen_wins_over_published
[新] tests/unit/test_realtime.py
[新] tests/unit/test_analysis.py
[新] tests/unit/test_create.py
```

---

## 1. 目標與結束時可看到

本 Phase 把 §16 的切片 B（餵票轉真人）與切片 C（CREATE v1）做完。結束時，在同一個 Streamlit 分頁上：

1. 按「餵下一張票」三次，中欄依序出現三張 `cancel_order` 的**轉真人**卡片（`status = escalated`）。
2. 每張卡片有一個解法框，內容**已預填 Bitext `response`**；按「確認解法」→ 該票 `resolution_steps` 有值、`status = resolved`。
3. 按「分析」→ 中欄顯示決策 `{user_problem_id: 1, action: CREATE}`。
4. 系統自動接著跑 CREATE → 中欄渲染出 `tutorials/cancel-order.md`，Step 3 含 `Click "Cancel Order"`。
5. hotdata 查得到 `Tutorial(status = published, current_version = v1, last_action = CREATE, path = tutorials/cancel-order.md)` 與 `TutorialVersion(v1, supersedes_version 空, 五欄皆有值)`。
6. 餵一張 `user_problem_id` 為空的票（`Something is wrong with my thing`）→ 一樣 `escalated`，不 crash。
7. RocketRide dev 連線可用時，中欄決策卡多出一行「Agent 決策：escalated（與本機一致）」；不可用時該行顯示「Agent 未回應（本機決策照跑）」，票流不中斷。

**本 Phase 不做**（留給後面）：deflect（要有 published Tutorial 才會發生，第 4 張票是 Phase 3）、Rote 捕捉／重放、Feedback、Release、下欄曲線。

---

## 2. 在整體迴圈的位置（六 phase 時間線）

```
  Phase 0        Phase 1         >>> Phase 2 <<<        Phase 3         Phase 4          Phase 5
  環境與骨架      種子建圖         即時路徑 + CREATE      deflect + Rote   指標 + REFINE    Release UPDATE
  ─────────      ─────────       ──────────────────     ───────────     ────────────     ─────────────
  uv 專案        Bitext 匯入      餵票 → escalated       第 4 張同類票    下欄三條曲線      貼 changelog
  9 表 schema    UserProblem      轉真人 → resolved       → deflected     種子低分 Review   → Release 入庫
  errors.py      Feature          分析 → CREATE          Workflow 捕捉    → REFINE v2      → UPDATE v2
  hotdata 連線   Cognee remember  Tutorial v1 published   第 5 張 replay  2.9 → 4.4        Step 3 diff
  Streamlit 殼   HydraDB 節點     tutorials/*.md 出現     _count = 1                       Snyk 掃描
                                 pipeline.json deploy
  ─────────      ─────────       ──────────────────     ───────────     ────────────     ─────────────
  showme §16 前置  切片 A          切片 B ＋ C            切片 D          切片 E           切片 F

  本 Phase 產生的東西，下游怎麼用：
    Tutorial(published, v1) ──────────────► Phase 3 的 deflect 判斷靠它
    rules.classify_ticket  ──────────────► Phase 3 重放失敗時的 fallback 走同一條
    rocketride_client      ──────────────► Phase 4/5 的 Review / Release pipeline 共用
    tutorials/cancel-order.md ───────────► Phase 5 的 Step 3 diff 拿它當基準
```

---

## 3. 流程與資料流

### 3.1 餵票 → 即時路徑決策樹

`realtime.handle_open_ticket(ticket_id)` 的判斷順序（順序有意義，第一個命中就結束）：

```
              [ 餵下一張票 ]  或  [ poll_new_tickets(cursor) ]
                        |
                        v
        ┌───────────────────────────────┐
        │ 讀 Ticket                      │   讀不到 / status != 'open'
        │ status == 'open' ?             ├──────────────► 不動它，return（不算失敗）
        └───────────────┬───────────────┘
                        │ yes
                        v
        ┌───────────────────────────────┐
        │ ① user_problem_id 為空？        │   yes
        │   （自動回覆顧客 Rule 3）        ├──────────────► escalated
        └───────────────┬───────────────┘                  deflected_* 留空
                        │ no                               reopened_from 留空
                        v
        ┌───────────────────────────────┐
        │ ② 同 customer_ref ＋ 同         │   yes
        │   user_problem_id 有一張        ├──────────────► escalated
        │   status='deflected' 的舊票？    │                  reopened_from_ticket_id = 舊票 id
        │   （Rule 5：再開票）             │                  deflected_* 留空
        └───────────────┬───────────────┘
                        │ no
                        v
        ┌───────────────────────────────┐
        │ ③ 該 user_problem_id 有         │   no（含沒有 Tutorial、
        │   status='published' 的         ├─── status='retired'）──► escalated
        │   Tutorial？                    │      （Rule 2、Rule 4）
        │   （Rule 1／2／4）               │
        └───────────────┬───────────────┘
                        │ yes
                        v
                    deflected
                    deflected_tutorial_id      = Tutorial.tutorial_id
                    deflected_tutorial_version = Tutorial.current_version

        任何一步讀寫丟例外 ─► rollback ─► raise OperationFailed
                                         票維持 open，本輪不分析
                                         （showme §7.1 失敗列、§14）
```

> ② 排在 ③ 前面：`自動回覆顧客.feature` Rule 5 的 Given **有** published Tutorial，結果仍是 escalated。所以再開票的優先序高於「有教學就 deflect」。
> ③ 的「retired 視同沒有」用 SQL `WHERE status = 'published'` 自然達成，不必額外寫 if。

### 3.2 轉真人 → 分析 → CREATE

```
  escalated 票（中欄卡片）
        │
        │  解法框預填 data/script/demo_tickets.json 的 bitext_response
        │  🙋 按「確認解法」
        v
  UPDATE Ticket SET resolution_steps = :text, status = 'resolved' WHERE id = :id
        │
        │  🙋 按「分析」
        v
  analysis.analyze_tickets()
        │
        │  只取 status IN ('escalated','resolved') 且 user_problem_id IS NOT NULL
        │  GROUP BY user_problem_id → count
        v
   ┌─────────────────────┐
   │ count >= 3 ?         │ no ──► 不進結果（recurring topic 為空 / 動作為空）
   └──────────┬──────────┘
              │ yes  ← recurring topic
              v
   ┌─────────────────────┐
   │ 有 published         │ yes ──► {user_problem_id, action: 'KEEP'}
   │ Tutorial ?           │
   └──────────┬──────────┘
              │ no   ← Knowledge Gap
              v
        {user_problem_id, action: 'CREATE'}
              │
              v
  create_tutorial(user_problem_id)
        │
        ├─ 1. 重驗 Knowledge Gap（action 必須是 CREATE）──── 不是 ──► OperationFailed
        ├─ 2. 取 feature_id（UserProblem.feature_id → 否則票的多數 feature_id）
        │     feature_id 為空 或 Feature 表查無此列 ────────────► OperationFailed
        ├─ 3. SELECT content, resolution_steps FROM Ticket（同 up，escalated/resolved，解法非空）
        ├─ 4. call_llm(prompt) → JSON 五欄
        ├─ 5. 五欄任一為空／缺鍵／JSON 壞掉 ──────────────────► OperationFailed（不寫半篇）
        │
        │   ─────── 以下是同一個成功邊界（showme §9）───────
        ├─ 6. BEGIN
        │       INSERT Tutorial(feature_id, user_problem_id, path,
        │                       status='published', current_version='v1',
        │                       is_possibly_outdated=false, is_obsolete=false,
        │                       last_action='CREATE')
        │       INSERT TutorialVersion(tutorial_id, 'v1', 五欄,
        │                              reason='', supersedes_version='',
        │                              created_at=now)
        │       write tutorials/<slug>.md
        │     COMMIT     ← 寫檔丟例外就 ROLLBACK ＋ 刪半檔 ＋ OperationFailed
        │   ──────────────────────────────────────────────
        │
        └─ 7. best-effort（失敗只記 warning，不回滾）：
                cognee_client.remember(TutorialVersion 全文)
                hydradb_client.upsert_node('Tutorial', ...)
                hydradb_client.upsert_edge('explains', Tutorial → Feature)
              （showme §17：Cognee／HydraDB 不通 → 只寫 hotdata）
```

### 3.3 RocketRide pipeline 節點接線

節點與參數名全部來自 `.rocketride/schema/<node>.json` 實查，不是憑印象寫的。

```
                    HTTP POST  {ROCKETRIDE_URI}/webhook/{project_id}/{source}
                    body = {"event":"ticket_opened", ...}
                                    │
                                    v
                  ┌─────────────────────────────────────┐
                  │ id: demo_webhook                     │
                  │ provider: webhook   (classType源)    │
                  │ config: {type:"webhook",             │
                  │          mode:"Source",              │
                  │          hideForm:true,              │
                  │          parameters:{}}              │
                  │ lanes(_source): tags text json       │
                  │                 audio video image    │
                  │                 questions            │
                  └──────────────┬──────────────────────┘
                                 │ input lane: "questions"
                                 v
        ┌────────────────────────────────────────────────────┐
        │ id: support_agent                                   │
        │ provider: agent_rocketride                          │
        │ config: { agent_description: "...",                 │
        │           instructions: [ …見 §5 步驟 2.9… ],       │
        │           max_waves: 10 }          ← 預設，不調      │
        │ lanes: questions ──► answers                        │
        └──┬──────────────┬───────────────┬─────────────┬────┘
           │ control      │ control       │ control     │ control
           │ classType    │ classType     │ classType   │ classType
           │ = "llm"      │ = "memory"    │ = "tool"    │ = "tool"
           │ (min1 max1)  │ (min1 max1)   │ (min0)      │ (min0)
           v              v               v             v
   ┌──────────────┐ ┌─────────────┐ ┌──────────────┐ ┌──────────────┐
   │ tutorial_llm │ │ agent_memory│ │semantic_memory│ │ graph_memory │
   │ llm_bedrock  │ │memory_       │ │ tool_cognee  │ │ db_hydradb   │
   │ profile:     │ │ internal     │ │ dataset:main │ │ profile:     │
   │ anthropic_   │ │              │ │ allow_dataset│ │  default     │
   │ claude-      │ │              │ │ _override:   │ │ database:    │
   │ sonnet-4-5   │ │              │ │  false       │ │ support_     │
   │ region /     │ │              │ │ search_type: │ │  tutorials   │
   │ accessKey /  │ │              │ │ GRAPH_COMPLE-│ │ collection:  │
   │ secretKey    │ │              │ │ TION_DECOMPO-│ │  default     │
   │              │ │              │ │ SITION       │ │ max_results: │
   │              │ │              │ │ top_k: 15    │ │  10          │
   └──────────────┘ └─────────────┘ └──────────────┘ └──────────────┘
        │
        │ 降級：把 tutorial_llm 的 provider 換成 llm_anthropic
        │      （profile: "claude-sonnet-4-6" ＋ apikey）
        │      invoke.llm 是 min 1 / max 1 ──► 不能掛兩顆 LLM，
        │      所以降級是「換 provider」而不是「加第二個節點」
        v
   answers lane ──► 由開任務的 client 讀回（SDK use()/chat() 的串流回應）
                    catalog 140 個節點裡沒有 response/sink 類節點，
                    所以不接輸出節點，也不發明一個。
```

**不接**（`showme` §5.4）：`mcp_client`、第二個 `agent_*`、`tool_slack`。catalog 裡**沒有** hotdata 與 Rote 節點——這兩層走本機 CLI（`hotdata`、`rote` 已裝），不發明 `db_hotdata` / `tool_rote`。

### 3.4 本機決策 vs RocketRide Agent：誰說了算

**Design decision：本機為主（authoritative），RocketRide 為決策展示（mirror）。**

| | 本機 `realtime.handle_open_ticket` | RocketRide `support_agent` |
|---|---|---|
| 寫 `Ticket.status` | **是，唯一寫入者** | 否 |
| 失敗時 | `raise OperationFailed`，票維持 open | 不影響票流，中欄顯示「Agent 未回應」 |
| 逾時 | 無（同步 SQL） | 3 秒，fire-and-forget |
| 驗收對象 | `.feature` 的 Then 表 | 中欄的「Agent 決策」一行 |

理由：

1. **規格的 Then 只寫資料狀態。** 四份 `.feature` 的驗收是「Ticket 資料為…」。唯一寫入者是本機 SQL，測試才可重跑、結果才可預測。
2. **Agent 是 wave-planning，輸出不保證形狀。** `agent_rocketride` 的 `max_waves` 預設 10，回應是自然語言＋工具呼叫的合成結果。把票的 status 綁在它身上，等於把 demo 綁在一個非決定性迴圈上。
3. **評審要看「RocketRide 真的在做事」，而不是「RocketRide 是單點故障」。** 中欄把兩邊決策並排（`本機：escalated ／ Agent：escalated（一致）`），反而比只有一邊更能證明五層都在跑；不一致時顯示 `⚠ 不一致`，那是值得講的觀察，不是 bug。
4. **`showme` §17 已定調降級：** RocketRide／Bedrock 連不上 → 本機用同一套門檻函式跑完迴圈。選「本機為主」，降級路徑跟正常路徑是同一條，不需要第二套程式。

實作約束：webhook 呼叫**絕不**丟 `OperationFailed`。它不在規格的成功邊界上，失敗就只是少一行展示。

---

## 4. 🖐️ 需要你手動做的事

| # | 事項 | 在哪做 | 用哪組憑證 | 完成判準 |
|---|---|---|---|---|
| M1 | 🖐️ 手動 在 `staging.rocketride.ai` 建一個 app（專案），名稱 `support-tutorial-generator`，記下 `project_id` | staging web UI | 登入帳號 | 拿到 `project_id` |
| M2 | 🖐️ 手動 在該 app 加 **AWS Bedrock 憑證**（`accessKey` / `secretKey` / `region`），region 選 `us-east-1`，並確認該帳號對 `anthropic_claude-sonnet-4-5` 有 model access | staging web UI → 憑證／Secrets | AWS 帳號 | `llm_bedrock` 節點在 UI 上不顯示紅色錯誤 |
| M3 | 🖐️ 手動 把 `app/agent/pipeline.json` 匯入／貼到該 app，確認 `demo_webhook → support_agent` 的邊落在 **`questions` lane**（webhook 的 Content-Type → lane 對照表官方文件未載明，這條邊要肉眼確認一次） | staging web UI | — | 畫布上五個節點都連上，agent 的 llm／memory 控制邊各一條 |
| M4 | 🖐️ 手動 **deploy**。**只用 `ROCKETRIDE_DEPLOY_URI` / `ROCKETRIDE_DEPLOY_APIKEY`。** `.env` 註解寫死：「never deploy to the dev connection」。程式端 `deploy_pipeline()` 預設直接 raise 提示手動，不自動 deploy | staging web UI 或帶 DEPLOY_* 的 CLI | **DEPLOY 組** | app 狀態為已部署 |
| M5 | 🖐️ 手動 把 M1 的 `project_id` 與 webhook source id 寫進 `.env`：`ROCKETRIDE_PROJECT_ID=` / `ROCKETRIDE_WEBHOOK_SOURCE=demo_webhook`。**不要寫進 repo 的任何 `.py` / `.json`** | 本機 `.env` | — | `git check-ignore -v .env` 有輸出 |
| M6 | 🖐️ 手動（降級用）準備一把 Anthropic API key，寫進 `.env` 的 `ANTHROPIC_API_KEY`。Bedrock 沒批准時 `call_llm` 靠它 | 本機 `.env` | — | `echo ${ANTHROPIC_API_KEY:0:7}` 有輸出 |
| M7 | 🖐️ 手動 跑一次 §6 的驗收劇本並截圖（中欄 `.md`、Step 3 的 `Click "Cancel Order"`） | Streamlit | dev 組 | 截圖進 demo 資料夾 |

> 所有 `run / 驗證 / 迭代`（`use()`、`send()`、chat、monitors）用 **dev 組** `ROCKETRIDE_URI` / `ROCKETRIDE_APIKEY`；所有 `deploy / schedules / publishApp / submitApp` 用 **DEPLOY 組**。兩組不可混用。

---

## 5. 實作步驟

### 步驟 2.0 — 前置檢查與 demo 劇本資料

先跑上面「⚠️ 交界處理」那段 SQL，確認 cancel_order 的分析母體為 0。

**檔案：** `data/script/demo_tickets.json` — **已由 Phase 1 建立，不要重寫。** 現況是一個**陣列**，每筆長這樣：

```json
{
  "content": "i need help cancelling puchase {{Order Number}}",
  "category": "ORDER",
  "intent": "cancel_order",
  "feature_name": "Cancel Order",
  "customer_ref": "alice@example.com",
  "created_at": "2026-09-01T15:00:00Z",
  "reopen_hint": false
}
```

Phase 2 只做三件事，用 `Edit` 補，不要 `Write` 蓋掉：

1. **每筆補一個 `bitext_response` 欄**（原樣抄 Bitext 資料集同 `intent` 的 `response` 欄，`data/raw/Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv` 已下載）。中欄解法框就是預填它。cancel_order 的前三筆一定要有值；其餘可留 `""`。
2. **在陣列尾端追加一筆 `intent: null` 的票**，content `"Something is wrong with my thing"`，`category: ""`，用來驗「`user_problem_id` 為空 → escalated」（自動回覆顧客 Rule 3）。
3. **確認 cancel_order 的前三筆排在陣列最前面**（劇本順序＝陣列順序；`created_at` 15:00 / 16:00 / 17:00 已遞增，符合輪詢的嚴格 `>`）。

欄位對應（既有欄名 → 本檔其餘章節的用詞）：`intent` ＝ `topic`（查 `UserProblem.topic`）、`feature_name` ＝ 查 `Feature.name`、`reopen_hint` ＝ Phase 3 用來排再開票劇本，Phase 2 不讀它。餵票游標存 `st.session_state`，不落表。

**指令：**
```bash
uv run python -c "
import json, pathlib
d = json.loads(pathlib.Path('data/script/demo_tickets.json').read_text())
print('筆數', len(d))
print('前三筆 intent', [t['intent'] for t in d[:3]])
print('前三筆有 bitext_response', all(t.get('bitext_response') for t in d[:3]))
print('有 null intent 的票', any(t['intent'] is None for t in d))
"
```
**預期輸出：** 前三筆 intent 全是 `cancel_order`、`有 bitext_response True`、`有 null intent 的票 True`

---

### 步驟 2.1 — `app/agent/rules.py`（純函式，零 I/O）

**這支檔案 Phase 1 已經寫齊**（`is_recurring`／`has_knowledge_gap`／`decide_analysis_action`／`classify_ticket`／`should_refine`／`decide_review_action`／`decide_release_action`／`validate_feedback`／`tutorial_slug`／`next_version`，常數 `RECURRING_MIN = 3` 等）。Phase 2 **不重寫**，只做一處修正。

#### 🐞 要修的一處：`classify_ticket` 的判斷順序

目前實作是：

```python
if not has_user_problem:       return "escalated"
if not has_published_tutorial: return "escalated"     # ← 這行在 is_reopen 之前
if is_reopen:                  return "escalated"
return "deflected"
```

三個分支都回 `escalated`，看起來順序無所謂——但**不是**。`自動回覆顧客.feature` Rule 5 的 Given 是「**有** published Tutorial ＋ alice 之前已被 deflected」，Then 是 `escalated` 且 `reopened_from_ticket_id = 1`。現行順序下 `has_published_tutorial=True`、`is_reopen=True` 會走到最後一行回 `deflected`，直接違反 Rule 5。

**改成：**

```python
def classify_ticket(
    has_user_problem: bool, has_published_tutorial: bool, is_reopen: bool
) -> str:
    if not has_user_problem:        # Rule 3：user_problem_id 為空
        return "escalated"
    if is_reopen:                   # Rule 5：再開票，優先於 Rule 1
        return "escalated"
    if not has_published_tutorial:  # Rule 2 ＋ Rule 4（retired 視同沒有）
        return "escalated"
    return "deflected"              # Rule 1
```

`has_published_tutorial` 由呼叫端算好：SQL 只撈 `status = 'published'`，`retired` / `draft` 一律傳 `False`，所以 Rule 4 不必在這裡寫 if。

#### 其餘沿用既有命名

本檔後面章節出現的 `RECURRING_MIN_TICKETS`、`rules.DEFLECTED`／`rules.ESCALATED` 都是為了說明而寫的名字；**實作一律用既有的 `rules.RECURRING_MIN` 與字串常值 `"deflected"` / `"escalated"`**，不要為了對齊文件而改既有 API（`app/analytics/metrics.py` 等已在用）。

**指令：**
```bash
uv run pytest tests/unit/test_rules.py -q
```
**預期輸出：** 既有測試全綠，並新增一支 `test_reopen_wins_over_published`（`classify_ticket(True, True, True) == "escalated"`）——修正前它會紅，修正後轉綠。

---

### 步驟 2.2 — `app/ingest/poll.py`（輪詢 ＋ cursor）

**對齊：** `輪詢新票單.feature` 唯一那條 Rule。

```python
import json, pathlib
from app.analytics.hotdata_client import run_sql
from app.analytics import sql

STATE = pathlib.Path(".state/last_checked.json")


def read_cursor() -> str:
    if not STATE.exists():
        return "1970-01-01T00:00:00Z"
    return json.loads(STATE.read_text())["last_checked"]


def write_cursor(ts: str) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"last_checked": ts}, ensure_ascii=False))


def poll_new_tickets(last_checked: str) -> list[int]:
    """回傳待處理的 ticket id：created_at 嚴格大於 cursor，且 status = 'open'。

    嚴格大於：Example 裡 created_at 剛好等於 10:00:00Z 的票不處理。
    """
    rows = run_sql(sql.SELECT_NEW_OPEN_TICKETS, {"last_checked": last_checked})
    return [r["id"] for r in rows]
```

`app/analytics/sql.py` 新增：

```python
SELECT_NEW_OPEN_TICKETS = """
SELECT id, created_at
  FROM Ticket
 WHERE status = 'open'
   AND created_at > :last_checked
 ORDER BY created_at ASC
"""
```

輪詢一輪跑完後，`write_cursor(max(created_at))`；沒有新票就不動 cursor。`.state/` 加進 `.gitignore`（cursor 是 demo session 狀態，不是業務表，`showme` §9）。

**指令：** `uv run pytest tests/unit/test_realtime.py -k poll -q`

---

### 步驟 2.3 — `app/agent/realtime.py`（即時路徑）

**對齊：** `自動回覆顧客.feature` 五條 Rule ＋ `輪詢新票單.feature`。

```python
from app.agent import rules
from app.analytics.hotdata_client import run_sql, transaction
from app.analytics import sql
from app.errors import OperationFailed


def handle_open_ticket(ticket_id: int) -> dict:
    """對一張 open 票跑即時路徑。回傳 {'ticket_id','status','reason',...}。

    失敗語意（showme §7.1／§14）：任何讀寫例外 → rollback → raise OperationFailed，
    票維持 open，本輪不進分析。
    """
    try:
        ticket = _one(run_sql(sql.SELECT_TICKET, {"id": ticket_id}))
        if ticket is None or ticket["status"] != "open":
            return {"ticket_id": ticket_id, "status": ticket and ticket["status"], "reason": "not_open"}

        up_id = ticket["user_problem_id"]
        has_up = up_id not in (None, "", 0)

        reopen_id = None
        published = None
        if has_up:
            reopen = _one(run_sql(sql.SELECT_PRIOR_DEFLECTED, {
                "customer_ref": ticket["customer_ref"],
                "user_problem_id": up_id,
                "id": ticket_id,
            }))
            reopen_id = reopen["id"] if reopen else None
            published = _one(run_sql(sql.SELECT_PUBLISHED_TUTORIAL, {"user_problem_id": up_id}))

        decision = rules.classify_ticket(
            has_user_problem=has_up,
            has_published_tutorial=published is not None,
            is_reopen=reopen_id is not None,
        )

        with transaction() as tx:
            if decision == rules.DEFLECTED:
                tx.exec(sql.UPDATE_TICKET_DEFLECTED, {
                    "id": ticket_id,
                    "tutorial_id": published["tutorial_id"],
                    "tutorial_version": published["current_version"],
                })
            else:
                tx.exec(sql.UPDATE_TICKET_ESCALATED, {
                    "id": ticket_id,
                    "reopened_from_ticket_id": reopen_id,
                })
    except OperationFailed:
        raise
    except Exception as exc:                       # 讀寫失敗 → 規格的「操作失敗」
        raise OperationFailed(f"即時路徑失敗，ticket {ticket_id} 維持 open") from exc

    return {
        "ticket_id": ticket_id,
        "status": decision,
        "reason": _reason(has_up, reopen_id, published),
        "tutorial_id": published and published["tutorial_id"],
        "tutorial_version": published and published["current_version"],
        "reopened_from_ticket_id": reopen_id,
    }
```

`app/analytics/sql.py` 新增：

```python
SELECT_TICKET = "SELECT * FROM Ticket WHERE id = :id"

SELECT_PUBLISHED_TUTORIAL = """
SELECT tutorial_id, current_version
  FROM Tutorial
 WHERE user_problem_id = :user_problem_id
   AND status = 'published'          -- retired / draft 自然被排除（Rule 4）
 LIMIT 1
"""

SELECT_PRIOR_DEFLECTED = """
SELECT id
  FROM Ticket
 WHERE customer_ref = :customer_ref
   AND user_problem_id = :user_problem_id
   AND status = 'deflected'          -- ERM 不變條件：reopened_from 必指向 deflected 票
   AND id <> :id
 ORDER BY created_at DESC
 LIMIT 1
"""

UPDATE_TICKET_DEFLECTED = """
UPDATE Ticket
   SET status = 'deflected',
       deflected_tutorial_id = :tutorial_id,
       deflected_tutorial_version = :tutorial_version
 WHERE id = :id
"""

UPDATE_TICKET_ESCALATED = """
UPDATE Ticket
   SET status = 'escalated',
       deflected_tutorial_id = NULL,
       deflected_tutorial_version = NULL,
       reopened_from_ticket_id = :reopened_from_ticket_id
 WHERE id = :id
"""
```

**測試 `tests/unit/test_realtime.py`（5 條 Rule 各一，＋輪詢 1 條）：**

| 測試 | 對齊 Example |
|---|---|
| `test_deflected_when_published_tutorial_exists` | 自動回覆 Rule 1「cancel_order 已有 published Tutorial」 |
| `test_escalated_when_no_tutorial` | Rule 2「UserProblem 尚無 Tutorial」 |
| `test_escalated_when_user_problem_id_empty` | Rule 3「無法對應 UserProblem 的票單轉真人」 |
| `test_retired_tutorial_treated_as_absent` | Rule 4「retired 的 cancel-order Tutorial 使票單 escalated」 |
| `test_reopen_sets_reopened_from_ticket_id` | Rule 5「alice 對 cancel_order 再開票」→ `reopened_from_ticket_id = 1` |
| `test_poll_respects_cursor_and_status` | 輪詢 Rule：09:00 open 不動、10:00（＝cursor）不動、10:30 open → escalated、10:30 resolved 不動 |
| `test_read_failure_keeps_ticket_open` | showme §7.1 失敗列：mock run_sql 丟例外 → `OperationFailed` 且票仍 open |

**指令：** `uv run pytest tests/unit/test_realtime.py -q`
**預期輸出：** `7 passed`

---

### 步驟 2.4 — Streamlit 左欄：餵下一張票

**檔案：** `app/demo/streamlit_app.py`

```python
# 左欄
if st.button("餵下一張票"):
    t = next_script_ticket()                     # data/script/demo_tickets.json，游標存 st.session_state
    ticket_id = insert_ticket(                   # INSERT Ticket(..., status='open', created_at=now)
        content=t["content"], category=t["category"],
        customer_ref=t["customer_ref"],
        user_problem_id=lookup_user_problem_id(t["topic"]),   # topic 為 null → None
        feature_id=lookup_feature_id(t["topic"]),
    )
    st.session_state.last_bitext_response = t["bitext_response"]

    # (1) 本機為主：同步決策並寫 DB
    try:
        result = realtime.handle_open_ticket(ticket_id)
    except OperationFailed as exc:
        st.error(f"操作失敗：{exc}；票維持 open")
        result = None

    # (2) RocketRide 為展示：fire-and-forget，絕不影響票流
    if result:
        st.session_state.agent_echo = rocketride_client.run_agent({
            "event": "ticket_opened",
            "ticket_id": ticket_id,
            "customer_ref": t["customer_ref"],
            "topic": t["topic"],
            "user_problem_id": result and result.get("tutorial_id") and ... ,
            "content": t["content"],
            "local_decision": result["status"],
            "local_reason": result["reason"],
        })   # 逾時 3s 回 None，不 raise
```

`insert_ticket` 的 `created_at` 用 `datetime.now(timezone.utc).isoformat()`（`Z` 結尾），必須嚴格大於 cursor，餵票才會被輪詢路徑看見。

**指令：** `uv run streamlit run app/demo/streamlit_app.py`
**預期輸出：** 按一次「餵下一張票」→ 中欄出現 seq 1 的卡片，狀態 `escalated`。

---

### 步驟 2.5 — Streamlit 中欄：決策卡 ＋ 轉真人解法確認框

```python
# 中欄
st.subheader("這張：deflected / 轉真人")
st.metric("本機決策", result["status"])
echo = st.session_state.get("agent_echo")
if echo is None:
    st.caption("Agent 未回應（本機決策照跑）")
elif echo.get("decision") == result["status"]:
    st.caption(f"Agent 決策：{echo['decision']}（與本機一致）")
else:
    st.caption(f"⚠ 不一致 — Agent：{echo.get('decision')} ／ 本機：{result['status']}")

if result["status"] == "escalated":
    text = st.text_area("解法（真人確認）", value=st.session_state.last_bitext_response, height=180)
    if st.button("確認解法"):
        run_sql(sql.UPDATE_TICKET_RESOLVED, {"id": ticket_id, "resolution_steps": text})
        st.success("已結案：status = resolved")

if st.button("分析"):
    st.session_state.actions = analysis.analyze_tickets()
    st.write(st.session_state.actions)
    for a in st.session_state.actions:
        if a["action"] == "CREATE":
            create_tutorial.create_tutorial(a["user_problem_id"])

# .md 檢視
for p in sorted(pathlib.Path("tutorials").glob("*.md")):
    with st.expander(p.name, expanded=True):
        st.markdown(p.read_text())
```

```python
UPDATE_TICKET_RESOLVED = """
UPDATE Ticket
   SET resolution_steps = :resolution_steps,
       status = 'resolved'
 WHERE id = :id
"""
```

> UI 只觸發、只展示。門檻計算、CREATE 決定都在 `analysis` / `create_tutorial`，**不在 UI**（`showme` §13）。UI 也不擋票。

---

### 步驟 2.6 — `app/agent/analysis.py`

**對齊：** `分析SupportTickets.feature` 九條 Rule。

```python
from app.agent import rules
from app.analytics.hotdata_client import run_sql
from app.analytics import sql
from app.errors import OperationFailed


def analyze_tickets() -> list[dict]:
    """回傳 [{'user_problem_id': int, 'topic': str, 'action': 'CREATE'|'KEEP'}]。

    只納入 status IN ('escalated','resolved') 的票（Rule 4）。
    count < 3 不進結果（Rule 1）；沒票／聚不起來 → [] （Rule 2、Rule 3）。
    """
    try:
        counts = run_sql(sql.COUNT_TICKETS_BY_USER_PROBLEM)     # [{user_problem_id, topic, ticket_count}]
        published = {r["user_problem_id"] for r in run_sql(sql.SELECT_PUBLISHED_USER_PROBLEMS)}
    except Exception as exc:
        raise OperationFailed("分析 Ticket 讀取失敗") from exc

    out = []
    for row in counts:
        if not rules.is_recurring(row["ticket_count"]):          # Rule 1
            continue
        has_pub = row["user_problem_id"] in published
        out.append({
            "user_problem_id": row["user_problem_id"],
            "topic": row["topic"],
            # Rule 6 / Rule 7 / Rule 8 / Rule 9：每個 gap 各自判斷，互不影響
            "action": "KEEP" if has_pub else "CREATE",
        })
    return out


def knowledge_gaps() -> list[dict]:
    """Knowledge Gap = action 為 CREATE 的那些（Rule 5）。"""
    return [a for a in analyze_tickets() if a["action"] == "CREATE"]
```

```python
COUNT_TICKETS_BY_USER_PROBLEM = """
SELECT t.user_problem_id       AS user_problem_id,
       up.topic                AS topic,
       COUNT(*)                AS ticket_count
  FROM Ticket t
  JOIN UserProblem up ON up.id = t.user_problem_id
 WHERE t.status IN ('escalated', 'resolved')     -- Rule 4：open / deflected 不算
   AND t.user_problem_id IS NOT NULL
 GROUP BY t.user_problem_id, up.topic
 ORDER BY t.user_problem_id
"""

SELECT_PUBLISHED_USER_PROBLEMS = """
SELECT user_problem_id FROM Tutorial WHERE status = 'published'
"""
```

**測試 `tests/unit/test_analysis.py`：**

| 測試 | 對齊 Example |
|---|---|
| `test_is_recurring_boundary` | 2 張 → 空；3 張 → recurring（Rule 1 兩個 Example） |
| `test_empty_when_no_tickets` | Rule 2 |
| `test_empty_when_tickets_do_not_cluster` | Rule 3（三張各一 topic） |
| `test_open_and_deflected_excluded` | Rule 4 第一個 Example（open×2 ＋ deflected×1 → 空） |
| `test_two_resolved_plus_one_escalated_is_recurring` | Rule 4 第二個 Example |
| `test_knowledge_gap_only_without_published` | Rule 5 兩個 Example |
| `test_action_create_for_gap` | Rule 6 |
| `test_action_keep_when_published` | Rule 7 |
| `test_multiple_gaps_all_create` | Rule 8（cancel_order ＋ track_refund 都 CREATE） |
| `test_other_topic_tutorial_does_not_block_create` | Rule 9（track_refund 有教學不影響 cancel_order） |

**指令：** `uv run pytest tests/unit/test_analysis.py -q` → `10 passed`

---

### 步驟 2.7 — `app/agent/create_tutorial.py`

**對齊：** `建立Tutorial.feature` 五條 Rule。

```python
FIVE_FIELDS = ("title", "problem", "prerequisites", "steps", "expected_outcome")


def create_tutorial(user_problem_id: int) -> int:
    # 1. Knowledge Gap（Rule 4）
    gaps = {g["user_problem_id"]: g for g in analysis.knowledge_gaps()}
    if user_problem_id not in gaps:
        raise OperationFailed("未識別出 Knowledge Gap，不建立 Tutorial")
    topic = gaps[user_problem_id]["topic"]

    # 2. Feature（Rule 5）
    feature = _resolve_feature(user_problem_id)          # UserProblem.feature_id → 票的多數 feature_id
    if feature is None:
        raise OperationFailed("沒有對應的 Feature，不建立 Tutorial")

    # 3. 素材
    tickets = run_sql(sql.SELECT_RESOLUTION_MATERIAL, {"user_problem_id": user_problem_id})
    if not tickets:
        raise OperationFailed("沒有可用的 resolution_steps")

    # 4. LLM 成型五欄
    fields = _shape_five_fields(feature["name"], topic, tickets)

    # 5. 五欄必填（Rule 3）
    missing = [f for f in FIVE_FIELDS if not (fields.get(f) or "").strip()]
    if missing:
        raise OperationFailed(f"缺少內容欄位：{missing}，不寫半篇 Tutorial")

    # 6. 同一成功邊界：兩表 ＋ .md
    path = f"tutorials/{topic.replace('_', '-')}.md"
    md = render_markdown(topic, feature["name"], "v1", fields)
    md_file = pathlib.Path(path)
    try:
        with transaction() as tx:
            tutorial_id = tx.exec_returning_id(sql.INSERT_TUTORIAL, {
                "feature_id": feature["id"], "user_problem_id": user_problem_id, "path": path,
            })
            tx.exec(sql.INSERT_TUTORIAL_VERSION_V1, {
                "tutorial_id": tutorial_id,
                **fields,
                "created_at": now_iso(),
            })
            md_file.parent.mkdir(parents=True, exist_ok=True)
            md_file.write_text(md, encoding="utf-8")
    except Exception as exc:
        md_file.unlink(missing_ok=True)                  # 寫檔成功但交易失敗 → 檔也不留
        raise OperationFailed("建立 Tutorial 失敗，已回滾") from exc

    # 7. best-effort 記憶層（showme §17：不通只寫 hotdata）
    _remember_best_effort(tutorial_id, feature, topic, fields, md)
    return tutorial_id
```

```python
INSERT_TUTORIAL = """
INSERT INTO Tutorial (feature_id, user_problem_id, path, status, current_version,
                      is_possibly_outdated, is_obsolete, last_action)
VALUES (:feature_id, :user_problem_id, :path, 'published', 'v1',
        0, 0, 'CREATE')
"""

INSERT_TUTORIAL_VERSION_V1 = """
INSERT INTO TutorialVersion (tutorial_id, tutorial_version, title, problem, prerequisites,
                             steps, expected_outcome, reason, supersedes_version, created_at)
VALUES (:tutorial_id, 'v1', :title, :problem, :prerequisites,
        :steps, :expected_outcome, '', '', :created_at)
"""

SELECT_RESOLUTION_MATERIAL = """
SELECT id, content, resolution_steps
  FROM Ticket
 WHERE user_problem_id = :user_problem_id
   AND status IN ('escalated', 'resolved')
   AND resolution_steps IS NOT NULL
   AND resolution_steps <> ''
 ORDER BY id
"""
```

`reason` 與 `supersedes_version` 寫 `''`（v1 必空，`建立Tutorial.feature` Rule 2 的 Then 表兩欄留白）。`is_possibly_outdated` / `is_obsolete` 寫 false。

#### LLM prompt 範本（寫死在 `create_tutorial.py`，不要現場改）

**System：**
```
You are a technical writer for a customer-support self-service knowledge base.
You turn already-resolved support tickets into ONE short tutorial.

Return ONLY a JSON object, nothing else. No markdown fence, no commentary.
Schema:
{"title": string, "problem": string, "prerequisites": string, "steps": string, "expected_outcome": string}

Hard rules:
- All five fields are REQUIRED and must be non-empty strings.
  If the tickets do not contain enough information for any field,
  return {"error": "<which field and why>"} instead of guessing.
- "steps" MUST be one single string of numbered steps separated by spaces, e.g.
  "1. Open Orders. 2. Select the order. 3. Click \"Cancel Order\"."
- Quote UI labels EXACTLY as they appear in the tickets, in double quotes.
  Do not paraphrase a button name.
- Do not invent product features, screens, or policies that are not in the tickets.
- Write in English. Keep the whole tutorial under 150 words.
```

**User：**
```
Feature: {feature_name}
User problem topic: {topic}

Resolved tickets ({n}):
--- ticket {id} ---
customer said: {content}
support resolved with: {resolution_steps}
--- ticket {id} ---
...

Produce the tutorial JSON now.
```

**解析：** 只接受 `json.loads` 成功、且鍵集合 ⊇ 五欄的物件。回 `{"error": ...}`、JSON 壞掉、或任一欄空字串 → `OperationFailed`（對齊 Rule 3：不寫半篇）。**不要**在解析失敗時自動重試三次然後硬塞預設值——那是腦補，規格沒寫。

#### `.md` 版型（`render_markdown`）

```markdown
# Cancel Order

<!-- 由客服自助教學生成器產生。權威內容在 TutorialVersion(tutorial_id=1, tutorial_version=v1)。 -->

| | |
|---|---|
| Version | v1 |
| Status | published |
| Feature | Cancel Order |
| User problem | cancel_order |

## Problem

Customer wants to cancel an existing order.

## Prerequisites

Customer is logged in and has an order number.

## Steps

1. Open Orders.
2. Select the order.
3. Click "Cancel Order".

## Expected Outcome

The order is cancelled.
```

`Steps` 區塊只是**渲染**：拿 DB 裡的單一字串 `steps`，用 `re.split(r"(?=\b\d+\.\s)", steps)` 切行後逐行輸出；原字串一個字都不改地留在 `TutorialVersion.steps`。Phase 5 的 Step 3 diff 比的是 DB 的 `steps` 字串，不是 `.md` 的排版。

**測試 `tests/unit/test_create.py`：**

| 測試 | 對齊 Example |
|---|---|
| `test_create_sets_published_v1_create` | Rule 1 的 Then 表（published / v1 / CREATE / 兩個旗標 false） |
| `test_version_v1_five_fields_and_empty_supersedes` | Rule 2 的 Then 表 |
| `test_missing_title_fails` … `test_missing_expected_outcome_fails`（5 支） | Rule 3 的五個 Example，各自 assert `OperationFailed` 且 `Tutorial` 表為空、`.md` 不存在 |
| `test_no_knowledge_gap_fails` | Rule 4 |
| `test_missing_feature_id_fails` / `test_feature_not_found_fails` | Rule 5 兩個 Example |
| `test_md_and_rows_share_success_boundary` | showme §9：mock 寫檔丟例外 → 兩表都沒列、`.md` 不存在 |

LLM 在單元測試裡一律 mock（`call_llm` 回固定 JSON），不打外部服務。

**指令：** `uv run pytest tests/unit/test_create.py -q` → `11 passed`

---

### 步驟 2.8 — `app/agent/rocketride_client.py`

```python
import os, httpx
from app.errors import OperationFailed

WEBHOOK_TIMEOUT = 3.0


def _dev() -> tuple[str, str]:
    uri, key = os.environ["ROCKETRIDE_URI"], os.environ["ROCKETRIDE_APIKEY"]
    return uri, key


def run_agent(event: dict) -> dict | None:
    """把事件送進 RocketRide 的 webhook source。純展示，失敗回 None，絕不 raise。

    端點形狀：POST {ROCKETRIDE_URI}/webhook/{project_id}/{source}
    Content-Type 決定 body 落在哪條 lane（官方文件：protocols/websocket）。
    """
    try:
        uri, key = _dev()
        url = f"{uri.rstrip('/')}/webhook/{os.environ['ROCKETRIDE_PROJECT_ID']}/{os.environ.get('ROCKETRIDE_WEBHOOK_SOURCE', 'demo_webhook')}"
        r = httpx.post(url, json=event,
                       headers={"X-Api-Key": key, "Authorization": f"Bearer {key}"},
                       timeout=WEBHOOK_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None            # showme §17：Agent 無回應 → 本機照跑


def call_llm(prompt: str, system: str) -> str:
    """五欄成型。順序：RocketRide(llm_bedrock) → 直打 Anthropic → OperationFailed。"""
    out = _via_rocketride(prompt, system)
    if out:
        return out
    out = _via_anthropic_direct(prompt, system)      # httpx POST https://api.anthropic.com/v1/messages
    if out:                                          # headers: x-api-key, anthropic-version: 2023-06-01
        return out
    raise OperationFailed("LLM 不可用，無法成型五欄")


def deploy_pipeline() -> None:
    """deploy 只能用 DEPLOY 組。本 Phase 不自動 deploy。"""
    raise RuntimeError(
        "🖐️ 手動：請在 staging.rocketride.ai 用 ROCKETRIDE_DEPLOY_URI / ROCKETRIDE_DEPLOY_APIKEY "
        "部署 app/agent/pipeline.json。絕不 deploy 到 dev 連線（ROCKETRIDE_URI）。"
    )
```

> `deploy_pipeline()` 刻意只留一個會 raise 的殼：本 Phase 沒有任何自動 deploy 路徑，程式也拿不到 DEPLOY 憑證去做別的事。`_dev()` 只讀 `ROCKETRIDE_URI` / `ROCKETRIDE_APIKEY`——**不要**在任何 run/驗證路徑 import `ROCKETRIDE_DEPLOY_*`。

**已查證的連線事實**（官方文件，見 §來源）：WebSocket `ws://<host>:<port>/task/service`（本機預設 port 5565，雲端 `https://api.rocketride.ai`）；第一個 frame 送 `{"auth": "$ROCKETRIDE_APIKEY", "clientName": ..., "clientVersion": ...}`；訊息是 DAP 風格（`type` / `seq` / `command` / `arguments`）；SDK 操作名 `use()`（開任務）、`send()` / `pipe()`（送資料）、`chat()`（串流對話）、`terminate()`（關任務）；HTTP webhook 端點 `/webhook/{project_id}/{source}`，Content-Type 決定 lane。**文件未載明** deploy / publishApp / submitApp 的具體端點——所以 deploy 一律走 §4 的 🖐️ 手動步驟，不在程式裡猜 URL。

---

### 步驟 2.9 — `app/agent/pipeline.json` ＋ `instructions` 全文草稿

格式依官方 Pipeline JSON Reference：`components[]`，每個節點 `{id, provider, config, input[], control[]}`；`input` 是資料流（`{lane, from}`），`control` 是 invoke 控制流（`{classType, from}`）。

```json
{
  "name": "support-tutorial-generator",
  "description": "客服自助教學生成器：單一 Agent 的三條 pipeline（Ticket Analysis / Release Note Update / Periodic Feedback Review）＋ 即時路徑決策展示。",
  "source": "demo_webhook",
  "components": [
    {
      "id": "demo_webhook",
      "provider": "webhook",
      "name": "Demo 事件入口",
      "config": { "type": "webhook", "mode": "Source", "hideForm": true, "parameters": {} }
    },
    {
      "id": "support_agent",
      "provider": "agent_rocketride",
      "name": "Support Tutorial Agent",
      "config": {
        "agent_description": "客服自助教學生成器的唯一 Agent。依 Ticket / Release Note / Feedback 訊號決定 Tutorial 的 CREATE / UPDATE / REFINE / KEEP / RETIRE，並對每張新票判斷 deflected 或 escalated。",
        "instructions": ["<見下方四段全文>"],
        "max_waves": 10
      },
      "input": [ { "lane": "questions", "from": "demo_webhook" } ],
      "control": [
        { "classType": "llm",    "from": "tutorial_llm" },
        { "classType": "memory", "from": "agent_memory" },
        { "classType": "tool",   "from": "semantic_memory" },
        { "classType": "tool",   "from": "graph_memory" }
      ]
    },
    {
      "id": "tutorial_llm",
      "provider": "llm_bedrock",
      "config": {
        "profile": "anthropic_claude-sonnet-4-5",
        "anthropic_claude-sonnet-4-5": { "region": "us-east-1", "accessKey": "", "secretKey": "" }
      }
    },
    {
      "id": "agent_memory",
      "provider": "memory_internal",
      "config": {}
    },
    {
      "id": "semantic_memory",
      "provider": "tool_cognee",
      "config": {
        "type": "tool_cognee",
        "base_url": "",
        "api_key": "",
        "dataset": "main",
        "allow_dataset_override": false,
        "search_type": "GRAPH_COMPLETION_DECOMPOSITION",
        "top_k": 15,
        "request_timeout": 120
      }
    },
    {
      "id": "graph_memory",
      "provider": "db_hydradb",
      "config": {
        "profile": "default",
        "default": { "api_key": "", "database": "support_tutorials", "collection": "default", "max_results": 10 }
      }
    }
  ]
}
```

節點與參數名的出處（`.rocketride/schema/`，實查）：

| 節點 | 關鍵參數 | 限制 |
|---|---|---|
| `agent_rocketride` | `agent_description` / `instructions`（陣列，textarea）／`max_waves`（預設 10，1–50） | `invoke`：`llm` min 1 max 1、`memory` min 1 max 1、`tool` min 0。lanes：`questions → answers` |
| `llm_bedrock` | `profile`（22 個 enum，含 `anthropic_claude-sonnet-4-5`、`anthropic_claude-opus-4-5`、`anthropic_claude-haiku-4-5`）；每個 profile 物件內 `region`（必填）／`accessKey`／`secretKey`；`custom` 另需 `model` ＋ `modelTotalTokens` | classType `llm` |
| `llm_anthropic` | `profile`（`claude-sonnet-4-6` / `claude-opus-4-6` / `claude-haiku-4-5` / … / `custom`），每個 profile 需 `apikey` | classType `llm`。**降級時換掉 `tutorial_llm` 的 provider，不新增節點**（llm max 1） |
| `tool_cognee` | `base_url`／`api_key`／`dataset`（預設 `main`）／`allow_dataset_override`（維持 false）／`search_type`／`top_k`／`request_timeout` | classType `tool` |
| `db_hydradb` | `profile: "default"` 內 `api_key`／`database`／`collection`／`max_results` | classType `database, tool` |
| `webhook` | `type`／`mode`（`Source`）／`hideForm`／`parameters` | classType `source`，`_source` lanes 含 `questions` |
| `memory_internal` | 無必填 | classType `memory`，滿足 agent 的 `memory` min 1 |

> catalog 140 個節點裡**沒有** `response` / sink 類節點，所以 pipeline 不接輸出節點；`answers` lane 由開任務的 client 讀回。也**沒有** hotdata 與 Rote 節點——這兩層走本機 CLI。
> `demo_webhook → support_agent` 用 `questions` lane：agent 只吃 `questions`，webhook 的 `_source` lane 清單含 `questions`，但「Content-Type → 哪條 lane」的對照表官方文件未載明。→ §4 M3 的 🖐️ 手動步驟要在畫布上確認這條邊；若送 `application/json` 落到 `json` lane 而非 `questions`，改用 `Content-Type: text/plain` 送 JSON 字串，或在 UI 上直接把邊拉到 `questions`。

#### `instructions` 全文草稿（四段，逐段填進陣列）

**[1／4] 角色與硬邊界**
```
你是「客服自助教學生成器」的唯一 Agent。你的產物是教學文件（Tutorial），不是客服回覆。

你只做五件事：對一張新票判斷 deflected 或 escalated；把重複出現的問題 CREATE 成教學；
依 Release Note UPDATE 或 RETIRE 教學；依顧客回饋 REFINE 或 KEEP 教學。

硬邊界：
- 不發明資料表。資料模型只有 9 張：Ticket, UserProblem, Feature, Tutorial, TutorialVersion,
  Feedback, Release, ReleaseFeatureChange, Workflow。
- 不發明門檻。所有數字都在下面第 3 段的門檻表裡，一個字都不要改。
- 教學內容只有五欄：Title / Problem / Prerequisites / Steps / Expected Outcome。五欄缺一，
  就回報「操作失敗」，不要產出半篇教學。
- 教學來源只有已解決票的 resolution_steps。不要從產品知識或常識補步驟。
- Release Note 永遠不會觸發 CREATE，只會 UPDATE 或 RETIRE。
- 你沒有人工審核佇列，沒有教學人員名單，不發 Slack，不產影片。
```

**[2／4] 即時路徑規則（收到 `event = ticket_opened`）**
```
依序判斷，第一個命中就停：
1. ticket.user_problem_id 是空的            -> escalated
2. 同一個 customer_ref、同一個 user_problem_id 已經有一張 status = deflected 的舊票
                                            -> escalated，並記下 reopened_from_ticket_id = 那張舊票
3. 這個 user_problem_id 沒有 status = published 的 Tutorial
   （status = retired 或 draft 一律視同「沒有」）-> escalated
4. 其餘                                     -> deflected，回覆該 Tutorial 的 current_version 連結

deflected 時同時記下 deflected_tutorial_id 與 deflected_tutorial_version。
escalated 時這兩欄留空。
讀不到 Tutorial 或圖譜時，回報「操作失敗」，票維持 open，本輪不進分析。

注意：本機系統是票單狀態的唯一寫入者。你的輸出是決策與理由，用來對照與說明，
不要假設你的回覆會直接改變資料庫。
```

**[3／4] 三條 pipeline 與門檻表**
```
A. Ticket Analysis（事件 analysis_requested，或有新的 escalated / resolved 票）
   只看 status 為 escalated 或 resolved 的票，依 user_problem_id 分組計數。
   同一 user_problem_id 的票數 >= 3            -> 這是 recurring topic
   recurring topic 且沒有 published Tutorial    -> Knowledge Gap，動作 CREATE
   recurring topic 且已有 published Tutorial    -> 動作 KEEP
   票數 < 3、沒有票、或聚不成同一 topic         -> 結果為空
   CREATE 時：Tutorial 直接 published，current_version = v1，last_action = CREATE，
   TutorialVersion v1 的 supersedes_version 必須為空。沒有對應的 Feature 就不建立。

B. Release Note Update（事件 release_posted）
   處理所有 processed_at 為空的 Release。
   ReleaseFeatureChange 命中某篇 Tutorial 的 feature_id 時：
     change_type = renamed 或 changed      -> UPDATE：出新版本、把 Feature.name 改成新名、填 processed_at
     change_type = deprecated 或 removed   -> RETIRE：Tutorial.status = retired、is_obsolete = true
     change_type = new 且沒有對應 Tutorial -> 只填 processed_at，什麼都不改
   擷取不到 change_type 就回報「操作失敗」，processed_at 保持空，下一輪可以重跑。

C. Periodic Feedback Review（事件 review_requested）
   只算 Tutorial.current_version 那一版的 Feedback。
   平均 rating < 3.5  且  筆數 >= 3  且  同一個 feedback_category >= 2 筆  -> REFINE，出新版本並填 reason
   其餘                                                                     -> KEEP
   Tutorial.is_possibly_outdated = true 時，本輪一律 KEEP，等 UPDATE 做完。
   同一輪同時命中 UPDATE 與 REFINE 時，先做 UPDATE，REFINE 等下一輪。

新版本一律：tutorial_version 遞增（v1 -> v2 -> v3），supersedes_version 指向同一篇的上一版，
Tutorial.current_version 更新，last_action 記成這次的動作。
```

**[4／4] 工具用法與輸出格式**
```
工具：
- semantic_memory（Cognee）：remember 用來記住新票、新版教學、回饋、Release 本文；
  recall 用來找「這個問題以前怎麼解的」。dataset 固定，不要嘗試切換 dataset。
- graph_memory（HydraDB）：存跨 session 的圖譜。邊只有五種：
  asks_about（Ticket -> Feature）、explains（Tutorial -> Feature）、
  refers_to（Feedback -> TutorialVersion）、changes（Release -> Feature）、
  supersedes（TutorialVersion -> 上一版）。不要發明第六種邊，不要建先備知識邊。
  多跳查詢「哪些教學受這次 Release 影響」：
  (Release)-[:changes]->(Feature)<-[:explains]-(Tutorial) WHERE Release.processed_at IS NULL

輸出：每次回覆都用一個 JSON 物件，欄位如下，不要加別的散文。
{"event": "<收到的事件名>", "decision": "<deflected|escalated|CREATE|UPDATE|REFINE|KEEP|RETIRE|none|操作失敗>",
 "user_problem_id": <int 或 null>, "tutorial_id": <int 或 null>,
 "reason": "<一句話，說明是哪一條規則命中>"}
任何一步失敗，decision 就寫「操作失敗」，reason 寫是哪一步失敗。不要編造成功結果。
```

---

### 步驟 2.10 — 🖐️ 手動 deploy 與端到端走一次

1. 🖐️ 手動 依 §4 的 M1–M5 建 app、加 Bedrock 憑證、匯入 pipeline、**用 DEPLOY 組** deploy。
2. 本機 `uv run streamlit run app/demo/streamlit_app.py`，照 §6 的驗收清單跑一遍。
3. 🖐️ 手動 截圖（M7）。

---

## 6. 驗收清單

### 6.1 `.feature` Rule → 程式位置 → 測試

| # | Feature | Rule | 程式位置 | 測試 |
|---|---|---|---|---|
| 1 | 輪詢新票單 | 只處理 created_at 大於上次檢查時間且 status 為 open 的票 | `app/ingest/poll.py::poll_new_tickets` ＋ `sql.SELECT_NEW_OPEN_TICKETS`（嚴格 `>`） | `test_realtime.py::test_poll_respects_cursor_and_status` |
| 2 | 自動回覆顧客 | UserProblem 已有 published Tutorial 時票單為 deflected | `rules.classify_ticket` 末行 ＋ `realtime` 的 `UPDATE_TICKET_DEFLECTED` | `test_realtime.py::test_deflected_when_published_tutorial_exists` |
| 3 | 自動回覆顧客 | 沒有 published Tutorial 時票單為 escalated | `rules.classify_ticket` 第三段 | `test_realtime.py::test_escalated_when_no_tutorial` |
| 4 | 自動回覆顧客 | user_problem_id 為空的票單為 escalated | `rules.classify_ticket` 第一段 | `test_realtime.py::test_escalated_when_user_problem_id_empty` |
| 5 | 自動回覆顧客 | Tutorial 為 retired 時視同沒有 Tutorial | `sql.SELECT_PUBLISHED_TUTORIAL` 的 `WHERE status = 'published'` | `test_realtime.py::test_retired_tutorial_treated_as_absent` |
| 6 | 自動回覆顧客 | 同一顧客同一 UserProblem 在 deflected 後再開票則新票為 escalated | `sql.SELECT_PRIOR_DEFLECTED` ＋ `rules.classify_ticket` 的 `is_reopen` 分支（**必須排在 `has_published_tutorial` 之前**，見步驟 2.1 的 🐞） | `test_realtime.py::test_reopen_sets_reopened_from_ticket_id`、`test_rules.py::test_reopen_wins_over_published` |
| 7 | 分析 Ticket | 同一 user_problem_id 且至少 3 張 Ticket 才識別為 recurring topic | `rules.is_recurring` / `RECURRING_MIN_TICKETS = 3` | `test_analysis.py::test_is_recurring_boundary` |
| 8 | 分析 Ticket | 沒有任何 Ticket 時分析結果為空 | `analysis.analyze_tickets` 回 `[]` | `test_analysis.py::test_empty_when_no_tickets` |
| 9 | 分析 Ticket | Tickets 無法聚成同一主題時分析結果為空 | 同上（每組 count = 1，全被 `is_recurring` 濾掉） | `test_analysis.py::test_empty_when_tickets_do_not_cluster` |
| 10 | 分析 Ticket | 分析只納入 status 為 escalated 或 resolved 的 Ticket | `sql.COUNT_TICKETS_BY_USER_PROBLEM` 的 `WHERE t.status IN (...)` | `test_analysis.py::test_open_and_deflected_excluded`、`test_two_resolved_plus_one_escalated_is_recurring` |
| 11 | 分析 Ticket | 沒有 published Tutorial 的 recurring topic 才識別為 Knowledge Gap | `rules.has_knowledge_gap` ＋ `analysis.knowledge_gaps` | `test_analysis.py::test_knowledge_gap_only_without_published` |
| 12 | 分析 Ticket | Knowledge Gap 的動作為 CREATE | `analysis.analyze_tickets` 的三元式 | `test_analysis.py::test_action_create_for_gap` |
| 13 | 分析 Ticket | 已有 published Tutorial 的動作為 KEEP | 同上 | `test_analysis.py::test_action_keep_when_published` |
| 14 | 分析 Ticket | 一次分析識別出多個 Knowledge Gap 時每個都 CREATE | `analyze_tickets` 逐 row 獨立判斷 | `test_analysis.py::test_multiple_gaps_all_create` |
| 15 | 分析 Ticket | 新問題的先備知識已有現成教學時動作仍為 CREATE | `published` 集合以 `user_problem_id` 為鍵，跨 topic 不互相影響 | `test_analysis.py::test_other_topic_tutorial_does_not_block_create` |
| 16 | 建立 Tutorial | 存在 Knowledge Gap 時建立 Tutorial，status 為 published、current_version 為 v1、last_action 為 CREATE | `create_tutorial` 步驟 6 ＋ `sql.INSERT_TUTORIAL` | `test_create.py::test_create_sets_published_v1_create` |
| 17 | 建立 Tutorial | 建立的 TutorialVersion v1 五個內容欄必填且 supersedes_version 為空 | `sql.INSERT_TUTORIAL_VERSION_V1`（`reason`／`supersedes_version` 寫 `''`） | `test_create.py::test_version_v1_five_fields_and_empty_supersedes` |
| 18 | 建立 Tutorial | 建立 Tutorial 時缺少五欄任一則操作失敗 | `create_tutorial` 步驟 5 的 `missing` 檢查 | `test_create.py::test_missing_*_fails`（5 支） |
| 19 | 建立 Tutorial | 未識別出 Knowledge Gap 時建立 Tutorial 操作失敗 | `create_tutorial` 步驟 1 | `test_create.py::test_no_knowledge_gap_fails` |
| 20 | 建立 Tutorial | 建立 Tutorial 時必須有對應的 Feature | `create_tutorial` 步驟 2 `_resolve_feature` | `test_create.py::test_missing_feature_id_fails`、`test_feature_not_found_fails` |

### 6.2 自動測試

- [ ] `uv run pytest tests/unit -q` 全綠（`test_realtime.py` 7、`test_analysis.py` 10、`test_create.py` 11）
- [ ] 上表 20 條 Rule 每一條都至少對到一支測試，沒有「未覆蓋」欄
- [ ] 所有 LLM 與 RocketRide 呼叫在單元測試裡都是 mock，`pytest` 不需要網路

### 6.3 手動 demo 劇本（切片 B）

- [ ] 按「餵下一張票」第 1 次 → seq 1 進 `Ticket(status = open)`，即時路徑後 `status = escalated`，`deflected_tutorial_id` / `deflected_tutorial_version` 為空
- [ ] 中欄解法框**已預填** seq 1 的 `bitext_response`，不必手打
- [ ] 按「確認解法」→ `Ticket 1` 的 `resolution_steps` 有值、`status = resolved`
- [ ] 按「餵下一張票」第 2 次 → seq 2 → `escalated` →（確認解法）→ `resolved`
- [ ] 此時按「分析」→ 結果為空（只有 2 張，未達 recurring 門檻）

### 6.4 手動 demo 劇本（切片 C）

- [ ] 按「餵下一張票」第 3 次 → seq 3 → `escalated` →（確認解法）→ `resolved`
- [ ] 按「分析」→ 中欄顯示 `[{"user_problem_id": 1, "topic": "cancel_order", "action": "CREATE"}]`
- [ ] CREATE 跑完後 `tutorials/cancel-order.md` **存在**
- [ ] 該檔的 Steps 區塊含 `Click "Cancel Order"`（雙引號一字不差）
  ```bash
  test -f tutorials/cancel-order.md && grep -c 'Click "Cancel Order"' tutorials/cancel-order.md
  ```
  預期輸出 `1`（或更多）
- [ ] hotdata 查得到：
  ```sql
  SELECT tutorial_id, status, current_version, last_action, path, is_possibly_outdated, is_obsolete
    FROM Tutorial WHERE user_problem_id = 1;
  -- 預期：1 | published | v1 | CREATE | tutorials/cancel-order.md | false | false
  SELECT tutorial_version, supersedes_version, reason,
         (title <> '') , (problem <> ''), (prerequisites <> ''), (steps <> ''), (expected_outcome <> '')
    FROM TutorialVersion WHERE tutorial_id = 1;
  -- 預期：v1 | (空) | (空) | 五欄皆為真
  ```
- [ ] 中欄把 `tutorials/cancel-order.md` 渲染出來（不是只顯示路徑）

### 6.5 邊界與失敗路徑

- [ ] 餵 seq 6（`topic = null`）→ `escalated`，不 crash，`reopened_from_ticket_id` 為空
- [ ] 已有 published Tutorial 後再按「分析」→ 動作變 `KEEP`，不重複 CREATE，`.md` 不被覆寫
- [ ] 把 LLM 回應 mock 成缺 `steps` → `OperationFailed`，`Tutorial` 與 `TutorialVersion` 都沒有新列，`tutorials/cancel-order.md` 不存在
- [ ] 斷網（或把 `ROCKETRIDE_URI` 指到不存在的 host）→ 餵票仍在 3 秒內完成，中欄顯示「Agent 未回應（本機決策照跑）」，票照樣 `escalated`

### 6.6 RocketRide 層

- [ ] 🖐️ 手動 app 已建立，Bedrock 憑證已加，`pipeline.json` 已匯入且五個節點都連上
- [ ] 🖐️ 手動 deploy 完成，且**只**用了 `ROCKETRIDE_DEPLOY_URI` / `ROCKETRIDE_DEPLOY_APIKEY`
- [ ] `git grep -n "ROCKETRIDE_DEPLOY" -- app/` 只在 `rocketride_client.deploy_pipeline` 的錯誤訊息裡出現，沒有任何實際呼叫
- [ ] `git status` 沒有 `.env`、沒有 `.state/`、沒有任何 key 字串

---

## 7. 降級方案

| 訊號 | 降級動作 | 驗收還剩下什麼 |
|---|---|---|
| RocketRide dev webhook 連不上（`run_agent` 回 None） | 什麼都不做。本機決策是唯一寫入者，票流完全不受影響。中欄顯示「Agent 未回應（本機決策照跑）」 | §6.3、§6.4 全部照跑；只少一行 Agent 決策展示 |
| Bedrock 沒有 model access／`llm_bedrock` 報錯 | `call_llm` 自動落到**直打 Anthropic API**（`httpx` POST `https://api.anthropic.com/v1/messages`，header `x-api-key` ＋ `anthropic-version: 2023-06-01`），用 `.env` 的 `ANTHROPIC_API_KEY`。pipeline 那邊把 `tutorial_llm` 的 provider 從 `llm_bedrock` 換成 `llm_anthropic`（`profile: "claude-sonnet-4-6"` ＋ `apikey`）——**不是**加第二個 LLM 節點，因為 agent 的 `invoke.llm` 是 min 1 / max 1 | CREATE 照做，五欄照樣成型，`.md` 照樣產出 |
| 兩邊 LLM 都不通 | `call_llm` raise `OperationFailed`。**不要**塞死的假五欄進 DB——那會讓 demo 的 CREATE 變成表演。改用預先錄好的一份 LLM 回應 JSON（`data/script/llm_fallback_cancel_order.json`）並在 UI 上明確標「LLM 離線，使用預錄回應」 | CREATE 流程與 Then 表照跑，但要口頭說明是預錄 |
| Cognee 不通（`remember` 失敗） | `_remember_best_effort` 只記 warning，不回滾。ERM 仍完整寫進 hotdata | §6.4 的 SQL 驗收照過；圖譜改事後補 remember |
| HydraDB 不通（`upsert_node` / `upsert_edge` 失敗） | 同上。`explains` 邊改事後補；「有沒有 published Tutorial」本來就是走 SQL（`sql.SELECT_PUBLISHED_TUTORIAL`），不依賴圖譜 | 即時路徑與 CREATE 完全不受影響 |
| hotdata 不可用 | `hotdata_client.run_sql` 落到 `app/analytics/local_db.py`，**同一份 SQL、同一組 9 表**，不建第 10 表 | 全部照跑 |
| Streamlit 卡住／改壞 | 用 CLI 走同一條路：`uv run python -m app.ingest.poll` ＋ `uv run python -c "from app.agent import analysis, create_tutorial; ..."`。UI 本來就只觸發、只展示 | Then 表可驗，只是沒有畫面 |

降級的共同底線：**規格的成功邊界不變**。五欄缺一還是 `OperationFailed`，票讀寫失敗還是維持 `open`，`.md` 與 `TutorialVersion` 還是同生共死。

---

## 8. 交接給 Phase 3 的東西

Phase 3（切片 D：deflect ＋ Rote）直接拿下面這些，不要重寫：

| 交付 | Phase 3 怎麼用 |
|---|---|
| `Tutorial(tutorial_id=1, user_problem_id=1, status='published', current_version='v1')` | 第 4 張 `cancel_order` 票走 `realtime.handle_open_ticket` 時，`sql.SELECT_PUBLISHED_TUTORIAL` 會命中 → 這次真的 `deflected`。Phase 3 不必改 `realtime.py` 一行 |
| `rules.classify_ticket` | Rote Play 重放失敗時的 fallback 走同一條判斷（`showme` §14：重放失敗 → 本張票改走 Agent 即時路徑，仍可 deflected，且**不**把失敗寫成 `replay_count + 1`） |
| `realtime.handle_open_ticket` 的回傳物件（含 `status` / `tutorial_id` / `tutorial_version` / `reason`） | Phase 3 在 `status == 'deflected'` 且該 `user_problem_id` **還沒有** Workflow 列時，觸發 Rote 捕捉（`Workflow.replay_count = 0`、`captured_at` = 系統目前時間）；已有 Workflow 就走重放並 `replay_count + 1` |
| `data/script/demo_tickets.json` 的 seq 4、5 | seq 4 → 第一次 deflected ＋ Workflow 捕捉；seq 5 → 重放，`replay_count = 1` |
| `app/agent/rocketride_client.py` | Phase 4（Periodic Review）與 Phase 5（Release Update）的事件也走 `run_agent()`，只換 `event` 欄位（`review_requested` / `release_posted`） |
| `app/agent/pipeline.json` 的 `instructions` 第 3 段 | 三條 pipeline 的門檻文字已經寫好，Phase 4／5 只驗證 Agent 行為，不必再改 instructions |
| `tutorials/cancel-order.md` ＋ `TutorialVersion(1, v1).steps` | Phase 5 的 Release Note 更名 diff 以這份 `steps` 字串為基準：`Click "Cancel Order"` → `Click "Cancel Purchase"` |
| `app/analytics/sql.py` 的具名常數 | Phase 4 的三條指標 SQL（deflection rate / 重放解決率 / 圖譜覆蓋）加在同一支檔案，命名風格沿用 |
| `.state/last_checked.json` | Phase 5 的 Release 輪詢用同一種 cursor 檔（另一個鍵或另一支檔），一樣不落第 10 表 |

**Phase 3 開工前要確認：** `SELECT COUNT(*) FROM Tutorial WHERE status='published'` ≥ 1，且 `tutorials/cancel-order.md` 存在。這兩條就是本 Phase 的交割單。

---

## 來源

**專案內（實讀）：**

- `/Users/linjunting/AWS-Hackathon/CLAUDE.md`（門檻表、五層對應、語言慣例、deploy 憑證規則）
- `/Users/linjunting/AWS-Hackathon/docs/design/showme.md` §5.4、§5.5、§6 步驟 2–6、§7.1、§7.2、§8、§9、§11、§13、§14、§16、§17
- `/Users/linjunting/AWS-Hackathon/docs/design/architecture.md` §1、§1.1、§4
- `/Users/linjunting/AWS-Hackathon/docs/spec/erm.dbml`（9 表欄位、不變條件、狀態轉換）
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/輪詢新票單.feature`（1 Rule）
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/自動回覆顧客.feature`（5 Rule）
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/分析SupportTickets.feature`（9 Rule）
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/建立Tutorial.feature`（5 Rule）
- `.rocketride/schema/agent_rocketride.json`（`invoke` 的 llm/memory/tool 基數、`lanes: questions → answers`、`Pipe.schema` 的 `agent_description` / `instructions` / `max_waves`）
- `.rocketride/schema/llm_bedrock.json`（22 個 `profile` enum、每個 profile 的 `region` / `accessKey` / `secretKey`）
- `.rocketride/schema/llm_anthropic.json`（`profile` enum 與 `apikey`）
- `.rocketride/schema/webhook.json`（`type` / `mode` / `hideForm` / `parameters`；`_source` lanes 含 `questions`）
- `.rocketride/schema/tool_cognee.json`（`dataset` / `allow_dataset_override` / `search_type` / `top_k` / `request_timeout` / `base_url` / `api_key`）
- `.rocketride/schema/db_hydradb.json`（`profile.default` 的 `api_key` / `database` / `collection` / `max_results`）
- `.rocketride/services-catalog.json`（140 個節點；memory 類只有 `memory_internal` 與 `memory_persistent`；source 類只有 `chat` / `dropper` / `filesys` / `telegram` / `webhook`；**無** response/sink 節點、**無** hotdata／Rote 節點）

**官方文件（本次查詢 3 次）：**

- RocketRide 文件首頁 — https://docs.rocketride.org （WebSocket 連線、TypeScript／Python SDK、MCP 支援）
- RocketRide Pipeline JSON Reference — https://docs.rocketride.org/pipeline-reference （`components[]` 的 `id` / `provider` / `config` / `input` / `control`；`input` 是 `{lane, from}`，`control` 是 `{classType, from}`；頂層另有 `name` / `description` / `version` / `source`）
- RocketRide WebSocket 協定 — https://docs.rocketride.org/protocols/websocket （`ws://<host>:<port>/task/service`，本機預設 port 5565、雲端 `https://api.rocketride.ai`；第一個 frame 送 `{"auth": "$ROCKETRIDE_APIKEY", ...}`；DAP 風格 `type`/`seq`/`command`/`arguments`；`rrext_process` 的 open/write/close；SDK `use()` / `send()` / `pipe()` / `chat()` / `terminate()`；HTTP webhook 端點 `/webhook/{project_id}/{source}`，Content-Type 決定 lane）

**查不到、因此標為 🖐️ 手動而不猜：** deploy / `publishApp` / `submitApp` 的 REST 端點；webhook 的「Content-Type → lane」對照表。

**未當來源：** `docs/spec/draft/design-draft.md` 的 Copilot 敘事、`docs/plan/dev-prompts/phase0911.md`（指向另一個專案的 prompt 模板）。

## 現況更新（2026-09-11）

- **Phase 0 已實作並驗證**：`uv run pytest -q` 35 passed；Bitext 真實下載（`data/raw/`），`data/seed/bitext_seed.json` 6 筆、`data/script/demo_tickets.json` 9 筆、`feedback_seed.json` 10 筆（avg 2.9）、`feedback_v2_seed.json` 5 筆（avg 4.4）；Streamlit 空殼可啟動；`.env`／`.state/`／`data/raw/` 已 git-ignore。
- **環境事實**：hotdata CLI 已登入（workspace `Hackathon_space`，尚無本專案 database）；`rote whoami` 正常；Cognee 伺服器可用（沿用本機記憶插件的 server，專案另開 dataset）；**沒有** HydraDB 直連憑證與 LLM 金鑰（`.env` 只有 `ROCKETRIDE_*`）。
- **已知偏差（以骨架命名為準）**：hotdata instant database 是 schema-on-load，9 表 DDL 主要用於 SQLite 降級；RocketRide `db_hydradb` 節點沒有 Cypher action，多跳查詢由 `app/memory/hydradb_client.py` 自己做；phase 專屬 SQL 放在該 phase 模組，不回改 `app/analytics/sql.py`；Streamlit 各區以 `app/demo/ui_<x>.py` 的 `render(db)` 提供，最後統一接進 `streamlit_app.py`。
- **共用介面**：`app/agent/llm.py: complete_json(prompt, schema_hint) -> dict`（無金鑰時 raise `LLMUnavailable`，呼叫端用模板降級）；`app/muscle/rote_client.py: on_deflected(db, ticket_id, user_problem_id) -> dict`。

