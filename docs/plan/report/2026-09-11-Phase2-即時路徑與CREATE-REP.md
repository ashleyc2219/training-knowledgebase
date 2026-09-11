# 2026-09-11 — Phase 2 即時路徑與 CREATE 完成報告

> ⚠️ 這只是 hackathon 作品，不要過度設計。

- 對應計畫：`docs/plan/unfinish/03-Phase2-即時路徑與CREATE.md`
- 對應規格：`docs/spec/features/輪詢新票單.feature`、`自動回覆顧客.feature`、`分析SupportTickets.feature`、`建立Tutorial.feature`（共 20 條 Rule）
- 狀態：**完成**（程式面全數完成；未完成項只剩 🖐️ 手動帳號類，見 §7）

---

## 1. 實作邏輯

### 這個 phase 解決什麼

Phase 2 是 demo 的**前半條學習迴圈**：把「顧客丟票進來」變成「系統判斷 → 沒有教學就轉真人 → 累積到門檻就自己寫一篇教學」。
沒有這一段，後面 Phase 3（deflect／重放）、Phase 4（REFINE）、Phase 5（UPDATE）都沒有東西可以動——它們全部都要先有一篇 `tutorials/cancel-order.md` v1。

一句話：**Phase 2 = 即時路徑（每張票即時判 deflected／escalated）＋ 批次路徑（累積 ≥3 張同類 escalated 票就 CREATE v1）**。

### 怎麼切（三條縱線，互不相干）

| 縱線 | 模組 | 負責 |
|---|---|---|
| 進料 | `app/ingest/poll.py` | 從劇本檔餵下一張票、輪詢新票（`created_at` 嚴格大於 ＋ 只取 `open`）、Bitext 解法預填 |
| 即時判斷 | `app/agent/realtime.py` | 一張票一次決策：deflected／escalated／轉真人解決 |
| 批次生成 | `app/agent/analysis.py` → `app/agent/create_tutorial.py` | 找 Knowledge Gap → 生成 Tutorial v1 ＋ TutorialVersion ＋ `.md` 檔 ＋ 圖譜邊 |

三條線**都不自己算門檻**，一律呼叫 Phase 0 已寫好的 `app/agent/rules.py`（`classify_ticket` / `decide_analysis_action`）。這是刻意的：門檻只有一份，改一個數字全專案跟著改，也讓 `test_rules.py` 的 27 個測試就是門檻的規格文件。

### 關鍵設計決定與理由

| 決定 | 理由 |
|---|---|
| `handle_open_ticket(db, ticket_id, rote=None)` 吃 `ticket_id` 不吃 dict | Streamlit 按鈕、smoke script、彩排腳本三個呼叫點共用同一支；ID 進去、DB 狀態出來，不用在三個地方組同一個 dict |
| 非 `open` 的票直接 `OperationFailed` | 規格「失敗一律 `Then 操作失敗`」。Demo 時連點兩下按鈕不會把同一張票判兩次 |
| `create_tutorial` 進來先**重驗** Knowledge Gap | `analyze_tickets` 與 `create_tutorial` 中間隔了一個使用者按鈕，票況可能已變。重驗一次比事後補救便宜 |
| 缺五欄任一 → `OperationFailed` 且**不寫任何一列** | `建立Tutorial.feature` 明寫。實作上是「先湊齊五欄再開始寫 DB」，不是寫到一半 rollback |
| `.md` 寫檔失敗要把已寫的 Tutorial／TutorialVersion **刪回去** | SQLite／hotdata 都沒有跨語句交易可用，只能補償式回滾。見 §5 |
| LLM 不通 → 模板降級，標 `source="template"` | 黑客松當天沒金鑰或額度爆掉是高機率事件。降級後**流程與門檻完全不變**，只有文字變樣板，demo 曲線照樣會動 |
| Cognee／HydraDB 寫入 best-effort（失敗只記不擋） | 圖譜是加分項，不是 CREATE 成功的條件。圖譜掛掉不該讓教學生不出來 |
| RocketRide 事件 fire-and-forget 鏡射 | Motion 層要「看得到有事發生」，但 demo 不能因為 staging 慢而卡住 |

---

## 2. 步驟（TDD 先紅後綠）

1. **前置檢查**：確認 Phase 0／1 的 `rules.py`、`db.py`、9 表 schema、`data/script/demo_tickets.json` 都在，`import app.agent.realtime` 不炸。
2. 建共用 fixture `tests/unit/_phase2_fixtures.py`（建空 DB、塞 UserProblem／Feature／Ticket 的小工具），四支測試共用，避免每支各自刻一份建表碼。
3. **先紅**：`tests/unit/test_poll.py` 照 `輪詢新票單.feature` 的 Rule（只取 `created_at` 嚴格大於且 `status = open`）寫 → 紅。
4. **後綠**：實作 `poll.poll_new_tickets` / `feed_next_ticket` / `peek_next_ticket` / `bitext_response` → 6 綠。
5. **先紅**：`tests/unit/test_realtime.py` 照 `自動回覆顧客.feature` 五條 Rule（有 published → deflected／無 → escalated／`user_problem_id` 空 → escalated／retired 視同沒有／同顧客再開票 → escalated ＋ `reopened_from_ticket_id`）寫 → 紅。
6. **後綠**：實作 `realtime.handle_open_ticket` / `resolve_ticket` → 11 綠。
7. **先紅**：`tests/unit/test_analysis.py` 照 `分析SupportTickets.feature` 的 Rule（≥3 張、只納入 escalated／resolved、已有 published → KEEP、多個 Gap 各自 CREATE）寫 → 紅。
8. **後綠**：實作 `analysis.analyze_tickets` / `knowledge_gaps`（門檻交給 `rules.decide_analysis_action`）→ 11 綠。
9. **先紅**：`tests/unit/test_create.py` 照 `建立Tutorial.feature` 五條 Rule（v1／published／CREATE、五欄必填且 `supersedes_version` 空、缺欄失敗、無 Gap 失敗、必須有 Feature）寫 → 紅。
10. **後綠**：實作 `create_tutorial.create_tutorial`，含模板降級與 `.md` 寫檔補償回滾 → 12 綠。
11. 接 Streamlit：`app/demo/ui_tickets.py` 左欄餵票＋回覆、中欄決策卡＋解法確認框＋「分析 Support Tickets」按鈕＋`tutorials/*.md` 檢視。
12. Motion 層：查 `{ROCKETRIDE_URI}/openapi.json` 找出真實 REST 形狀，寫 `app/agent/rocketride_client.py` ＋ `app/agent/pipeline.json`，實打 dev 連線驗證。
13. 寫 `scripts/phase2_smoke.py` 走一次完整劇本（餵 3 張 → 分析 → CREATE → 第 4 張 deflected），確認四個模組串得起來。
14. 全套 `uv run pytest -q -m "not integration"` → 全綠。

---

## 3. 產出檔案

| 檔案 | 行數 | 內容 |
|---|---|---|
| `app/agent/realtime.py` | 207 | `handle_open_ticket()`：非 open → `OperationFailed`；查再開票／published Tutorial → `rules.classify_ticket` → 寫 `status` ＋ `deflected_tutorial_id` / `deflected_tutorial_version` 或 `reopened_from_ticket_id`；deflected 後呼叫 `rote_client.on_deflected`；最後 fire-and-forget 鏡射事件給 RocketRide。另有 `resolve_ticket(db, ticket_id, resolution_steps)` |
| `app/agent/analysis.py` | 62 | `analyze_tickets(db)` / `knowledge_gaps(db)`：只納入 `escalated` / `resolved`，門檻全交給 `rules.decide_analysis_action` |
| `app/agent/create_tutorial.py` | 332 | Gap 重驗 → Feature 解析 → `llm.complete_json` 產五欄（`LLMUnavailable` → 模板降級標 `source="template"`；缺欄 → `OperationFailed` 不寫任何東西）→ Tutorial(published/v1/CREATE) ＋ TutorialVersion v1 ＋ `tutorials/<slug>.md`（寫檔失敗刪回列）→ Cognee／HydraDB best-effort 補 `explains` 邊 |
| `app/ingest/poll.py` | 190 | `poll_new_tickets`（嚴格大於、只取 open）、`feed_next_ticket`（游標存 `.state/demo_cursor.json`，intent 對回 `user_problem_id` / `feature_id`）、`peek_next_ticket`、`bitext_response`（從 `data/seed/bitext_seed.json` 同 intent 撈解法預填） |
| `app/demo/ui_tickets.py` | 166 | 左欄餵票＋回覆、中欄決策卡／解法確認框／「分析 Support Tickets」自動 CREATE／`tutorials/*.md` 檢視；已由整合步驟接進 `streamlit_app.py` |
| `app/agent/rocketride_client.py` | 168 | 真實 REST：`POST /task`（body = pipeline JSON，回 token）→ `POST /webhook?token=…`。`deploy_pipeline()` 只 raise 手動提示，**完全沒碰 `ROCKETRIDE_DEPLOY_*`** |
| `app/agent/pipeline.json` | — | `webhook → agent_rocketride`（instructions 全文）→ `llm_bedrock` / `memory_internal` / `tool_cognee` / `db_hydradb` |
| `tests/unit/_phase2_fixtures.py` | 89 | 四支測試共用的 DB fixture |
| `tests/unit/test_realtime.py` | 182 | 11 tests |
| `tests/unit/test_analysis.py` | 126 | 11 tests |
| `tests/unit/test_create.py` | 185 | 12 tests |
| `tests/unit/test_poll.py` | 119 | 6 tests |
| `scripts/phase2_smoke.py` | 112 | 端到端煙測腳本 |

順手改動（非本 phase 範圍但擋路）：

| 檔案 | 改了什麼 | 為什麼 |
|---|---|---|
| `app/agent/llm.py` | model 預設改 `claude-opus-5`（`ANTHROPIC_MODEL` 可覆寫）、`max_tokens` 16000、effort 調 low | adaptive thinking 會吃掉大量額度，黑客松當天額度有限 |
| `data/script/demo_tickets.json` | 重排成 cancel_order 6 張在前（第 4、5 張同類、第 6 張 alice 再開票 `reopen_hint`），其餘 intent 在後 | 讓「一路按下一張票」就自然走出 escalated → CREATE → deflected → 重放 → 再開票五個劇情點，不用在 demo 現場挑票 |

---

## 4. 測試方式（指令＋對齊 .feature Rule）

```bash
cd /Users/linjunting/AWS-Hackathon
uv run pytest -q tests/unit/test_poll.py tests/unit/test_realtime.py \
               tests/unit/test_analysis.py tests/unit/test_create.py
uv run python scripts/phase2_smoke.py     # 端到端煙測（sqlite，安全）
```

| 測試檔 | 對齊的 Rule | 條數 |
|---|---|---|
| `test_poll.py` | `輪詢新票單.feature`：只處理 `created_at` 大於上次檢查且 `status` 為 open 的票 | 6 |
| `test_realtime.py` | `自動回覆顧客.feature` 全 5 條 Rule：已有 published → deflected／沒有 → escalated／`user_problem_id` 為空 → escalated／`retired` 視同沒有 Tutorial／同顧客同 UserProblem 再開票 → escalated ＋ `reopened_from_ticket_id` | 11 |
| `test_analysis.py` | `分析SupportTickets.feature` 8 條 Rule：≥3 張才 recurring／無票為空／聚不成主題為空／只納入 escalated 或 resolved／無 published 才是 Gap／Gap 動作 CREATE／已有 published 為 KEEP／多 Gap 各自 CREATE | 11 |
| `test_create.py` | `建立Tutorial.feature` 5 條 Rule：published/v1/CREATE／五欄必填且 `supersedes_version` 為空／缺欄操作失敗／未識別 Gap 操作失敗／必須有對應 Feature | 12 |

**煙測驗收的具體劇情**（`scripts/phase2_smoke.py`）：餵 3 張 cancel_order 票 → 三張都 escalated（`no_published_tutorial`）→ 轉真人 resolved → 分析出 1 個 Gap 動作 CREATE → 產出 `tutorials/cancel-order.md`，Step 3 字面含 `Click "Cancel Order"` → 餵第 4 張同類票 → deflected ＋ Workflow 一列。

---

## 5. 遇到的問題與解法

| 問題 | 現象 | 解法 |
|---|---|---|
| RocketRide 的 REST 形狀官方文件沒寫 | 憑記憶猜端點必錯，而 `CLAUDE.md` 明令不准猜 SDK 方法名 | 直接抓 `{ROCKETRIDE_URI}/openapi.json` 讀真實規格，找到 `POST /task`（body = pipeline JSON，回 token）→ `POST /webhook?token=…` 兩段式。實打 dev 連線驗證：`GET /version` 200（server 3.3.0.5）、`POST /task` 200、`POST /webhook` 200 且 `objectsCompleted: 1` |
| RocketRide answers lane 要 WebSocket | 想讓 `call_llm()` 走 RocketRide 的 `llm_bedrock`，但同步取回答案需要 WebSocket 通道 | **不做**。`call_llm` 一律丟 `LLMUnavailable`，讓 `llm.py` 往下掉到 Anthropic key，再往下掉到模板。RocketRide 保留「事件鏡射」角色，Motion 層仍看得到實跑紀錄。黑客松時間內不值得為此開 WebSocket |
| `.md` 寫檔失敗會留下孤兒列 | Tutorial／TutorialVersion 已 insert，但檔案寫失敗（權限／路徑），DB 與檔案不一致 | 補償式回滾：catch 寫檔例外後把剛 insert 的兩列刪回去再 raise。**這不是真交易**，是 hackathon 等級的權宜，見 §8 |
| LLM 回的 JSON 缺欄 | `建立Tutorial.feature` 要求缺任一欄就操作失敗 | 在「開始寫 DB 之前」就把五欄湊齊並驗證，缺欄直接 `OperationFailed`，DB 一列都不寫。順序決定正確性，比事後 rollback 乾淨 |
| 懷疑 `rules.classify_ticket` 有 bug | 再開票案例判斷不如預期 | 實際逐行查過 `rules.py`，**沒有 bug**，是測試 fixture 少塞 `reopened_from_ticket_id` 的前置票。修 fixture，`rules.py` 一個字沒動（門檻模組維持單一出處） |
| adaptive thinking 吃額度 | `llm.py` 預設參數會觸發長思考，CREATE 一次就燒掉不少 token | model 預設改 `claude-opus-5`、`max_tokens` 16000、effort 調 low。黑客松要的是「能跑完」不是「想得深」 |
| hotdata 沒有 `RETURNING` | insert 後要拿新列 id | hotdata backend 用 `MAX(id)` 取。單機 demo 無併發，夠用；見 §8 |

---

## 6. 測試結果（實跑數字）

```
$ uv run pytest -q tests/unit/test_poll.py tests/unit/test_realtime.py \
                  tests/unit/test_analysis.py tests/unit/test_create.py
40 passed
```

| 測試檔 | 通過 |
|---|---|
| `test_realtime.py` | 11 |
| `test_analysis.py` | 11 |
| `test_create.py` | 12 |
| `test_poll.py` | 6 |
| **Phase 2 小計** | **40** |

全套回歸（含其他 phase）：`uv run pytest -q -m "not integration"` → **190 passed, 2 deselected, 11.35s**。

`scripts/phase2_smoke.py` 通過。RocketRide dev 連線實測結果：

| 呼叫 | 結果 |
|---|---|
| `GET /version` | 200（server 3.3.0.5） |
| `POST /task`（body = `pipeline.json`） | 200，回 token |
| `POST /webhook?token=…` | 200，`objectsCompleted: 1` |
| `deploy_pipeline()` | 依設計 raise 手動提示，未發出任何 deploy 請求 |

彩排腳本中屬於 Phase 2 的三步（實跑）：

```
▶ 1 種子建圖 → seed() = {'tickets': 6, 'user_problems': 3, 'features': 3, ...}
▶ 2 餵 3 張 cancel_order → 轉真人 → CREATE v1
   票 #7：escalated｜no_published_tutorial
   票 #8：escalated｜no_published_tutorial
   票 #9：escalated｜no_published_tutorial
   analyze_tickets → [{'user_problem_id': 1, 'topic': 'cancel_order', 'action': 'CREATE'}]
   create_tutorial → tutorial_id=1 tutorials/cancel-order.md
   Tutorial #1 tutorials/cancel-order.md｜published｜v1｜CREATE   ⏱ 3.9s
▶ 3 第 4 張 cancel_order 票 → deflected ＋ Rote 捕捉
   票 #10：deflected｜published_tutorial
   Workflow：[{'id': 1, 'user_problem_id': 1, 'replay_count': 0}]  ⏱ 0.5s
```

---

## 7. 🖐️ 留給使用者的手動事項

完整版見 `docs/plan/todo/2026-09-11-手動設定清單.md`。與 Phase 2 直接相關的只有兩項：

| # | 項目 | 影響 Phase 2 的什麼 | 沒做的降級 |
|---|---|---|---|
| 1 | **LLM 金鑰**：`.env` 填 `ANTHROPIC_API_KEY`（方案 A，5 分鐘）**或** 在 RocketRide console 幫 `llm_bedrock` 加 AWS Bedrock 憑證（方案 B） | `create_tutorial` 的五欄內容 | 走模板降級，結果標 `source="template"`。**CREATE 照樣成功、門檻與流程完全不變**，只是 `tutorials/cancel-order.md` 的文字是樣板不是生成 |
| 4 | **RocketRide console**：確認 credits → 建 app `support-tutorial-generator` → 匯入 `app/agent/pipeline.json` → 肉眼確認 `demo_webhook → support_agent` 這條邊落在 **`questions` lane** → **deploy** → 把 `ROCKETRIDE_PROJECT_ID` 寫進 `.env` | Motion 層有沒有「一條真的部署好的 pipeline」給評審看 | `rocketride_client` 在沒有 `ROCKETRIDE_PROJECT_ID` 時丟 `LLMUnavailable`，決策全部由本機 `app/agent/*.py` 跑。Demo 完整，但 Motion 層只有 client 程式碼 |

> 🚨 **紅線**：deploy／schedules／publishApp **只能**用 `ROCKETRIDE_DEPLOY_URI` / `ROCKETRIDE_DEPLOY_APIKEY`，絕不 deploy 到 dev 連線。deploy 端點官方文件未載明，所以 `deploy_pipeline()` **故意**直接 raise 手動提示——請在 staging console 上手動按，不要讓任何程式猜 URL。

---

## 8. 與計畫的偏差／hackathon 簡化

| 項目 | 計畫寫的 | 實際做的 | 為什麼 |
|---|---|---|---|
| 交易 | 「Tutorial ＋ TutorialVersion ＋ `.md` 要原子性」 | **補償式回滾**（寫檔失敗刪回已 insert 的兩列） | SQLite 與 hotdata 沒有共用的跨語句交易介面。單機 demo 無併發，補償夠用；正式化要靠 DB 層交易或 outbox |
| 新列 id | 未指定 | hotdata backend 用 `MAX(id)` 取 | hotdata 不支援 `RETURNING`。無併發下正確 |
| hotdata 實測 | 「CREATE 走一次 hotdata」 | **未在 hotdata 上實跑 CREATE**，只在 SQLite 驗過 | 兩個 backend 共用同一組方法名與同一份 SQL 常數，切換是改 `DB_BACKEND` 一行的事。當天要驗只需切換後重跑煙測 |
| RocketRide LLM | 「`call_llm` 走 `llm_bedrock` 取回答案」 | **不做**，一律 `LLMUnavailable` 讓 provider 鏈往下掉 | answers lane 需要 WebSocket，時間內不划算。Motion 層改由「事件鏡射」證明有在做事 |
| `rules.py` | 「必要時修門檻邏輯」 | **一個字沒動** | 實查沒有 bug，問題在測試 fixture。門檻模組維持單一出處是刻意的 |
| 劇本資料 | Phase 0 產的 9 筆順序 | 重排成 cancel_order 6 張在前 | Demo 現場「一路按下一張票」就要自然走出五個劇情點，不該靠現場挑票 |

**不做的（Scope guardrail，與 `CLAUDE.md` 一致）**：人工審核佇列、SLA／票量暴增監測、Slack 輸入、Customer 表、先備知識圖譜邊、教學影片、複雜 dashboard。
