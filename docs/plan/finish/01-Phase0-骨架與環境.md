# Phase 0 — 骨架與環境

> ⚠️ **這只是 hackathon 作品，不要過度設計。** 8 小時內能 demo 迴圈就好：先讓它能跑，再談漂亮。
> 能用最簡單的方式做到驗收條件就停手；不加規格沒寫的欄位、不做抽象層、不為「日後擴充」多寫一行。
> 遇到「這樣夠不夠好」的猶豫時，選最短路徑，並在 report 標記「hackathon 簡化」即可。

## 現況更新（2026-09-11）

- **本 phase 已實作並驗證**（2026-09-11 14:20）：`uv run pytest -q` 35 passed；Bitext 真實下載；Streamlit 空殼可啟動；git 未 commit。
- **與本文件不同之處**：`test_metrics.py` 重放率案例改用 4 張 deflected（對齊 `展示學習指標.feature` Example 2/4）；`feedback_seed.json` 用 10 筆整數湊 avg 2.9；`HotdataClient` 依 CLI help 寫但未實跑，`execute()` 不回 lastrowid、`reset()` 未實作，Phase 1 補。
- **🖐️ 手動事項尚未做**：HydraDB 連線字串、Cognee 專案 dataset、LLM 金鑰、Snyk 安裝與 `snyk auth`。hotdata 與 rote 已登入。

- **對應設計：** `docs/design/showme.md` §5.2（規劃中的模組）、§16 切片 A 的前置、§17（當日風險與降級）
- **前置：** 無（本 phase 就是所有 phase 的前置）
- **預估時間：** 約 55 分鐘 — 🖐️ 手動帳號／CLI 登入 20 分鐘（可與寫碼並行）＋ 骨架與程式 35 分鐘
- **狀態：** 計畫（尚未實作）。本檔所有目錄、檔名、程式片段都是「要建立的東西」，不是已存在的東西。

## 產出檔案清單

```
pyproject.toml                      uv 專案定義（新建）
.python-version                     uv python pin（新建）
.gitignore                          補 .venv/ .state/ data/raw/ __pycache__/（修改）
app/__init__.py
app/config.py                       Settings dataclass ← .env
app/errors.py                       OperationFailed
app/analytics/__init__.py
app/analytics/sql.py                9 表 DDL ＋ 所有查詢 SQL（本 phase 寫滿）
app/analytics/hotdata_client.py     run_sql(sql, params) → list[dict]（本 phase 寫滿）
app/analytics/local_db.py           SQLite 降級，同介面（本 phase 寫滿）
app/analytics/metrics.py            三條學習指標（本 phase 寫滿）
app/agent/__init__.py
app/agent/rules.py                  門檻純函式（本 phase 寫滿）
app/agent/realtime.py               空殼 → Phase 2
app/agent/analysis.py               空殼 → Phase 2
app/agent/create_tutorial.py        空殼 → Phase 2
app/agent/feedback_review.py        空殼 → Phase 4
app/agent/release_update.py         空殼 → Phase 5
app/agent/rocketride_client.py      空殼 → Phase 2
app/agent/pipeline.json             空殼 → Phase 2
app/memory/__init__.py
app/memory/cognee_client.py         空殼 → Phase 1
app/memory/hydradb_client.py        空殼 → Phase 1
app/ingest/__init__.py
app/ingest/bitext.py                下載＋篩選 Bitext（本 phase 寫滿）
app/ingest/seed.py                  空殼 → Phase 1
app/ingest/poll.py                  cursor 讀寫（本 phase 寫最小可用）
app/muscle/__init__.py
app/muscle/rote_client.py           空殼 → Phase 3
app/demo/__init__.py
app/demo/streamlit_app.py           三區空殼（本 phase 寫滿骨架）
data/seed/bitext_seed.json          由 bitext.py 產生
data/script/demo_tickets.json       由 bitext.py 產生
data/script/changelog.json          手寫一則更名 Release Note
tutorials/.gitkeep                  之後放產出的 .md
tests/unit/test_rules.py            門檻臨界測試（本 phase 寫滿）
tests/integration/.gitkeep          → Phase 1 起
.state/                             cursor 目錄（git-ignore）
```

---

## 1. 目標與結束時可看到

**目標：** 讓後面五個 phase 只需要「填內容」，不需要再決定檔案放哪、函式叫什麼、SQL 長什麼樣。門檻與 9 表 schema 在本 phase 一次釘死，之後任何 phase 都不得再改。

結束時（不需要任何外部服務就能跑）：

1. `uv run pytest` 全綠 — 門檻函式對齊 `.feature` 的臨界 Example（2 張不算／3 張算、avg 3.5 是 KEEP、count 2 不算、同 category 1 不算、content+created_at 重複不新增）。
2. `uv run python -m app.ingest.bitext` 產出 `data/seed/bitext_seed.json`（3 topic × 2 張 resolved）與 `data/script/demo_tickets.json`（現場劇本）。
3. `uv run python -m app.analytics.local_db --init` 在 `.state/demo.sqlite3` 建出 9 張表（同一份 `app/analytics/sql.py` 的 DDL）。
4. `uv run streamlit run app/demo/streamlit_app.py` 打得開，左／中／下三區都在，下區從 local_db 讀出三條指標（此時全是 0）。
5. 🖐️ 手動清單全部打勾，`.env` 補齊，`hotdata auth status` 與 `rote whoami` 都認得出身分。

**本 phase 不做：** 不呼叫 Cognee／HydraDB／RocketRide／Rote 的任何 API，不 deploy，不寫 pipeline 內容，不產 Tutorial。

---

## 2. 在整體迴圈的位置

```text
 ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
 │ Phase 0  │→ │ Phase 1  │→ │ Phase 2  │→ │ Phase 3  │→ │ Phase 4  │→ │ Phase 5  │
 │ 骨架環境 │  │ 種子建圖 │  │ 餵票分析 │  │ deflect  │  │ Feedback │  │ Release  │
 │          │  │          │  │ ＋CREATE │  │ ＋ Rote  │  │ REFINE   │  │ UPDATE   │
 │          │  │          │  │          │  │          │  │ /KEEP    │  │ /RETIRE  │
 └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
     ▲              │             │              │             │             │
   【你在這】    Cognee /      RocketRide      Rote Play    hotdata AVG   HydraDB 多跳
                 HydraDB       ＋ LLM 五欄     捕捉/重放     ＋ 新版本     ＋ 新版本
                 showme §16 A  §16 B,C         §16 D        §16 E         §16 F

 Phase 0 沒有對外呼叫；它交出的是：9 表 DDL、門檻函式、run_sql 介面、Bitext 種子資料。
 後面每一個 phase 都只 import 這些東西，不重新發明。
```

---

## 3. 模組與資料流

### 3.1 目錄樹（本 phase 要建出來的形狀）

```text
AWS-Hackathon/
├── pyproject.toml            uv 專案；deps 見 §5 步驟 2
├── .python-version           3.12（見 §5 步驟 2 的版本說明）
├── .env                      🖐️ 手動補；git-ignored
├── .state/                   git-ignored：last_checked.json、demo.sqlite3
├── app/
│   ├── config.py             .env → Settings（唯一讀 os.environ 的地方）
│   ├── errors.py             OperationFailed ＝ 規格的「操作失敗」
│   ├── analytics/            ← hotdata 層（Phase 0 寫滿）
│   │   ├── sql.py            9 表 DDL ＋ 輪詢／統計／指標 SQL（唯一 SQL 來源）
│   │   ├── hotdata_client.py run_sql(sql, params) -> list[dict]（走 hotdata CLI）
│   │   ├── local_db.py       run_sql 同介面，走 sqlite3（降級／離線）
│   │   └── metrics.py        deflection_rate / replay_rate / coverage
│   ├── agent/                ← RocketRide 層
│   │   ├── rules.py          純函式門檻（無 I/O、無 import 其他 app 模組）
│   │   ├── realtime.py       Phase 2：輪詢新票 → deflect/escalate
│   │   ├── analysis.py       Phase 2：Ticket Analysis
│   │   ├── create_tutorial.py Phase 2：CREATE
│   │   ├── feedback_review.py Phase 4：REFINE / KEEP
│   │   ├── release_update.py  Phase 5：UPDATE / RETIRE
│   │   ├── rocketride_client.py Phase 2：HTTP 呼叫 agent_rocketride
│   │   └── pipeline.json      Phase 2：pipeline 定義
│   ├── memory/               ← Cognee / HydraDB 層（Phase 1）
│   │   ├── cognee_client.py  remember() / recall()
│   │   └── hydradb_client.py store() / cypher()
│   ├── ingest/
│   │   ├── bitext.py         Phase 0 寫滿：HF csv → seed / script json
│   │   ├── seed.py           Phase 1：把 seed json 寫進 9 表 ＋ remember
│   │   └── poll.py           cursor 讀寫（.state/last_checked.json）
│   ├── muscle/
│   │   └── rote_client.py    Phase 3：capture() / replay()
│   └── demo/
│       └── streamlit_app.py  單一分頁：左／中／下
├── data/
│   ├── raw/                  git-ignored：HF 下載的原始 csv
│   ├── seed/bitext_seed.json 每 topic 2 張 resolved
│   └── script/
│       ├── demo_tickets.json 現場餵票劇本
│       └── changelog.json    模擬 Release Note
├── tutorials/                Phase 2 起產出 .md
└── tests/{unit,integration}/
```

### 3.2 資料流（Phase 0 只接通虛線左半邊）

```text
 HuggingFace Bitext csv
        │  app/ingest/bitext.py（Phase 0）
        ▼
 data/seed/bitext_seed.json ──┐
 data/script/demo_tickets.json│  app/ingest/seed.py（Phase 1）
 data/script/changelog.json ──┘        │
                                       ▼
        ┌──────────────── app/analytics/sql.py（唯一 SQL 來源）────────────────┐
        │                                                                      │
        ▼                                                                      ▼
 app/analytics/hotdata_client.py                              app/analytics/local_db.py
   run_sql(sql, params) -> list[dict]  ◀── 同一個介面，同一份 SQL ──▶  run_sql(sql, params)
        │  （hotdata CLI / 正式路徑）                        （sqlite3 / 降級路徑）
        └──────────────────────────┬───────────────────────────────────────────┘
                                   ▼
                 app/agent/rules.py（純函式，不碰 DB）
                 app/analytics/metrics.py（算三條指標）
                                   ▼
                 app/demo/streamlit_app.py（左／中／下）
```

**規則：** SQL 只能出現在 `app/analytics/sql.py`；門檻數字只能出現在 `app/agent/rules.py`。其他檔案一律 import，不得重打字串或數字。

---

## 4. 🖐️ 需要你手動做的事

八小時黑客松，這一節要在寫碼之前（或並行）做完。全部做完才算 Phase 0 結束。

| # | 項目 | 指令／網址 | 怎麼確認完成 | 寫進 `.env` 的變數 |
|---|---|---|---|---|
| 1 | RocketRide 帳號 ＋ credits ＋ API key | https://staging.rocketride.ai （coupon code 現場拿）<br>指南：hackathon.md §5 的 Guide／YouTube 連結 | `.env` 已有 `ROCKETRIDE_URI` / `ROCKETRIDE_APIKEY` / `ROCKETRIDE_DEPLOY_URI` / `ROCKETRIDE_DEPLOY_APIKEY`；`grep -c ROCKETRIDE .env` 回 4。**只要確認 credits 有進帳、key 沒過期** | 已存在，不用新增 |
| 2 | hotdata 登入 | `hotdata auth login`（開瀏覽器；已登入可跳過）<br>`hotdata auth status` | `hotdata auth status` 顯示帳號而不是 not logged in | `HOTDATA_API_KEY=`（從 hotdata 後台取；CLI 說明有 `--api-key` 覆寫 env 與 config，保險起見明寫） |
| 3 | hotdata instant database | `hotdata databases create --name "support-tutorial" --catalog support`<br>`hotdata databases use <id>`<br>`hotdata workspaces list` | `hotdata databases list` 看得到這一筆；`hotdata query "SELECT 1 AS x" -o json` 有回傳 | `HOTDATA_DATABASE=`（資料庫 id 或 name）<br>`HOTDATA_CATALOG=support`<br>`HOTDATA_WORKSPACE_ID=` |
| 4 | HydraDB instance ＋ 連線字串 | 依 hackathon.md §5：cloud 或本機 open-source repo 起一個 instance | 手上有一條可貼的連線字串／endpoint ＋ 金鑰 | `HYDRADB_URI=`<br>`HYDRADB_APIKEY=` |
| 5 | Cognee（自架 Docker 或 Cognee Cloud）金鑰 | Cognee Cloud 註冊取 key，或 `docker run` 自架後拿 base URL。SDK 本機未安裝（CLAUDE.md 已記） | 能對 `${COGNEE_BASE_URL}` 打通一次健康檢查，或 Cloud 後台看得到 API key | `COGNEE_API_KEY=`<br>`COGNEE_BASE_URL=`<br>`COGNEE_DATASET=main`（showme §5.4：dataset 固定不開 per-call override） |
| 6 | Rote 登入 ＋ hello-world 暖機 | `rote whoami`（已登入會顯示身分）<br>未登入：`rote login github`（或 `rote login`）<br>暖機：`rote setup`，再依 https://www.modiqo.ai/blog/the-playoffs 跑一次 hello world play<br>`rote play list` | `rote whoami` 有身分；`rote play list` 至少列得出一個 play；Discord 回報 `ready & warmed up` | 不需要（Rote 用 `~/.rote` 的本機 session，不走 .env） |
| 7 | Snyk 帳號 ＋ CLI | https://app.snyk.io/signup<br>`brew install snyk/tap/snyk`（本機尚未安裝）<br>`snyk auth` | `snyk --version` 有版本；`snyk auth` 後 `snyk config get api` 有值 | `SNYK_TOKEN=`（可選；`snyk auth` 已寫進 `~/.config/configstore`，CI 才需要 env） |

**紅線（來自 `.env` 註解與 CLAUDE.md）：** deploy 類操作（`deploy.*`、schedules、publishApp／submitApp）只能用 `ROCKETRIDE_DEPLOY_URI` / `ROCKETRIDE_DEPLOY_APIKEY`；dev 那組只用來 run／validate／iterate。任何金鑰都不得寫進 repo，`.env` 已 git-ignore。

---

## 5. 實作步驟

### 步驟 1 — 🖐️ 手動：開四個終端機分頁

一個跑 `uv`，一個跑 `streamlit`，一個跑 `hotdata`，一個空著查 schema（`cat .rocketride/schema/<node>.json`）。同時把 §4 的表照著做完。

---

### 步驟 2 — 建立 uv 專案與依賴

**注意 Python 版本：** 本機預設是 `/opt/homebrew/bin/python3` → **3.14.7**。Streamlit／pyarrow 在 3.14 的 wheel 未必齊，黑客松沒有時間等原始碼編譯。**釘 3.12**：

```bash
cd /Users/linjunting/AWS-Hackathon
uv python install 3.12
uv init --python 3.12 --name support-tutorial-generator --no-workspace
uv python pin 3.12                      # 產生 .python-version
uv add streamlit pandas httpx python-dotenv pyarrow huggingface_hub
uv add --dev pytest
```

`pyproject.toml` 要點（`uv init` 會先產一版，改成這樣）：

```toml
[project]
name = "support-tutorial-generator"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "streamlit>=1.40", "pandas>=2.2", "httpx>=0.27",
  "python-dotenv>=1.0", "pyarrow>=17", "huggingface_hub>=0.25",
]

[dependency-groups]
dev = ["pytest>=8.3"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`uv init` 若產生 `main.py` / `hello.py`，刪掉（entry point 是 `app/demo/streamlit_app.py` 與 `python -m app.*`）。

**預期輸出：** `uv run python -c "import streamlit, pandas, httpx; print('ok')"` 印 `ok`。

---

### 步驟 3 — `.gitignore` 補齊

在現有兩行（`.rocketride/`、`.env`）之後追加：

```
.venv/
.state/
data/raw/
__pycache__/
*.pyc
.pytest_cache/
```

`tutorials/` **不要** ignore（產出的 `.md` 是 demo 證據）。

**預期輸出：** `git status --short` 不再出現 `.venv`、`__pycache__`。

---

### 步驟 4 — 建立所有空模組

依 §3.1 建目錄與檔案，每個空模組只放 docstring，寫清楚「哪個 phase 填、填什麼、對應哪份 .feature」。例如：

```python
# app/agent/release_update.py
"""Release Note → UPDATE / RETIRE（Phase 5 實作）。

對應規格：docs/spec/features/依ReleaseNote更新Tutorial.feature（7 Rule）
門檻來源：app.agent.rules.decide_release_action
- renamed / changed  → UPDATE：新 TutorialVersion、改 Feature.name、寫 processed_at
- deprecated / removed → RETIRE：status=retired、is_obsolete=true
- new 且無對應 Tutorial → 只寫 processed_at，不決定動作
本檔 Phase 0 只有骨架，不得在此重打門檻數字。
"""
```

`app/errors.py` 是唯一有實體內容的小檔：

```python
class OperationFailed(Exception):
    """規格中所有 `Then 操作失敗` 的唯一例外型別。

    使用規範（來自 showme.md §14）：raise 之前不得留下半筆資料 —
    缺五欄不寫 Tutorial、rating 非 1–5 不寫 Feedback、
    Release 擷取不到 change_type 時 processed_at 保持空，下一輪可重跑。
    """
```

`app/config.py`：

```python
from dataclasses import dataclass
import os
from dotenv import load_dotenv

@dataclass(frozen=True)
class Settings:
    rocketride_uri: str; rocketride_apikey: str
    rocketride_deploy_uri: str; rocketride_deploy_apikey: str   # 只給 deploy 用
    hotdata_api_key: str; hotdata_workspace_id: str
    hotdata_database: str; hotdata_catalog: str
    hydradb_uri: str; hydradb_apikey: str
    cognee_api_key: str; cognee_base_url: str; cognee_dataset: str
    use_local_db: bool          # true → local_db；false → hotdata_client

def load_settings() -> Settings:
    load_dotenv()
    g = lambda k, d="": os.environ.get(k, d)
    return Settings(..., use_local_db=g("USE_LOCAL_DB", "false").lower() == "true")
```

`app/ingest/poll.py`（本 phase 就要能用，Phase 1／2 直接 import）：

```python
CURSOR_PATH = ".state/last_checked.json"
def read_cursor(name: str, default: str = "1970-01-01T00:00:00Z") -> str: ...
def write_cursor(name: str, value: str) -> None: ...
```

cursor 存檔不是業務表（showme §9 的 design decision）；`name` 至少兩個 key：`ticket`、`changelog`。

**預期輸出：** `uv run python -c "import app.config, app.errors, app.ingest.poll; print('ok')"`。

---

### 步驟 5 — `app/analytics/sql.py`：9 表 DDL ＋ 查詢

型別對應（erm.dbml 只允許 int / long / float / bool / string）：

| DBML | SQL（hotdata 與 SQLite 共用寫法） |
|---|---|
| int / long | `INTEGER` |
| float | `DOUBLE`（SQLite 視為 REAL，相容） |
| bool | `BOOLEAN`（SQLite 存 0/1） |
| string（含所有時間欄，ISO 8601） | `TEXT` |

九張表的欄位（逐欄照 `docs/spec/erm.dbml`，**不加、不改、不補欄**）：

| 表 | 欄位（型別） |
|---|---|
| `ticket` | id INTEGER PK, content TEXT, resolution_steps TEXT, category TEXT, customer_ref TEXT, feature_id INTEGER, user_problem_id INTEGER, status TEXT, deflected_tutorial_id INTEGER, deflected_tutorial_version TEXT, reopened_from_ticket_id INTEGER, created_at TEXT |
| `user_problem` | id INTEGER PK, topic TEXT, feature_id INTEGER |
| `feature` | id INTEGER PK, name TEXT, status TEXT |
| `tutorial` | tutorial_id INTEGER PK, feature_id INTEGER, user_problem_id INTEGER, path TEXT, status TEXT, current_version TEXT, is_possibly_outdated BOOLEAN, is_obsolete BOOLEAN, last_action TEXT |
| `tutorial_version` | tutorial_id INTEGER, tutorial_version TEXT, title TEXT, problem TEXT, prerequisites TEXT, steps TEXT, expected_outcome TEXT, reason TEXT, supersedes_version TEXT, created_at TEXT, **PK (tutorial_id, tutorial_version)** |
| `feedback` | id INTEGER PK, tutorial_id INTEGER, tutorial_version TEXT, rating INTEGER, feedback_category TEXT, comment TEXT, submitter_id TEXT, timestamp TEXT |
| `release` | id INTEGER PK, content TEXT, created_at TEXT, processed_at TEXT |
| `release_feature_change` | id INTEGER PK, release_id INTEGER, feature_id INTEGER, change_type TEXT, from_name TEXT, to_name TEXT |
| `workflow` | id INTEGER PK, user_problem_id INTEGER, steps TEXT, captured_at TEXT, replay_count INTEGER |

`release` 是 SQL 保留字風險字；統一用雙引號寫成 `"release"`，或表名前綴 `rel_`——**選一種寫死在 sql.py，兩條路徑（hotdata / SQLite）用同一份**。建議 `"release"` 加引號，保持與 erm.dbml 同名。

DDL 範例（一張表的完整寫法，其餘 8 張照做）：

```python
DDL_TICKET = """
CREATE TABLE IF NOT EXISTS ticket (
  id INTEGER PRIMARY KEY,
  content TEXT,                       -- Bitext instruction
  resolution_steps TEXT,              -- Bitext response；新進票為空
  category TEXT,                      -- Bitext category：ORDER / REFUND / ACCOUNT
  customer_ref TEXT,                  -- demo：alice@example.com / bob@example.com
  feature_id INTEGER,                 -- asks_about
  user_problem_id INTEGER,
  status TEXT,                        -- open / deflected / escalated / resolved
  deflected_tutorial_id INTEGER,
  deflected_tutorial_version TEXT,
  reopened_from_ticket_id INTEGER,    -- 指向被攔截的舊票（status 必為 deflected）
  created_at TEXT                     -- ISO 8601；輪詢依據
)
"""

DDL_TUTORIAL_VERSION = """
CREATE TABLE IF NOT EXISTS tutorial_version (
  tutorial_id INTEGER,
  tutorial_version TEXT,
  title TEXT, problem TEXT, prerequisites TEXT, steps TEXT, expected_outcome TEXT,
  reason TEXT,
  supersedes_version TEXT,            -- v1 必空；v2 起指同篇上一版
  created_at TEXT,
  PRIMARY KEY (tutorial_id, tutorial_version)
)
"""

ALL_DDL = [DDL_FEATURE, DDL_USER_PROBLEM, DDL_TICKET, DDL_TUTORIAL,
           DDL_TUTORIAL_VERSION, DDL_FEEDBACK, DDL_RELEASE,
           DDL_RELEASE_FEATURE_CHANGE, DDL_WORKFLOW]
```

查詢常數（全部用 `:name` 具名參數，兩條路徑共用）：

```python
# 輪詢新票（輪詢新票單.feature：created_at 嚴格大於、且 status = open）
Q_POLL_NEW_TICKETS = """
SELECT * FROM ticket
WHERE status = 'open' AND created_at > :last_checked
ORDER BY created_at
"""

# 輪詢 changelog 去重（輪詢ReleaseNote.feature：content + created_at 已存在則不新增）
Q_RELEASE_EXISTS = """
SELECT COUNT(*) AS n FROM "release"
WHERE content = :content AND created_at = :created_at
"""
Q_UNPROCESSED_RELEASES = """
SELECT * FROM "release" WHERE processed_at IS NULL OR processed_at = ''
ORDER BY created_at
"""

# 分析 Ticket（分析SupportTickets.feature：只納入 escalated / resolved）
Q_TICKET_COUNT_BY_PROBLEM = """
SELECT user_problem_id, COUNT(*) AS ticket_count
FROM ticket
WHERE status IN ('escalated', 'resolved') AND user_problem_id IS NOT NULL
GROUP BY user_problem_id
"""
Q_PUBLISHED_TUTORIAL_BY_PROBLEM = """
SELECT user_problem_id, tutorial_id, current_version
FROM tutorial WHERE status = 'published'
"""

# Feedback Review（定期優化Tutorial.feature：只算 current_version）
Q_FEEDBACK_STATS = """
SELECT AVG(f.rating) AS avg_rating, COUNT(*) AS feedback_count
FROM feedback f JOIN tutorial t
  ON f.tutorial_id = t.tutorial_id AND f.tutorial_version = t.current_version
WHERE t.tutorial_id = :tutorial_id
"""
Q_FEEDBACK_CATEGORY_COUNT = """
SELECT f.feedback_category, COUNT(*) AS n
FROM feedback f JOIN tutorial t
  ON f.tutorial_id = t.tutorial_id AND f.tutorial_version = t.current_version
WHERE t.tutorial_id = :tutorial_id AND f.feedback_category <> ''
GROUP BY f.feedback_category ORDER BY n DESC
"""

# 三條學習指標（展示學習指標.feature）
Q_DEFLECTION_COUNTS = """
SELECT
  SUM(CASE WHEN status = 'deflected'  THEN 1 ELSE 0 END) AS deflected,
  SUM(CASE WHEN status = 'escalated' THEN 1 ELSE 0 END) AS escalated
FROM ticket
"""
Q_REPLAY_TOTALS = """
SELECT
  (SELECT COALESCE(SUM(replay_count), 0) FROM workflow) AS replay_sum,
  (SELECT COUNT(*) FROM ticket WHERE status = 'deflected') AS deflected
"""
Q_COVERAGE = """
SELECT
  (SELECT COUNT(DISTINCT user_problem_id) FROM tutorial WHERE status = 'published') AS covered,
  (SELECT COUNT(*) FROM user_problem) AS total
"""
```

**預期輸出：** `uv run python -c "from app.analytics import sql; print(len(sql.ALL_DDL))"` 印 `9`。

---

### 步驟 6 — `app/agent/rules.py`：門檻純函式

門檻常數只在這裡出現一次：

```python
RECURRING_MIN_TICKETS = 3          # 分析SupportTickets.feature
REFINE_AVG_THRESHOLD = 3.5         # 定期優化Tutorial.feature（嚴格小於才 REFINE）
REFINE_MIN_FEEDBACK = 3
REFINE_MIN_SAME_CATEGORY = 2

def is_recurring(count: int) -> bool:
    """同一 user_problem_id 的 escalated/resolved 票數 >= 3 才是 recurring topic。"""
    return count >= RECURRING_MIN_TICKETS

def has_knowledge_gap(count: int, has_published: bool) -> bool:
    """recurring 且沒有 published Tutorial ＝ Knowledge Gap（動作 CREATE）。"""
    return is_recurring(count) and not has_published

def classify_ticket(user_problem_id: int | None,
                    has_published_tutorial: bool,
                    is_reopen: bool) -> str:
    """自動回覆顧客.feature：回 'deflected' 或 'escalated'。
    retired Tutorial 視同沒有 Tutorial（呼叫端傳 has_published_tutorial=False）。"""
    if user_problem_id is None or not has_published_tutorial or is_reopen:
        return "escalated"
    return "deflected"

def should_refine(avg: float, count: int, max_same_category: int) -> bool:
    """三條件同時成立才 REFINE；否則 KEEP。
    注意：is_possibly_outdated=true 的本輪 KEEP，由呼叫端先擋，不進本函式。"""
    return (avg < REFINE_AVG_THRESHOLD
            and count >= REFINE_MIN_FEEDBACK
            and max_same_category >= REFINE_MIN_SAME_CATEGORY)

def decide_release_action(change_type: str) -> str | None:
    """依ReleaseNote更新Tutorial.feature：renamed/changed → UPDATE；
    deprecated/removed → RETIRE；new → None（只寫 processed_at）。"""
    if change_type in ("renamed", "changed"):
        return "UPDATE"
    if change_type in ("deprecated", "removed"):
        return "RETIRE"
    return None

def is_duplicate_release(content: str, created_at: str,
                         existing: list[dict]) -> bool:
    """輪詢ReleaseNote.feature：content 與 created_at 皆相同才算重複。"""
    return any(r["content"] == content and r["created_at"] == created_at
               for r in existing)
```

硬規定：本檔 **不 import** `app` 底下任何其他模組、不碰檔案／網路、不新增函式（無腦補原則）。

---

### 步驟 7 — `tests/unit/test_rules.py`：臨界測試

一條 Example 對一個 assert，測試函式名字帶上對應的 Rule：

```python
from app.agent.rules import *

def test_兩張票不算_三張票才算():                     # 分析SupportTickets
    assert is_recurring(2) is False
    assert is_recurring(3) is True

def test_knowledge_gap_需要同時滿足三張與無published():
    assert has_knowledge_gap(3, has_published=False) is True
    assert has_knowledge_gap(3, has_published=True)  is False
    assert has_knowledge_gap(2, has_published=False) is False

def test_平均剛好3_5是KEEP_3_4才REFINE():             # 定期優化Tutorial
    assert should_refine(3.5, 4, 4) is False
    assert should_refine(3.4, 3, 2) is True
    assert should_refine(4.0, 5, 5) is False

def test_筆數2不算_3才算():
    assert should_refine(2.0, 2, 2) is False
    assert should_refine(2.0, 3, 2) is True

def test_同category_1筆不算_2筆才算():
    assert should_refine(2.0, 3, 1) is False
    assert should_refine(2.0, 3, 2) is True

def test_票單分類():                                   # 自動回覆顧客
    assert classify_ticket(1, True,  False) == "deflected"
    assert classify_ticket(None, True, False) == "escalated"   # 無 UserProblem
    assert classify_ticket(1, False, False) == "escalated"     # 無/retired Tutorial
    assert classify_ticket(1, True,  True)  == "escalated"     # 同顧客再開票

def test_release動作對應():                            # 依ReleaseNote更新Tutorial
    assert decide_release_action("renamed")    == "UPDATE"
    assert decide_release_action("changed")    == "UPDATE"
    assert decide_release_action("deprecated") == "RETIRE"
    assert decide_release_action("removed")    == "RETIRE"
    assert decide_release_action("new")        is None

def test_release去重看content加created_at():           # 輪詢ReleaseNote
    existing = [{"content": "Cancel Order has been renamed to Cancel Purchase.",
                 "created_at": "2026-09-11T09:30:00Z"}]
    assert is_duplicate_release("Cancel Order has been renamed to Cancel Purchase.",
                                "2026-09-11T09:30:00Z", existing) is True
    assert is_duplicate_release("Cancel Order has been renamed to Cancel Purchase.",
                                "2026-09-11T10:30:00Z", existing) is False
```

再補 `tests/unit/test_metrics.py`，照 `展示學習指標.feature` 的三個 Example：`deflection_rate(2, 2) == 0.5`、`replay_rate(2, 4) == 0.5`、`coverage(1, 2) == 0.5`。分母為 0 時規格沒有例子 —— 實作取 `0.0`，在 docstring 標「規格未定義，實作決定，不寫回 .feature」。

**執行：** `uv run pytest -q` → 預期全綠。

---

### 步驟 8 — 兩條 run_sql：`local_db.py`（先做）與 `hotdata_client.py`

**`app/analytics/local_db.py`（降級路徑，Phase 0 一定要能跑）：**

```python
import sqlite3, json
from app.analytics import sql as S

DB_PATH = ".state/demo.sqlite3"

def _conn():
    c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row; return c

def init_db() -> None:
    with _conn() as c:
        for ddl in S.ALL_DDL:
            c.execute(ddl)

def run_sql(sql: str, params: dict | None = None) -> list[dict]:
    """與 hotdata_client.run_sql 相同介面；sql 用 :name 具名參數。"""
    with _conn() as c:
        cur = c.execute(sql, params or {})
        return [dict(r) for r in cur.fetchall()] if cur.description else []

if __name__ == "__main__":     # uv run python -m app.analytics.local_db --init
    init_db(); print(f"initialized {DB_PATH}")
```

**`app/analytics/hotdata_client.py`（正式路徑，走本機 CLI）：**

已用 `--help` 查到的實際旗標（v0.33.0）：

| 需求 | 指令 |
|---|---|
| 執行 SQL | `hotdata query "<SQL>" -d <database> -o json --api-key <key> --no-input` |
| 指定 workspace | `-w <WORKSPACE_ID>`（省略則用登入的第一個 workspace） |
| 輸出格式 | `-o json`（`query` 支援 table/json/csv） |
| SQL 方言 | `--dialect hotsql`（預設）；可選 `duckdb` / `postgres` / `snowflake`，非 hotsql 會 server-side 轉譯且**唯讀** |
| 建資料庫 | `hotdata databases create --name <n> --catalog <alias> [--table <t> ...]` |
| 選定資料庫 | `hotdata databases use <name-or-id>`（之後 `query` 可省略 `-d`） |
| 載入檔案 | `hotdata databases load --catalog <alias> --table <t> --file <path> [--append]`（csv/json/parquet） |
| 列表／狀態 | `hotdata databases list`、`hotdata auth status`、`hotdata manage usage` |
| 長查詢 | `hotdata query status <id>`（exit code 0 成功／1 失敗／2 還在跑／3 截斷預覽） |

實作要點：

```python
import json, subprocess
from app.config import load_settings
from app.errors import OperationFailed

def _render(sql: str, params: dict | None) -> str:
    """把 :name 換成字面值。CLI 不吃具名參數，只能在送出前組字串。
    只允許 int / float / bool / None / str；str 以單引號包起並把 ' 轉成 ''。
    參數一律來自本地 seed / demo script，不接受外部輸入（Snyk 掃到會標 SQL 注入，
    在 PR 說明註明資料來源是本機固定檔）。"""

def run_sql(sql: str, params: dict | None = None) -> list[dict]:
    s = load_settings()
    cmd = ["hotdata", "query", _render(sql, params),
           "-d", s.hotdata_database, "-o", "json", "--no-input"]
    if s.hotdata_api_key:    cmd += ["--api-key", s.hotdata_api_key]
    if s.hotdata_workspace_id: cmd += ["-w", s.hotdata_workspace_id]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise OperationFailed(f"hotdata query failed: {p.stderr.strip()[:400]}")
    return _rows(json.loads(p.stdout or "[]"))

def _rows(payload):      # 防禦：list 或 {"rows": [...]} / {"data": [...]} 都吃
    if isinstance(payload, list): return payload
    for k in ("rows", "data", "results"):
        if isinstance(payload, dict) and k in payload: return payload[k]
    return []
```

🖐️ **手動一次性確認：** `hotdata query "SELECT 1 AS x" -o json` 看實際 JSON 形狀，把 `_rows()` 的分支砍到只留對的那一個。（CLI 說明沒有寫死輸出結構，不要猜。）

**選擇路徑：** 加一個 `app/analytics/db.py` 的一行 facade，或在各呼叫端依 `Settings.use_local_db` 取 module。建議前者：

```python
# app/analytics/__init__.py 或 db.py
def get_db():
    from app.config import load_settings
    from app.analytics import local_db, hotdata_client
    return local_db if load_settings().use_local_db else hotdata_client
```

**預期輸出：** `uv run python -m app.analytics.local_db --init` → `initialized .state/demo.sqlite3`；`sqlite3 .state/demo.sqlite3 ".tables"` 看到 9 張表。

---

### 步驟 9 — `app/analytics/metrics.py`

```python
from app.analytics import sql as S

def deflection_rate(deflected: int, escalated: int) -> float:
    """展示學習指標.feature：deflected / (deflected + escalated)。open/resolved 不進分母。"""
def replay_rate(replay_sum: int, deflected: int) -> float:
    """SUM(Workflow.replay_count) / deflected 票數。"""
def coverage(covered: int, total: int) -> float:
    """有 published Tutorial 的 UserProblem 數 / UserProblem 總數。"""
def current_metrics(db) -> dict:
    """跑 Q_DEFLECTION_COUNTS / Q_REPLAY_TOTALS / Q_COVERAGE，回三個 float。"""
```

純算術函式與 SQL 執行分開，才能在 `tests/unit` 測到 Example 的 2/4、2/4、1/2。

---

### 步驟 10 — `app/ingest/bitext.py`：抓資料集、產兩份 json

資料集：`bitext/Bitext-customer-support-llm-chatbot-training-dataset`（欄位 `instruction` / `category` / `intent` / `response`，授權 CDLA-Sharing-1.0）。

```python
REPO_ID = "bitext/Bitext-customer-support-llm-chatbot-training-dataset"
TOPICS = ["cancel_order", "track_refund", "change_shipping_address"]
INTENT_TO_FEATURE = {
    "cancel_order": "Cancel Order",
    "track_refund": "Track Refund",
    "change_shipping_address": "Change Shipping Address",
}
SEED_PER_TOPIC = 2          # showme §11：每類 2 張歷史 resolved，不到 CREATE 門檻
```

流程：

1. `huggingface_hub.list_repo_files(REPO_ID, repo_type="dataset")` 先列檔名，挑出那支 `.csv`（**不要憑記憶寫死檔名，跑一次看清楚**），再 `hf_hub_download(..., repo_type="dataset", local_dir="data/raw")`。
2. `pandas.read_csv` → `df[df.intent.isin(TOPICS)]`。
3. 每個 topic 取前 `SEED_PER_TOPIC` 列 → `data/seed/bitext_seed.json`，每列：
   `{"content": instruction, "resolution_steps": response, "category": category, "intent": intent, "feature_name": INTENT_TO_FEATURE[intent], "status": "resolved", "created_at": "2026-09-01T..Z"}`
   （`建構知識圖譜.feature`：匯入後 status = resolved、`resolution_steps` 與 `created_at` 有值；topic = intent；同名 Feature／同 topic UserProblem 重用同一列。）
4. 同一個 topic 的**後續**列扣住當現場劇本 → `data/script/demo_tickets.json`，每列多帶 `customer_ref`、`status: "open"`、`expect`（只是註解，程式不讀它做決策）：

   | 序 | intent | customer_ref | 期望 | 為什麼 |
   |---|---|---|---|---|
   | T3 | cancel_order | alice@example.com | escalated → 真人確認 → resolved | 湊滿 3 張 → 分析 → CREATE v1 |
   | T4 | cancel_order | bob@example.com | deflected | 第一次攔截 → Rote 捕捉 Workflow（replay_count=0） |
   | T5 | cancel_order | alice@example.com | deflected | 重放 → replay_count=1 |
   | T6 | cancel_order | alice@example.com，`reopened_from_ticket_id` 指 T5 | escalated | 同顧客同問題再開票（教學無效的隱性訊號） |

5. `data/script/changelog.json` 手寫（不是 Bitext 來的）：
   `[{"content": "Cancel Order has been renamed to Cancel Purchase.", "created_at": "2026-09-11T10:30:00Z"}]`

**執行：** `uv run python -m app.ingest.bitext`
**預期輸出：** 印出 `seed: 6 rows (3 topics x 2)`、`script: N rows`，且兩個 json 檔存在、`data/raw/*.csv` 被 git ignore。

---

### 步驟 11 — `app/demo/streamlit_app.py`：三區空殼

依 showme §13 與 `docs/design/architecture.md`：一個分頁，`st.set_page_config(layout="wide")`。

```
┌─ 左：假裝進資料 ───────────┬─ 中：Agent 寫／改教學 ─────────────┐
│ [餵下一張票] 顯示劇本下一筆 │ 目前 Tutorial .md 內容              │
│ [貼 changelog] 顯示 release │ Release 後的 Step 3 diff（Phase 5） │
│ 系統回覆（教學連結／轉真人）│ [分析] [Review] 按鈕（Phase 2/4）   │
└────────────────────────────┴──────────────────────────────────────┘
┌─ 下：曲線（只讀）──────────────────────────────────────────────┐
│ deflection rate ・ 平均 rating ・ 重放解決率 ・ 圖譜覆蓋        │
└─────────────────────────────────────────────────────────────────┘
```

Phase 0 只做到：版面存在、按鈕存在但 `st.info("Phase N 接上")`、下區呼叫 `metrics.current_metrics(local_db)` 顯示四個 `st.metric`（此時 0.0）。**UI 不算門檻、不決定 CREATE／擋票**（showme §13）。

**執行：** `uv run streamlit run app/demo/streamlit_app.py` → 瀏覽器開得起來、不報錯。

---

### 步驟 12 — 🖐️ 手動：第一次 commit 與 Snyk 首掃

```bash
git add -A && git commit -m "Phase 0：建立 uv 骨架、9 表 DDL、門檻函式與 demo 空殼"
snyk test            # 依賴漏洞
snyk code test       # 原始碼
```

確認 `git status` 沒有 `.env`、`.rocketride/`、`.state/`、`data/raw/`。Snyk 有 high 以上就當場修（評審會扣分）。

---

## 6. 驗收清單

環境（對齊 hackathon.md §5 Setup Checklist）：

- [ ] 🖐️ `hotdata auth status` 顯示已登入，`hotdata databases list` 看得到本專案的 instant database
- [ ] 🖐️ `hotdata query "SELECT 1 AS x" -o json` 有回傳，且 `_rows()` 已按實際形狀收斂
- [ ] 🖐️ `rote whoami` 有身分、hello-world play 跑過、Discord 回報 ready & warmed up
- [ ] 🖐️ HydraDB 連線字串、Cognee 金鑰／base URL 都已寫進 `.env`
- [ ] 🖐️ `snyk --version` 有版本且 `snyk auth` 完成
- [ ] `.env` 有 `ROCKETRIDE_*`（dev 4 個）＋ `HOTDATA_*` ＋ `HYDRADB_*` ＋ `COGNEE_*`；`.env` 不在 `git status` 裡

程式（每一條對應一份 `.feature` 的 Rule）：

- [ ] `uv run pytest -q` 全綠
- [ ] 分析SupportTickets：`is_recurring(2)=False`、`is_recurring(3)=True`
- [ ] 分析SupportTickets：`has_knowledge_gap(3, True)=False`（已有 published → KEEP）
- [ ] 自動回覆顧客：`classify_ticket` 四種 escalated 情境（無 UserProblem／無 published／retired／再開票）都回 escalated
- [ ] 定期優化Tutorial：`should_refine(3.5, …)=False`（剛好等於 3.5 是 KEEP）
- [ ] 定期優化Tutorial：`count=2` 不 REFINE、同 category `=1` 不 REFINE
- [ ] 依ReleaseNote更新Tutorial：renamed/changed → UPDATE、deprecated/removed → RETIRE、new → None
- [ ] 輪詢ReleaseNote：content 同但 created_at 不同 → 不算重複
- [ ] 展示學習指標：三條公式在 Example 數字下都得 0.5
- [ ] `uv run python -m app.analytics.local_db --init` 建出 **9 張表**，欄位與 `docs/spec/erm.dbml` 逐欄一致（沒有第 10 張表、沒有多欄）
- [ ] `uv run python -m app.ingest.bitext` 產出 `data/seed/bitext_seed.json`（6 列）與 `data/script/demo_tickets.json`
- [ ] `uv run streamlit run app/demo/streamlit_app.py` 開得起來，左／中／下三區都在，下區顯示四個數字
- [ ] `app/agent/rules.py` 沒有 import 其他 app 模組、沒有 I/O；門檻數字在全 repo 只出現這一處
- [ ] 所有空模組的 docstring 都寫明「哪個 phase 填、對應哪份 .feature」

---

## 7. 降級方案

| 情境 | 訊號 | 降級做法 |
|---|---|---|
| Python 3.14 裝不起 streamlit／pyarrow | `uv add` 開始編譯原始碼或報 wheel 找不到 | `uv python install 3.12` ＋ `uv python pin 3.12`，重跑 `uv sync`（本步驟已預設這樣做） |
| 抓不到 HuggingFace（網路／需要登入） | `hf_hub_download` timeout 或 401 | 直接用 `https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset` 網頁下載 csv 丟進 `data/raw/`；再不行就手寫 6 列 seed，內容照 `分析SupportTickets.feature` / `建構知識圖譜.feature` 的 Example 句子（例如 `I want to cancel order {{Order Number}}`），**欄位形狀不變**，Phase 1 之後完全無感 |
| hotdata 當日不可用／建不了 database | `hotdata query` 非 0 exit code | `.env` 設 `USE_LOCAL_DB=true`，走 `local_db.py`。**同一份 DDL、同一份 SQL、同樣 9 張表**（showme §5.4／§17）。demo 時口頭說明 hotdata 的角色與 SQL，不改表形狀 |
| `hotdata query -o json` 輸出形狀跟預期不同 | `_rows()` 回空 list | 先 `-o csv` 或 `-o table` 人工看一次，再改 `_rows()`；不要在呼叫端各自 parse |
| `hotdata` CLI 版本行為變了 | 旗標不存在 | 本檔旗標查自本機 v0.33.0；當場 `hotdata query --help`／`hotdata databases --help` 重查，改 `hotdata_client.py` 一處即可 |
| node 相關工具被擋 | shell function 攔截 `node` | 本專案全 Python，不需要 node；UI 是 Streamlit，不引入任何 npm 依賴 |
| Snyk 太晚裝／掃不動 | `snyk` 不存在 | 先 `uv pip list` 人工看依賴版本，Phase 5 之前一定要補掃（showme §17：切片 F 之前掃完） |
| 時間不夠 | 55 分鐘到了還沒完 | 最低可交付順序：步驟 2 → 5 → 6 → 7 →（8 的 local_db）。步驟 10、11 可延到 Phase 1 開頭；§4 的手動項可與寫碼並行 |

---

## 8. 交接給 Phase 1 的東西

Phase 1（種子建圖，showme §16 切片 A）拿到的是：

1. **`app/analytics/sql.py`** — 9 表 DDL 與所有查詢常數。Phase 1 只新增 INSERT 常數，不改既有表結構、不加欄位。
2. **`run_sql(sql, params) -> list[dict]`** — 兩條實作（hotdata／SQLite）同介面，靠 `Settings.use_local_db` 切換。Phase 1 的 `seed.py` 只 import 這個介面。
3. **`app/agent/rules.py`** — 門檻已定案。Phase 2／4／5 直接 import，任何 phase 都不得重新定義 3、3.5、3、2 這四個數字。
4. **`data/seed/bitext_seed.json`** — 3 topic × 2 張 resolved，帶 `intent`（= `UserProblem.topic`）與 `feature_name`（= `Feature.name`）。Phase 1 照 `建構知識圖譜.feature` 的 Rule 匯入：同 topic 重用同一列 UserProblem、同名重用同一列 Feature。
5. **`data/script/demo_tickets.json` / `changelog.json`** — 現場劇本；Phase 2 起由左欄「餵下一張票／貼 changelog」逐筆送出。
6. **`app/ingest/poll.py` 的 cursor** — `.state/last_checked.json`，key 至少 `ticket` 與 `changelog`。不是業務表（showme §9）。
7. **`app/memory/cognee_client.py` / `hydradb_client.py` 的空殼與 docstring** — Phase 1 第一件事是照 showme §18 的限制做一次 remember ＋ Cypher 煙測，確認 Cognee → HydraDB 當日可直連。
8. **`.env` 變數名** — `COGNEE_API_KEY` / `COGNEE_BASE_URL` / `COGNEE_DATASET`（固定 `main`）、`HYDRADB_URI` / `HYDRADB_APIKEY`、`HOTDATA_*`。Phase 1 之後不再新增變數名，需要新變數請回頭改 `app/config.py` 的 `Settings`。

**Phase 1 開始前要再確認一次的事：** RocketRide 節點參數不要憑記憶寫，查 `.rocketride/schema/tool_cognee.json`、`.rocketride/schema/db_hydradb.json`（本機快取共 140 個節點 schema）。deploy 一律只用 `ROCKETRIDE_DEPLOY_*`。

---

## 引用來源

**本專案檔案**

- `/Users/linjunting/AWS-Hackathon/CLAUDE.md` — 門檻表、五層 stack 對應、語言與目錄慣例、`.env` deploy 紅線
- `/Users/linjunting/AWS-Hackathon/docs/design/showme.md` — §5.2 規劃模組、§5.3 資料流、§5.4 RocketRide 節點、§9 資料模型對應與 cursor 決策、§11 Demo 資料策略、§12 學習指標、§13 UI 邊界、§14 錯誤語意、§15 測試策略、§16 交付切片、§17 當日風險
- `/Users/linjunting/AWS-Hackathon/docs/spec/erm.dbml` — 9 表逐欄型別與不變條件
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/分析SupportTickets.feature` — 3 張門檻、只納入 escalated/resolved、Knowledge Gap
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/定期優化Tutorial.feature` — avg 3.5／count 3／同 category 2 的臨界 Example
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/輪詢ReleaseNote.feature` — content + created_at 去重、processed_at 為空
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/自動回覆顧客.feature` — deflected／escalated 四種情境
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/依ReleaseNote更新Tutorial.feature` — renamed/changed→UPDATE、deprecated/removed→RETIRE、new→無動作
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/展示學習指標.feature` — 三條指標公式與 0.5 的 Example
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/建構知識圖譜.feature` — 匯入後 status=resolved、topic=intent、同名重用
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/收集Feedback.feature`、`建立Tutorial.feature`、`重放已驗證流程.feature`、`輪詢新票單.feature` — 空模組 docstring 的對應來源
- `/Users/linjunting/AWS-Hackathon/docs/hackathon.md` §5 Setup Checklist、§6 Pre-Hackathon Warm-up — §4 手動清單的依據
- `/Users/linjunting/AWS-Hackathon/docs/客服自助教學生成器 — 系統架構規格.md` — 五層職責與輪詢機制定位
- `/Users/linjunting/AWS-Hackathon/.rocketride/schema/`（git-ignored，140 個節點）— Phase 2 起查參數用

**本機實查（2026-09-11）**

- `hotdata --help` / `hotdata query --help` / `hotdata databases --help` / `hotdata databases create --help` / `hotdata databases load --help` / `hotdata auth --help`（CLI v0.33.0）— §5 步驟 8 的旗標表
- `rote --help` / `rote play --help` — §4 第 6 項的 `whoami` / `login` / `setup` / `play list`
- `uv --version`（0.11.32）、`python3 --version`（3.14.7，故釘 3.12）

**官方網址**

- RocketRide staging：https://staging.rocketride.ai
- Modiqo Rote Playoffs 暖機指南：https://www.modiqo.ai/blog/the-playoffs ／ 文件：https://www.modiqo.ai/docs
- Snyk 註冊：https://app.snyk.io/signup
- Cognee 文件：https://docs.cognee.ai/core-concepts/data-flows
- Bitext 資料集：https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset
