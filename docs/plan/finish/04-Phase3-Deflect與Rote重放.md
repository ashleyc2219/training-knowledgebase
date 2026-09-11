# Phase 3 — Deflect 與 Rote 重放

> ⚠️ **這只是 hackathon 作品，不要過度設計。** 8 小時內能 demo 迴圈就好：先讓它能跑，再談漂亮。
> 能用最簡單的方式做到驗收條件就停手；不加規格沒寫的欄位、不做抽象層、不為「日後擴充」多寫一行。
> 遇到「這樣夠不夠好」的猶豫時，選最短路徑，並在 report 標記「hackathon 簡化」即可。

## 現況更新（2026-09-11）

- **Phase 0 已實作並驗證**：`uv run pytest -q` 35 passed；Bitext 真實下載（`data/raw/`），`data/seed/bitext_seed.json` 6 筆、`data/script/demo_tickets.json` 9 筆、`feedback_seed.json` 10 筆（avg 2.9）、`feedback_v2_seed.json` 5 筆（avg 4.4）；Streamlit 空殼可啟動；`.env`／`.state/`／`data/raw/` 已 git-ignore。
- **環境事實**：hotdata CLI 已登入（workspace `Hackathon_space`，尚無本專案 database）；`rote whoami` 正常；Cognee 伺服器可用（沿用本機記憶插件的 server，專案另開 dataset）；**沒有** HydraDB 直連憑證與 LLM 金鑰（`.env` 只有 `ROCKETRIDE_*`）。
- **已知偏差（以骨架命名為準）**：hotdata instant database 是 schema-on-load，9 表 DDL 主要用於 SQLite 降級；RocketRide `db_hydradb` 節點沒有 Cypher action，多跳查詢由 `app/memory/hydradb_client.py` 自己做；phase 專屬 SQL 放在該 phase 模組，不回改 `app/analytics/sql.py`；Streamlit 各區以 `app/demo/ui_<x>.py` 的 `render(db)` 提供，最後統一接進 `streamlit_app.py`。
- **共用介面**：`app/agent/llm.py: complete_json(prompt, schema_hint) -> dict`（無金鑰時 raise `LLMUnavailable`，呼叫端用模板降級）；`app/muscle/rote_client.py: on_deflected(db, ticket_id, user_problem_id) -> dict`。

- **對應設計：** `docs/design/showme.md` §16 切片 D、§7.5（Rote 契約）、§7.1（即時路徑）、§12（重放解決率）、§14（重放失敗語意）、§17（Rote 未暖機降級）
- **對應規格：** `docs/spec/features/重放已驗證流程.feature`（3 Rule）、`docs/spec/features/自動回覆顧客.feature`（deflected Rule）、`docs/spec/erm.dbml` 的 `Workflow` / `Ticket`
- **前置：** Phase 2 驗收通過（條件見下）
- **預估時間：** 60–75 分鐘（含 🖐️ 手動暖機 10 分鐘）
- **產出：**
  - `app/muscle/rote_client.py`（新增）
  - `app/muscle/deflect_api.py`（新增；Play 要打的本機 HTTP endpoint）
  - `app/muscle/steps.py`（新增；四步的純 Python 實作，API 與 Agent 共用）
  - `app/agent/realtime.py`（修改；`handle_open_ticket` 加 Rote 分支）
  - `app/analytics/metrics.py`（新增／補上 `replay_rate()`）
  - `app/demo/streamlit_app.py`（修改；中欄標籤＋下欄 `replay_count`）
  - `tests/unit/test_rote_client.py`（新增；fake rote，subprocess mock）
  - 一支本機 Rote Play：`deflect-user-problem`（`~/.rote/flows/` 底下，不進 repo）

> 本檔是**計畫**。撰寫當下 repo 內 `app/`、`tests/`、`tutorials/`、`~/.rote/flows/`、`~/.rote/workspaces/` 都還不存在（2026-09-11 實查：`~/.rote/flows` 與 `~/.rote/workspaces` 為空目錄）。文中所有目錄、檔案、Play 名稱都是待建立，不是已實作。

### 前置條件（Phase 2 驗收要先過）

| # | 條件 | 怎麼確認 |
|---|---|---|
| P2-1 | hotdata `Tutorial` 有一列：`tutorial_id=1`、`feature_id=1`、`user_problem_id=1`、`path=tutorials/cancel-order.md`、`status=published`、`current_version=v1`、`last_action=CREATE` | `SELECT * FROM Tutorial WHERE user_problem_id = 1` |
| P2-2 | hotdata `TutorialVersion(1, 'v1')` 存在且內容五欄皆非空、`supersedes_version` 為空 | `SELECT * FROM TutorialVersion WHERE tutorial_id = 1` |
| P2-3 | 檔案 `tutorials/cancel-order.md` 存在，Step 3 文字是 `Click "Cancel Order"` | `cat tutorials/cancel-order.md` |
| P2-4 | hotdata `UserProblem(id=1, topic='cancel_order', feature_id=1)`、`Feature(id=1, name='Cancel Order', status='active')` | `SELECT * FROM UserProblem; SELECT * FROM Feature` |
| P2-5 | 前 3 張 cancel_order 票為 `escalated` / `resolved`；目前沒有 `deflected` 票 | `SELECT id, status FROM Ticket ORDER BY id` |
| P2-6 | `app/agent/realtime.py:handle_open_ticket(ticket_id)` 已可把第 4 張票判成 `deflected`（尚未接 Rote） | Phase 2 的單元測試綠燈 |
| P2-7 | `app/analytics/hotdata_client.py:run_sql(sql, params)`、`app/errors.py:OperationFailed` 已存在 | `python -c "import app.analytics.hotdata_client"` |

任一條不成立就**不要開始 Phase 3**——Rote 捕捉的前提是「第一次 deflected 真的成功」，沒有 published Tutorial 就只會捕捉到失敗流程。

---

## 1. 目標與結束時可看到

**一句話：** 把 §7.5 的 Rote 契約接上 Phase 2 的即時路徑——**第一次**攔截成功時把方法固化成 Play 並寫下 `Workflow` 一列，**第二次**起直接重放同一支 Play（帶新的 `ticket_id`），`replay_count` 往上跳。

結束時可以看到：

1. Demo 左欄餵**第 4 張** `cancel_order` 票 → 中欄出現 `tutorials/cancel-order.md` 的教學連結，標籤是「**deflected（第一次，已捕捉 Play）**」。
2. hotdata `Workflow` 出現 1 列：`user_problem_id=1`、`replay_count=0`、`captured_at` = 捕捉當下系統時間。
3. `rote play list` 看得到 `deflect-user-problem` 這支 Play。
4. Demo 左欄餵**第 5 張** `cancel_order` 票（`bob@example.com`） → 中欄標籤是「**deflected（Rote 重放）**」，`Workflow.replay_count` 變成 `1`，而且**沒有**再進 LLM 推理。
5. 下欄顯示 `replay_count` 與重放解決率（`SUM(replay_count) / COUNT(deflected)`）。

**不做（Non-Goals，來自 showme §3、§7.5）：** 不重放 `resolution_steps`、不產教學影片、`escalated` 不捕捉 Workflow、不把 Rote 塞進 RocketRide（catalog 沒有 rote 節點，不發明 `tool_rote`）、不把 Play 推到 registry（本機 release 就夠 demo）。

---

## 2. 在整體迴圈的位置

```
 Phase 0        Phase 1        Phase 2        >>> Phase 3 <<<     Phase 4        Phase 5
 環境/骨架  →   A 種子建圖  →  B 餵票轉真人   D deflect + Rote  →  E 指標+REFINE → F Release UPDATE
                               C CREATE v1
 ─────────────────────────────────────────────────────────────────────────────────────────────
 uv / .env      Bitext 2 張    第 3 張湊滿     第 4 張 → 回連結    下欄曲線上升    changelog 更名
 app/ 骨架      UserProblem    tutorials/      Workflow 出現       v1 2.9 → v2     Step 3 diff
 errors.py      Feature        cancel-order    第 5 張 → replay      4.4           Snyk 掃描
 hotdata_client Cognee/Hydra   .md published   _count = 1
 ─────────────────────────────────────────────────────────────────────────────────────────────
                                               ^
                                               │ 本檔範圍：
                                               │  1. Play 打什麼（本機 HTTP adapter）
                                               │  2. capture / replay / has_play
                                               │  3. Workflow 表兩種狀態變化
                                               │  4. 降級：Play 未捕捉 / 重放失敗
```

五層 stack 裡，Phase 3 是**唯一**讓 Muscle memory 層（Modiqo Rote）真的在做事的階段。評審那句「每層都要真的在做事」，Rote 這層的證據就是 §5 第 5–7 步跑出來的 Play 檔與 `replay_count`。

---

## 3. 流程

### 3.1 第 4 張 vs 第 5 張（兩條路徑並排）

```
        ┌──────────── 第 4 張票（ticket_id=4, alice）────────────┐   ┌─────────── 第 5 張票（ticket_id=5, bob）────────────┐
        │                                                        │   │                                                      │
        │  realtime.handle_open_ticket(4)                         │   │  realtime.handle_open_ticket(5)                      │
        │            │                                            │   │            │                                         │
        │            ▼                                            │   │            ▼                                         │
        │  判定 deflected？（自動回覆顧客.feature 5 條 Rule）        │   │  判定 deflected？ ── 同上 ──► 是                       │
        │   user_problem_id 有值 ✓                                 │   │            │                                         │
        │   published Tutorial 有 ✓                                │   │            ▼                                         │
        │   非 retired ✓  非再開票 ✓                                │   │  rote_client.has_play(user_problem_id=1)             │
        │            │                                            │   │            │                                         │
        │            ▼                                            │   │            ▼  True（Workflow 已有列）                  │
        │  rote_client.has_play(user_problem_id=1)                │   │  rote_client.replay_play(1, ticket_id=5)             │
        │            │                                            │   │            │                                         │
        │            ▼  False（Workflow 無列）                      │   │            ▼                                         │
        │  ── Agent 即時路徑（Phase 2 既有）──                       │   │  cd /tmp && rote play run deflect-user-problem \     │
        │   1 匹配 UserProblem                                     │   │              ticket_id=5                             │
        │   2 取 published Tutorial(current_version)                │   │            │                                         │
        │   3 回覆連結                                              │   │            ▼                                         │
        │   4 UPDATE Ticket → deflected                            │   │  驗證 Ticket(5).status == 'deflected'                 │
        │            │                                            │   │            │                                         │
        │            ▼  成功                                       │   │      成功 ─┴─ 失敗                                    │
        │  rote_client.capture_play(1, ticket_id=4)                │   │       │        │                                     │
        │   （workspace → crystallize → Play 存檔，見 3.2）          │   │       ▼        ▼                                     │
        │            │                                            │   │  replay_count  改走 Agent 即時路徑                     │
        │            ▼                                            │   │     + 1        （仍 deflected）                        │
        │  INSERT Workflow(replay_count=0, captured_at=now)        │   │                **不** +1                              │
        │            │                                            │   │            │                                         │
        │            ▼                                            │   │            ▼                                         │
        │  中欄：deflected（第一次，已捕捉 Play）                     │   │  中欄：deflected（Rote 重放）                          │
        └─────────────────────────────────────────────────────────┘   └──────────────────────────────────────────────────────┘
```

重點三條（都直接寫成測試）：

- **捕捉發生在 deflect 成功之後**，不是之前。捕捉失敗不能讓已經 deflected 的票回滾（票的狀態是規格 Then 表，Rote 是附加價值）。
- **重放要先驗證結果**再 `+1`。驗證方式是回 hotdata 讀 `Ticket.status`，不是解析 `rote play run` 的 stdout 文字。
- **`escalated` 完全不碰 Rote**（`重放已驗證流程.feature` Rule 3）。

### 3.2 Rote 生命週期：workspace → crystallize → play run

```
  ┌─ 🖐️ 一次性（Phase 3 第一次跑，或 demo 前暖機）───────────────────────────────────┐
  │                                                                                │
  │  rote whoami                        確認已登入（沒登入就停，不要 rote login 亂試） │
  │  rote play search "deflect ..."     CHECK 1：Play 已經存在就不要重建              │
  │        │ 沒有                                                                    │
  │        ▼                                                                        │
  │  uv run uvicorn app.muscle.deflect_api:app --port 8765     ← Play 要打的東西      │
  │        │                                                                        │
  │        ▼                                                                        │
  │  rote adapter new deflect-api http://127.0.0.1:8765/openapi.json --yes          │
  │        │                                                                        │
  │        ▼                                                                        │
  │  rote init deflect-cancel-order --seq                       workspace 開張        │
  │  cd ~/.rote/workspaces/deflect-cancel-order                                     │
  │  rote model set <model> --provider anthropic --confirmed-current                │
  │        │                                                                        │
  │        ▼   ── 在 workspace 裡把四步真的跑一遍（用第 4 張票）──                      │
  │  rote deflect_api_probe "match user problem for a ticket"                       │
  │  rote deflect_api_call match_user_problem   '{"ticket_id": 4}'          → @1     │
  │  rote deflect_api_call get_published_tutorial '{"user_problem_id": 1}'  → @2     │
  │  rote deflect_api_call reply_tutorial_link  '{"ticket_id": 4, ...}'     → @3     │
  │  rote deflect_api_call mark_deflected       '{"ticket_id": 4, ...}'     → @4     │
  │  rote query @4 '.status' -r                              → deflected（成功證據）  │
  │        │                                                                        │
  │        ▼   ── crystallize：把「方法」抽出來，ticket_id 變參數 ──                    │
  │  rote play pending write deflect-cancel-order --name deflect-user-problem ...   │
  │  rote play pending save  deflect-cancel-order   → 印出 template create 指令       │
  │  <原封不動執行它>  rote play template create --name deflect-user-problem ...      │
  │  rote play validate ~/.rote/flows/deflect-user-problem/main.ts --fix            │
  │  rote play lint    deflect-user-problem                                         │
  │  rote play release deflect-user-problem --keep-local                            │
  │  rote play list --json        → 確認 deflect-user-problem 在列                    │
  └────────────────────────────────────────────────────────────────────────────────┘
                       │
                       ▼  之後每一張同類票（程式自動，不再手動）
  ┌─ 每次重放 ──────────────────────────────────────────────────────────────────────┐
  │  cd /tmp && rote play run deflect-user-problem ticket_id=<新票號>                 │
  │       （一定要從 ~/.rote/workspaces/ 以外的目錄跑，Play 會自建臨時 workspace）       │
  │  Play 用**同一套方法**打同一組 endpoint，但參數是新票號 → 產生新答案，不是舊答案      │
  └────────────────────────────────────────────────────────────────────────────────┘
```

**一支 Play 服務所有 UserProblem。** `Workflow` 是 1:1 `UserProblem`（erm.dbml 已定），但 Play 重的是**方法**，`user_problem_id` 是查出來的、`ticket_id` 是參數。所以不要為 `track_refund` 再 crystallize 第二支 Play——`Workflow` 多一列，Play 還是同一支。這是 Phase 3 能在 75 分鐘內做完的關鍵。

### 3.3 Workflow 表狀態變化

```
 t0  Phase 2 結束                     Workflow: （空）
                                      Ticket:   1,2,3 = escalated/resolved

 t1  第 4 張進來，判 deflected 成功      Ticket:   4 = deflected, deflected_tutorial_id=1, _version=v1
     has_play(1) = False
     → capture_play(1, 4)
                                      Workflow:
                                      ┌────┬─────────────────┬──────────────────────────────────────────────────────┬──────────────────────┬──────────────┐
                                      │ id │ user_problem_id │ steps                                                │ captured_at          │ replay_count │
                                      ├────┼─────────────────┼──────────────────────────────────────────────────────┼──────────────────────┼──────────────┤
                                      │ 1  │ 1               │ 匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket │ 2026-09-11T12:00:00Z │ 0            │
                                      └────┴─────────────────┴──────────────────────────────────────────────────────┴──────────────────────┴──────────────┘

 t2  第 5 張進來，判 deflected 成功      Ticket:   5 = deflected, deflected_tutorial_id=1, _version=v1
     has_play(1) = True
     → replay_play(1, 5) 驗證通過
                                      Workflow:
                                      │ 1  │ 1 │ （不變） │ 2026-09-11T12:00:00Z（不變） │ 1 │
                                                                      ▲                  ▲
                                                     captured_at 永遠不改      每次成功重放 +1

 t3  某張 escalated 的票                Workflow: （不新增、不變動）── Rule 3
```

`captured_at` 只在 `INSERT` 時寫一次（`重放已驗證流程.feature` Rule 2 的 Then 表把 `captured_at` 保留成 `2026-09-11T10:05:00Z`，不是重放當下時間）。這條很容易寫錯成 `UPDATE ... SET captured_at = now`，測試要卡住它。

---

## 4. 🖐️ 需要你手動做的事

| # | 動作 | 指令／操作 | 預期看到 | 卡住怎麼辦 |
|---|---|---|---|---|
| M1 | 🖐️ 手動：確認 Rote 已登入 | `rote whoami` | 印出你的 Rote 身分（帳號／org） | 沒登入就先在自己的終端機處理登入；**不要**讓 agent 代跑 `rote login`。仍不通 → 走 §7 降級 A，Phase 3 其餘照做 |
| M2 | 🖐️ 手動：hello-world 暖機（hackathon 要求「Rote 真的跑過」） | `rote init hello-warmup --seq`，然後 `cd ~/.rote/workspaces/hello-warmup && rote proc run -- echo "rote warm"` | `@1` 有回應，`rote ls` 看得到那筆 | `rote health` 診斷；binary 版本 `rote --version`（本機 0.82.0） |
| M3 | 🖐️ 手動：確認 model identity | `cd ~/.rote/workspaces/<ws> && rote model set <你正在用的模型> --provider anthropic --confirmed-current` | 無錯誤 | UI 顯示什麼就填什麼，不要猜；看不到就跳過，Play 會標 `model: not-captured` |
| M4 | 🖐️ 手動：啟動 Play 要打的本機 API（demo 全程都要開著） | `uv run uvicorn app.muscle.deflect_api:app --port 8765`（另開一個終端機分頁） | `curl -s http://127.0.0.1:8765/openapi.json \| head -c 200` 有 JSON | port 被占用就換 8766，並同步改 `--base-url` 與 `ROTE_DEFLECT_API_BASE` |
| M5 | 🖐️ 手動：建 adapter | `rote adapter new deflect-api http://127.0.0.1:8765/openapi.json --yes` | `rote adapter list` 出現 `deflect-api` | 先 `rote adapter new deflect-api ./openapi.json --dry-run` 看解析結果。仍失敗 → 走 §7 降級 B（`rote proc` 路線） |
| M6 | 🖐️ 手動：跑 §3.2 的 workspace 四步 + crystallize | 見 §5 步驟 5–7 | `rote play list` 有 `deflect-user-problem` | `rote play doctor`、`rote play validate <path> --fix` |
| M7 | 🖐️ 手動：Demo 前煙測一次重放 | `cd /tmp && rote play run deflect-user-problem ticket_id=<一張測試票> --dry-run` | 印出執行計畫、無錯誤 | `--dry-run` 只印計畫不打 API，煙測完記得把那張測試票的狀態改回去 |

> `rote play run` 的 `--yes` 只用在 **registry** 參照；本機 Play 用名稱或絕對路徑跑，不需要也不該加 `--yes`。

---

## 5. 實作步驟

### 步驟 1：四步的純 Python 實作（`app/muscle/steps.py`）

Play 和 Agent 即時路徑必須跑**同一套**四步，否則重放出來的結果會和第一次不一致。先把四步從 `app/agent/realtime.py` 抽成可單獨呼叫的函式。

```python
# app/muscle/steps.py
"""Deflect 四步。Agent 即時路徑與 Rote Play 共用同一份實作。
步驟序列固定：匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket。"""
from app.analytics.hotdata_client import run_sql
from app.errors import OperationFailed

# 規格 Example 逐字定義的 steps 內容；不要改字，Then 表會逐字比對
STEPS_TEXT = "匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket"


def match_user_problem(ticket_id: int) -> int:
    rows = run_sql("SELECT user_problem_id FROM Ticket WHERE id = :tid", {"tid": ticket_id})
    if not rows or rows[0]["user_problem_id"] is None:
        raise OperationFailed("ticket 沒有 user_problem_id")
    return int(rows[0]["user_problem_id"])


def get_published_tutorial(user_problem_id: int) -> dict:
    rows = run_sql(
        "SELECT tutorial_id, current_version, path FROM Tutorial "
        "WHERE user_problem_id = :upid AND status = 'published'",
        {"upid": user_problem_id},
    )
    if not rows:
        raise OperationFailed("沒有 published Tutorial")
    return rows[0]


def reply_tutorial_link(ticket_id: int, tutorial_id: int, tutorial_version: str, path: str) -> dict:
    # demo 的「回覆」= 產生要顯示在中欄的連結文字；不寄信、不打客服系統
    return {"ticket_id": ticket_id, "reply": f"請參考教學：{path} ({tutorial_version})", "path": path}


def mark_deflected(ticket_id: int, tutorial_id: int, tutorial_version: str) -> dict:
    run_sql(
        "UPDATE Ticket SET status = 'deflected', deflected_tutorial_id = :tid, "
        "deflected_tutorial_version = :ver WHERE id = :id",
        {"tid": tutorial_id, "ver": tutorial_version, "id": ticket_id},
    )
    return {"ticket_id": ticket_id, "status": "deflected"}
```

**預期輸出：** `python -c "from app.muscle.steps import STEPS_TEXT; print(STEPS_TEXT)"` 印出規格那串中文。

> ⚠️ **契約衝突已裁決：** 上游共用契約寫 `Workflow.steps = Play 步驟 JSON`，但 `重放已驗證流程.feature` 三個 Then 表都逐字寫中文字串。驗收來源是 `.feature`（CLAUDE.md 來源優先序：`.feature` > 其他），所以 `steps` 欄位存 `STEPS_TEXT`；Play 的四步結構化定義留在 Play 檔本身的 `steps:` frontmatter，不重複落表、也不落第 10 表。

### 步驟 2：Play 要打什麼 —— 本機極簡 HTTP endpoint（`app/muscle/deflect_api.py`）

**決策：Play 打本機 FastAPI（`127.0.0.1:8765`），用它自動產生的 `/openapi.json` 建成 rote adapter。**

理由（依 rote skill 文件判斷，`rote-workspace` §3、`rote-flow-crystallization`、`rote-shell`）：

1. Modiqo 官方文件說 rote 可以 wrap 三種東西：**REST API / 本機 process / 瀏覽器**。瀏覽器路線（`rote-browse`）要真的有產品 UI 可操作——Bitext 沒有產品，直接出局。
2. `rote play pending write --adapter <id>` 與 `rote play template create --adapter <ADAPTER>` 都**要求真 adapter id**；`rote-flow-crystallization` 明講「Pass only real adapters to `--adapter`；do not pass `process`, `shell`」。純 `rote proc` 路線要走 process-only 的 **adapterless workspace export**，會跳過 pending write/save，是比較冷門的分支，8 小時黑客松出包風險高。
3. FastAPI **免費**給 OpenAPI 3.1 spec（`/openapi.json`），`rote adapter new deflect-api <url> --yes` 一行就建好 adapter，不用手寫 spec。本機 endpoint 無 auth，`rote adapter new` 不會卡在認證設定。
4. 四步天生就是四個 HTTP 呼叫，參數化 `ticket_id` 最自然，Play 的 `steps:` DAG 幾乎是 crystallize 直接生出來的。
5. 端點只包住 `app/muscle/steps.py`，**沒有第二套業務邏輯**，Agent 與 Play 共用同一份程式。

```python
# app/muscle/deflect_api.py
"""Rote Play 打的本機 endpoint。只是 app/muscle/steps.py 的 HTTP 外衣，沒有額外邏輯。
啟動：uv run uvicorn app.muscle.deflect_api:app --port 8765"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.errors import OperationFailed
from app.muscle import steps

app = FastAPI(title="deflect-api", version="1.0.0")


class TicketIn(BaseModel):
    ticket_id: int


class DeflectIn(BaseModel):
    ticket_id: int
    tutorial_id: int
    tutorial_version: str
    path: str | None = None


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except OperationFailed as exc:          # 規格語意：操作失敗
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/match-user-problem", operation_id="match_user_problem")
def _match(body: TicketIn):
    return {"user_problem_id": _guard(steps.match_user_problem, body.ticket_id)}


@app.get("/published-tutorial/{user_problem_id}", operation_id="get_published_tutorial")
def _tutorial(user_problem_id: int):
    return _guard(steps.get_published_tutorial, user_problem_id)


@app.post("/reply-link", operation_id="reply_tutorial_link")
def _reply(body: DeflectIn):
    return _guard(steps.reply_tutorial_link, body.ticket_id, body.tutorial_id,
                  body.tutorial_version, body.path or "")


@app.post("/mark-deflected", operation_id="mark_deflected")
def _deflect(body: DeflectIn):
    return _guard(steps.mark_deflected, body.ticket_id, body.tutorial_id, body.tutorial_version)
```

`operation_id` 一定要自己指定——rote 會拿它當 tool 名稱，FastAPI 預設會產出 `_match__match_user_problem_post` 這種難用的名字。

指令與預期輸出：

```bash
uv add fastapi uvicorn
uv run uvicorn app.muscle.deflect_api:app --port 8765          # 另一個分頁常駐
curl -s http://127.0.0.1:8765/openapi.json | head -c 120        # 應看到 {"openapi":"3.1.0",...
```

### 步驟 3：`rote_client.py`（本 Phase 的核心）

```python
# app/muscle/rote_client.py
"""Rote muscle memory：把第一次成功的 deflect 方法固化成 Play，之後直接重放。
RocketRide catalog 沒有 rote 節點，這層一律走本機 CLI（subprocess），不發明 tool_rote。"""
import json
import os
import subprocess
from datetime import datetime, timezone

from app.analytics.hotdata_client import run_sql
from app.errors import OperationFailed
from app.muscle.steps import STEPS_TEXT

ROTE_BIN = os.environ.get("ROTE_BIN", os.path.expanduser("~/.local/bin/rote"))
PLAY_NAME = "deflect-user-problem"       # 一支 Play 服務所有 UserProblem，ticket_id 是參數
WORKSPACE = "deflect-cancel-order"
ADAPTER_ID = "deflect-api"
RUN_CWD = "/tmp"                          # Play 會自建臨時 workspace，必須從 ~/.rote/workspaces/ 外面跑

_play_available_cache: bool | None = None


def _rote(args: list[str], cwd: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run([ROTE_BIN, *args], cwd=cwd, capture_output=True,
                          text=True, timeout=timeout)


def play_available() -> bool:
    """Play 檔在不在（降級判斷用）。一個 process 只查一次，避免每張票都 fork。"""
    global _play_available_cache
    if _play_available_cache is None:
        try:
            proc = _rote(["play", "list", "--json"], timeout=30)
            names = {p.get("name") for p in json.loads(proc.stdout or "[]")} if proc.returncode == 0 else set()
            _play_available_cache = PLAY_NAME in names
        except (OSError, ValueError, subprocess.SubprocessError):
            _play_available_cache = False
    return _play_available_cache


def has_play(user_problem_id: int) -> bool:
    """規格語意：這個 UserProblem 是否已經有捕捉過的 Workflow。
    權威來源是 Workflow 表（.feature 的 Then 表看的是它），不是 Play 檔。"""
    rows = run_sql("SELECT id FROM Workflow WHERE user_problem_id = :upid",
                   {"upid": user_problem_id})
    return bool(rows)


def capture_play(user_problem_id: int, ticket_id: int) -> dict:
    """第一次 deflected 成功後呼叫。寫 Workflow 一列（replay_count = 0）。
    Play 檔本身由 §5 步驟 5–7 的手動 crystallize 產生，這裡不在票流程裡跑 crystallize
    （crystallize 要 30 秒以上，會卡住 demo 的即時路徑）。"""
    if has_play(user_problem_id):
        return {"captured": False, "reason": "already_captured"}

    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    next_id = (run_sql("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM Workflow", {})
               or [{"next_id": 1}])[0]["next_id"]
    run_sql(
        "INSERT INTO Workflow (id, user_problem_id, steps, captured_at, replay_count) "
        "VALUES (:id, :upid, :steps, :cap, 0)",
        {"id": next_id, "upid": user_problem_id, "steps": STEPS_TEXT, "cap": captured_at},
    )
    return {"captured": True, "workflow_id": next_id, "captured_at": captured_at,
            "play_captured": play_available()}      # False → UI 標「Play 未捕捉」


def replay_play(user_problem_id: int, ticket_id: int) -> dict:
    """同類新票：重放 Play（帶新 ticket_id）。成功才 replay_count + 1。
    失敗回 replayed=False，呼叫端改走 Agent 即時路徑，**不** +1（showme §14）。"""
    if not play_available():
        # 降級 A：Rote 未暖機。Workflow 仍由本機計數，UI 標「Play 未捕捉」
        _bump(user_problem_id)
        return {"replayed": True, "degraded": True, "reason": "play_not_captured"}

    try:
        proc = _rote(["play", "run", PLAY_NAME, f"ticket_id={ticket_id}"], cwd=RUN_CWD)
    except subprocess.SubprocessError as exc:
        return {"replayed": False, "reason": f"subprocess:{exc}"}

    if proc.returncode != 0:
        return {"replayed": False, "reason": (proc.stderr or proc.stdout or "")[-400:]}

    # 驗證用資料狀態，不解析 stdout 文字（rote-flow-run：verify artifact content）
    rows = run_sql("SELECT status FROM Ticket WHERE id = :tid", {"tid": ticket_id})
    if not rows or rows[0]["status"] != "deflected":
        return {"replayed": False, "reason": "ticket_not_deflected_after_replay"}

    _bump(user_problem_id)
    return {"replayed": True, "degraded": False}


def _bump(user_problem_id: int) -> None:
    run_sql("UPDATE Workflow SET replay_count = replay_count + 1 WHERE user_problem_id = :upid",
            {"upid": user_problem_id})
```

設計重點（每條都對應一個測試）：

| 決策 | 為什麼 |
|---|---|
| `has_play` 讀 `Workflow` 表，不讀 `rote play list` | `.feature` 的 Then 表看的是 `Workflow`；降級模式下 Play 不存在但表仍要對 |
| `capture_play` 不在票流程裡跑 crystallize | crystallize 是互動式、要 30 秒以上；demo 即時路徑不能卡。Play 在 §5 步驟 5–7 先 crystallize 好 |
| `replay_play` 用 `Ticket.status` 驗證 | `rote play run` 沒有 `--json`，解析 stdout 文字太脆 |
| `play_available()` 快取 | 每張票 fork 一次 `rote play list` 會讓 demo 很鈍 |
| `_bump` 用 `replay_count + 1` 而非讀後寫 | 避免競態，也讓 `captured_at` 絕對不會被改到 |
| `RUN_CWD = "/tmp"` | `rote start` 明講：Play 會自建臨時 workspace，必須從 `~/.rote/workspaces/` 以外跑 |

### 步驟 4：接上即時路徑（`app/agent/realtime.py`）

在 Phase 2 既有的 `handle_open_ticket(ticket_id)` 判定成 `deflected` 的分支後面插入 Rote 分支。**不要動 escalated 分支**（Rule 3）。

```python
# app/agent/realtime.py（節錄：Phase 3 新增的分支）
from app.muscle import rote_client

def handle_open_ticket(ticket_id: int) -> dict:
    decision = _decide(ticket_id)               # Phase 2 既有：deflected / escalated

    if decision["status"] == "escalated":
        _apply_escalated(ticket_id, decision)   # Rule 3：escalated 完全不碰 Rote
        return decision

    upid = decision["user_problem_id"]

    if rote_client.has_play(upid):
        result = rote_client.replay_play(upid, ticket_id)
        if result["replayed"]:
            decision["route"] = "rote_replay_degraded" if result.get("degraded") else "rote_replay"
            return decision
        decision["route"] = "agent_fallback_after_replay_failure"   # 不 +1

    _apply_deflected(ticket_id, decision)       # Phase 2 既有的四步
    if not rote_client.has_play(upid):
        capture = rote_client.capture_play(upid, ticket_id)
        decision["route"] = ("agent_first_captured" if capture.get("play_captured")
                             else "agent_first_play_missing")
    return decision
```

`route` 的四個值就是中欄標籤的來源：

| `route` | 中欄顯示 |
|---|---|
| `agent_first_captured` | deflected（第一次，已捕捉 Play） |
| `agent_first_play_missing` | deflected（第一次｜Play 未捕捉） |
| `rote_replay` | deflected（Rote 重放） |
| `rote_replay_degraded` | deflected（Rote 重放｜Play 未捕捉，本機計數） |
| `agent_fallback_after_replay_failure` | deflected（Rote 重放失敗 → Agent 即時路徑） |

### 步驟 5：🖐️ 手動 — Play 搜尋與 adapter

```bash
rote whoami                                              # M1
rote play search "deflect support ticket with published tutorial"
#  → 有 full match 就直接用，不要重建（rote start 的 CHECK 1）
rote play search "deflect support ticket with published tutorial" --source registry
#  → 兩邊都沒有，才往下建

uv run uvicorn app.muscle.deflect_api:app --port 8765 &  # M4，另一個分頁常駐
rote adapter new deflect-api http://127.0.0.1:8765/openapi.json --yes
rote adapter list                                        # 預期看到 deflect-api
```

### 步驟 6：🖐️ 手動 — 在 workspace 把四步跑一遍（用第 4 張票）

```bash
rote init deflect-cancel-order --seq
cd ~/.rote/workspaces/deflect-cancel-order
rote model set <你正在用的模型> --provider anthropic --confirmed-current

rote deflect_api_probe "match user problem for a ticket"     # 先 probe 讀 tool 名與 schema
rote deflect_api_call match_user_problem    '{"ticket_id": 4}'
rote deflect_api_call get_published_tutorial '{"user_problem_id": 1}'
rote deflect_api_call reply_tutorial_link   '{"ticket_id": 4, "tutorial_id": 1, "tutorial_version": "v1", "path": "tutorials/cancel-order.md"}'
rote deflect_api_call mark_deflected        '{"ticket_id": 4, "tutorial_id": 1, "tutorial_version": "v1"}'
rote query @4 '.status' -r                                   # 預期：deflected
rote ls                                                      # 四筆 @1..@4 都在
```

adapter id 有連字號時，shorthand 指令要換成底線：`deflect-api` → `rote deflect_api_probe` / `rote deflect_api_call`（`rote-workspace` §3）。指令**一次一條**，讀完 `@@status` / `@@next` 再下一條。

### 步驟 7：🖐️ 手動 — crystallize 成 Play

```bash
rote play pending write deflect-cancel-order \
  --name deflect-user-problem \
  --adapter deflect-api \
  --description "Deflect an open support ticket by replying with the published tutorial link for its UserProblem" \
  --query '.status' \
  --response-path '.status' \
  --response-index 4 \
  --notes "四步固定：匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket。ticket_id 必須參數化；tutorial_id / version 必須由第二步查出來，不可寫死。base URL http://127.0.0.1:8765 由本機 deflect-api 提供，需先啟動 uvicorn。"

rote play pending save deflect-cancel-order
#  → 印出 pre-filled `rote play template create ...`；**原封不動**執行它，不要加 shape flags

rote play validate ~/.rote/flows/deflect-user-problem/main.ts --fix
rote play lint    deflect-user-problem
rote play release deflect-user-problem --keep-local
rote play index --rebuild
rote play list --json | grep deflect-user-problem     # 預期：看得到
rote play info deflect-user-problem --json            # 確認參數只有 ticket_id
```

crystallize 後**一定要打開 `main.ts` 檢查 `ticket_id` 真的是參數**，不是被寫死成 `4`。`rote play run ... --dry-run` 印出的執行計畫如果看到 `4` 硬編在裡面，就回去改 frontmatter 的 `params`，再 `rote play bind deflect-user-problem` 重新綁定內容雜湊。

不推 registry（`rote play share` / `rote registry`）——本機 release 就滿足 demo，推 registry 是額外的 auth 與時間風險。

### 步驟 8：指標（`app/analytics/metrics.py`）

```python
def replay_rate() -> float:
    """重放解決率 = SUM(Workflow.replay_count) / COUNT(Ticket.status = 'deflected')（showme §12）"""
    rows = run_sql(
        "SELECT COALESCE((SELECT SUM(replay_count) FROM Workflow), 0) * 1.0 "
        "/ NULLIF((SELECT COUNT(*) FROM Ticket WHERE status = 'deflected'), 0) AS rate", {})
    return float(rows[0]["rate"] or 0.0)
```

第 4 張後：`0 / 1 = 0.0`。第 5 張後：`1 / 2 = 0.5`（與 showme §12 的 Example `2/4 = 0.5` 同一條公式）。

### 步驟 9：Demo UI（`app/demo/streamlit_app.py`）

- **中欄**：依 `decision["route"]` 顯示 §5 步驟 4 那張對照表的文字；Rote 重放時額外顯示 `rote play run deflect-user-problem ticket_id=<N>` 這行指令（評審要看到 Muscle 層真的在跑）。
- **下欄**：先顯示 `SELECT user_problem_id, replay_count, captured_at FROM Workflow` 的原始列（最直觀的證據），再顯示 `replay_rate()`。曲線等 Phase 4。
- 降級時在下欄加一行紅字：`Play 未捕捉（replay_count 為本機計數）`。

### 步驟 10：測試（`tests/unit/test_rote_client.py`）

用 fake rote：`monkeypatch` 掉 `app.muscle.rote_client._rote` 與 `run_sql`，**不真的 fork CLI、不打 hotdata**。

```python
# tests/unit/test_rote_client.py（骨架）
import subprocess
import pytest
from app.muscle import rote_client
from app.muscle.steps import STEPS_TEXT


class FakeRote:
    """假的 rote CLI：記錄被呼叫的 argv，回傳預先安排的 CompletedProcess。"""
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls, self.returncode, self.stdout, self.stderr = [], returncode, stdout, stderr

    def __call__(self, args, cwd=None, timeout=120):
        self.calls.append((args, cwd))
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)


@pytest.fixture(autouse=True)
def _reset_cache():
    rote_client._play_available_cache = None


def test_第一次攔截新增_workflow_replay_count_為_0(fake_db, monkeypatch):
    """重放已驗證流程.feature / Rule 1 / Example 第一次攔截 cancel_order"""
    monkeypatch.setattr(rote_client, "_rote", FakeRote(stdout='[{"name": "deflect-user-problem"}]'))
    result = rote_client.capture_play(user_problem_id=1, ticket_id=1)
    row = fake_db.one("SELECT * FROM Workflow WHERE user_problem_id = 1")
    assert (row["steps"], row["replay_count"]) == (STEPS_TEXT, 0)
    assert result["captured"] is True


def test_第二次攔截_replay_count_加一且_captured_at_不變(fake_db, monkeypatch):
    """Rule 2 / Example 第二次攔截 cancel_order"""
    fake_db.insert_workflow(id=1, user_problem_id=1, steps=STEPS_TEXT,
                            captured_at="2026-09-11T10:05:00Z", replay_count=0)
    fake_db.set_ticket_status(2, "deflected")                     # Play 真的做完事
    monkeypatch.setattr(rote_client, "_rote", FakeRote(stdout='[{"name": "deflect-user-problem"}]'))
    assert rote_client.replay_play(1, ticket_id=2)["replayed"] is True
    row = fake_db.one("SELECT * FROM Workflow WHERE id = 1")
    assert (row["replay_count"], row["captured_at"]) == (1, "2026-09-11T10:05:00Z")


def test_escalated_不建立_workflow(fake_db, monkeypatch): ...
    # Rule 3：走 realtime.handle_open_ticket，斷言 Workflow 仍為空、rote 一次都沒被呼叫

def test_重放失敗不加_replay_count(fake_db, monkeypatch):
    """showme §14：重放失敗 → 走 Agent 即時路徑，不算 replay"""
    fake_db.insert_workflow(id=1, user_problem_id=1, steps=STEPS_TEXT,
                            captured_at="2026-09-11T10:05:00Z", replay_count=0)
    monkeypatch.setattr(rote_client, "_rote",
                        FakeRote(returncode=1, stderr="adapter unreachable",
                                 stdout='[{"name": "deflect-user-problem"}]'))
    assert rote_client.replay_play(1, ticket_id=2)["replayed"] is False
    assert fake_db.one("SELECT * FROM Workflow WHERE id = 1")["replay_count"] == 0


def test_play_未捕捉時仍本機計數並標降級(fake_db, monkeypatch):
    """showme §17：Rote 未暖機 → replay_count 本機計數，UI 標「Play 未捕捉」"""
    fake_db.insert_workflow(id=1, user_problem_id=1, steps=STEPS_TEXT,
                            captured_at="2026-09-11T10:05:00Z", replay_count=0)
    monkeypatch.setattr(rote_client, "_rote", FakeRote(stdout="[]"))   # play list 空
    result = rote_client.replay_play(1, ticket_id=2)
    assert (result["replayed"], result["degraded"]) == (True, True)
    assert fake_db.one("SELECT * FROM Workflow WHERE id = 1")["replay_count"] == 1


def test_重放帶的是新_ticket_id(fake_db, monkeypatch):
    """Play 重的是方法：argv 必須帶 ticket_id=<新票號>，不是舊票號"""
    fake = FakeRote(stdout='[{"name": "deflect-user-problem"}]')
    fake_db.insert_workflow(id=1, user_problem_id=1, steps=STEPS_TEXT,
                            captured_at="2026-09-11T10:05:00Z", replay_count=0)
    fake_db.set_ticket_status(5, "deflected")
    monkeypatch.setattr(rote_client, "_rote", fake)
    rote_client.replay_play(1, ticket_id=5)
    run_argv = [c for c in fake.calls if c[0][:2] == ["play", "run"]][0]
    assert "ticket_id=5" in run_argv[0] and run_argv[1] == "/tmp"
```

`uv run pytest tests/unit/test_rote_client.py -v` 預期 6 綠。

### 規格 → 程式／測試對照表

| 規格 | Rule / Example | 程式 | 測試 |
|---|---|---|---|
| `重放已驗證流程.feature` | Rule 1「某 UserProblem 第一次 deflected 成功時新增 Workflow」／Example 第一次攔截 cancel_order | `rote_client.capture_play` | `test_第一次攔截新增_workflow_replay_count_為_0` |
| `重放已驗證流程.feature` | Rule 2「同 UserProblem 已有 Workflow 時再次 deflected 則 replay_count 加 1」／Example 第二次攔截 cancel_order | `rote_client.replay_play` + `_bump` | `test_第二次攔截_replay_count_加一且_captured_at_不變` |
| `重放已驗證流程.feature` | Rule 3「escalated 不建立 Workflow」／Example 無 Tutorial 時不新增 Workflow（Then 表空） | `realtime.handle_open_ticket` 的 escalated 早退 | `test_escalated_不建立_workflow` |
| `重放已驗證流程.feature` | Feature 描述「Then 中的 captured_at 等於 Given 的系統目前時間」 | `capture_play` 的 `datetime.now(timezone.utc)`；`_bump` 不碰 `captured_at` | 前兩條測試各斷言一半 |
| `自動回覆顧客.feature` | Rule「UserProblem 已有 published Tutorial 時票單為 deflected」／Example cancel_order 已有 published Tutorial | `steps.mark_deflected`（Agent 與 Play 共用） | Phase 2 既有契約測試＋`test_重放帶的是新_ticket_id` |
| `showme` §14 | Rote Play 重放失敗 → 走 Agent 即時路徑，不寫成 `replay_count+1` | `replay_play` 回 `replayed=False` | `test_重放失敗不加_replay_count` |
| `showme` §17 | Rote 未暖機 → 本機計數並標「Play 未捕捉」 | `play_available()` + `degraded` 旗標 | `test_play_未捕捉時仍本機計數並標降級` |
| `showme` §12 | 重放解決率 = `SUM(replay_count) / COUNT(deflected)` | `metrics.replay_rate` | `tests/unit/test_metrics.py`（Phase 4 補齊曲線，本 Phase 先驗單點） |

---

## 6. 驗收清單

資料層（對齊 `.feature` Then 表）

- [ ] **Rule 1**：餵第 4 張 cancel_order 票後，`SELECT * FROM Workflow` 剛好 1 列，`user_problem_id=1`、`replay_count=0`、`steps` 逐字等於 `匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket`、`captured_at` 是捕捉當下時間
- [ ] **Rule 2**：餵第 5 張 cancel_order 票後，同一列 `replay_count=1`，`captured_at` **沒有變**，`Workflow` 仍只有 1 列
- [ ] **Rule 3**：餵一張 `user_problem_id` 為空（或無 published Tutorial）的票後，`Workflow` 列數不變、內容不變
- [ ] **自動回覆顧客 deflected Example**：`Ticket(4)` 與 `Ticket(5)` 都是 `status=deflected`、`deflected_tutorial_id=1`、`deflected_tutorial_version=v1`
- [ ] 第 5 張票的 deflect 路徑**沒有**呼叫 LLM（log 或 `route == "rote_replay"` 可證）

Rote 層

- [ ] `rote play list` 看得到 `deflect-user-problem`，`rote play info deflect-user-problem --json` 顯示參數只有 `ticket_id`
- [ ] `cd /tmp && rote play run deflect-user-problem ticket_id=5 --dry-run` 印出的計畫裡沒有硬編的舊票號
- [ ] `rote adapter list` 看得到 `deflect-api`
- [ ] 🖐️ 手動：`rote whoami` 有身分；hello-world 暖機跑過

畫面層

- [ ] 第 4 張：中欄顯示教學連結 `tutorials/cancel-order.md` ＋ 標籤「deflected（第一次，已捕捉 Play）」
- [ ] 第 5 張：中欄標籤「deflected（Rote 重放）」，並顯示實際跑的 `rote play run ...` 指令
- [ ] 下欄顯示 `Workflow` 原始列與 `replay_rate()`：第 4 張後 `0.0`，第 5 張後 `0.5`

測試層

- [ ] `uv run pytest tests/unit/test_rote_client.py -v` 全綠（6 條）
- [ ] 測試**沒有**真的 fork `rote`、沒有打 hotdata、沒有起 uvicorn（全部 monkeypatch）

---

## 7. 降級方案

| 情境 | 訊號 | 降級動作 | demo 還看得到什麼 |
|---|---|---|---|
| **A. Rote 未暖機／未登入／Play 從未捕捉** | `rote whoami` 失敗，或 `rote play list` 沒有 `deflect-user-problem` | `play_available()` 回 `False`。`capture_play` 照常寫 `Workflow` 一列；`replay_play` 走本機計數 `+1` 並回 `degraded=True` | `Workflow` 表、`replay_count`、重放解決率曲線**全部照常**；中欄與下欄標「Play 未捕捉（本機計數）」。Muscle 層口頭對應到 §7.5 契約 |
| **B. adapter 建不起來（OpenAPI 解析失敗／port 不通）** | `rote adapter new` 非 0 退出 | 改走 process-only 路線：`cd ~/.rote/workspaces/<ws> && rote proc run -- uv run python -m app.muscle.steps_cli --step match --ticket-id 4`（四步四次），crystallize 走 adapterless workspace export（`rote play pending write/save` 不吃 `process` 當 adapter，要跳過 pending、直接把計畫交給 export）。`rote_client` 只要把 `_rote(["play", "run", ...])` 換成對應的 Play 名稱，其餘不動 | Play 仍存在、仍可重放；只是 Play 打的是本機 process 不是 HTTP |
| **C. Play 存在但 `rote play run` 失敗**（adapter 掛了、uvicorn 沒開、逾時） | `returncode != 0`，或重放後 `Ticket.status != 'deflected'` | 本張票**改走 Agent 即時路徑**，仍然 deflected；**不** `replay_count + 1`（showme §14） | 票照樣被攔截，指標誠實（重放解決率不灌水）。中欄標「Rote 重放失敗 → Agent 即時路徑」 |
| **D. hotdata 不可用** | `run_sql` 拋錯 | 同一份 SQL 打本機 Postgres，表形狀仍是 9 表（showme §17）。`Workflow` 不變成第 10 表 | 全部照常 |
| **E. 時間真的不夠** | 剩 < 20 分鐘 | 只做 §5 步驟 1、3、4、8、9、10（純 Python + 降級 A），**跳過** 步驟 2、5、6、7 的 Rote 手動流程 | `Workflow` 表、`replay_count`、曲線都在，Muscle 層降成口頭說明。這是最後手段 |

三條紅線（降級時也不能破）：

1. **票的狀態永遠以 `.feature` Then 表為準。** Rote 出任何問題都不能讓該 deflected 的票變成 escalated。
2. **`replay_count` 只在「這張票真的沒讓 LLM 重新推理」時才 +1。** 失敗 fallback 不算。
3. **不 deploy、不碰 `ROCKETRIDE_DEPLOY_*`。** Phase 3 完全不需要 RocketRide deploy。

---

## 8. 交接給 Phase 4 的東西

Phase 4（切片 E：指標 + REFINE）可以直接拿：

| 交付物 | 位置 | Phase 4 怎麼用 |
|---|---|---|
| `metrics.replay_rate()` | `app/analytics/metrics.py` | 直接畫進下欄曲線，不用再寫 SQL |
| `Workflow` 表有真實資料（1 列、`replay_count>=1`） | hotdata | 重放解決率曲線的第一個非零點 |
| `Ticket(4)`、`Ticket(5)` 皆 `deflected` | hotdata | deflection rate 從 `0/3` 跳到 `2/5`；Phase 4 的曲線有東西可畫 |
| `decision["route"]` 五個值 | `app/agent/realtime.py` 回傳 | 下欄可以分色標示「重放 vs 重新推理」 |
| `rote_client.play_available()` 的降級旗標 | `app/muscle/rote_client.py` | UI 決定要不要標「Play 未捕捉」 |
| `app/muscle/steps.py` 的四步函式 | — | Phase 5（Release UPDATE）改完 `tutorials/cancel-order.md` 後，deflect 路徑自動回新版本，不用改 Rote 那層 |
| Play `deflect-user-problem` 與 adapter `deflect-api` | `~/.rote/flows/`、`~/.rote/adapters/`（git-ignored） | Phase 4/5 再餵 `track_refund` 票時**重用同一支 Play**，只會多一列 `Workflow`，不用再 crystallize |

Phase 4 要注意：`Tutorial` 被 REFINE 成 v2 之後，`deflected_tutorial_version` 應該跟著變成 `v2`——那是 `steps.get_published_tutorial` 讀 `current_version` 的自然結果，**Play 不用重新捕捉**（Play 重的是方法）。這句話拿去跟評審講，正好是「method not answer」最好的示範。

---

## 來源

**專案內部（作用中規格與設計）**

- `/Users/linjunting/AWS-Hackathon/CLAUDE.md`
- `/Users/linjunting/AWS-Hackathon/docs/design/showme.md` §5.5、§6 步驟 7、§7.1、§7.5、§12、§14、§16 切片 D、§17
- `/Users/linjunting/AWS-Hackathon/docs/spec/erm.dbml`（`Workflow`、`Ticket`）
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/重放已驗證流程.feature`（3 Rule / 3 Example，全文）
- `/Users/linjunting/AWS-Hackathon/docs/spec/features/自動回覆顧客.feature`（5 Rule / 5 Example，全文）
- `/Users/linjunting/AWS-Hackathon/docs/客服自助教學生成器 — 系統架構規格.md`（🔁 Modiqo.ai (Rote) 段、「重放解決率」段）

**Rote 官方 skill 文件（本機，2026-09-11 讀取）**

- `~/.claude/skills/rote/SKILL.md`（Play-search gate、skill vs CLI 命名規則）
- `~/.claude/skills/rote-workspace/SKILL.md`（`rote init --seq`、`rote model set`、adapter shorthand 底線規則、sequential discipline、recovery checklist）
- `~/.claude/skills/rote-flow-crystallization/SKILL.md`（`rote play pending write/save/discard`、「不可把 `process`/`shell` 當 adapter」、save gate）
- `~/.claude/skills/rote-flow-run/SKILL.md`（`rote play run <target> param=value`、本機 vs registry 執行契約、「verify artifact content, not only existence」）
- `~/.claude/skills/rote-shell/SKILL.md`（`rote proc run` 各旗標，降級 B 的依據）

**Rote CLI 實測（本機 `rote 0.82.0`，只跑 `--help` 類唯讀指令）**

- `rote --help`、`rote play --help`、`rote play run --help`、`rote play template create --help`、`rote play pending --help`、`rote play pending write/save --help`、`rote adapter --help`、`rote adapter new --help`、`rote init --help`、`rote proc --help`、`rote proc run --help`、`rote start`

**Modiqo 官方網站（2026-09-11 各取一次）**

- https://www.modiqo.ai/docs — Rote 可 wrap「APIs / local processes / the browser」；生命週期 recorded workspace → crystallization → run
- https://www.modiqo.ai/faq — 「rote saves the method. Each Play run uses new inputs and current tool responses.」「The Play does not return the old answer. It uses the old method to produce a new answer.」；deterministic flow crystallization 會把固定值轉成可重用輸入、先產生 pending Play 再 release；local-first execution model
