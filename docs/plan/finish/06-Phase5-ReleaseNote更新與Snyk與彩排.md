# Phase 5 — Release Note 更新、Snyk 與 Demo 彩排

> ⚠️ **這只是 hackathon 作品，不要過度設計。** 8 小時內能 demo 迴圈就好：先讓它能跑，再談漂亮。
> 能用最簡單的方式做到驗收條件就停手；不加規格沒寫的欄位、不做抽象層、不為「日後擴充」多寫一行。
> 遇到「這樣夠不夠好」的猶豫時，選最短路徑，並在 report 標記「hackathon 簡化」即可。

## 現況更新（2026-09-11）

- **Phase 0 已實作並驗證**：`uv run pytest -q` 35 passed；Bitext 真實下載（`data/raw/`），`data/seed/bitext_seed.json` 6 筆、`data/script/demo_tickets.json` 9 筆、`feedback_seed.json` 10 筆（avg 2.9）、`feedback_v2_seed.json` 5 筆（avg 4.4）；Streamlit 空殼可啟動；`.env`／`.state/`／`data/raw/` 已 git-ignore。
- **環境事實**：hotdata CLI 已登入（workspace `Hackathon_space`，尚無本專案 database）；`rote whoami` 正常；Cognee 伺服器可用（沿用本機記憶插件的 server，專案另開 dataset）；**沒有** HydraDB 直連憑證與 LLM 金鑰（`.env` 只有 `ROCKETRIDE_*`）。
- **已知偏差（以骨架命名為準）**：hotdata instant database 是 schema-on-load，9 表 DDL 主要用於 SQLite 降級；RocketRide `db_hydradb` 節點沒有 Cypher action，多跳查詢由 `app/memory/hydradb_client.py` 自己做；phase 專屬 SQL 放在該 phase 模組，不回改 `app/analytics/sql.py`；Streamlit 各區以 `app/demo/ui_<x>.py` 的 `render(db)` 提供，最後統一接進 `streamlit_app.py`。
- **共用介面**：`app/agent/llm.py: complete_json(prompt, schema_hint) -> dict`（無金鑰時 raise `LLMUnavailable`，呼叫端用模板降級）；`app/muscle/rote_client.py: on_deflected(db, ticket_id, user_problem_id) -> dict`。

- **對應設計：** `docs/design/showme.md` §16 切片 F（Release UPDATE ＋ Snyk）、§7.3（Release Note 入庫 ≠ 處理）、§10（HydraDB 多跳）、§6 步驟 10–11、§8 生命週期、§11 Demo 資料、§14 錯誤語意、§17 當日風險
- **對應規格：** `docs/spec/features/輪詢ReleaseNote.feature`（3 Rule）、`docs/spec/features/依ReleaseNote更新Tutorial.feature`（7 Rule）、`docs/spec/erm.dbml`（Release / ReleaseFeatureChange / Feature / Tutorial / TutorialVersion）
- **狀態：** 待實作。本檔描述的目錄、模組、函式、按鈕**尚未存在**，全部是本 Phase 要寫出來的東西。
- **預估時間：** 約 90 分鐘（實作 55 分、Snyk 15 分、彩排與 Q&A 排練 20 分）
- **前置：** Phase 4 驗收通過

## 前置：Phase 4 必須已經成立的具體條件

沒有這些，本 Phase 的驗收案例跑不出來（本 Phase **不**負責補做）：

| # | 前置條件 | 怎麼確認 |
|---|---|---|
| P1 | `app/errors.py` 有 `OperationFailed` | `python3 -c "from app.errors import OperationFailed"` |
| P2 | `app/analytics/hotdata_client.py` 有 `run_sql(sql, params)` 並能讀寫 9 表 | `SELECT COUNT(*) FROM Ticket` 有值 |
| P3 | `Feature` 有一列 `id=1 / name="Cancel Order" / status=active` | SQL 查 Feature |
| P4 | `Tutorial` 有一列 `tutorial_id=1 / feature_id=1 / path=tutorials/cancel-order.md / status=published` | SQL 查 Tutorial |
| P5 | `TutorialVersion` 至少有 v1，且 `steps` 含 `Step 3: Click "Cancel Order"` | SQL 查 TutorialVersion |
| P6 | Phase 4 REFINE 已跑過 → `current_version = v2`、`last_action = REFINE`、`v2.supersedes_version = v1` | SQL 查 Tutorial / TutorialVersion |
| P7 | `tutorials/cancel-order.md` 實體檔存在且內容＝current_version 五欄 | `cat tutorials/cancel-order.md` |
| P8 | `app/demo/streamlit_app.py` 跑得起來，三欄（左／中／下）都有東西 | `uv run streamlit run app/demo/streamlit_app.py` |
| P9 | `app/memory/cognee_client.py` 的 `remember()` 可呼叫（失敗也要能被 catch） | Phase 1 煙測紀錄 |
| P10 | `.state/` 目錄可寫（Phase 1 的 cursor 檔已用同一機制） | `ls .state/` |

P6 未成立（Phase 4 只到 v1）時，本 Phase 的 UPDATE 產出 **v2** 而不是 v3，驗收條文照 `.feature` 的 Example 走（見 §6）。

## 產出

| 類別 | 檔案 |
|---|---|
| 新增 | `app/ingest/poll.py`（`poll_changelog`）、`app/agent/release_update.py`、`data/script/changelog.json`、`scripts/demo_rehearsal.py`、`scripts/reset_demo.py`、`tests/unit/test_release.py` |
| 修改 | `app/analytics/sql.py`（Release 相關 SQL）、`app/agent/rules.py`（`is_duplicate_release` / `decide_release_action`）、`app/memory/hydradb_client.py`（`cypher()`）、`app/demo/streamlit_app.py`（貼 changelog ＋ Step 3 diff） |
| 手動產出 | `docs/plan/report/<日期>-snyk-deps.json`、`docs/plan/report/<日期>-snyk-code.txt`、Snyk 截圖 |

---

## 1. 目標與結束時可看到

**目標：** 讓「產品改名了」這件事自己走完一圈——貼一則 changelog，系統自己找到受影響的教學、自己改內容、自己升版、自己把功能改名，畫面上看得到 Step 3 的文字變了。再加上 Snyk 掃過、彩排跑順。

結束時，在 Streamlit 上按兩個按鈕，評審會看到：

1. **左欄**：貼上 `Cancel Order has been renamed to Cancel Purchase.` → 按「入庫」→ 顯示「Release #N 已入庫，processed_at 空」。
2. **中欄**：按「處理 Release」→ 顯示
   - 受影響 Tutorial：`tutorials/cancel-order.md`（來自 HydraDB 多跳，不是硬寫）
   - 決定的動作：`UPDATE`
   - **Step 3 diff**：左 `Step 3: Click "Cancel Order"` ／ 右 `Step 3: Click "Cancel Purchase"`
3. **中欄下方**：`Feature.name` 從 `Cancel Order` 變成 `Cancel Purchase`；Tutorial 版本從 v2 變 v3（或 v1→v2）。
4. **再按一次「處理 Release」→ 什麼都不變**（`processed_at` 已有值）。
5. **終端機**：`snyk test` 與 `snyk code test` 各跑一次，0 個 high／critical；`git status` 看不到 `.env`。
6. **彩排**：`uv run python scripts/demo_rehearsal.py --reset` 之後，六步在 5 分鐘內跑完。

不做的事（Non-Goal，寫程式時不要手滑）：

- Release Note **不 CREATE** Tutorial。
- 不新增第 10 張表、不新增「上次檢查時間」欄位（cursor 走 `.state/last_checked.json`）。
- 不做人工審核、不做 Release 專屬頁面、不發明 RocketRide `release` 節點。
- RETIRE 不刪 `.md` 檔、不改 `current_version`。

---

## 2. 在整體迴圈的位置

```text
 t=0                                                                    t=8h
 |----------|----------|----------|----------|----------|--------------|
 | Phase 0  | Phase 1  | Phase 2  | Phase 3  | Phase 4  |   Phase 5    |
 | 環境與骨架 | 種子建圖  | 餵票/轉真人| CREATE v1 | deflect  | Release      |
 |          | (切片A)  | (切片B)   | (切片C)   | +Rote    | UPDATE/RETIRE|
 |          |          |          |          | +REFINE  | +Snyk        |
 |          |          |          |          | (切片D/E) | +彩排(切片F)  |
 |----------|----------|----------|----------|----------|--------------|
                                                          ^ 本檔
 資料狀態沿著時間軸長大：
   Ticket 0 → 2/類(種子) → 3(escalated→resolved) → 4(deflected) → 5(replay)
   Tutorial  ─────────────────── v1(CREATE) ──── v2(REFINE) ── v3(UPDATE)
   Feature.name  "Cancel Order" ───────────────────────────── "Cancel Purchase"
   Release   ───────────────────────────────────────────── 1 列(入庫→已處理)

 Phase 5 是唯一會「回頭改已發布教學內容」的 phase：
 前五個 phase 都在往前長，本 phase 證明它會因為外部世界變了而自我修正。
```

---

## 3. 流程圖

### 3.1 決策樹：changelog → Release → ReleaseFeatureChange → 多跳 → UPDATE / RETIRE

```text
   data/script/changelog.json   或   Streamlit 左欄貼上的文字
                 |
                 v
   +--------------------------------------------------+
   | poll_changelog(last_checked)                     |   Feature: 輪詢ReleaseNote
   |  1. created_at > last_checked ?  ── 否 ──> 丟掉  |   (等於也丟掉, Rule 1)
   |  2. is_duplicate_release(content, created_at) ?  |
   |        ── 是 ──> 不新增 (Rule 3)                 |
   |  3. INSERT Release(processed_at = NULL) (Rule 2) |
   |  4. 更新 .state/last_checked.json                |
   +--------------------------------------------------+
                 |
                 v  （入庫 ≠ 處理；showme §7.3）
   +--------------------------------------------------+
   | process_unprocessed_releases()                   |   Feature: 依ReleaseNote更新Tutorial
   | SELECT * FROM Release WHERE processed_at IS NULL |   (Rule 10: 有值的不撈)
   +--------------------------------------------------+
                 |  逐列
                 v
        LLM 擷取 {feature_name, change_type, from_name, to_name}
                 |
        +--------+--------------------------+
        | 擷取不到 change_type              |
        v                                   v
   OperationFailed                    在 Feature 表比對 feature_name
   processed_at 保持 NULL                    |
   本列跳過，下輪可重跑              +--------+---------+
                                     | 對不到 Feature   |  對到 feature_id
                                     v                  v
                          只寫 processed_at        INSERT ReleaseFeatureChange
                          (Rule 9)                 (Rule 4)
                                                        |
                                                        v
                                          HydraDB 寫邊 (Release)-[:changes]->(Feature)
                                                        |
                                                        v
                                      多跳查受影響 Tutorial（見 3.2；Rule 5）
                                          WHERE Tutorial.feature_id = 命中的 feature_id
                                                        |
                        +-------------------------------+------------------------------+
                        | 沒有 Tutorial                  | 有 Tutorial                  |
                        v                                v                              |
                 只寫 processed_at            decide_release_action(change_type)         |
                 動作為空 (Rule 8/9)                      |                              |
                                        +----------------+----------------+             |
                                        | renamed/changed | deprecated/removed | new    |
                                        v                 v                    v        |
                                     UPDATE             RETIRE               None       |
                                     (Rule 6)           (Rule 7)            (Rule 8)    |
                                        |                 |                    |        |
                                        +--------+--------+--------------------+--------+
                                                 v
                                      UPDATE Release SET processed_at = now
```

### 3.2 HydraDB 多跳：哪些教學受這次 Release 影響

```text
                    [:changes]                    [:explains]
   (Release #1) ───────────────► (Feature id=1) ◄──────────────── (Tutorial #1)
    content: "Cancel Order        name: "Cancel Order"             path: tutorials/
     has been renamed to          status: active                     cancel-order.md
     Cancel Purchase."                    ▲
    processed_at: NULL                    │ [:explains]
                                          │
                                   (Tutorial #2  ← 不命中，feature_id=2)

   Cypher（showme §10 原文）：
     MATCH (r:Release)-[:changes]->(f:Feature)<-[:explains]-(t:Tutorial)
     WHERE r.processed_at IS NULL
     RETURN t

   被 UPDATE 之後圖上多一條：
     (TutorialVersion v3) ─[:supersedes]─► (TutorialVersion v2)
```

### 3.3 版本鏈：v1 → v2 → v3（快照，不是 diff）

```text
  TutorialVersion(tutorial_id=1)
  ┌───────────────────────────────────────────────────────────────────────┐
  │ v1  steps: Step 3: Click "Cancel Order"                               │
  │     reason: (空)              supersedes_version: (空)   ← v1 必空     │
  │     ▲                                                                 │
  │     │ supersedes                                                      │
  │ v2  steps: Step 3: Click "Cancel Order"（REFINE 只補說明，沒改按鈕名） │
  │     reason: "Repeated feedback indicates Step 3 lacks context."       │
  │     supersedes_version: v1                            ← Phase 4 產生   │
  │     ▲                                                                 │
  │     │ supersedes                                                      │
  │ v3  steps: Step 3: Click "Cancel Purchase"            ← 本 Phase 產生  │
  │     reason: "Cancel Order has been renamed to Cancel Purchase."       │
  │     supersedes_version: v2                                            │
  └───────────────────────────────────────────────────────────────────────┘

  Tutorial（只存身分與狀態，不存內容）
      current_version: v2 ──► v3
      is_possibly_outdated: (處理中 true) ──► false
      is_obsolete: false
      last_action: REFINE ──► UPDATE
      status: published（UPDATE 不改）

  RETIRE 走另一條，不產新版本：
      current_version 不動 │ status → retired │ is_obsolete → true
      is_possibly_outdated → false │ last_action → RETIRE
      Feature.status → deprecated | removed
```

### 3.4 Demo 彩排時間軸（目標 ≤ 5 分鐘）

```text
  0s                60s               120s              180s        240s   275s
  ├─────────────────┼─────────────────┼─────────────────┼───────────┼──────┤
  │ ①種子建圖 25s   │                 │                 │           │      │
  │      │ ②餵3張→轉真人→CREATE v1 60s │                 │           │      │
  │      │          │  │ ③第4張 deflect＋Rote捕捉 40s    │           │      │
  │      │          │  │       │ ④第5張 重放 replay=1 25s│           │      │
  │      │          │  │       │       │ ⑤Review REFINE v2 2.9→4.4 45s     │
  │      │          │  │       │       │         │ ⑥貼Release UPDATE v3 50s│
  │      │          │  │       │       │         │           │ ⑦三指標 30s │
  └─────────────────┴─────────────────┴─────────────────┴───────────┴──────┘
     累計 25        85               125     170          220        275s
                                                        剩 25s buffer

  評審拍照點：③(deflected 第一次) ⑥(Step 3 diff) ⑦(三條指標)
```

---

## 4. 🖐️ 需要你手動做的事

| # | 事項 | 指令／連結 | 完成判準 |
|---|---|---|---|
| M1 | 🖐️ 手動：註冊 Snyk 免費帳號 | https://app.snyk.io/signup?utm_source=evt_260101_aiseceng_meetups_amer_sf_2026&utm_medium=aisecurity-engineer&utm_campaign=sfhackathon | 能登入 app.snyk.io |
| M2 | 🖐️ 手動：安裝 Snyk CLI（**不要用 npm，node 被封鎖**） | `brew tap snyk/tap && brew install snyk` | `snyk --version` 有輸出 |
| M2b | 🖐️ 手動：M2 失敗時改官方二進位 | `curl -Lo /usr/local/bin/snyk https://downloads.snyk.io/cli/stable/snyk-macos-arm64 && chmod +x /usr/local/bin/snyk` | 同上 |
| M3 | 🖐️ 手動：登入 CLI | `snyk auth`（開瀏覽器 OAuth）；CI 用 `export SNYK_TOKEN=...` | `snyk auth` 顯示 authenticated |
| M4 | 🖐️ 手動：匯出依賴清單給 Snyk（uv 專案） | `uv export --format requirements-txt --no-hashes > requirements.txt` | 檔案存在且有套件列 |
| M5 | 🖐️ 手動：掃依賴 | `snyk test --file=requirements.txt --severity-threshold=high --json > docs/plan/report/$(date +%Y%m%d)-snyk-deps.json` | exit code 0（0 個 high/critical） |
| M6 | 🖐️ 手動：掃原始碼（Snyk Code） | `snyk code test --severity-threshold=high 2>&1 \| tee docs/plan/report/$(date +%Y%m%d)-snyk-code.txt` | 無 high/critical |
| M7 | 🖐️ 手動：截圖 Snyk 網頁儀表板與 CLI 輸出，存 `docs/plan/report/` | — | 兩張圖在 report 目錄 |
| M8 | 🖐️ 手動：確認 `.env` 沒進 git | `git status --porcelain \| grep '\.env'`（應無輸出）＋ `git check-ignore -v .env`（應命中 `.gitignore`） | 兩者都符合 |
| M9 | 🖐️ 手動：確認 `.state/`、`requirements.txt` 是否要進 git | `cat .gitignore` | `.state/` 建議 ignore |
| M10 | 🖐️ 手動：RocketRide deploy **只用** `ROCKETRIDE_DEPLOY_URI` / `ROCKETRIDE_DEPLOY_APIKEY` | 依 Phase 2 的 deploy 步驟；**絕不 deploy 到 dev 連線** | deploy log 顯示 deploy endpoint |
| M11 | 🖐️ 手動：Phase 2 若尚未 deploy，在此做最後一次 deploy 並複測一則 Release | 同上 | Agent 回應正常 |
| M12 | 🖐️ 手動：彩排前把 `.state/`、`tutorials/`、9 表清乾淨 | `uv run python scripts/reset_demo.py --yes` | 見 §8 重置清單 |
| M13 | 🖐️ 手動：彩排至少實跑 2 次並記秒數 | 碼錶 | 兩次都 ≤ 5 分鐘 |

> `snyk test` 的 exit code：`0` 沒有漏洞、`1` 找到漏洞、`2` 執行失敗（加 `-d` 除錯）、`3` 沒有支援的專案。CI／驗收只接受 `0`。

---

## 5. 實作步驟

依序做。每步做完就能單獨驗一次，不要一路寫到底再跑。

### S1. `app/analytics/sql.py` — Release 相關 SQL（約 8 分）

只加常數，不加邏輯。9 表形狀不變。

```python
# --- 輪詢入庫 -------------------------------------------------------------
SQL_RELEASE_EXISTS = """
SELECT id FROM Release
WHERE content = :content AND created_at = :created_at
"""

SQL_INSERT_RELEASE = """
INSERT INTO Release (content, created_at, processed_at)
VALUES (:content, :created_at, NULL)
"""

# --- 處理 ---------------------------------------------------------------
SQL_UNPROCESSED_RELEASES = """
SELECT id, content, created_at
FROM Release
WHERE processed_at IS NULL OR processed_at = ''
ORDER BY created_at, id
"""

SQL_MARK_RELEASE_PROCESSED = """
UPDATE Release SET processed_at = :now WHERE id = :release_id
"""

SQL_ALL_FEATURES = "SELECT id, name, status FROM Feature ORDER BY id"

SQL_INSERT_RELEASE_FEATURE_CHANGE = """
INSERT INTO ReleaseFeatureChange (release_id, feature_id, change_type, from_name, to_name)
VALUES (:release_id, :feature_id, :change_type, :from_name, :to_name)
"""

# 受影響 Tutorial：規格 Rule 只寫「依 Tutorial.feature_id」，不加 status 過濾
SQL_TUTORIALS_BY_FEATURE = """
SELECT tutorial_id, feature_id, path, status, current_version,
       is_possibly_outdated, is_obsolete, last_action
FROM Tutorial
WHERE feature_id = :feature_id
ORDER BY tutorial_id
"""

# HydraDB 不通時的降級（§7）
SQL_TUTORIALS_BY_FEATURE_IN = """
SELECT tutorial_id, feature_id, path FROM Tutorial
WHERE feature_id IN :feature_ids
"""

SQL_VERSION_ROW = """
SELECT tutorial_id, tutorial_version, title, problem, prerequisites,
       steps, expected_outcome, reason, supersedes_version, created_at
FROM TutorialVersion
WHERE tutorial_id = :tutorial_id AND tutorial_version = :tutorial_version
"""

SQL_INSERT_VERSION = """
INSERT INTO TutorialVersion
  (tutorial_id, tutorial_version, title, problem, prerequisites,
   steps, expected_outcome, reason, supersedes_version, created_at)
VALUES
  (:tutorial_id, :tutorial_version, :title, :problem, :prerequisites,
   :steps, :expected_outcome, :reason, :supersedes_version, :created_at)
"""

SQL_TUTORIAL_APPLY_UPDATE = """
UPDATE Tutorial
SET current_version = :new_version,
    is_possibly_outdated = 0,
    last_action = 'UPDATE'
WHERE tutorial_id = :tutorial_id
"""

SQL_TUTORIAL_MARK_OUTDATED = """
UPDATE Tutorial SET is_possibly_outdated = 1 WHERE tutorial_id = :tutorial_id
"""

SQL_TUTORIAL_APPLY_RETIRE = """
UPDATE Tutorial
SET status = 'retired',
    is_obsolete = 1,
    is_possibly_outdated = 0,
    last_action = 'RETIRE'
WHERE tutorial_id = :tutorial_id
"""

SQL_FEATURE_RENAME = "UPDATE Feature SET name = :name WHERE id = :feature_id"
SQL_FEATURE_SET_STATUS = "UPDATE Feature SET status = :status WHERE id = :feature_id"
```

**驗：** `python3 -c "import app.analytics.sql"` 不炸；`run_sql(SQL_UNPROCESSED_RELEASES, {})` 回空 list。

### S2. `app/agent/rules.py` — 兩個純函式（約 5 分）

純函式、零 I/O，這是單元測試唯一測得準的地方。

```python
RELEASE_ACTION = {
    "renamed": "UPDATE",
    "changed": "UPDATE",
    "deprecated": "RETIRE",
    "removed": "RETIRE",
    "new": None,
}

def decide_release_action(change_type: str) -> str | None:
    """renamed/changed -> 'UPDATE'；deprecated/removed -> 'RETIRE'；new -> None。
    其他值（含空字串）視為擷取失敗，由呼叫端丟 OperationFailed。"""
    if change_type not in RELEASE_ACTION:
        raise KeyError(change_type)
    return RELEASE_ACTION[change_type]


def is_duplicate_release(content: str, created_at: str, existing: list[dict]) -> bool:
    """content 與 created_at 都相同才算重複（輪詢ReleaseNote Rule 3）。"""
    return any(r["content"] == content and r["created_at"] == created_at
               for r in existing)


def is_after_cursor(created_at: str, last_checked: str) -> bool:
    """嚴格大於。剛好等於上次檢查時間的列不入庫（Rule 1 的 Example 明寫）。"""
    return created_at > last_checked          # ISO 8601 字串可直接比大小
```

**驗：** 直接跑 §S9 的單元測試前半。

### S3. `data/script/changelog.json` ＋ `app/ingest/poll.py`（約 10 分）

`data/script/changelog.json`（demo 劇本，三列剛好覆蓋 Rule 1 的三種情況）：

```json
[
  {"content": "Cancel Order has been renamed to Cancel Purchase.", "created_at": "2026-09-11T14:30:00Z"},
  {"content": "Track Refund is a new feature.",                    "created_at": "2026-09-11T14:31:00Z"}
]
```

`app/ingest/poll.py`：

```python
import json, pathlib
from app.analytics import sql
from app.analytics.hotdata_client import run_sql
from app.agent.rules import is_duplicate_release, is_after_cursor
from app.errors import OperationFailed

STATE = pathlib.Path(".state/last_checked.json")
SCRIPT = pathlib.Path("data/script/changelog.json")


def read_cursor(default: str = "1970-01-01T00:00:00Z") -> str:
    if STATE.exists():
        return json.loads(STATE.read_text())["last_checked"]
    return default


def write_cursor(value: str) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"last_checked": value}))


def poll_changelog(last_checked: str | None = None,
                   rows: list[dict] | None = None) -> list[dict]:
    """rows 為 None 時讀 data/script/changelog.json；
    Streamlit 貼上的文字由呼叫端包成 [{'content':…, 'created_at':…}] 傳進來。
    回傳這次新入庫的 Release 列。"""
    cursor = last_checked or read_cursor()
    rows = rows if rows is not None else json.loads(SCRIPT.read_text())

    existing = run_sql("SELECT content, created_at FROM Release", {})
    inserted, newest = [], cursor
    for row in rows:
        if not is_after_cursor(row["created_at"], cursor):      # Rule 1
            continue
        if is_duplicate_release(row["content"], row["created_at"], existing):  # Rule 3
            continue
        run_sql(sql.SQL_INSERT_RELEASE, row)                    # Rule 2：processed_at 空
        existing.append(row)
        inserted.append(row)
        newest = max(newest, row["created_at"])
    write_cursor(newest)
    return inserted
```

失敗語意：`run_sql` 拋錯就讓它往上冒成 `OperationFailed`（`hotdata_client` 已包），cursor 不更新，下輪可重跑（showme §14）。

**驗：**
```bash
uv run python -c "from app.ingest.poll import poll_changelog; print(poll_changelog('2026-09-11T00:00:00Z'))"
uv run python -c "from app.analytics.hotdata_client import run_sql; print(run_sql('SELECT * FROM Release',{}))"
```
預期：兩列，`processed_at` 都是 NULL。再跑一次 → 不新增（Rule 3）。

### S4. LLM 擷取（約 10 分）

放在 `app/agent/release_update.py` 內或 `app/agent/llm.py`（沿用 Phase 3 建立 Tutorial 的同一個 `llm_bedrock` 呼叫入口）。**兩個 prompt**，都要求純 JSON、禁止臆測。

**Prompt A — 擷取產品變更：**

```text
你是產品 Release Note 擷取器。只輸出一個 JSON 物件，不要任何解釋、不要 markdown code fence。

已知 Feature 清單（id | name | status）：
{feature_table}

Release Note 本文：
{content}

輸出 schema：
{"feature_name": "", "change_type": "", "from_name": "", "to_name": ""}

規則：
- change_type 只能是 new / changed / renamed / deprecated / removed 其中之一。
- feature_name 必須逐字等於上面清單中的既有 name；更名時填「舊名稱」。
- 清單裡對不到任何 name 時，feature_name 輸出空字串。
- 只有 renamed 才填 from_name（舊名）與 to_name（新名）；其餘一律空字串。
- 本文沒寫的變更不得臆測；判斷不出 change_type 時輸出空字串。
```

對 demo 那一則，期望輸出：
```json
{"feature_name": "Cancel Order", "change_type": "renamed",
 "from_name": "Cancel Order", "to_name": "Cancel Purchase"}
```

**Prompt B — 把舊名換成新名（產生新版本五欄）：**

```text
你是教學文件維護器。把下面這篇教學裡的舊功能名稱換成新名稱，其餘一字不改。

舊名稱：{from_name}
新名稱：{to_name}

目前版本內容（JSON）：
{current_version_json}

只輸出一個 JSON 物件，欄位固定為：
{"title": "", "problem": "", "prerequisites": "", "steps": "", "expected_outcome": ""}

規則：
- 不得新增或刪除任何步驟，不得改寫語氣或重排順序。
- 只替換功能名稱字面（含被引號包住的按鈕名，例如 Click "Cancel Order"）。
- 五個欄位都必須有值，任一為空即視為失敗。
```

`change_type = changed`（非 renamed、沒有 from/to）時，Prompt B 改成「依 Release 本文調整受影響段落，其餘不動」，`reason` 一樣填 Release.content。

**驗：** 先不接 DB，單獨呼叫兩個 prompt，把 demo 那則與 v2 的 steps 丟進去，確認輸出 JSON 可 `json.loads`，且 `steps` 含 `Click "Cancel Purchase"`。

### S5. `app/memory/hydradb_client.py` — `cypher()` 與三段查詢（約 8 分）

> **事實提醒：** `.rocketride/schema/db_hydradb.json` 的節點只提供 `store` / `recall_memory`（自然語言檢索，描述明寫 "no embeddings or query language required"），**沒有 cypher action**。OpenCypher 多跳要由 `app/memory/hydradb_client.py` 直接對 HydraDB 連線送，不經 RocketRide 節點。RocketRide 那條 pipeline 仍可用 `db_hydradb` 做 recall；兩者不衝突。

```python
def cypher(query: str, params: dict | None = None) -> list[dict]:
    """對 HydraDB 送 OpenCypher。連線失敗一律 raise OperationFailed，
    由呼叫端決定是否走 §7 的 SQL 降級。"""
```

三段查詢：

```cypher
-- (a) 寫 changes 邊（處理每一列 Release 時）
MERGE (r:Release {id: $release_id})
  SET r.content = $content, r.created_at = $created_at
MERGE (f:Feature {id: $feature_id})
MERGE (r)-[c:changes]->(f)
  SET c.change_type = $change_type, c.from_name = $from_name, c.to_name = $to_name
```

```cypher
-- (b) 多跳：這次 Release 影響哪些 Tutorial（showme §10 原文）
MATCH (r:Release)-[:changes]->(f:Feature)<-[:explains]-(t:Tutorial)
WHERE r.processed_at IS NULL
RETURN t.tutorial_id AS tutorial_id, t.path AS path, f.id AS feature_id
```

```cypher
-- (b') 單列版（處理迴圈裡實際用這個，避免撈到別列的結果）
MATCH (r:Release {id: $release_id})-[:changes]->(f:Feature)<-[:explains]-(t:Tutorial)
RETURN t.tutorial_id AS tutorial_id, t.path AS path, f.id AS feature_id
```

```cypher
-- (c) UPDATE 後補 supersedes 邊
MATCH (nv:TutorialVersion {tutorial_id: $tutorial_id, tutorial_version: $new_version})
MATCH (ov:TutorialVersion {tutorial_id: $tutorial_id, tutorial_version: $old_version})
MERGE (nv)-[:supersedes]->(ov)
```

**驗：** 手動先跑 (a) 再跑 (b)，回傳應含 `tutorial_id=1 / path=tutorials/cancel-order.md`，且 **不含** `tutorials/track-refund.md`（Rule 5）。

### S6. `app/agent/release_update.py` — 主流程（約 15 分）

```python
from datetime import datetime, timezone

from app.analytics import sql
from app.analytics.hotdata_client import run_sql
from app.agent.rules import decide_release_action
from app.agent.llm import extract_release_change, rewrite_version_fields
from app.memory import hydradb_client, cognee_client
from app.errors import OperationFailed


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_version(current: str) -> str:
    return f"v{int(current.lstrip('v')) + 1}"


def process_unprocessed_releases(now: str | None = None) -> dict:
    """處理所有 processed_at 為空的 Release。
    回傳 {'decisions': [{'release_id','tutorial_id','action'}...], 'failed': [...]}。
    一列失敗不影響其他列；全部跑完後若有 failed 則 raise OperationFailed。"""
    now = now or _now()
    releases = run_sql(sql.SQL_UNPROCESSED_RELEASES, {})   # Rule 10：有值的撈不到
    features = run_sql(sql.SQL_ALL_FEATURES, {})
    decisions, failed = [], []

    for rel in releases:
        try:
            decisions += _process_one(rel, features, now)
        except OperationFailed as exc:                     # processed_at 保持空
            failed.append({"release_id": rel["id"], "error": str(exc)})

    if failed:
        raise OperationFailed(f"操作失敗：{failed}")
    return {"decisions": decisions, "failed": failed}


def _process_one(rel: dict, features: list[dict], now: str) -> list[dict]:
    change = extract_release_change(rel["content"], features)   # Prompt A（失敗→regex 降級）
    change_type = change.get("change_type") or ""
    try:
        action = decide_release_action(change_type)              # Rule 6/7/8
    except KeyError:
        raise OperationFailed(f"擷取不到 change_type：release_id={rel['id']}")

    feature = _match_feature(change.get("feature_name"), features)
    if feature is None:                                          # Rule 9
        run_sql(sql.SQL_MARK_RELEASE_PROCESSED, {"release_id": rel["id"], "now": now})
        return []

    run_sql(sql.SQL_INSERT_RELEASE_FEATURE_CHANGE, {             # Rule 4
        "release_id": rel["id"], "feature_id": feature["id"],
        "change_type": change_type,
        "from_name": change.get("from_name") or "",
        "to_name": change.get("to_name") or "",
    })
    _write_changes_edge(rel, feature, change)                    # HydraDB (a)

    tutorials = _affected_tutorials(rel["id"], feature["id"])    # HydraDB (b')，降級見 §7
    results = []
    for tut in tutorials:
        if action == "UPDATE":
            _apply_update(tut, feature, rel, change, now)
            results.append({"release_id": rel["id"], "tutorial_id": tut["tutorial_id"],
                            "action": "UPDATE"})
        elif action == "RETIRE":
            _apply_retire(tut, feature, change_type)
            results.append({"release_id": rel["id"], "tutorial_id": tut["tutorial_id"],
                            "action": "RETIRE"})
        # action is None（new）：不決定動作，什麼都不寫（Rule 8）

    run_sql(sql.SQL_MARK_RELEASE_PROCESSED, {"release_id": rel["id"], "now": now})
    return results
```

**`_apply_update` 寫入清單（順序固定，缺一不可）：**

| # | 目標 | 內容 |
|---|---|---|
| 1 | `Tutorial` | `is_possibly_outdated = true`（同一次處理內先標，Rule 6 的說明行） |
| 2 | LLM Prompt B | 讀 `current_version` 五欄 → 舊名換新名；五欄任一為空 → `OperationFailed` |
| 3 | `TutorialVersion` | `tutorial_version = vN+1`、五欄、`reason = Release.content`、`supersedes_version = 舊 current_version`、`created_at = now` |
| 4 | `Tutorial` | `current_version = vN+1`、`is_possibly_outdated = false`、`last_action = 'UPDATE'`（`status` 維持 published） |
| 5 | `Feature` | `renamed` 時 `name = to_name`；`changed` 時不改 name；`status` 不動 |
| 6 | `.md` | 用新版五欄重寫 `Tutorial.path`（沿用 Phase 3 的 writer；五欄缺一則檔與表都不寫） |
| 7 | Cognee | `remember()` 新版全文 |
| 8 | HydraDB | Cypher (c) 補 `supersedes` 邊 |
| 9 | `Release` | `processed_at = now`（由 `_process_one` 收尾做） |

**`_apply_retire` 寫入清單：**

| # | 目標 | 內容 |
|---|---|---|
| 1 | `Tutorial` | `status = 'retired'`、`is_obsolete = true`、`is_possibly_outdated = false`、`last_action = 'RETIRE'`；**`current_version` 不動、不產新版本** |
| 2 | `Feature` | `status = 'deprecated'` 或 `'removed'`（直接用 change_type） |
| 3 | `.md` | **不動**（規格沒寫要刪或加標記，不腦補） |
| 4 | `Release` | `processed_at = now` |

不變條件自我檢查（寫完後 assert）：`is_obsolete = true` ⇒ `is_possibly_outdated = false` ∧ `status = 'retired'` ∧ `last_action = 'RETIRE'`。

**與 REFINE 的衝突：** 同一 Tutorial 在同一輪同時命中 UPDATE 與 REFINE 時 **先 UPDATE**，REFINE 等下一輪（showme §7.4）。實作上 Phase 4 的 `feedback_review()` 開頭加一行：`if tutorial['is_possibly_outdated'] or 本輪已 UPDATE: 本輪 KEEP`。

**驗：**
```bash
uv run python -c "from app.agent.release_update import process_unprocessed_releases as p; print(p())"
```

### S7. `app/demo/streamlit_app.py` — 貼 changelog ＋ Step 3 diff（約 10 分）

左欄（沿用既有 `st.columns` 版面，不新增分頁）：

```python
with left:
    st.subheader("貼 changelog")
    text = st.text_area("Release Note 一則",
                        value='Cancel Order has been renamed to Cancel Purchase.')
    if st.button("入庫"):
        rows = [{"content": text.strip(), "created_at": iso_now()}]
        inserted = poll_changelog(rows=rows)
        st.success(f"入庫 {len(inserted)} 列，processed_at 空") if inserted \
            else st.info("沒有新列（重複或早於上次檢查時間）")
```

中欄：

```python
with mid:
    if st.button("處理 Release"):
        before = load_current_version(TUTORIAL_ID)     # 處理前的五欄快照
        try:
            result = process_unprocessed_releases()
            st.session_state["release_result"] = (before, result)
        except OperationFailed as exc:
            st.error(f"操作失敗：{exc}")

    if "release_result" in st.session_state:
        before, result = st.session_state["release_result"]
        after = load_current_version(TUTORIAL_ID)
        st.write("受影響 Tutorial 與動作：", result["decisions"])
        c1, c2 = st.columns(2)
        c1.caption(f"{before['tutorial_version']}（舊）"); c1.code(before["steps"], language="text")
        c2.caption(f"{after['tutorial_version']}（新）");  c2.code(after["steps"],  language="text")
        st.caption("行級 diff")
        st.code("\n".join(difflib.unified_diff(
            before["steps"].splitlines(), after["steps"].splitlines(),
            fromfile=before["tutorial_version"], tofile=after["tutorial_version"],
            lineterm="")), language="diff")
        st.write("Feature 目前名稱：", load_feature_name(FEATURE_ID))
```

UI 只觸發、只展示；門檻與決策全在 `release_update.py`（showme §13）。

**驗：** `uv run streamlit run app/demo/streamlit_app.py` → 貼 → 入庫 → 處理 → 兩欄並排看到 `Cancel Order` vs `Cancel Purchase`。

### S8. `tests/unit/test_release.py`（約 8 分）

只測純函式與寫入清單（不打外部服務；LLM 與 HydraDB 以 fake 取代）。對齊的 Rule 見 §6。

```python
import pytest
from app.agent.rules import decide_release_action, is_duplicate_release, is_after_cursor

def test_cursor_strictly_greater():          # 輪詢 Rule 1
    assert not is_after_cursor("2026-09-11T10:00:00Z", "2026-09-11T10:00:00Z")
    assert not is_after_cursor("2026-09-11T09:00:00Z", "2026-09-11T10:00:00Z")
    assert     is_after_cursor("2026-09-11T10:30:00Z", "2026-09-11T10:00:00Z")

def test_duplicate_needs_both_fields():      # 輪詢 Rule 3
    existing = [{"content": "A", "created_at": "T1"}]
    assert     is_duplicate_release("A", "T1", existing)
    assert not is_duplicate_release("A", "T2", existing)
    assert not is_duplicate_release("B", "T1", existing)

@pytest.mark.parametrize("ct,expected", [
    ("renamed", "UPDATE"), ("changed", "UPDATE"),
    ("deprecated", "RETIRE"), ("removed", "RETIRE"), ("new", None),
])
def test_decide_release_action(ct, expected):   # 更新 Rule 6/7/8
    assert decide_release_action(ct) == expected

def test_unknown_change_type_raises():         # 失敗語意
    with pytest.raises(KeyError):
        decide_release_action("")
```

再加四個以 fake client 驗寫入清單的測試：`test_update_writes_v_next`、`test_retire_invariants`、`test_processed_release_is_skipped`、`test_extract_failure_keeps_processed_at_null`。

**驗：** `uv run pytest tests/unit/test_release.py -q` 全綠。

### S9. 🖐️ 手動：Snyk（約 15 分，見 §4 的 M1–M8）

跑完把兩份輸出放進 `docs/plan/report/`。有 high／critical 時的處理順序：升套件版本 → 若是 transitive 且無新版，記在 report 並向評審說明取捨；**不要**為了過關把依賴刪掉導致 demo 跑不動。

### S10. `scripts/reset_demo.py` ＋ `scripts/demo_rehearsal.py`（約 10 分）

重置要清的東西（**九張表全清，順序照外鍵反向**）：

```text
Feedback → Workflow → ReleaseFeatureChange → Release
        → Ticket → TutorialVersion → Tutorial → UserProblem → Feature
```

加上：

- `.state/*.json`（`last_checked.json`、票的 cursor）
- `tutorials/*.md`
- Cognee dataset：`prune()` 或換 dataset 名（依 Phase 1 的作法，不在本檔發明 API）
- HydraDB：`MATCH (n) DETACH DELETE n`（demo collection 專用，**不要對共用 database 跑**）
- Rote：Play 不刪（重捕捉很花時間），改在 UI 標「本輪重新捕捉」；`Workflow.replay_count` 由清表歸零

`scripts/demo_rehearsal.py` 用 `--step N` 逐步跑、`--all` 一路跑、`--reset` 先重置，每步印出「評審此刻該看到什麼」與耗時秒數。

**驗：** `uv run python scripts/demo_rehearsal.py --reset --all` 一路到底不中斷，總秒數印在最後一行。

---

## 6. 驗收清單

### 6.1 對齊 `輪詢ReleaseNote.feature`（3 Rule）

| Rule | 條文 | 程式 | 測試 | 勾 |
|---|---|---|---|---|
| R1 | 只把 `created_at` 大於上次檢查時間的列寫入 Release（等於不寫） | `rules.is_after_cursor` + `poll.poll_changelog` | `test_cursor_strictly_greater` | [ ] |
| R2 | 寫入的 Release `processed_at` 為空 | `sql.SQL_INSERT_RELEASE`（寫死 NULL） | `test_insert_leaves_processed_at_null` | [ ] |
| R3 | 相同 content + created_at 已存在時不新增列 | `rules.is_duplicate_release` | `test_duplicate_needs_both_fields` | [ ] |

### 6.2 對齊 `依ReleaseNote更新Tutorial.feature`（7 Rule）

| Rule | 條文 | 程式 | 測試 | 勾 |
|---|---|---|---|---|
| R4 | 擷取產品變更並寫入 ReleaseFeatureChange | Prompt A + `SQL_INSERT_RELEASE_FEATURE_CHANGE` | `test_extract_writes_rfc` | [ ] |
| R5 | 只依 `Tutorial.feature_id` 找出受影響 Tutorial | Cypher (b') / `SQL_TUTORIALS_BY_FEATURE` | `test_only_matching_feature_id` | [ ] |
| R6 | renamed／changed → UPDATE（v2、Feature 改名、processed_at、last_action=UPDATE、旗標回 false） | `_apply_update` | `test_update_writes_v_next` | [ ] |
| R7 | deprecated／removed → RETIRE（retired、is_obsolete、Feature.status） | `_apply_retire` | `test_retire_invariants` | [ ] |
| R8 | new feature 且無對應 Tutorial → 不決定動作，只記 processed_at | `decide_release_action('new') is None` | `test_new_feature_no_action` | [ ] |
| R9 | 找不到受影響 Tutorial → 只記錄 processed_at | `_process_one` 的兩個 early return | `test_no_tutorial_only_processed_at` | [ ] |
| R10 | 已有 processed_at 的 Release 不再處理 | `SQL_UNPROCESSED_RELEASES` 的 WHERE | `test_processed_release_is_skipped` | [ ] |

### 6.3 端到端驗收（照任務指定的九步）

- [ ] 貼一則 `Cancel Order has been renamed to Cancel Purchase.` → 按「入庫」
- [ ] `SELECT * FROM Release` → 恰一列，`processed_at` 為空
- [ ] 按「處理 Release」
- [ ] `ReleaseFeatureChange` 有一列：`change_type='renamed'`、`from_name='Cancel Order'`、`to_name='Cancel Purchase'`、`feature_id=1`
- [ ] `TutorialVersion` 出現 **v3**（Phase 4 未 REFINE 時為 **v2**），`steps` 含 `Click "Cancel Purchase"`，`reason` = Release 本文，`supersedes_version` = 前一版
- [ ] `Feature` id=1 的 `name = 'Cancel Purchase'`、`status` 仍 `active`
- [ ] `Tutorial`：`current_version` = 新版、`is_possibly_outdated = false`、`is_obsolete = false`、`status = published`、`last_action = 'UPDATE'`
- [ ] `Release.processed_at` 有值（等於處理當下的系統時間）
- [ ] `tutorials/cancel-order.md` 檔案內容已同步為新版五欄
- [ ] **再按一次「處理 Release」→ 四張表零變化**（R10）
- [ ] 中欄 Step 3 diff 在畫面上肉眼可見
- [ ] `snyk test --file=requirements.txt --severity-threshold=high` exit code 0
- [ ] `snyk code test --severity-threshold=high` 無 high/critical
- [ ] `git status` 看不到 `.env`；`git check-ignore -v .env` 命中
- [ ] 彩排兩次都 ≤ 5 分鐘，六步無中斷

### 6.4 不變條件（RETIRE 路徑另測）

- [ ] `is_obsolete = true` 時，`is_possibly_outdated = false`、`status = 'retired'`、`last_action = 'RETIRE'` 同時成立
- [ ] RETIRE 不產生新的 TutorialVersion、不改 `current_version`
- [ ] UPDATE 後 `status` 仍為 `published`（UPDATE 不會把教學下架）

---

## 7. 降級方案

| 失效 | 訊號 | 降級做法 | 畫面怎麼標 |
|---|---|---|---|
| LLM 擷取失敗（Bedrock 逾時／輸出不是 JSON／`change_type` 空） | `extract_release_change` 拋錯或回空 | 改用 regex 規則式擷取（下方範本），只認 demo 劇本的四種句型 | 中欄顯示「規則式擷取」小標 |
| Prompt B 改寫失敗 | 五欄任一為空 | 用 `str.replace(from_name, to_name)` 對五欄做字面替換 | 同上標「規則式」 |
| HydraDB 不通（`cypher()` 拋 `OperationFailed`） | Cypher 連線錯誤 | 改用 `SQL_TUTORIALS_BY_FEATURE`（`WHERE feature_id = :fid`，或多列時 `feature_id IN (...)`）找受影響 Tutorial；`changes` / `supersedes` 邊事後補寫 | 中欄標「圖譜降級：SQL 命中」 |
| Cognee `remember()` 失敗 | 呼叫拋錯 | catch 後繼續，把失敗的版本記進 `.state/pending_remember.json`，demo 後補 | 不影響 Then 表 |
| hotdata 不可用 | `run_sql` 全失敗 | 同一份 SQL 打本機 Postgres，**表仍是 9 張**（showme §17） | 口頭說明 |
| Snyk CLI 裝不起來（brew 慢／node 被封鎖） | `snyk --version` 失敗 | ① 官方二進位 `curl -Lo snyk https://downloads.snyk.io/cli/stable/snyk-macos-arm64`；② 退而求其次用 app.snyk.io 網頁 Import Git repo 掃，截圖存 report | report 註明用網頁版 |
| Streamlit diff 元件出問題 | 畫面空白 | 改 `st.code` 兩欄並排；再不行 `cat tutorials/cancel-order.md` 給評審看 | 口頭補 |
| Release 處理整批失敗 | `OperationFailed` | `processed_at` 保持空，修完再按一次「處理 Release」即可重跑（冪等來自 R10） | 中欄紅字「操作失敗」 |

**regex 規則式擷取範本（降級用，只認劇本句型）：**

```python
import re

PATTERNS = [
    (re.compile(r'^(?P<from>.+?)\s+has been renamed to\s+(?P<to>.+?)\.?$', re.I), "renamed"),
    (re.compile(r'^(?P<name>.+?)\s+has been deprecated\.?$',               re.I), "deprecated"),
    (re.compile(r'^(?P<name>.+?)\s+has been removed\.?$',                  re.I), "removed"),
    (re.compile(r'^(?P<name>.+?)\s+is a new feature\.?$',                  re.I), "new"),
    (re.compile(r'^(?P<name>.+?)\s+has(?: been)? changed\.?$',             re.I), "changed"),
]

def extract_by_regex(content: str) -> dict:
    for pattern, change_type in PATTERNS:
        m = pattern.match(content.strip())
        if not m:
            continue
        g = m.groupdict()
        if change_type == "renamed":
            return {"feature_name": g["from"], "change_type": "renamed",
                    "from_name": g["from"], "to_name": g["to"]}
        return {"feature_name": g["name"], "change_type": change_type,
                "from_name": "", "to_name": ""}
    return {"feature_name": "", "change_type": "", "from_name": "", "to_name": ""}
```

回空 `change_type` 時照常 `OperationFailed`、`processed_at` 保持空——降級不改變失敗語意。

---

## 8. Demo 彩排腳本與評審 Q&A

### 8.1 一鍵重置清單

| 對象 | 動作 | 指令 |
|---|---|---|
| 9 張表 | 反向外鍵順序全清 | `uv run python scripts/reset_demo.py --yes` |
| `.state/` | 刪 `last_checked.json` 與票 cursor | 同上 |
| `tutorials/` | 刪 `*.md` | 同上 |
| HydraDB | demo collection `MATCH (n) DETACH DELETE n` | 同上（`--graph` 旗標） |
| Cognee | prune 或換 dataset | 同上（`--memory` 旗標） |
| Rote | **不刪 Play**，UI 標「本輪重新捕捉」 | 手動確認 |

### 8.2 彩排腳本（照 `architecture.md` §7 順序）

| 步 | 按哪個按鈕／跑哪個指令 | 評審看到什麼 | 秒 |
|---|---|---|---|
| 0 | 🖐️ 手動：`uv run python scripts/reset_demo.py --yes`（**上台前**跑完，不計時） | 空畫面 | — |
| 1 | 左欄「匯入種子」或 `demo_rehearsal.py --step 1` | 每類 2 張 resolved 票、UserProblem、Feature 出現；HydraDB recall `cancel_order` 有節點 | 25 |
| 2 | 左欄「餵下一張票」×3 → 每次中欄「確認解法」（預填 Bitext response） | 前兩張 escalated、第 3 張湊滿門檻 → `tutorials/cancel-order.md` **v1 published** 出現在中欄 | 60 |
| 3 | 左欄「餵下一張票」（第 4 張 cancel_order） | 中欄變成 **deflected**，回教學連結；Workflow 一列出現，`replay_count = 0`（Rote 捕捉） | 40 |
| 4 | 左欄「餵下一張票」（第 5 張） | 一樣 deflected，但走重放；`replay_count = 1` | 25 |
| 5 | 中欄「Review」 | v1 均分 2.9（種子低分）→ REFINE → **v2**，均分 4.4；下欄均分曲線上揚 | 45 |
| 6 | 左欄貼 `Cancel Order has been renamed to Cancel Purchase.` →「入庫」→ 中欄「處理 Release」 | Release 入庫（processed_at 空）→ 受影響 Tutorial = `cancel-order.md` → **Step 3 diff**：`Click "Cancel Order"` → `Click "Cancel Purchase"`；Feature 改名；**v3** | 50 |
| 7 | 指向下欄（不用按） | deflection rate 2/4 = 0.5、重放解決率 SUM(replay_count)/deflected、圖譜覆蓋 | 30 |
| — | **合計** | | **275s ≈ 4:35**（buffer 25s） |

講稿三句（背這三句就好）：

1. 「第 3 張票之前它只會轉真人；第 4 張開始它自己回答了——這是它學會的第一件事。」
2. 「顧客給低分，它自己改了教學；沒人下指令。」
3. 「產品改名了，它自己找到受影響的教學、自己改了 Step 3——`past outcomes change future behavior`。」

### 8.3 評審 Q&A：五層各在哪裡做事

| 層 | 工具 | 模組／進入點 | 這一層在 demo 哪一步可見 |
|---|---|---|---|
| Memory 建構（Structure） | Cognee | `app/memory/cognee_client.remember()`；種子票、每個新 TutorialVersion、每筆 Feedback、每則 Release 本文各呼叫一次 | 步 1（種子建圖）、步 2（v1）、步 5（v2）、步 6（v3 + Release 本文） |
| Memory 儲存（Memory） | HydraDB | `app/memory/hydradb_client.cypher()`；邊 `asks_about` / `explains` / `refers_to` / `changes` / `supersedes` | 步 3（查「這題有沒有 published 教學」）、**步 6 多跳**「哪些教學受這次 Release 影響」 |
| Live 分析（Insight） | hotdata.dev | `app/analytics/sql.py` + `hotdata_client.run_sql()`；輪詢 `created_at >` cursor、`AVG(rating)`、三條指標 | 步 2（輪詢新票）、步 5（AVG 2.9 判 REFINE）、步 6（撈 processed_at 空）、步 7（三指標） |
| Motion / 協調 | RocketRide | 單一 `agent_rocketride` 三條 pipeline：Ticket Analysis（`app/agent/analyze.py`）／Release Note Update（`app/agent/release_update.py`）／Periodic Feedback Review（`app/agent/feedback_review.py`）；`llm_bedrock` 收五欄與改寫 | 步 2（CREATE）、步 5（REFINE）、步 6（UPDATE） |
| Muscle memory | Modiqo Rote | `app/muscle/`：第一次成功攔截 crystallize 成 Play，之後 `rote play run` 帶新 `ticket_id` | 步 3（捕捉，`replay_count=0`）、步 4（重放，`replay_count=1`） |
| 安全 | Snyk | `snyk test --file=requirements.txt` 掃依賴、`snyk code test` 掃原始碼；輸出在 `docs/plan/report/` | 不在票流內；評審問就開 report 的 JSON 與截圖 |

**預期追問與答法：**

| 問 | 答 |
|---|---|
| 「這是 fine-tuning 嗎？」 | 不是。模型不變，變的是記憶與規則命中的資料：第 4 張票之所以被擋，是因為第 3 張的結果寫進了圖譜。 |
| 「HydraDB 只是個 KV 吧？」 | 步 6 那條是三跳：`(Release)-[:changes]->(Feature)<-[:explains]-(Tutorial)`。SQL 要 join 三張表，圖上是一句 Cypher；而且 `supersedes` 讓版本鏈可回溯。 |
| 「Rote 重放了什麼？」 | 重放的是**攔截流程**（匹配 UserProblem → 取 published Tutorial → 回連結 → 更新票），不是舊答案。教學換版本，重放的流程不用改。 |
| 「Release Note 為什麼不直接產新教學？」 | 規格定案：CREATE 只由票量門檻決定（≥3 張同類且無 published）。Release 只 UPDATE／RETIRE，避免為沒人問的功能生教學。 |
| 「同時要 REFINE 又要 UPDATE 怎麼辦？」 | 先 UPDATE，REFINE 等下一輪；因為內容過期時的評分沒有參考價值。 |
| 「重複處理同一則 Release 會怎樣？」 | 不會怎樣。`processed_at` 有值就撈不到，現場可以當場按第二次給你看。 |
| 「安全呢？」 | `snyk test` 掃依賴、`snyk code test` 掃原始碼，輸出在 `docs/plan/report/`；`.env` 在 `.gitignore`，金鑰沒進 repo。 |
| 「hotdata 掛了怎麼辦？」 | 同一份 SQL 打本機 Postgres，表還是那 9 張，迴圈照跑（§7）。 |

---

## 來源

**專案內部（本次實讀）：**

- `/Users/linjunting/AWS-Hackathon/CLAUDE.md`
- `/Users/linjunting/AWS-Hackathon/docs/design/showme.md`（§6 步驟 10–11、§7.3、§8、§10、§11、§13、§14、§16 切片 F、§17、§19.1）
- `/Users/linjunting/AWS-Hackathon/docs/design/architecture.md`（§7 Demo 現場建議順序）
- `/Users/linjunting/AWS-Hackathon/docs/spec/erm.dbml`（Release、ReleaseFeatureChange、Feature、Tutorial、TutorialVersion）
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/輪詢ReleaseNote.feature`（3 Rule、3 Example）
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/依ReleaseNote更新Tutorial.feature`（7 Rule、8 Example）
- `/Users/linjunting/AWS-Hackathon/docs/hackathon.md`（Snyk 段、Pre-Hackathon checklist）
- `/Users/linjunting/AWS-Hackathon/.rocketride/schema/db_hydradb.json`（節點只有 store／recall_memory，無 cypher action；設定為 api_key / database / collection / max_results）
- `/Users/linjunting/AWS-Hackathon/.rocketride/schema/llm_bedrock.json`（profile：custom 或內建模型；required region／model／modelTotalTokens）

**外部（WebFetch，2026-09-11 查）：**

- Snyk 官方文件查詢介面 https://docs.snyk.io/?ask=snyk%20CLI%20install%20homebrew%20snyk%20auth%20snyk%20test%20snyk%20code%20test%20severity-threshold%20exit%20codes
  → `brew tap snyk/tap && brew install snyk`；`snyk auth`／`SNYK_TOKEN`；`snyk test --severity-threshold=<low|medium|high|critical>`、`--all-projects`、`--json`；`snyk code test`；`snyk monitor`；exit code `0` 無漏洞／`1` 有漏洞／`2` 執行失敗／`3` 無支援專案／`69` 服務不可用／`75` 暫時失敗／`77` 無權限
  （註：`https://docs.snyk.io/snyk-cli` 直接存取為 404，改用官方提供的 `?ask=` 查詢介面）
- Snyk 免費註冊（hackathon 專用連結，出自 `docs/hackathon.md`）https://app.snyk.io/signup?utm_source=evt_260101_aiseceng_meetups_amer_sf_2026&utm_medium=aisecurity-engineer&utm_campaign=sfhackathon
