# Phase 1 — 種子建圖

> ⚠️ **這只是 hackathon 作品，不要過度設計。** 8 小時內能 demo 迴圈就好：先讓它能跑，再談漂亮。
> 能用最簡單的方式做到驗收條件就停手；不加規格沒寫的欄位、不做抽象層、不為「日後擴充」多寫一行。
> 遇到「這樣夠不夠好」的猶豫時，選最短路徑，並在 report 標記「hackathon 簡化」即可。

## 現況更新（2026-09-11）

- **Phase 0 已實作並驗證**：`uv run pytest -q` 35 passed；Bitext 真實下載（`data/raw/`），`data/seed/bitext_seed.json` 6 筆、`data/script/demo_tickets.json` 9 筆、`feedback_seed.json` 10 筆（avg 2.9）、`feedback_v2_seed.json` 5 筆（avg 4.4）；Streamlit 空殼可啟動；`.env`／`.state/`／`data/raw/` 已 git-ignore。
- **環境事實**：hotdata CLI 已登入（workspace `Hackathon_space`，尚無本專案 database）；`rote whoami` 正常；Cognee 伺服器可用（沿用本機記憶插件的 server，專案另開 dataset）；**沒有** HydraDB 直連憑證與 LLM 金鑰（`.env` 只有 `ROCKETRIDE_*`）。
- **已知偏差（以骨架命名為準）**：hotdata instant database 是 schema-on-load，9 表 DDL 主要用於 SQLite 降級；RocketRide `db_hydradb` 節點沒有 Cypher action，多跳查詢由 `app/memory/hydradb_client.py` 自己做；phase 專屬 SQL 放在該 phase 模組，不回改 `app/analytics/sql.py`；Streamlit 各區以 `app/demo/ui_<x>.py` 的 `render(db)` 提供，最後統一接進 `streamlit_app.py`。
- **共用介面**：`app/agent/llm.py: complete_json(prompt, schema_hint) -> dict`（無金鑰時 raise `LLMUnavailable`，呼叫端用模板降級）；`app/muscle/rote_client.py: on_deflected(db, ticket_id, user_problem_id) -> dict`。

- **對應設計：** `docs/design/showme.md` §16 切片 A（種子建圖）、§6 步驟 1（建構知識圖譜）、§5.3–5.5、§9、§10、§11、§17、§18
- **對應規格：** `docs/spec/features/建構知識圖譜.feature`（5 條 Rule、5 個 Example）、`docs/spec/erm.dbml`（Ticket / UserProblem / Feature）
- **前置：** Phase 0 驗收通過（條件見下）
- **預估時間：** 60–75 分鐘（其中 🖐️ 手動開帳號／建庫約 20 分鐘，可與寫碼並行）
- **產出：** `app/ingest/bitext.py`、`app/ingest/seed.py`、`app/analytics/sql.py`（9 表欄位定義與查詢 SQL）、`app/analytics/hotdata_client.py`、`app/analytics/local_db.py`、`app/memory/cognee_client.py`、`app/memory/hydradb_client.py`、`tests/integration/test_seed.py`、hotdata 上一個 instant database（3 張表有資料）、Cognee dataset `main` 有 6 筆記憶、HydraDB 有 12 個節點與 6 條 `asks_about` 邊

> 本檔是**待做計畫**，不是完工報告。文中所有目錄、函式、指令在撰寫當下**尚未實作**。

---

## 1. 目標與結束時可看到

把 Bitext 的 6 張歷史票（3 個 topic × 2 張）一次匯入，讓三個儲存層同時有東西，成為後面所有切片的地基。

結束時可以親眼看到（三條煙測，§6 有指令）：

| # | 看到什麼 | 在哪裡看 |
|---|---|---|
| 1 | `SELECT COUNT(*) ... WHERE status = 'resolved'` 回 **6** | hotdata CLI |
| 2 | `MATCH (t:Ticket)-[:asks_about]->(f:Feature {name:'Cancel Order'}) RETURN count(t)` 回 **2** | HydraDB Cypher |
| 3 | recall `"how to cancel order"` 回得出含 cancel_order 解法的內容 | Cognee `/api/v1/search` |

再加三個結構數字：`user_problem` 3 列（`cancel_order` / `track_refund` / `change_shipping_address`）、`feature` 3 列、`ticket` 6 列。

**這個 phase 不做：** 不判斷 CREATE 門檻（Ticket ≥ 3 是 Phase 3 的事）、不寫 Tutorial、不接 RocketRide pipeline、不算學習指標。種子刻意**只放每 topic 2 張**，讓門檻差一張，demo 現場餵第 3 張才觸發 CREATE（showme §11）。

---

## 2. 在整體迴圈的位置

```text
 Phase 0        Phase 1        Phase 2        Phase 3        Phase 4        Phase 5
 骨架/環境  →   種子建圖   →   餵票轉真人  →  CREATE v1  →  deflect+Rote →  指標/REFINE/Release
   uv init      ▲▲▲▲▲▲▲▲      第1-2張票      第3張湊滿      第4-5張票       曲線+UPDATE
   app/ 空殼    ★本 phase★    → escalated    → v1 published  replay_count    2.9 → 4.4
   .env 就位    6票/3問題/3功能
                （showme §16 切片 A）（切片 B）   （切片 C）     （切片 D）    （切片 E/F）

 依賴方向： Phase 0 ──> [Phase 1] ──> Phase 2 ──> Phase 3 ──> Phase 4 ──> Phase 5
                        三個儲存層都有資料之後，後面每一片才有東西可讀
```

---

## 3. 資料流

### 3.1 種子匯入三路並列

```text
                  data/seed/bitext_seed.json   （Phase 0 產出，6 列）
                  { content, category, intent, response,
                    customer_ref, feature_name, created_at }
                                |
                                v
                  +---------------------------+
                  |  app/ingest/seed.py       |
                  |  1. load_seed()           |
                  |  2. ensure_feature()      |  同名重用
                  |  3. ensure_user_problem() |  同 topic 重用
                  |  4. build_ticket()        |  status=resolved
                  +------------+--------------+
                               |
        +----------------------+----------------------+
        |                      |                      |
        v                      v                      v
  hotdata（真相）        Cognee（建圖）          HydraDB（記憶）
  run_sql / load_rows    remember(text,kind,meta) upsert_node / upsert_edge
        |                      |                      |
  ticket        6 列     每票 1 次 remember      Ticket 節點 x6
  user_problem  3 列     text = instruction      UserProblem 節點 x3
  feature       3 列            + response       Feature 節點 x3
        |                       + intent         asks_about 邊 x6
        |                      |                      |
        v                      v                      v
  降級：local_db.py       降級：跳過，事後補      降級：跳過，事後補
  （SQLite，同介面）      （--graph-only 重跑）   （--graph-only 重跑）
```

**寫入順序固定：** hotdata 先寫成功，才寫 Cognee / HydraDB。理由：hotdata 是 9 表即時列的家（showme §9），圖譜掉了可以事後補；表掉了整條迴圈死。

### 3.2 這個 phase 建出來的圖譜

```text
        (Feature {name:"Cancel Order", status:"active"})
              ^            ^                 ^
              |            |                 |  :asks_about
   :asks_about|            |:asks_about      |
              |            |                 |
   (Ticket {id:1})   (Ticket {id:2})    (UserProblem {topic:"cancel_order"})
    alice@...         bob@...            （本 phase 只建節點，
    resolved          resolved             不建 UserProblem→Feature 邊）


   同樣形狀再兩組：
     Track Refund            <- Ticket 3, 4   <- UserProblem track_refund
     Change Shipping Address <- Ticket 5, 6   <- UserProblem change_shipping_address

   本 phase 只用五種邊裡的 asks_about（showme §10）：
     asks_about   Ticket  -> Feature          ← 本 phase 唯一
     explains     Tutorial-> Feature          ← Phase 3
     refers_to    Feedback-> TutorialVersion  ← Phase 5
     changes      Release -> Feature          ← Phase 5
     supersedes   TutorialVersion -> 上一版    ← Phase 5
```

節點數 12（6 Ticket + 3 UserProblem + 3 Feature）、邊數 6。這就是「圖譜覆蓋」指標的分母起點：3 個 UserProblem、0 個有 published Tutorial → 覆蓋 0/3。

---

## 4. 🖐️ 需要你手動做的事

四項，做完才跑得動 §5。第 4 項可以延到 Phase 3 再做。

| 項目 | 指令／網址 | 怎麼確認完成 | 寫進 `.env` 的變數 |
|---|---|---|---|
| **🖐️ 手動 1：hotdata 建 instant database ＋ 宣告 9 表** | 見下方 4.1 | `hotdata databases tables list` 列出 9 張表 | `HOTDATA_API_KEY`、`HOTDATA_DATABASE`（db id）、`HOTDATA_CATALOG=support`、`HOTDATA_SCHEMA=public` |
| **🖐️ 手動 2：HydraDB instance 連線字串** | HydraDB dashboard（黑客松主辦提供的入口）建一個 database + collection，複製 API key | 用 §6 煙測 3 跑 `RETURN 1` 不報錯 | `HYDRADB_URI`、`HYDRADB_API_KEY`、`HYDRADB_DATABASE`、`HYDRADB_COLLECTION=default` |
| **🖐️ 手動 3：Cognee server 可用（二選一）** | 見下方 4.2 | `curl $COGNEE_BASE_URL/api/v1/datasets` 回 200 | `COGNEE_BASE_URL`、`COGNEE_API_KEY`、`COGNEE_DATASET=main` |
| **🖐️ 手動 4（可延後到 Phase 3）：RocketRide app 骨架** | 見下方 4.3 | app 裡有 `tool_cognee` 與 `db_hydradb` 兩個節點且參數填完 | 已有 `ROCKETRIDE_URI` / `ROCKETRIDE_APIKEY`（dev） |

### 4.1 🖐️ 手動 1：hotdata

已裝 `hotdata` v0.33.0，`~/.hotdata/session.json` 存在，所以多半已登入。

```bash
export PATH="$PATH:$HOME/.hotdata/cli"

# (a) 確認登入
hotdata auth status

# (b) 建 instant database（catalog 名必須 [a-z_][a-z0-9_]*，全域唯一）
hotdata databases create \
  --name "support-tutorial-generator" \
  --catalog support \
  --schema public

# 輸出會給 database id，記下來 → HOTDATA_DATABASE
hotdata databases use <db-id>

# (c) 宣告 9 張表並給 key（有 key 才能用 upsert 模式重複載入）
hotdata databases tables add ticket                 --key id
hotdata databases tables add user_problem           --key id
hotdata databases tables add feature                --key id
hotdata databases tables add tutorial               --key tutorial_id
hotdata databases tables add tutorial_version       --key tutorial_id --key tutorial_version
hotdata databases tables add feedback               --key id
hotdata databases tables add release_note           --key id
hotdata databases tables add release_feature_change --key id
hotdata databases tables add workflow               --key id

# (d) 確認
hotdata databases tables list
```

**要知道的兩件事（實測 `--help` 得到，不是猜的）：**

1. hotdata 的 instant database 是 **schema-on-load**：`tables add` 只宣告名字、key 與 on-disk layout（`--sorted-by` / `--partition-by`），**沒有 `--column type` 這種 DDL 旗標**。欄位是第一次 `databases load` 時由檔案內容定型。所以「9 表 DDL」在本專案的落點是 `app/analytics/sql.py` 裡的欄位定義（供 SQLite 降級直接 `CREATE TABLE`，供 hotdata 用來補齊每一列的所有欄位），**不是**打到 hotdata 的 `CREATE TABLE`。
2. 表名用 snake_case，查詢時要寫**三段式** `catalog.schema.table`：`SELECT ... FROM support.public.ticket`。ERM 的 `Release` 表在 SQL 裡叫 `release_note`（`release` 在多數方言是保留字），映射寫在 `sql.py` 的 `TABLES` dict。**這不是第 10 張表，只是識別字改名。**

### 4.2 🖐️ 手動 3：Cognee（本機 docker 或 Cloud，二選一）

**選項 A — 本機 docker（推薦，不用等帳號）**

```bash
# 先準備一個給 cognee 用的 env 檔（不要用專案的 .env，避免把 ROCKETRIDE key 灌進容器）
cat > ~/cognee.env <<'EOF'
LLM_API_KEY=<你的 OpenAI/Anthropic key>
EOF

docker run --env-file ~/cognee.env -p 8000:8000 --rm -it cognee/cognee:main
```

確認：`curl http://localhost:8000/api/v1/datasets` 回 200。
`.env` 填 `COGNEE_BASE_URL=http://localhost:8000`、`COGNEE_API_KEY=`（本機可留空）。

**選項 B — Cognee Cloud**

到 <https://platform.cognee.ai> 開 instance，拿 tenant URL（形如 `https://<tenant>.aws.cognee.ai`）與 API key。
`.env` 填 `COGNEE_BASE_URL=https://<tenant>.aws.cognee.ai`、`COGNEE_API_KEY=<key>`。呼叫時帶 header `X-Api-Key`。

兩個選項的 REST 路徑相同，都要有 `/api/v1` 前綴：`POST /api/v1/remember`（等同 add + cognify）、`POST /api/v1/search`（recall）、`GET /api/v1/datasets`。

> `cognee` Python 套件本機**尚未安裝**，本 phase **不裝**：`cognee_client.py` 直接打 REST（`httpx`），少一個相依、也和 RocketRide `tool_cognee` 走同一條 HTTP 介面。

### 4.3 🖐️ 手動 4：RocketRide app 骨架（可延後）

Phase 1 的 `seed.py` 是本機 Python 腳本，**不經過 RocketRide**，所以本項不擋 Phase 1 驗收。

要先開的話：**在 RocketRide web console 手動建**（用 dev 連線 `ROCKETRIDE_URI` / `ROCKETRIDE_APIKEY` 登入的那個環境，例如 staging 站台），建一個 app，拉 `tool_cognee` 與 `db_hydradb` 兩個節點，參數照 `.rocketride/schema/` 實際欄位填：

- `tool_cognee`：`base_url`、`api_key`、`dataset=main`、`allow_dataset_override=false`、`search_type=GRAPH_COMPLETION_DECOMPOSITION`、`top_k=15`、`request_timeout=120`
- `db_hydradb`：`profile=default`，內含 `api_key`、`database`、`collection=default`、`max_results=10`

也可以改用 API 建（同樣**只能**用 dev 連線）。**絕對不要**用 `ROCKETRIDE_DEPLOY_URI` / `ROCKETRIDE_DEPLOY_APIKEY` 做這件事——那兩把 key 只准用於 deploy（`.env` 註解明寫）。

---

## 5. 實作步驟

依序做。每步跑完再進下一步。

### 步驟 0：確認 Phase 0 已交出骨架

```bash
cd /Users/linjunting/AWS-Hackathon
ls app/config.py app/errors.py app/analytics app/memory app/ingest data/seed/bitext_seed.json
uv run python -c "from app.config import Settings; print(Settings())"
python3 -c "import json;d=json.load(open('data/seed/bitext_seed.json'));print(len(d), sorted({r['intent'] for r in d}))"
```

預期：`6 ['cancel_order', 'change_shipping_address', 'track_refund']`。
若 `bitext_seed.json` 不存在或不是 6 列 → 回頭催 Phase 0，不要自己另起爐灶。

### 步驟 1：`app/analytics/sql.py` — 9 表欄位定義 ＋ 查詢 SQL

**檔案：** `app/analytics/sql.py`

**要點：**

- `TABLES: dict[str, str]` — ERM 表名 → SQL 表名（`"Release": "release_note"`，其餘 snake_case）。
- `COLUMNS: dict[str, list[str]]` — 9 表每張的欄位順序，**逐字照 `docs/spec/erm.dbml`**，不加不減。這份就是「DDL」的單一來源：SQLite 降級用它組 `CREATE TABLE`，hotdata 上傳前用它補齊每列的所有欄位（沒值就填 `None`／空字串），確保 schema-on-load 一次定型正確。
- `DDL: dict[str, str]` — 由 `COLUMNS` 產生的 `CREATE TABLE IF NOT EXISTS`（型別只用 `TEXT` / `INTEGER` / `REAL`，對應 erm.dbml 的 string / int / bool、float）。
- `KEYS: dict[str, list[str]]` — 與 §4.1 的 `tables add --key` 一致，`load_rows` 的 upsert 用它。
- 本 phase 需要的查詢常數：

```python
COUNT_RESOLVED_TICKETS = "SELECT COUNT(*) AS c FROM {t} WHERE status = 'resolved'"
COUNT_USER_PROBLEMS    = "SELECT COUNT(*) AS c FROM {t}"
SELECT_FEATURE_BY_NAME = "SELECT id, name, status FROM {t} WHERE name = :name"
SELECT_UP_BY_TOPIC     = "SELECT id, topic, feature_id FROM {t} WHERE topic = :topic"
```

`{t}` 由 client 依 `HOTDATA_CATALOG.HOTDATA_SCHEMA.<table>`（hotdata）或裸表名（SQLite）填入，這樣同一份 SQL 兩邊共用。

**預期輸出：** `uv run python -c "from app.analytics.sql import COLUMNS; print(len(COLUMNS), sum(map(len, COLUMNS.values())))"` → 9 張表、欄位總數與 erm.dbml 相符。

### 步驟 2：`app/analytics/hotdata_client.py`

**檔案：** `app/analytics/hotdata_client.py`

**要點：**

- `run_sql(sql: str, params: dict | None = None) -> list[dict]`（共用契約）
  - 參數用 Python 端安全插值（`:name` → 轉義後字串），因為走 CLI 沒有 bind 參數。
  - 實作：`subprocess.run(["hotdata", "query", sql, "-d", settings.hotdata_database, "-o", "json"])`，解析 stdout JSON。
  - exit code 2 = 查詢還在跑 → 用 `hotdata query status <id>` 輪詢，最多重試 N 次；其餘非 0 → raise `OperationFailed`。
- `load_rows(table: str, rows: list[dict], mode: str = "upsert") -> None`（**在共用契約之外新增，必要**）
  - 原因（實測 `--help`）：hotdata CLI 的寫入入口是 `hotdata databases load`，而 `hotdata query` 的非 `hotsql` 方言明寫 read-only，用 `INSERT` 灌資料不是 CLI 的正規路徑。所以**讀走 `run_sql`、寫走 `load_rows`**。
  - 實作：把 rows 依 `sql.COLUMNS[table]` 補齊欄位 → 寫成暫存 JSON → `hotdata databases load --catalog $HOTDATA_CATALOG --schema public --table <t> --file <tmp.json> --mode upsert --key <k>`（多欄 key 就重複 `--key`）。
  - upsert 讓 `seed.py` **可以重跑而不產生重複列**（冪等）。
- 兩個函式失敗都丟 `app.errors.OperationFailed`（規格的「操作失敗」）。

**指令 / 預期輸出：**

```bash
export PATH="$PATH:$HOME/.hotdata/cli"
uv run python -c "
from app.analytics.hotdata_client import run_sql
print(run_sql('SELECT 1 AS ok'))"
# → [{'ok': 1}]
```

### 步驟 3：`app/analytics/local_db.py`（降級用，先寫好）

**檔案：** `app/analytics/local_db.py`

**要點：** 同介面 `run_sql(sql, params)` / `load_rows(table, rows, mode)`，底層 `sqlite3`，DB 檔 `data/local.db`（加進 `.gitignore`）。第一次呼叫時跑 `sql.DDL` 建 9 表。`load_rows` 的 upsert 用 `INSERT ... ON CONFLICT(<key>) DO UPDATE SET ...`。

**選擇邏輯**（放在 `app/analytics/__init__.py` 或 `hotdata_client` 旁的 `get_db()`）：`Settings.use_local_db` 為真、或 hotdata 前置檢查（`hotdata auth status`）失敗 → 回 `local_db`，並在 log 印一行明確的降級訊息。

**預期輸出：** `HOTDATA_FALLBACK=1 uv run python -c "from app.analytics.local_db import run_sql; print(run_sql('SELECT 1 AS ok'))"` → `[{'ok': 1}]`。

### 步驟 4：`app/memory/cognee_client.py`

**檔案：** `app/memory/cognee_client.py`

**要點：**

- `remember(text: str, kind: str, meta: dict) -> None`
  - `POST {COGNEE_BASE_URL}/api/v1/remember`，header `X-Api-Key`（有 key 才帶）、`Content-Type: application/json`。
  - body 帶文字與 `datasetName`/`dataset`（固定 `COGNEE_DATASET`，預設 `main`；**不開 per-call override**，對齊 showme §5.4 與 `tool_cognee` 的 `allow_dataset_override=false`）。
  - `kind` / `meta`（如 `{"ticket_id": 1, "intent": "cancel_order"}`）序列化後**併進文字尾端**當可檢索的上下文，同時原樣留在 payload；Cognee 的 remember = Add + Cognify，餵純文字即可。
  - 逾時 120 秒（對齊 `tool_cognee.request_timeout` 預設）。
- `recall(query: str) -> list[dict]`
  - `POST {COGNEE_BASE_URL}/api/v1/search`，body `{"query": ..., "search_type": "GRAPH_COMPLETION"}`（`tool_cognee` 的預設 `GRAPH_COMPLETION_DECOMPOSITION` 留作參數預設值，recall 允許覆寫）。
- 兩者連不上 → raise `OperationFailed`；**呼叫端（`seed.py`）決定要不要吞掉**（見步驟 6 的降級旗標）。

**預期輸出：** `uv run python -c "from app.memory.cognee_client import remember; remember('smoke test', 'smoke', {})"` 不報錯。

### 步驟 5：`app/memory/hydradb_client.py`

**檔案：** `app/memory/hydradb_client.py`

**要點：**

- `upsert_node(label: str, key: dict, props: dict) -> None` — 組 `MERGE (n:<label> {<key>}) SET n += $props` 送出。
- `upsert_edge(from_: tuple, rel: str, to: tuple) -> None` — `MATCH (a:<L1> {..}), (b:<L2> {..}) MERGE (a)-[:<rel>]->(b)`。
- `cypher(query: str, params: dict | None = None) -> list[dict]` — 直送 OpenCypher。
- **邊白名單**：模組常數 `ALLOWED_RELS = {"asks_about", "explains", "refers_to", "changes", "supersedes"}`，`upsert_edge` 收到白名單外的 rel 直接 raise `OperationFailed`。理由：showme §10 只允許這五種，且 label/rel 不能參數化（要字串插進 Cypher），白名單同時是防注入。
- label 也白名單：`Ticket / UserProblem / Feature / Tutorial / TutorialVersion / Feedback / Release / Workflow`。
- 連線：`HYDRADB_URI` + `HYDRADB_API_KEY` + `HYDRADB_DATABASE` + `HYDRADB_COLLECTION`。
  **⚠️ 未實測：** HydraDB 的實際 HTTP 介面（路徑、body 形狀）要在 🖐️ 手動 2 拿到 dashboard／文件後才能確定。把 transport 收在單一私有函式 `_post(payload)` 裡，當天只改那一個函式。RocketRide 的 `db_hydradb` 節點另外提供 `store` / `recall_memory` 兩個 agent 工具，Phase 3 接 pipeline 時用，本 phase 走直連。

**預期輸出：** `uv run python -c "from app.memory.hydradb_client import cypher; print(cypher('RETURN 1 AS ok'))"` → `[{'ok': 1}]`。

### 步驟 6：`app/ingest/bitext.py`

**檔案：** `app/ingest/bitext.py`

**要點：**

```python
SEED_INTENTS = ("cancel_order", "track_refund", "change_shipping_address")

INTENT_TO_FEATURE = {
    "cancel_order": "Cancel Order",
    "track_refund": "Track Refund",
    "change_shipping_address": "Change Shipping Address",
}

def load_seed(path="data/seed/bitext_seed.json") -> list[dict]: ...
    # 讀 Phase 0 產出的 JSON；驗證每列有 content/category/intent/response/
    # customer_ref/feature_name/created_at 七個欄位（＝.feature 的匯入列欄位）
    # 缺欄位 → OperationFailed

def fetch_bitext(limit_per_intent: int = 2) -> list[dict]: ...
    # 只在 bitext_seed.json 不存在時才用；抓 HuggingFace
    # bitext/Bitext-customer-support-llm-chatbot-training-dataset，
    # 篩 SEED_INTENTS，每 intent 取前 limit_per_intent 列，
    # 補 feature_name = INTENT_TO_FEATURE[intent]、customer_ref、created_at
```

`feature_name` 以 seed JSON 內的值優先，缺才用 `INTENT_TO_FEATURE` 補；兩者衝突時以 JSON 為準並 log 一行。`fetch_bitext` 需要網路，黑客松當天不一定通——所以 seed JSON 是 Phase 0 的產出，**Phase 1 的正常路徑只讀檔**。

### 步驟 7：`app/ingest/seed.py` — 主程式

**檔案：** `app/ingest/seed.py`，入口 `uv run python -m app.ingest.seed`

**流程（與 §3.1 圖一致）：**

```python
def main(graph_only: bool = False, db_only: bool = False) -> Summary:
    rows = bitext.load_seed()                      # 6 列，依 created_at 排序後穩定編號

    features: dict[str, int] = {}                  # name  -> feature_id
    problems: dict[str, int] = {}                  # topic -> user_problem_id
    tickets: list[dict] = []

    for i, row in enumerate(rows, start=1):
        fid = ensure_feature(features, row["feature_name"])      # 同名重用 → Rule 4
        pid = ensure_user_problem(problems, row["intent"], fid)  # 同 topic 重用 → Rule 2,3
        tickets.append(build_ticket(i, row, fid, pid))           # Rule 1

    if not graph_only:
        db.load_rows("Feature",     feature_rows(features))
        db.load_rows("UserProblem", problem_rows(problems))
        db.load_rows("Ticket",      tickets)                     # 先寫 hotdata

    if not db_only:
        for t, row in zip(tickets, rows):
            remember_ticket(t, row)                              # Cognee，每票一次
            push_graph(t, problems, features, row)               # HydraDB 節點 + asks_about

    return summarize(...)
```

**各段要點：**

- **`ensure_feature(cache, name)`** — `cache` 命中就回舊 id；否則先問 `run_sql(SELECT_FEATURE_BY_NAME)`（讓重跑也能重用既有列），都沒有才配新 id（`max(existing)+1`，第一次跑就是 1、2、3）。`status` 固定 `"active"`（`.feature` Example 的 Then 表就是 active）。
- **`ensure_user_problem(cache, topic, fid)`** — 同上，`topic = row["intent"]`（Rule 2），`feature_id = fid`。
- **`build_ticket(i, row, fid, pid)`** — 逐欄對齊 `建構知識圖譜.feature` 第一個 Example 的 Then 表：

  | 欄位 | 值 |
  |---|---|
  | `id` | 迴圈序號（1..6，依 `created_at` 排序） |
  | `content` | `row["content"]`（Bitext `instruction`） |
  | `resolution_steps` | `row["response"]`（**必有值**） |
  | `category` | `row["category"]` |
  | `customer_ref` | `row["customer_ref"]` |
  | `feature_id` / `user_problem_id` | 上面兩步的 id |
  | `status` | 固定 `"resolved"` |
  | `created_at` | `row["created_at"]`（**必填**） |
  | `deflected_tutorial_id` / `deflected_tutorial_version` / `reopened_from_ticket_id` | `None`（歷史票沒有這三個） |

- **`remember_ticket`** — 文字 = `f"{instruction}\n\n{response}\n\nintent: {intent}"`，`kind="ticket"`，`meta={"ticket_id":…, "intent":…, "feature":…, "customer_ref":…}`。一票一次呼叫（showme §5.5）。
- **`push_graph`** — 三個 `upsert_node`（`Ticket` key `{id}`、`UserProblem` key `{topic}`、`Feature` key `{name}`）＋ 一條 `upsert_edge(("Ticket", {"id": tid}), "asks_about", ("Feature", {"name": fname}))`。**本 phase 不寫其他四種邊。**
- **旗標：** `--graph-only`（只補 Cognee/HydraDB，給降級復原用）、`--db-only`（只寫 hotdata，圖譜層掛掉時用）。預設兩者都跑。
- **錯誤語意：** hotdata 寫入失敗 → `OperationFailed` 直接往上拋，整批不寫半套。Cognee/HydraDB 失敗 → 預設吞掉並印 `WARN: graph layer degraded, rerun with --graph-only`，**不讓圖譜拖垮資料層**（showme §17 的降級表就是這個意思）。

**指令與預期輸出：**

```bash
export PATH="$PATH:$HOME/.hotdata/cli"
uv run python -m app.ingest.seed
```

```text
seed: 6 tickets, 3 user problems, 3 features
  features:      Cancel Order(1), Track Refund(2), Change Shipping Address(3)
  user_problems: cancel_order(1), track_refund(2), change_shipping_address(3)
  hotdata:  ok (catalog=support)
  cognee:   ok (dataset=main, 6 remembered)
  hydradb:  ok (12 nodes, 6 asks_about edges)
```

再跑第二次，數字**完全一樣**（upsert 冪等），不會變成 12 張票。

### 步驟 8：`tests/integration/test_seed.py`

**檔案：** `tests/integration/test_seed.py`

**要點：** 用 `local_db`（SQLite，`tmp_path` 上的檔）跑 `seed.main(db_only=True)`，直接把 `.feature` 五個 Example 的 Then 表寫成斷言。Cognee / HydraDB 用 monkeypatch 假物件記錄呼叫次數與參數，不打真服務（真服務留給 §6 煙測）。

測試函式（對照 §6 的 Rule 表）：

```python
def test_匯入後票單為_resolved_且有解法與時間()      # Rule 1
def test_user_problem_topic_等於_intent()            # Rule 2
def test_同一_topic_重用同一列_user_problem()         # Rule 3
def test_同名_feature_重用同一列()                    # Rule 4
def test_不同_intent_建立不同_user_problem_與_feature() # Rule 5
def test_重跑不產生重複列()                           # 冪等（非規格 Rule，工程需求）
def test_每張票呼叫一次_cognee_remember()             # 圖譜層契約
def test_只寫_asks_about_邊()                        # 邊白名單
```

前五個測試各自只餵對應 Example 的那幾列（Rule 1/2 餵 1 列，Rule 3/4 餵 2 列同 intent，Rule 5 餵 cancel_order + track_refund 各 1 列），Then 表逐欄比對，**不要用整包 6 列去湊**——Example 是什麼就斷言什麼。

**指令：** `uv run pytest tests/integration/test_seed.py -v` → 8 passed。

---

## 6. 驗收清單

### 6.1 規格對齊（`docs/spec/features/建構知識圖譜.feature` 5 條 Rule）

| # | Rule（規格原文摘要） | 實作落點 | 測試 |
|---|---|---|---|
| 1 | 匯入後 Ticket `status = resolved` 且 `resolution_steps`、`created_at` 有值 | `seed.build_ticket()` | `test_匯入後票單為_resolved_且有解法與時間` |
| 2 | `UserProblem.topic` 等於 `intent` | `seed.ensure_user_problem()` | `test_user_problem_topic_等於_intent` |
| 3 | 同一 topic 重用同一列 UserProblem | `ensure_user_problem()` 的 cache ＋ `SELECT_UP_BY_TOPIC` 回查 | `test_同一_topic_重用同一列_user_problem` |
| 4 | `Feature.name` 等於 `feature_name`，同名重用同一列 | `seed.ensure_feature()` ＋ `bitext.INTENT_TO_FEATURE` | `test_同名_feature_重用同一列` |
| 5 | 不同 intent 建立不同 UserProblem 與 Feature | 上兩個 ensure 函式的 key 分離 | `test_不同_intent_建立不同_user_problem_與_feature` |

### 6.2 Checklist

**環境（🖐️ 手動）**

- [ ] `hotdata auth status` 已登入
- [ ] instant database 建好，`hotdata databases tables list` 列出 9 張表
- [ ] `.env` 有 `HOTDATA_API_KEY` / `HOTDATA_DATABASE` / `HOTDATA_CATALOG` / `HOTDATA_SCHEMA`
- [ ] `.env` 有 `HYDRADB_URI` / `HYDRADB_API_KEY` / `HYDRADB_DATABASE` / `HYDRADB_COLLECTION`
- [ ] `.env` 有 `COGNEE_BASE_URL` / `COGNEE_API_KEY` / `COGNEE_DATASET=main`，且 `curl $COGNEE_BASE_URL/api/v1/datasets` 回 200
- [ ] `.env` **沒有**被 commit（`git status` 看不到它）

**程式**

- [ ] `app/analytics/sql.py` 9 表欄位逐字對齊 `erm.dbml`，且 `Release → release_note` 的映射有寫在 `TABLES`
- [ ] `app/analytics/hotdata_client.py` 的 `run_sql` / `load_rows` 失敗都丟 `OperationFailed`
- [ ] `app/analytics/local_db.py` 與 hotdata_client **同介面**
- [ ] `app/memory/hydradb_client.py` 的 rel 白名單只有五種
- [ ] `app/memory/cognee_client.py` dataset 固定 `main`，沒有 per-call override
- [ ] `uv run pytest tests/integration/test_seed.py -v` 全綠
- [ ] `uv run python -m app.ingest.seed` 跑**兩次**，第二次數字不變（冪等）
- [ ] 沒有新增第 10 張業務表

**三條煙測**

```bash
# 煙測 1 — hotdata：resolved 票 = 6
export PATH="$PATH:$HOME/.hotdata/cli"
hotdata query "SELECT COUNT(*) AS c FROM support.public.ticket WHERE status = 'resolved'" -o json
# 預期 [{"c":6}]

hotdata query "SELECT topic, COUNT(*) AS c FROM support.public.ticket t
               JOIN support.public.user_problem u ON t.user_problem_id = u.id
               GROUP BY topic ORDER BY topic" -o json
# 預期 cancel_order 2、change_shipping_address 2、track_refund 2

# 煙測 2 — HydraDB：Cancel Order 有 2 張票問它
uv run python -c "
from app.memory.hydradb_client import cypher
print(cypher(\"MATCH (t:Ticket)-[:asks_about]->(f:Feature {name:'Cancel Order'}) RETURN count(t) AS c\"))"
# 預期 [{'c': 2}]

# 煙測 3 — Cognee：recall 回得出 cancel_order 的解法
uv run python -c "
from app.memory.cognee_client import recall
r = recall('how to cancel order')
print(len(r)); print(str(r)[:400])"
# 預期：非空，且內容出現 Orders / Cancel Order 之類字樣
```

- [ ] 煙測 1 回 6
- [ ] 煙測 2 回 2
- [ ] 煙測 3 有結果

---

## 7. 降級方案

對齊 showme §17 的風險表。**降級要在 log 印出來，demo 時口頭講得出現在跑哪一條。**

| 狀況 | 判斷訊號 | 怎麼降 | 之後怎麼補 |
|---|---|---|---|
| Cognee 起不來 / remember 逾時 | `POST /api/v1/remember` 非 2xx 或連線被拒 | `seed.py` 印 `WARN: cognee degraded`，繼續寫 hotdata + HydraDB | 服務恢復後 `uv run python -m app.ingest.seed --graph-only` |
| HydraDB 連不上 / Cypher 失敗 | `_post` 非 2xx 或 `RETURN 1` 煙測失敗 | 同上，印 `WARN: hydradb degraded`；demo 先秀 hotdata 的 SQL 覆蓋數字 | 同上 `--graph-only` |
| 兩個圖譜層都不通 | 上面兩條同時發生 | `--db-only` 跑完，9 表照常有資料，Phase 2–3 不受影響 | 同上 |
| **hotdata 不可用** | `hotdata auth status` 失敗、或 `run_sql('SELECT 1')` 失敗 | 切 `local_db`（SQLite `data/local.db`），**同一份 `sql.py`、同樣 9 表** | 服務恢復後把 SQLite 的列 dump 成 JSON，用 `load_rows` 灌回 hotdata |
| Bitext 抓不到 / seed JSON 缺 | `load_seed` 找不到檔或欄位不全 | 手寫 6 列 JSON（`.feature` Example 的三列已經是現成範本，補到每 topic 2 列） | — |
| RocketRide 沒開好 | — | **Phase 1 不需要**，直接跳過（見 §4.3） | Phase 3 再補 |

**不可降級的一條：** 9 表形狀。不管跑 hotdata 還是 SQLite，表就是 `erm.dbml` 的 9 張，不准為了方便多開一張。

---

## 8. 交接給 Phase 2 的東西

Phase 2（切片 B：餵票轉真人）開工時可以直接假設這些已存在：

**資料**

- hotdata（或 SQLite 降級）`ticket` 6 列全 `resolved`、`user_problem` 3 列、`feature` 3 列 `active`
- 三個 topic 各 **2** 張票 —— 差 1 張就滿 CREATE 門檻（≥3），Phase 2 餵第 1–2 張新票會 `escalated`，Phase 3 的第 3 張才觸發 CREATE
- Cognee dataset `main` 有 6 筆 ticket 記憶；HydraDB 12 節點 / 6 條 `asks_about`
- 圖譜覆蓋指標起點：0/3

**程式介面（Phase 2 直接 import，不要另寫一份）**

| 模組 | 給 Phase 2 用的東西 |
|---|---|
| `app/analytics/sql.py` | `TABLES` / `COLUMNS` / `KEYS` / `DDL`；新增輪詢 SQL 時加在這裡 |
| `app/analytics/hotdata_client.py` | `run_sql(sql, params)`、`load_rows(table, rows, mode)` |
| `app/analytics/local_db.py` | 同介面降級 |
| `app/memory/cognee_client.py` | `remember(text, kind, meta)`、`recall(query)` |
| `app/memory/hydradb_client.py` | `upsert_node` / `upsert_edge` / `cypher`＋rel 白名單 |
| `app/ingest/bitext.py` | `INTENT_TO_FEATURE`、`load_seed()` —— Phase 2 餵新票用同一份 intent→Feature 對應 |
| `app/errors.py` | `OperationFailed` = 規格的「操作失敗」 |

**已知待辦／風險（不是 open question，是要現場確認的事）**

1. HydraDB 的實際 HTTP 介面未實測，`hydradb_client._post` 是唯一要改的地方。
2. hotdata 的 `hotsql` 方言是否支援 `INSERT`，本 phase 沒有依賴它（寫入走 `databases load`）；若當天確認支援，可以簡化 `load_rows`，但**不急**。
3. `.env` 的 `ROCKETRIDE_DEPLOY_*` 在 Phase 1–4 都不該被讀到；`Settings` 若把它載進來，只能給 deploy 專用路徑用。

---

## 來源

**專案內**

- `docs/design/showme.md` §5.3–5.5、§6 步驟 1、§9、§10、§11、§16 切片 A、§17、§18
- `docs/spec/features/建構知識圖譜.feature`（5 Rule / 5 Example，全文）
- `docs/spec/erm.dbml`（Ticket / UserProblem / Feature 欄位與不變條件）
- `docs/客服自助教學生成器 — 系統架構規格.md`（五層職責；其中審核佇列、Slack、SLA 已被 Clarify 推翻）
- `CLAUDE.md`（門檻表、五層 stack 對應、deploy key 限制）
- `.rocketride/schema/tool_cognee.json` — `base_url` / `api_key`(`X-Api-Key`) / `dataset`(預設 `main`) / `allow_dataset_override`(預設 false) / `search_type`(預設 `GRAPH_COMPLETION_DECOMPOSITION`，另有 `GRAPH_COMPLETION`、`RAG_COMPLETION`、`CHUNKS`、`SUMMARIES`、`TEMPORAL`、`FEELING_LUCKY`) / `top_k`(15) / `request_timeout`(120)
- `.rocketride/schema/db_hydradb.json` — `profile=default` 下的 `api_key`(fallback `HYDRA_DB_API_KEY`) / `database` / `collection`(預設 `default`) / `max_results`(10)；節點工具為 store 與 recall_memory

**本機 CLI（實際 `--help` 輸出，v0.33.0）**

- `hotdata`：`auth` / `workspaces` / `databases` / `query` / `jobs` / `ingest` / `search` / `manage` / `support`
- `hotdata databases`：`list` / `create`(`--name` `--catalog` `--schema` `--table` `--expires-at` `--attach`) / `use` / `tables` / `load` / `query` / `results`
- `hotdata databases tables add`：`--key`（可重複，組合鍵）、`--key-determines`、`--sorted-by`、`--partition-by`、`--schema` —— **沒有欄位型別旗標，schema-on-load**
- `hotdata databases load`：`--catalog` `--table` `--file` `--url` `--mode replace|append|delete|update|upsert` `--key` `--format csv|json|parquet`
- `hotdata query`：`[SQL]` `-d/--database` `--dialect hotsql|duckdb|postgres|snowflake`（非 hotsql 方言 read-only）`-o table|json|csv`；exit code 0 成功 / 1 失敗 / 2 仍在跑 / 3 截斷預覽
- `hotdata ingest`：`create` / `sources add` / `schedule --next now`（沒有 `run` 動詞）

**官方文件（本次查證）**

- Cognee REST 與本機啟動：<https://docs.cognee.ai/api-reference/introduction> —— base URL `http://localhost:8000`（本機）或 `https://<tenant>.aws.cognee.ai`（Cloud）；header `X-Api-Key`；端點一律 `/api/v1` 前綴，含 `POST /api/v1/remember`、`POST /api/v1/search`、`POST /api/v1/add`、`POST /api/v1/cognify`、`GET /api/v1/datasets`；啟動指令 `docker run --env-file ./.env -p 8000:8000 --rm -it cognee/cognee:main`，`.env` 需要 `LLM_API_KEY`
- Cognee 資料流概念：<https://docs.cognee.ai/core-concepts/data-flows> —— `remember(data)` 不帶 `session_id` 寫入永久記憶、`recall(query)` 從快取或知識圖譜取回
- Cognee cognify Python API：<https://docs.cognee.ai/python-api/cognify>
- Bitext 資料集：<https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset>（CDLA-Sharing-1.0；欄位 instruction / category / intent / response）
- RocketRide 節點文件入口：<https://docs.rocketride.org>

**查不到 / 未驗證（照實記，當天補）**

- HydraDB 的直連 HTTP 介面規格：`.rocketride/schema/db_hydradb.json` 只描述 RocketRide 節點設定，沒有 REST 路徑；OpenCypher 多跳的說法來自黑客松指南。`hydradb_client._post` 需在 🖐️ 手動 2 之後確認。
