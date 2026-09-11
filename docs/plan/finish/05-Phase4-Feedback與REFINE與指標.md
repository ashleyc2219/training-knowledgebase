# Phase 4 — Feedback、REFINE 與學習指標

> ⚠️ **這只是 hackathon 作品，不要過度設計。** 8 小時內能 demo 迴圈就好：先讓它能跑，再談漂亮。
> 能用最簡單的方式做到驗收條件就停手；不加規格沒寫的欄位、不做抽象層、不為「日後擴充」多寫一行。
> 遇到「這樣夠不夠好」的猶豫時，選最短路徑，並在 report 標記「hackathon 簡化」即可。

## 現況更新（2026-09-11）

- **Phase 0 已實作並驗證**：`uv run pytest -q` 35 passed；Bitext 真實下載（`data/raw/`），`data/seed/bitext_seed.json` 6 筆、`data/script/demo_tickets.json` 9 筆、`feedback_seed.json` 10 筆（avg 2.9）、`feedback_v2_seed.json` 5 筆（avg 4.4）；Streamlit 空殼可啟動；`.env`／`.state/`／`data/raw/` 已 git-ignore。
- **環境事實**：hotdata CLI 已登入（workspace `Hackathon_space`，尚無本專案 database）；`rote whoami` 正常；Cognee 伺服器可用（沿用本機記憶插件的 server，專案另開 dataset）；**沒有** HydraDB 直連憑證與 LLM 金鑰（`.env` 只有 `ROCKETRIDE_*`）。
- **已知偏差（以骨架命名為準）**：hotdata instant database 是 schema-on-load，9 表 DDL 主要用於 SQLite 降級；RocketRide `db_hydradb` 節點沒有 Cypher action，多跳查詢由 `app/memory/hydradb_client.py` 自己做；phase 專屬 SQL 放在該 phase 模組，不回改 `app/analytics/sql.py`；Streamlit 各區以 `app/demo/ui_<x>.py` 的 `render(db)` 提供，最後統一接進 `streamlit_app.py`。
- **共用介面**：`app/agent/llm.py: complete_json(prompt, schema_hint) -> dict`（無金鑰時 raise `LLMUnavailable`，呼叫端用模板降級）；`app/muscle/rote_client.py: on_deflected(db, ticket_id, user_problem_id) -> dict`。

- **對應設計：** `docs/design/showme.md` §16 切片 E、§7.4（Periodic Feedback Review 契約）、§12（學習指標）；另引用 §6 步驟 8／9／12、§8（生命週期狀態機）、§13（UI 邊界）、§14（錯誤語意）、§17（降級）
- **對應規格：** `docs/spec/features/收集Feedback.feature`（7 Rule）、`docs/spec/features/定期優化Tutorial.feature`（10 Rule）、`docs/spec/features/展示學習指標.feature`（3 Rule），共 **20 Rule**
- **狀態：** 尚未實作。本檔是實作計畫，底下所有目錄、檔案、函式、SQL 都是**要寫的東西**，不是已上線的系統。
- **前置：** Phase 3（切片 D）驗收通過，具體條件見 §0
- **預估時間：** 75–95 分鐘（Feedback 寫入 25 / Review 與 REFINE 30 / 指標與曲線 20 / 種子與驗收 15）
- **產出：**
  - `app/ingest/feedback.py`（`collect_feedback()`、種子匯入 CLI）
  - `app/agent/rules.py` 追加 `should_refine()`
  - `app/agent/feedback_review.py`（`review_all()`）
  - `app/analytics/sql.py` 追加 5 條 SQL、`app/analytics/metrics.py`（三條指標 + `avg_rating` + `snapshot`）
  - `app/demo/streamlit_app.py` 中欄 Feedback 表單＋Review 按鈕、下欄曲線與四個數字
  - `data/seed/feedback_seed.json`（v1 avg 2.9）、`data/seed/feedback_v2_seed.json`（v2 avg 4.4，demo 安排）
  - `tests/unit/test_feedback.py`、`tests/unit/test_review.py`、`tests/unit/test_metrics.py`
  - `.state/metrics_history.json`（曲線用；不是第 10 張業務表）

---

## 0. 前置：Phase 3 要交到我手上的東西

Phase 4 不自己造票、不自己建教學。開工前先用 `hotdata query` 逐條確認：

| # | 條件 | 檢查方式 |
|---|---|---|
| 1 | `Tutorial` 有 `tutorial_id = 1`、`status = published`、`current_version = v1`、`last_action = CREATE`、`is_possibly_outdated = false`、`is_obsolete = false` | `SELECT * FROM Tutorial WHERE tutorial_id = 1` |
| 2 | `TutorialVersion (1, v1)` 五欄（title / problem / prerequisites / steps / expected_outcome）皆有值，`reason` 空、`supersedes_version` 空 | `SELECT * FROM TutorialVersion WHERE tutorial_id = 1` |
| 3 | `tutorials/cancel-order.md` 檔案存在，內容與 v1 五欄一致 | `cat tutorials/cancel-order.md` |
| 4 | `Ticket` 至少 2 張 `deflected` + 2 張 `escalated`（deflection rate 才有 0.5 的起點） | `SELECT status, COUNT(*) FROM Ticket GROUP BY status` |
| 5 | `Workflow` 有 1 列 `user_problem_id = 1`、`replay_count >= 1` | `SELECT * FROM Workflow` |
| 6 | `UserProblem` 至少 2 列（`cancel_order`、`track_refund`），覆蓋率才不是 1/1 | `SELECT * FROM UserProblem` |
| 7 | `app/errors.py` 的 `OperationFailed`、`app/analytics/hotdata_client.py` 的 `run_sql()` 可直接 import | `uv run python -c "from app.errors import OperationFailed; from app.analytics.hotdata_client import run_sql"` |
| 8 | `app/memory/cognee_client.py`、`app/memory/hydradb_client.py` 有 `remember()` / `write_edge()` 可呼叫（不通也要能 raise，不能 import 就掛） | 同上 |

任何一條不成立就不要開始寫 Review：REFINE 是「改既有教學」，沒有 v1 就沒有 v2。

---

## 1. 目標與結束時可看到

Phase 4 把迴圈的**回授端**接起來：顧客評分進來 → 系統自己決定要不要改教學 → 改完的效果在曲線上看得到。這是評審判斷「有沒有 self-learning」的那一段，`past outcomes change future system behavior`。

結束時，在同一個 Streamlit 分頁要能看到：

1. **中欄**多一塊 Feedback 表單（rating 1–5、category 七選一、comment、submitter），送出後畫面出現該筆回饋；rating 填 0 或 6 會被擋下並顯示「操作失敗」，資料不入庫。
2. **中欄**多一顆「Review」按鈕。按下去之前 `tutorials/cancel-order.md` 的 Step 3 是 `Click "Cancel Order".`；按下去之後同一檔案的 Step 3 多了一句定位說明，`Tutorial.current_version` 變 `v2`、`last_action` 變 `REFINE`。
3. **下欄**四個數字（deflection rate、平均 rating、重放解決率、圖譜覆蓋）＋一張折線圖。匯入 v2 高分回饋後，平均 rating 從 **2.9 → 4.4**，曲線往上折。
4. `TutorialVersion` 出現 `(1, v2)`，`supersedes_version = v1`、`reason` 有值、`created_at` 有值；`(1, v1)` 原樣保留（版本是快照，不是就地修改）。

**不做**（維持 Non-Goals）：不做人工審核佇列、不做複雜 dashboard、不在 UI 算門檻、再開票不直接觸發 REFINE（只進指標）。

---

## 2. 在整體迴圈的位置

```
 Phase 0        Phase 1        Phase 2        Phase 3        Phase 4        Phase 5
 骨架/連線      種子建圖        餵票→CREATE    deflect+Rote   Feedback       Release
                (切片 A)       (切片 B/C)     (切片 D)       REFINE+指標    UPDATE/RETIRE
                                                            (切片 E)       (切片 F)
 ---+--------------+--------------+--------------+--------------+--------------+--->
    |              |              |              |              |              |
    |              |              |              |              |<-- 本檔 -----|
    |              |              |              |              |
    |              |              |              |              +-- 讀：Tutorial v1 / Ticket 狀態 / Workflow
    |              |              |              |              +-- 寫：Feedback、TutorialVersion v2、
    |              |              |              |                      Tutorial.current_version / last_action
    |              |              |              |              +-- 交棒：v2 版本鏈、metrics_history.json
    |              |              |              |
    |              |              |              +-- 給我：deflected/escalated 票、Workflow.replay_count
    |              |              +-- 給我：Tutorial 1 / TutorialVersion (1,v1) / cancel-order.md
    |              +-- 給我：UserProblem、Feature
    +-- 給我：run_sql / OperationFailed / cognee / hydradb client

 迴圈方向：Ticket --> Tutorial --> Feedback --> (REFINE) --> 新版 Tutorial --> 下一批 Ticket 的 deflection
                                      ^                                              |
                                      +----------------------------------------------+
                                          回授：這就是 self-learning 的那一圈
```

Phase 4 與 Phase 5 的交界規則（showme §7.4）：**同時命中 UPDATE 與 REFINE 時先 UPDATE**，REFINE 等下一輪。實作上 Phase 4 只要守住「`is_possibly_outdated = true` 本輪一律 KEEP」就自動讓路，不需要跨 phase 的鎖。

---

## 3. 流程

### 3.1 Feedback 寫入驗證流程（`collect_feedback(payload)`）

七條 Rule 全部在這張圖上；任一 `[FAIL]` 一律 `raise OperationFailed`，**一列都不寫**。

```
payload = {tutorial_id, tutorial_version?, rating, feedback_category?, comment?, submitter_id?, timestamp}
        |
        v
  [1] tutorial_id 有值？                 --no--> [FAIL] 操作失敗
        | yes
        v
  [2] timestamp 有值？                   --no--> [FAIL] 操作失敗
        | yes
        v
  [3] rating 有值？                      --no--> [FAIL] 操作失敗
        | yes
        v
  [4] rating 是整數且 1 <= rating <= 5？  --no--> [FAIL] 操作失敗   (0 / 6 / "3" / 3.5 都失敗)
        | yes
        v
  [5] tutorial_version 有填？
        |                     \
        | no                   \ yes
        v                       v
   查 Tutorial.current_version   直接採用
        |                       |
        +-----------+-----------+
                    v
  [6] TutorialVersion(tutorial_id, tutorial_version) 存在？ --no--> [FAIL] 操作失敗  (例：v9)
                    | yes
                    v
  [7] feedback_category 正規化
        - 未填 / None            -> ""     (存空字串)
        - 七類之一                -> 原值
        - 其他字串                -> [FAIL] 操作失敗
      comment 未填               -> ""
      submitter_id 未填          -> ""     (同一 submitter 可重複評分，各自成列)
                    |
                    v
  [8] id = COALESCE(MAX(id),0) + 1  -> INSERT INTO Feedback  (hotdata)
                    |
                    v
  [9] Cognee remember(回饋本文) + HydraDB (Feedback)-[:refers_to]->(TutorialVersion)
      記憶層失敗 -> 記 warning、UI 標「圖譜未同步」，不回滾已寫的列（showme §17）
                    |
                    v
              回傳 feedback_id
```

七類 `feedback_category`（來自 `erm.dbml`）：`指示不清楚` / `缺少資訊` / `UI 與 Tutorial 不一致` / `Tutorial 太長` / `Tutorial 沒有解決問題` / `缺少自己的使用情境` / `其他`。

### 3.2 Review 決策樹（REFINE / KEEP）

`review_all()` 逐篇掃 `status = published` 的 Tutorial（`retired` 不進 Review）。

```
for each Tutorial where status = 'published':
        |
        v
  is_possibly_outdated == true ?
        |
        +-- yes --> KEEP（last_action = KEEP，current_version 不變，旗標保持 true）
        |            理由：等 Release UPDATE 先做完（showme §7.4）
        | no
        v
  以 current_version 為範圍，用 hotdata 算三個數字：
     avg          = AVG(rating)      只算 current_version
     count        = COUNT(*)         只算 current_version
     max_same_cat = MAX(同一 feedback_category 的筆數)，排除空字串
        |
        v
  should_refine(avg, count, max_same_cat)
     = (avg is not None) and avg < 3.5 and count >= 3 and max_same_cat >= 2
        |
        +-- False --> KEEP（last_action = KEEP）
        |             涵蓋：0 筆 / 1 筆 / 2 筆 / avg == 3.5 / avg 4.0 / 三筆不同 category
        | True
        v
  REFINE：
     (a) LLM 讀「舊五欄 + current_version 的回饋」-> 產新五欄 + reason（JSON）
     (b) 五欄缺任一 -> 操作失敗，本篇完全不動（與 CREATE 同一成功邊界，showme §9）
     (c) INSERT TutorialVersion(tutorial_id, vN+1, 五欄, reason, supersedes_version=vN, created_at)
     (d) UPDATE Tutorial SET current_version = vN+1, last_action = 'REFINE'
     (e) 重寫 tutorials/<slug>.md（用新五欄）
     (f) Cognee remember(新版本) + HydraDB (vN+1)-[:supersedes]->(vN)
        |
        v
  回傳 [{tutorial_id, action, from_version, to_version, reason}]
```

**邊界（規格沒有 Example，列為實作決定）：**
- `count == 0` 時 `avg` 為 `None` → KEEP（不得把 0 筆當成 avg 0 而誤觸 REFINE）。
- `feedback_category = ""` 不算 recurring complaint（空字串不是類別）。
- 分母為 0 的指標回 `0.0`，UI 顯示 `—`。

### 3.3 版本鏈：v1 → v2 是快照，不是就地修改

```
 Tutorial (tutorial_id=1)                      REFINE 前            REFINE 後
 ├─ status                                     published            published
 ├─ current_version  ─────────────┐            v1                   v2
 ├─ last_action                   │            CREATE               REFINE
 ├─ is_possibly_outdated          │            false                false
 └─ path = tutorials/cancel-order.md           （檔案內容 = v1）    （檔案內容 = v2）
                                  │
                                  v
 TutorialVersion
   (1, v1)  title/problem/prerequisites/steps/expected_outcome
            reason = ""            supersedes_version = ""      <-- 原樣保留，永不改寫
              ^
              | supersedes
              |
   (1, v2)  title/problem/prerequisites/expected_outcome 沿用
            steps = Step 3 補上定位說明
            reason = "Repeated feedback indicates Step 3 lacks context."
            supersedes_version = v1        created_at = now()

 Feedback
   id 1..10  -> (1, v1)   avg 2.9   <-- REFINE 的證據，留著，不搬版本
   id 11..15 -> (1, v2)   avg 4.4   <-- Review 之後才種，下欄均分改看這批

 注意：avg_rating「只算 current_version」。REFINE 當下 v2 還沒有回饋，
 均分會是「無資料」；要看到 2.9 --> 4.4 必須匯入 v2 回饋（§5 步驟 7，demo 安排）。
```

### 3.4 Streamlit 三區畫面（Phase 4 新增的部分標 `*`）

```
+------------------------------+-------------------------------------------+
| 左：假裝進資料               | 中：Agent 產出                             |
|  [餵下一張票]                |  這張：deflected / 轉真人                   |
|  [貼 changelog]              |  教學：tutorials/cancel-order.md            |
|  顧客：「我要取消訂單」       |  ------------------------------------------|
|                              | *[Feedback 表單]                           |
|                              | *  rating      ( ) 1 ( ) 2 ( ) 3 ( ) 4 ( ) 5|
|                              | *  category    [指示不清楚        v]        |
|                              | *  comment     [____________________]       |
|                              | *  submitter   [alice@example.com___]       |
|                              | *  [送出]  -> 成功：顯示 feedback_id        |
|                              | *           -> 失敗：紅字「操作失敗」        |
|                              | *------------------------------------------|
|                              | *[Review]  -> REFINE：顯示 v1 -> v2 與 reason|
|                              | *           -> KEEP：顯示「本輪 KEEP」       |
+------------------------------+-------------------------------------------+
| 下：評審拍照區（只讀，不算門檻）                                           |
| *  deflection rate  0.50   平均 rating 2.9   重放率 0.50   覆蓋 0.50      |
| *  +----------------------------------------------------------------+    |
| *  |                                             avg_rating ___/‾‾‾ |    |
| *  |                            deflection ___/‾‾‾‾‾               |    |
| *  |  ___/‾‾‾‾                                                      |    |
| *  +----------------------------------------------------------------+    |
| *   x 軸 = snapshot 序號（每次餵票／Review／匯入回饋各存一點）             |
+---------------------------------------------------------------------------+
```

UI **只觸發、只展示**：表單只送 payload、按鈕只呼叫 `review_all()`，門檻判斷完全在 `app/agent/rules.py`（showme §13）。

---

## 4. 🖐️ 需要你手動做的事

| # | 🖐️ 手動 | 何時 | 指令／動作 | 為什麼不能自動 |
|---|---|---|---|---|
| M1 | 🖐️ 手動 匯入 v1 低分種子 | Phase 3 驗收後、demo 開始前 | `uv run python -m app.ingest.feedback --seed data/seed/feedback_seed.json` | 規格沒有「系統自己產生顧客評分」的行為；種子是 demo 資料策略（showme §11） |
| M2 | 🖐️ 手動 按一次「Review」 | demo 中，講到「它會自己檢討」時 | Streamlit 中欄 `Review` 按鈕（或 `uv run python -m app.agent.feedback_review`） | showme §7.4 明寫「demo 手動觸發，不規定週期」 |
| M3 | 🖐️ 手動 匯入 v2 高分種子 | Review 出現 v2 之後 | `uv run python -m app.ingest.feedback --seed data/seed/feedback_v2_seed.json` | **這是 demo 安排**：要讓評審看到 2.9 → 4.4，必須有人替新版打分。現場沒有真顧客 |
| M4 | 🖐️ 手動 在 Feedback 表單送一筆 rating = 6 | demo 講「不是什麼都收」時（可選） | 中欄表單填 6 → 送出 | 展示 `操作失敗` 的可見結果；自動化測試已覆蓋，現場是加分演出 |
| M5 | 🖐️ 手動 確認 `.state/metrics_history.json` 在 demo 前是乾淨的 | demo 開始前 | `rm -f .state/metrics_history.json`（要重跑一次完整故事時） | 曲線是累積檔；上一輪彩排的點會讓曲線起點不對 |
| M6 | 🖐️ 手動 截圖下欄 | 每個關鍵節點後 | 螢幕截圖 | 評審拍照區，網路掛掉時的備援證據 |

**M3 是刻意的 demo 安排，要在口頭說明時講清楚**：v2 的高分回饋是預先準備的劇本資料，不是系統自己生的。誠實講反而加分，不要讓評審自己發現。

---

## 5. 實作步驟

> **先對齊 Phase 0 已落地的骨架（2026-09-11 實查 `app/`）。** 其他 agent 已建立 `app/analytics/{sql,metrics,hotdata_client,db,local_db}.py`、`app/agent/{rules,feedback_review}.py`、`data/seed/feedback_seed.json`、`data/seed/feedback_v2_seed.json`。**以既有骨架的名稱為準**，本檔的程式碼只示範邏輯：
>
> | 本檔寫法 | 骨架實際名稱 | 怎麼辦 |
> |---|---|---|
> | `sql.AVG_RATING_CURRENT` | `sql.AVG_RATING_CURRENT_VERSION` | 用骨架的名字，不要改骨架 |
> | `metrics.deflection_rate()` | `metrics.deflection_rate(db)` | 指標函式吃一個 `db`（`app/analytics/db.py`），照骨架簽章傳入 |
> | `run_sql(...)` | `db.run_sql(...)` | 同上 |
> | 新建 `data/seed/feedback_seed.json` | **已存在**，avg 2.9 / 10 筆 / 全 `v1` | 直接用，不要覆蓋；步驟 3 只是說明它為什麼長這樣 |
> | 新建 `data/seed/feedback_v2_seed.json` | **已存在**，avg 4.4 / 5 筆 / 全 `v2` | 同上 |
> | `app/ingest/feedback.py` | 尚不存在 | 這是 Phase 4 真正要新增的檔案 |
>
> 骨架裡的 `app/agent/feedback_review.py`、`app/analytics/metrics.py` 目前是空殼／部分實作，Phase 4 的工作是把 §5 的邏輯填進去，不是另開新檔。

### 步驟 1 — `app/analytics/sql.py`：補 5 條 SQL

檔案：`app/analytics/sql.py`（Phase 0 已建立，這裡只追加常數）

```python
# --- Phase 4 追加 ---

# 1) deflection rate：open / resolved 不進分母
DEFLECTION_RATE = """
SELECT
  SUM(CASE WHEN status = 'deflected' THEN 1 ELSE 0 END)                 AS numerator,
  SUM(CASE WHEN status IN ('deflected', 'escalated') THEN 1 ELSE 0 END) AS denominator
FROM Ticket
"""

# 2) 重放解決率：SUM(replay_count) / deflected 票數
REPLAY_RATE = """
SELECT
  (SELECT COALESCE(SUM(replay_count), 0) FROM Workflow)              AS numerator,
  (SELECT COUNT(*) FROM Ticket WHERE status = 'deflected')           AS denominator
"""

# 3) 圖譜覆蓋：有 published Tutorial 的 UserProblem / 全部 UserProblem
COVERAGE = """
SELECT
  (SELECT COUNT(DISTINCT up.id)
     FROM UserProblem up
     JOIN Tutorial t ON t.user_problem_id = up.id AND t.status = 'published') AS numerator,
  (SELECT COUNT(*) FROM UserProblem)                                          AS denominator
"""

# 4) 某篇 Tutorial 的 current_version 平均分與筆數（只算 current_version）
AVG_RATING_CURRENT = """
SELECT t.tutorial_id,
       t.current_version,
       AVG(CAST(f.rating AS DOUBLE)) AS avg_rating,
       COUNT(*)                      AS feedback_count
FROM Tutorial t
JOIN Feedback f
  ON f.tutorial_id = t.tutorial_id
 AND f.tutorial_version = t.current_version
WHERE t.tutorial_id = {tutorial_id}
GROUP BY t.tutorial_id, t.current_version
"""

# 5) current_version 裡「同一 category 最多幾筆」（空字串不算 recurring complaint）
MAX_SAME_CATEGORY = """
SELECT f.feedback_category, COUNT(*) AS c
FROM Tutorial t
JOIN Feedback f
  ON f.tutorial_id = t.tutorial_id
 AND f.tutorial_version = t.current_version
WHERE t.tutorial_id = {tutorial_id}
  AND f.feedback_category <> ''
GROUP BY f.feedback_category
ORDER BY c DESC
LIMIT 1
"""

# 6) Review 掃描範圍
PUBLISHED_TUTORIALS = """
SELECT tutorial_id, path, status, current_version, is_possibly_outdated, is_obsolete, last_action
FROM Tutorial
WHERE status = 'published'
ORDER BY tutorial_id
"""
```

手動驗證（不改資料，安全）：

```bash
hotdata query "SELECT SUM(CASE WHEN status='deflected' THEN 1 ELSE 0 END) AS n, \
               SUM(CASE WHEN status IN ('deflected','escalated') THEN 1 ELSE 0 END) AS d FROM Ticket" -o json
```

預期輸出（Phase 3 之後）：`[{"n": 2, "d": 4}]` → 0.5。

### 步驟 2 — `app/ingest/feedback.py`：`collect_feedback()` 與七條驗證

檔案：`app/ingest/feedback.py`（新檔。若 Phase 0 已把寫入層放在別處，沿用該位置，函式簽章不變。）

```python
"""顧客 Feedback 寫入。對齊 docs/spec/features/收集Feedback.feature 的 7 條 Rule。"""
from app.errors import OperationFailed
from app.analytics.hotdata_client import run_sql
from app.memory import cognee_client, hydradb_client

CATEGORIES = (
    "指示不清楚", "缺少資訊", "UI 與 Tutorial 不一致",
    "Tutorial 太長", "Tutorial 沒有解決問題", "缺少自己的使用情境", "其他",
)


def collect_feedback(payload: dict) -> int:
    """成功回傳 feedback_id；任一條 Rule 不過即 raise OperationFailed，且一列都不寫。"""
    tutorial_id = payload.get("tutorial_id")
    timestamp = payload.get("timestamp")
    rating = payload.get("rating")

    # Rule 4：tutorial_id / rating / timestamp 必填（tutorial_version 可省，見下）
    if tutorial_id in (None, ""):
        raise OperationFailed("缺少 tutorial_id")
    if not timestamp:
        raise OperationFailed("缺少 timestamp")
    if rating is None:
        raise OperationFailed("缺少 rating")

    # Rule 1：rating 必須是 1..5 的整數（bool 是 int 的子類，要擋掉）
    if isinstance(rating, bool) or not isinstance(rating, int) or not (1 <= rating <= 5):
        raise OperationFailed(f"rating 不合法：{rating!r}")

    # Rule 6：未指定版本時綁 current_version；指定則用指定版
    version = payload.get("tutorial_version") or _current_version(tutorial_id)
    if not version or not _version_exists(tutorial_id, version):
        raise OperationFailed(f"找不到對應 TutorialVersion：{tutorial_id} {version!r}")

    # Rule 2：七類或空字串；Rule 3：comment 可空；Rule 7：submitter_id 可空
    category = payload.get("feedback_category") or ""
    if category and category not in CATEGORIES:
        raise OperationFailed(f"feedback_category 不合法：{category!r}")
    comment = payload.get("comment") or ""
    submitter = payload.get("submitter_id") or ""

    # Rule 5 + Rule 7：存進 Database，重複評分各自成列（不做 upsert、不做去重）
    new_id = _next_id()
    run_sql(
        "INSERT INTO Feedback "
        "(id, tutorial_id, tutorial_version, rating, feedback_category, comment, submitter_id, timestamp) "
        f"VALUES ({new_id}, {tutorial_id}, '{version}', {rating}, "
        f"'{category}', '{_esc(comment)}', '{submitter}', '{timestamp}')"
    )

    # 記憶層：失敗只記 warning，不回滾（showme §17 降級：ERM 仍寫 hotdata，圖譜事後補）
    try:
        cognee_client.remember(f"Feedback on tutorial {tutorial_id} {version}: "
                               f"rating={rating} category={category} comment={comment}")
        hydradb_client.write_edge("Feedback", new_id, "refers_to", "TutorialVersion",
                                  f"{tutorial_id}:{version}")
    except Exception as exc:  # noqa: BLE001 - demo 降級
        _warn(f"圖譜未同步：{exc}")

    return new_id
```

`_esc()` 至少要處理單引號（`'` → `''`）。Demo 範圍不接受任意使用者 SQL，但 comment 是自由文字，不跳脫會直接炸掉整條 INSERT。

種子匯入 CLI（同檔 `__main__`）：

```python
# python -m app.ingest.feedback --seed data/seed/feedback_seed.json
def main() -> None:
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True)
    args = ap.parse_args()
    rows = json.load(open(args.seed, encoding="utf-8"))
    ok = 0
    for row in rows:
        try:
            fid = collect_feedback(row)
            ok += 1
            print(f"  + Feedback {fid}: t{row['tutorial_id']} {row.get('tutorial_version','(current)')} "
                  f"rating={row['rating']} {row.get('feedback_category','')}")
        except OperationFailed as exc:
            print(f"  ! 略過：{exc}")
    print(f"匯入完成：{ok}/{len(rows)} 筆")
```

預期輸出：

```
  + Feedback 1: t1 v1 rating=2 指示不清楚
  ...
  + Feedback 10: t1 v1 rating=4 指示不清楚
匯入完成：10/10 筆
```

### 步驟 3 — `data/seed/feedback_seed.json`：v1 avg 2.9

檔案：`data/seed/feedback_seed.json`（**Phase 0 已建立，內容等價，不要覆蓋**；以下是它該長成的樣子與理由）。數字直接取自 `定期優化Tutorial.feature` Rule「過去結果會改變系統下一次的行為」的 Example（ratings `2,2,3,3,3,3,3,3,3,4` → 29/10 = **2.9**，全部 `指示不清楚` → recurring complaint 成立）。

```json
[
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 2, "feedback_category": "指示不清楚", "comment": "Step 3 很難懂。", "submitter_id": "alice@example.com", "timestamp": "2026-09-01T10:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 2, "feedback_category": "指示不清楚", "comment": "Cancel Order 按鈕在哪？", "submitter_id": "bob@example.com", "timestamp": "2026-09-01T11:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 3, "feedback_category": "指示不清楚", "comment": "這一步需要更多說明。", "submitter_id": "alice@example.com", "timestamp": "2026-09-02T10:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 3, "feedback_category": "指示不清楚", "comment": "Step 3 很難懂。", "submitter_id": "bob@example.com", "timestamp": "2026-09-02T11:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 3, "feedback_category": "指示不清楚", "comment": "Cancel Order 按鈕在哪？", "submitter_id": "alice@example.com", "timestamp": "2026-09-03T10:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 3, "feedback_category": "指示不清楚", "comment": "這一步需要更多說明。", "submitter_id": "bob@example.com", "timestamp": "2026-09-03T11:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 3, "feedback_category": "指示不清楚", "comment": "Step 3 很難懂。", "submitter_id": "alice@example.com", "timestamp": "2026-09-04T10:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 3, "feedback_category": "指示不清楚", "comment": "Cancel Order 按鈕在哪？", "submitter_id": "bob@example.com", "timestamp": "2026-09-04T11:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 3, "feedback_category": "指示不清楚", "comment": "這一步需要更多說明。", "submitter_id": "alice@example.com", "timestamp": "2026-09-05T10:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v1", "rating": 4, "feedback_category": "指示不清楚", "comment": "Step 3 很難懂。", "submitter_id": "bob@example.com", "timestamp": "2026-09-05T11:00:00Z"}
]
```

🖐️ 手動 匯入（M1）：

```bash
uv run python -m app.ingest.feedback --seed data/seed/feedback_seed.json
hotdata query "SELECT AVG(CAST(rating AS DOUBLE)) AS avg, COUNT(*) AS n FROM Feedback WHERE tutorial_id=1 AND tutorial_version='v1'" -o json
```

預期：`[{"avg": 2.9, "n": 10}]`。

### 步驟 4 — `app/agent/rules.py`：`should_refine()`

檔案：`app/agent/rules.py`（Phase 2 已有 CREATE 門檻，這裡追加）

```python
REFINE_AVG_THRESHOLD = 3.5
REFINE_MIN_COUNT = 3
REFINE_MIN_SAME_CATEGORY = 2


def should_refine(avg: float | None, count: int, max_same_category: int) -> bool:
    """三條件同時成立才 REFINE。avg 為 None（0 筆回饋）一律 False。

    對齊 定期優化Tutorial.feature：
      - avg 剛好 3.5 -> False（嚴格小於）
      - count 1 或 2 -> False
      - 三筆不同 category -> False（max_same_category = 1）
    """
    if avg is None:
        return False
    return (avg < REFINE_AVG_THRESHOLD
            and count >= REFINE_MIN_COUNT
            and max_same_category >= REFINE_MIN_SAME_CATEGORY)
```

臨界表（`tests/unit/test_review.py` 直接照抄）：

| avg | count | max_same_cat | 期望 | 來源 Example |
|---|---|---|---|---|
| 3.5 | 3 | 3 | False | 平均 rating 剛好等於 3.5 時動作為 KEEP |
| 3.49 | 3 | 2 | True | 三條件都成立時產生 Tutorial v2 |
| 2.0 | 2 | 2 | False | 平均 rating 小於 3.5 但只有 2 筆時動作為 KEEP |
| 2.0 | 1 | 1 | False | 只有 1 筆 Feedback 時動作為 KEEP |
| 2.67 | 3 | 1 | False | 三筆各為不同 category 時動作為 KEEP |
| 4.0 | 3 | 3 | False | 平均 rating 為 4.0 時動作為 KEEP |
| None | 0 | 0 | False | 實作決定（規格無 Example） |

### 步驟 5 — `app/agent/feedback_review.py`：`review_all()`

檔案：`app/agent/feedback_review.py`

```python
"""Periodic Feedback Review。對齊 showme §7.4 與 定期優化Tutorial.feature 的 10 條 Rule。"""
from datetime import datetime, timezone

from app.errors import OperationFailed
from app.analytics import metrics, sql
from app.analytics.hotdata_client import run_sql
from app.agent.rules import should_refine
from app.agent import llm            # Phase 2 建立的 llm_bedrock 呼叫封裝
from app.memory import cognee_client, hydradb_client

FIVE_FIELDS = ("title", "problem", "prerequisites", "steps", "expected_outcome")


def review_all() -> list[dict]:
    results = []
    for tut in run_sql(sql.PUBLISHED_TUTORIALS):
        results.append(_review_one(tut))
    return results


def _review_one(tut: dict) -> dict:
    tid, cur = tut["tutorial_id"], tut["current_version"]

    # Rule：is_possibly_outdated 為 true 本輪 KEEP（讓 Release UPDATE 先做）
    if tut.get("is_possibly_outdated"):
        return _keep(tid, cur, reason="is_possibly_outdated")

    avg, count = metrics.avg_rating(tid), metrics.feedback_count(tid)
    max_same = metrics.max_same_category(tid)

    if not should_refine(avg, count, max_same):
        return _keep(tid, cur, reason=f"avg={avg} count={count} same_cat={max_same}")

    old = _load_version(tid, cur)
    new = llm.refine_tutorial(old, _feedback_of(tid, cur))     # 見步驟 6

    missing = [f for f in FIVE_FIELDS if not (new.get(f) or "").strip()]
    if missing:
        raise OperationFailed(f"REFINE 產出缺欄位 {missing}，不寫半篇 Tutorial")

    nxt = f"v{int(cur.lstrip('v')) + 1}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    run_sql(  # (c) 新版本快照：reason、supersedes_version、created_at 必填
        "INSERT INTO TutorialVersion (tutorial_id, tutorial_version, title, problem, "
        "prerequisites, steps, expected_outcome, reason, supersedes_version, created_at) "
        f"VALUES ({tid}, '{nxt}', ...)"
    )
    run_sql(  # (d) Tutorial 指向新版；is_possibly_outdated 保持 false
        f"UPDATE Tutorial SET current_version = '{nxt}', last_action = 'REFINE' "
        f"WHERE tutorial_id = {tid}"
    )
    _write_markdown(tut["path"], new)                                     # (e)
    try:                                                                  # (f)
        cognee_client.remember(_markdown(new))
        hydradb_client.write_edge("TutorialVersion", f"{tid}:{nxt}",
                                  "supersedes", "TutorialVersion", f"{tid}:{cur}")
    except Exception as exc:  # noqa: BLE001
        _warn(f"圖譜未同步：{exc}")

    metrics.snapshot(event=f"REFINE t{tid} {cur}->{nxt}")
    return {"tutorial_id": tid, "action": "REFINE", "from_version": cur,
            "to_version": nxt, "reason": new["reason"]}


def _keep(tid: int, cur: str, reason: str) -> dict:
    run_sql(f"UPDATE Tutorial SET last_action = 'KEEP' WHERE tutorial_id = {tid}")
    return {"tutorial_id": tid, "action": "KEEP", "from_version": cur,
            "to_version": cur, "reason": reason}
```

**寫入順序不可換**：先驗五欄 → 再寫 TutorialVersion → 再改 Tutorial → 再寫檔 → 最後記憶層。任一步在「改 Tutorial」之前失敗，`current_version` 仍指向舊版，畫面不會出現半篇教學（showme §9、§14）。

CLI 入口（給 M2 與無頭驗收用）：

```bash
uv run python -m app.agent.feedback_review
```

預期輸出：

```
[REFINE] tutorial 1: v1 -> v2  reason=Repeated feedback indicates Step 3 lacks context.
         tutorials/cancel-order.md 已重寫
Review 完成：1 篇 REFINE、0 篇 KEEP
```

### 步驟 6 — REFINE 的 LLM prompt 範本

RocketRide 的 `llm_bedrock` 節點（查 `.rocketride/schema/llm_bedrock.json`）**只有一個 Pipe 參數 `profile`**（模型選擇，例如 `anthropic_claude-sonnet-4-5`），外加該 profile 的 `region` / `accessKey` / `secretKey`；提示詞不是節點參數，而是走 lane：`questions` 進、`answers` 出。所以 prompt 由我們組好後送進 `questions`。

```
你是技術文件編輯。以下是一篇客服自助教學的目前版本，以及顧客對這一版的回饋。
請只針對回饋指出的問題改寫，不要重寫整篇、不要新增回饋沒有提到的步驟、不要改變步驟數量。

[current version v{N}]
title: {title}
problem: {problem}
prerequisites: {prerequisites}
steps: {steps}
expected_outcome: {expected_outcome}

[feedback on v{N}]（avg={avg}，共 {count} 筆）
- rating=2 category=指示不清楚 comment=Step 3 很難懂。
- rating=3 category=指示不清楚 comment=Cancel Order 按鈕在哪？
- rating=3 category=指示不清楚 comment=這一步需要更多說明。
...

[recurring complaint] 指示不清楚（{max_same} 筆）

只輸出一個 JSON 物件，不要 markdown 圍欄、不要任何其他文字：
{"title": "...", "problem": "...", "prerequisites": "...", "steps": "...",
 "expected_outcome": "...", "reason": "一句英文，說明為什麼產生這一版"}
```

回傳處理：`json.loads`（先剝掉可能的 ```json 圍欄）→ 檢查五欄非空 → 缺一即 `OperationFailed`。`reason` 缺漏時補預設字串，**不**算失敗（`reason` 在 ERM 是可空欄，只有五欄是必填）。

對照規格 Example，v2 的 Step 3 應該長成：

```
3. On the order details page, locate the Cancel Order button beside the order status
   and click "Cancel Order". This starts cancellation for that order.
```

單元測試用 fake LLM 直接回這串，不呼叫真模型（測的是流程與版本鏈，不是模型品質）。

### 步驟 7 — `data/seed/feedback_v2_seed.json`（🖐️ demo 安排）

檔案：`data/seed/feedback_v2_seed.json`（**Phase 0 已建立，內容等價，不要覆蓋**）。ratings `4,4,4,5,5` → 22/5 = **4.4**，category 全部 `其他`（避免再次觸發 REFINE：avg 4.4 已經擋住，category 一致也無妨）。數字同樣取自規格 Example。

```json
[
  {"tutorial_id": 1, "tutorial_version": "v2", "rating": 4, "feedback_category": "其他", "comment": "", "submitter_id": "alice@example.com", "timestamp": "2026-09-08T10:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v2", "rating": 4, "feedback_category": "其他", "comment": "", "submitter_id": "bob@example.com", "timestamp": "2026-09-08T11:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v2", "rating": 4, "feedback_category": "其他", "comment": "", "submitter_id": "alice@example.com", "timestamp": "2026-09-09T10:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v2", "rating": 5, "feedback_category": "其他", "comment": "", "submitter_id": "bob@example.com", "timestamp": "2026-09-09T11:00:00Z"},
  {"tutorial_id": 1, "tutorial_version": "v2", "rating": 5, "feedback_category": "其他", "comment": "", "submitter_id": "alice@example.com", "timestamp": "2026-09-10T10:00:00Z"}
]
```

🖐️ 手動 匯入（M3，**必須在 Review 產生 v2 之後**，否則 `v2` 不存在 → 每列都 `操作失敗`）：

```bash
uv run python -m app.ingest.feedback --seed data/seed/feedback_v2_seed.json
```

預期：`匯入完成：5/5 筆`，下欄平均 rating 變 4.4。

> **這是 demo 安排，不是系統行為。** 現場沒有真顧客會對新版打分，所以用劇本資料替代。口頭說明時要講明白。

### 步驟 8 — `app/analytics/metrics.py`：三條指標 + avg_rating + snapshot

檔案：`app/analytics/metrics.py`

```python
"""學習指標。全部由 hotdata 算，不落欄（showme §12）。"""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.analytics import sql
from app.analytics.hotdata_client import run_sql

HISTORY = Path(".state/metrics_history.json")   # 曲線用，不是業務表


def _ratio(row: dict) -> float:
    n, d = row.get("numerator") or 0, row.get("denominator") or 0
    return round(n / d, 4) if d else 0.0         # 分母 0 -> 0.0（實作決定）


def deflection_rate() -> float:
    return _ratio(run_sql(sql.DEFLECTION_RATE)[0])


def replay_rate() -> float:
    return _ratio(run_sql(sql.REPLAY_RATE)[0])


def coverage() -> float:
    return _ratio(run_sql(sql.COVERAGE)[0])


def avg_rating(tutorial_id: int) -> float | None:
    rows = run_sql(sql.AVG_RATING_CURRENT.format(tutorial_id=tutorial_id))
    return round(float(rows[0]["avg_rating"]), 2) if rows else None   # 0 筆 -> None


def feedback_count(tutorial_id: int) -> int:
    rows = run_sql(sql.AVG_RATING_CURRENT.format(tutorial_id=tutorial_id))
    return int(rows[0]["feedback_count"]) if rows else 0


def max_same_category(tutorial_id: int) -> int:
    rows = run_sql(sql.MAX_SAME_CATEGORY.format(tutorial_id=tutorial_id))
    return int(rows[0]["c"]) if rows else 0


def snapshot(event: str = "", tutorial_id: int = 1) -> dict:
    """存一個點供曲線累積。append-only，不落表。"""
    point = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "event": event,
        "deflection_rate": deflection_rate(),
        "replay_rate": replay_rate(),
        "coverage": coverage(),
        "avg_rating": avg_rating(tutorial_id),
    }
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    history.append(point)
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2))
    return point
```

`snapshot()` 的呼叫點（各 phase 都只呼叫，不自己算）：餵票後（Phase 3）、REFINE 後（本 phase 步驟 5）、匯入回饋後（步驟 2 CLI 結尾）、Release 處理後（Phase 5）。

### 步驟 9 — Streamlit：中欄表單＋Review 按鈕、下欄曲線

檔案：`app/demo/streamlit_app.py`（Phase 0 已建立三區骨架，這裡填中欄下半與下欄）

```python
# --- 中欄：Feedback 表單 ---
with mid:
    st.subheader("顧客回饋")
    with st.form("feedback_form", clear_on_submit=True):
        rating = st.radio("rating", [1, 2, 3, 4, 5], index=2, horizontal=True)
        category = st.selectbox("category", [""] + list(CATEGORIES))
        comment = st.text_input("comment")
        submitter = st.text_input("submitter", value="alice@example.com")
        if st.form_submit_button("送出"):
            try:
                fid = collect_feedback({
                    "tutorial_id": 1, "rating": rating,          # 不填版本 -> 綁 current_version
                    "feedback_category": category, "comment": comment,
                    "submitter_id": submitter, "timestamp": _now_iso(),
                })
                st.success(f"已收到 Feedback #{fid}")
                metrics.snapshot(event="feedback")
            except OperationFailed as exc:
                st.error(f"操作失敗：{exc}")

    if st.button("Review", type="primary"):                       # 🖐️ 手動 M2
        for r in review_all():
            if r["action"] == "REFINE":
                st.success(f"REFINE：tutorial {r['tutorial_id']} {r['from_version']} -> "
                           f"{r['to_version']}｜{r['reason']}")
            else:
                st.info(f"KEEP：tutorial {r['tutorial_id']}（{r['reason']}）")
        st.rerun()

# --- 下欄：四個數字 + 曲線 ---
with bottom:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("deflection rate", f"{metrics.deflection_rate():.2f}")
    avg = metrics.avg_rating(1)
    c2.metric("平均 rating（current_version）", f"{avg:.1f}" if avg is not None else "—")
    c3.metric("重放解決率", f"{metrics.replay_rate():.2f}")
    c4.metric("圖譜覆蓋", f"{metrics.coverage():.2f}")

    history = _load_history()      # .state/metrics_history.json
    if history:
        df = pd.DataFrame(history)[["deflection_rate", "avg_rating", "replay_rate", "coverage"]]
        st.line_chart(df)          # x 軸 = snapshot 序號
        st.caption("每次餵票／送出回饋／Review／匯入種子各存一個點")
```

啟動：

```bash
uv run streamlit run app/demo/streamlit_app.py
```

`avg_rating` 與另外三條的尺度不同（1–5 vs 0–1）。同圖兩軸在 `st.line_chart` 做不到，Phase 4 的做法是**畫兩張**：`st.line_chart(df[["deflection_rate","replay_rate","coverage"]])` 與 `st.line_chart(df[["avg_rating"]])` 上下排。這符合「兩條曲線」的畫面需求，也不需要額外繪圖套件。

### 步驟 10 — 測試

```bash
uv run pytest tests/unit/test_feedback.py tests/unit/test_review.py tests/unit/test_metrics.py -q
```

| 檔案 | 測什麼 | 對齊 |
|---|---|---|
| `tests/unit/test_feedback.py` | rating 0/1/5/6/缺；category 七類／未填／非法；comment 空；缺 tutorial_id／timestamp；v9 不存在；未指定版本綁 current_version；指定版本綁指定版；同一 submitter 兩列 | 收集Feedback 7 Rule、20 Example |
| `tests/unit/test_review.py` | `should_refine` 臨界表 7 列；`review_all` REFINE 路徑（fake LLM）、KEEP 路徑、`is_possibly_outdated` KEEP、五欄缺一 `OperationFailed` | 定期優化Tutorial 10 Rule |
| `tests/unit/test_metrics.py` | deflection 2/4=0.5、replay 2/4=0.5、coverage 1/2=0.5、分母 0 回 0.0、avg 只算 current_version（v1 2.9 不污染 v2 4.4）、snapshot 追加一點 | 展示學習指標 3 Rule + 定期優化 Rule 2 |

Fake LLM 與 fake `run_sql` 用 `monkeypatch`，不連外部服務；單元測試要能離線跑完。

---

## 6. 驗收清單（對齊 3 份 .feature 的 20 條 Rule）

### 6.1 `收集Feedback.feature`（7 Rule）

- [ ] R1 rating 必須為 1 到 5 的整數：rating=1 成功、rating=5 成功、rating=0 操作失敗、rating=6 操作失敗、未填 rating 操作失敗
- [ ] R2 feedback_category 允許六類與「其他」，未填存空字串：`指示不清楚` 成功、`其他` 成功、未填存 `""`
- [ ] R3 comment 可空，未填存空字串：三種 comment 內容皆成功、未填存 `""`
- [ ] R4 Feedback 必須包含 tutorial_id、tutorial_version、rating、timestamp：四欄齊全成功、缺 tutorial_id 操作失敗、缺 timestamp 操作失敗
- [ ] R5 Feedback 存進 Database：成功後 `SELECT * FROM Feedback` 看得到 id 與各欄
- [ ] R6 Feedback 參照 TutorialVersion：`v9` 操作失敗、未指定版本綁 `current_version`、指定版本綁指定版
- [ ] R7 submitter_id 可空，同一 submitter 重複評分各自成列：未填成功存 `""`、alice 第二次評分成為 id=2 新列（不覆蓋 id=1）

### 6.2 `定期優化Tutorial.feature`（10 Rule）

- [ ] R1 平均 rating 小於 3.5 才進入 REFINE：avg 剛好 3.5 → KEEP
- [ ] R2 平均 rating 只計算 current_version 的 Feedback：current_version=v2、v2 avg > 3.5 時不受 v1 低分影響 → KEEP
- [ ] R3 current_version 的 Feedback 數量 ≥ 3 才 REFINE：avg < 3.5 但只有 2 筆 → KEEP
- [ ] R4 同一 feedback_category 至少 2 筆才算 recurring complaints：3 筆各不同 category → KEEP
- [ ] R5 不得因單一低分立刻修改：1 筆 → KEEP
- [ ] R6 觀察累積 pattern，不看日曆天數：2 筆 → KEEP（程式裡**沒有**任何日期差計算）
- [ ] R7 三條件成立 → REFINE 並發布新版本：產生 `(1, v2)`，`supersedes_version = v1`、`reason` 有值、`current_version = v2`、`last_action = REFINE`、`is_possibly_outdated = false`
- [ ] R8 Feedback 表現良好時 KEEP：avg 4.0、3 筆、同 category 3 筆 → KEEP，`current_version` 不變、`last_action = KEEP`
- [ ] R9 過去結果會改變系統下一次的行為：v1 avg 2.9（10 筆）、v2 avg 4.4（5 筆），Review 對 v2 的判定是 KEEP
- [ ] R10 `is_possibly_outdated = true` 本輪 KEEP：三條件都成立仍 KEEP，旗標保持 `true`、`current_version` 不變

### 6.3 `展示學習指標.feature`（3 Rule）

- [ ] R1 deflection rate = deflected / (deflected + escalated)：2 deflected + 2 escalated + 1 open → 2/4 = 0.5（open 不進分母）
- [ ] R2 重放解決率 = SUM(replay_count) / deflected 票數：replay_count 總和 2、deflected 4 → 0.5
- [ ] R3 圖譜覆蓋 = 有 published Tutorial 的 UserProblem / UserProblem 總數：1/2 = 0.5

### 6.4 端到端（demo 走一遍）

- [ ] 🖐️ M1 匯入 `feedback_seed.json` → `SELECT AVG(rating)` 回 2.9、10 筆
- [ ] 下欄顯示：deflection 0.50、平均 rating 2.9、重放率 0.50、覆蓋 0.50
- [ ] 🖐️ M2 按一次「Review」→ 畫面出現 `REFINE：tutorial 1 v1 -> v2`
- [ ] `SELECT * FROM TutorialVersion WHERE tutorial_id=1` 回兩列；v2 的 `supersedes_version = v1`、`reason` 非空、`created_at` 非空；v1 列**完全沒被改動**
- [ ] `SELECT current_version, last_action FROM Tutorial WHERE tutorial_id=1` → `v2 / REFINE`
- [ ] `diff` 或肉眼確認 `tutorials/cancel-order.md` 的 Step 3 已改變（多了 Cancel Order 按鈕的定位說明）
- [ ] Review 後下欄平均 rating 顯示 `—`（v2 尚無回饋，這是正確行為，不是 bug）
- [ ] 🖐️ M3 匯入 `feedback_v2_seed.json` → 下欄平均 rating 變 4.4，曲線折上去
- [ ] 再按一次「Review」→ `KEEP`（avg 4.4 > 3.5），`current_version` 仍是 v2、不會產生 v3
- [ ] `.state/metrics_history.json` 至少有 4 個點，`event` 欄看得出故事線
- [ ] 🖐️ M4（可選）表單送 rating=6 → 紅字「操作失敗」，`SELECT COUNT(*) FROM Feedback` 不變

---

## 7. 降級方案

| 風險 | 訊號 | 降級做法 | 誠實標示 |
|---|---|---|---|
| Bedrock / RocketRide 連不上 | `llm.refine_tutorial()` timeout 或 401 | 改走**本機模板改寫**：取 `steps` 中被抱怨最多的那一步（demo 固定 Step 3），在原句後面接一句定位說明；`reason` 寫 `"[模板] Repeated feedback indicates Step 3 lacks context."` | UI 在版本旁顯示標籤 `模板`；口頭說明「LLM 不通，改用本機模板，流程與門檻完全一樣」 |
| hotdata 不可用 | `run_sql` 連線失敗 | 同一批 SQL 打本機 SQLite（`.state/demo.db`），**表形狀仍是 9 表**，不新增第 10 表；`AVG(CAST(... AS DOUBLE))` 在 SQLite 改成 `AVG(rating * 1.0)` | 下欄加一行小字 `data source: sqlite (fallback)` |
| Cognee / HydraDB 未就緒 | `remember()` / `write_edge()` 丟例外 | 表照寫、檔照改，記憶層失敗只記 warning，**不回滾**；demo 後再補 remember（showme §17） | 中欄顯示 `圖譜未同步`；不要假裝圖譜有寫進去 |
| Review 產出五欄缺一 | `OperationFailed` | 本篇維持舊版（`current_version` 不變），畫面顯示「操作失敗，Tutorial 未變更」；可重按 Review 再試 | 這是規格要求的行為，不是降級，照實展示 |
| 曲線太平／看不出上升 | 下欄四個數字都不動 | 確認 `snapshot()` 有在餵票與 Review 後被呼叫；真的沒點時，先 `rm .state/metrics_history.json` 再照 demo 順序重跑一次（M5） | 不要手改 `metrics_history.json` 造假資料 |
| Streamlit 起不來 | port 佔用 / 套件衝突 | 全部改 CLI 走一遍：`python -m app.ingest.feedback` → `python -m app.agent.feedback_review` → `hotdata query` 三條指標，終端輸出就是證據 | 評審看終端也算數；畫面是加分不是必要 |

**模板改寫的具體規則**（避免現場臨時發明）：

```
輸入 steps：  ... 3. Click "Cancel Order". 4. ...
命中規則：    找出含有 Feature.name（"Cancel Order"）的那一步
輸出 steps：  ... 3. On the order details page, locate the Cancel Order button
                 beside the order status and click "Cancel Order". This starts
                 cancellation for that order. 4. ...
其餘四欄：    原樣沿用（title / problem / prerequisites / expected_outcome）
```

---

## 8. 交接給 Phase 5 的東西

| 交付 | 位置 | Phase 5（Release UPDATE / RETIRE）怎麼用 |
|---|---|---|
| `Tutorial 1` 已在 `v2` | hotdata `Tutorial` | UPDATE 要接在 v2 之後產 **v3**，`supersedes_version = v2`（不是 v1） |
| 版本鏈寫法 | `app/agent/feedback_review.py` 的 (c)(d)(e)(f) 順序 | UPDATE 照抄同一順序與同一成功邊界；差別只在 `last_action = UPDATE`、觸發來源是 `ReleaseFeatureChange` |
| `is_possibly_outdated` 的約定 | 本 phase 只**讀**，不寫 | Phase 5 比對到受影響時設 `true`；產出新版後設回 `false`。設為 `true` 期間 Review 自動 KEEP，兩條 pipeline 不會搶同一篇 |
| 「先 UPDATE 再 REFINE」 | 由旗標達成，無額外鎖 | Phase 5 不需要呼叫 Phase 4 的任何函式來讓路 |
| `metrics.snapshot(event=...)` | `app/analytics/metrics.py` | Release 處理完呼叫一次，曲線才會有「Release 之後」那一段 |
| `tutorials/cancel-order.md` 的寫檔函式 | `_write_markdown(path, five_fields)` | Step 3 diff 的「改後」內容由同一支函式產生，確保 diff 只有內容差異，沒有格式雜訊 |
| 三條指標 API | `deflection_rate()` / `replay_rate()` / `coverage()` / `avg_rating()` | 下欄不需要再改；Phase 5 只要讓資料變，數字就會動 |
| Feedback 寫入 API | `collect_feedback(payload)` | RETIRE 後該 Tutorial 不再 published，Review 掃不到；但既有 Feedback 列保留，不刪 |

**留給 Phase 5 的一個已知缺口**：Phase 4 的 `_review_one()` 在 `is_possibly_outdated = true` 時回 KEEP，但**沒有**把旗標清成 false（那是 UPDATE 的職責）。Phase 5 若忘記清旗標，該篇教學會永遠 KEEP、再也不會 REFINE。驗收時要一起檢查。

---

## 來源

**規格（真相來源）：**
- `docs/spec/features/收集Feedback.feature`（Feature 1、Rule 7、Example 20）
- `docs/spec/features/定期優化Tutorial.feature`（Feature 1、Rule 10、Example 10）
- `docs/spec/features/展示學習指標.feature`（Feature 1、Rule 3、Example 3）
- `docs/spec/erm.dbml`：`Feedback`（七類 category、AVG 只算 current_version、三條件門檻）、`Tutorial`（不變條件）、`TutorialVersion`（五欄必填、`supersedes_version` 只指同篇上一版）、`Workflow`（重放解決率公式）

**設計：**
- `docs/design/showme.md` §6 步驟 8／9／12、§7.4、§8、§9、§12、§13、§14、§16 切片 E、§17
- `docs/design/architecture.md` §1（demo 三區畫面）、§7（現場順序第 4 點）

**專案規則：**
- `CLAUDE.md`：門檻定案表、Demo 範例（v1 avg 2.9 → v2 avg 4.4、`alice@example.com` / `bob@example.com`）、Scope guardrail、`docs/plan/` 四目錄流程

**環境實查（2026-09-11）：**
- `.rocketride/schema/llm_bedrock.json`：Pipe 參數只有 `profile`（＋該 profile 的 `region` / `accessKey` / `secretKey`），提示詞走 `lanes: questions -> answers`；profile enum 含 `anthropic_claude-sonnet-4-5`、`anthropic_claude-haiku-4-5` 等 22 項
- `hotdata query --help`（CLI v0.33.0）：`hotdata query "<SQL>" -o {table,json,csv}`，`--dialect` 預設 `hotsql`
- `app/` 實查：Phase 0 已建立 `analytics/{sql,metrics,hotdata_client,db,local_db}.py`、`agent/{rules,feedback_review,analysis,create_tutorial,realtime,release_update,rocketride_client}.py`、`ingest/{seed,bitext,poll}.py`、`memory/{cognee_client,hydradb_client}.py`、`muscle/rote_client.py`；`data/seed/feedback_seed.json`（avg 2.9）與 `data/seed/feedback_v2_seed.json`（avg 4.4）已存在；`app/ingest/feedback.py` 尚不存在

**未當來源：** `docs/spec/draft/design-draft.md` 的 Copilot 敘事、`docs/plan/dev-prompts/phase0829-1.md`（屬於另一個專案）。
