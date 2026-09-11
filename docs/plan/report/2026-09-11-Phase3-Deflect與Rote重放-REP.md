# 2026-09-11 — Phase 3 Deflect 與 Rote 重放 完成報告

> ⚠️ 這只是 hackathon 作品，不要過度設計。

- 對應計畫：`docs/plan/unfinish/04-Phase3-Deflect與Rote重放.md`
- 狀態：**完成**（Play 已 release 且端到端重放成功；未完成項只剩 demo 當天要手動開 API server，見 §7）

---

## 1. 實作邏輯

### 這個 phase 解決什麼

五層 stack 裡的 **Muscle memory（Modiqo Rote）**——也是最難「證明它真的在做事」的一層。
規格說的是：某個 UserProblem **第一次** deflected 成功時捕捉成 Workflow，**之後**同樣的情況直接重放、`replay_count` +1。
要讓這件事不是作假，deflect 這個動作必須是一個 Rote 能呼叫的**真實外部操作**——所以我們把它包成 HTTP API，讓 Rote 透過 adapter 打進來。

### 怎麼切

| 層 | 檔案 | 職責 |
|---|---|---|
| HTTP 介面 | `app/api/deflect_api.py` | `POST /deflect {ticket_id}`（`operation_id=deflect_ticket`）、`GET /health`。存在的唯一理由是給 Rote 一個可以 crystallize 的操作 |
| 肌肉記憶 | `app/muscle/rote_client.py` | `on_deflected(db, ticket_id, user_problem_id)`：判斷「第一次捕捉」還是「之後重放」 |
| 啟動 | `scripts/run_deflect_api.sh` | uvicorn on 8765 |

### 關鍵設計決定與理由

| 決定 | 理由 |
|---|---|
| **成功判定只看資料狀態**（`Ticket.status == 'deflected'`），不看 rote 的 exit code | `rote play run` 的回傳碼在本機 Play 上不夠可靠。真正的事實在 DB：票有沒有被 deflect 掉。這樣「假成功」不可能發生 |
| **重放失敗就不加 `replay_count`** | 對齊 `docs/design/showme.md` §14。`replay_count` 是要上 demo 曲線的數字，寧可少算也不能灌水 |
| **Play 從未 crystallize → 本機計數 +1 並標 `play_captured=False`** | `showme.md` §17 的降級路徑。Rote 服務當天掛掉時，demo 的「重放解決率」曲線還是有東西可看，而且旗標誠實標示「這次沒走 Rote」 |
| `has_play()` 查一次就**快取** | 每次 deflect 都 fork 一個 `rote play list` 會讓 demo 卡頓。Play 名單在 demo 過程中不會變 |
| subprocess `timeout=20`、失敗吞掉 | 外部 CLI 是 demo 當天的風險點。卡住比失敗更糟——寧可跳過重放，也不能讓整條 pipeline 停在那裡 |
| `rote play run` **不帶 `-y`** | rote 0.82.0 對本機 Play 會拒絕 `--yes`（見 §5）。踩過才知道 |
| 測試全部 **monkeypatch，不 fork** | 單元測試不該依賴 rote CLI 或起 server。真實驗證另外用手動端到端跑 |

---

## 2. 步驟（TDD 先紅後綠）

1. **先紅**：`tests/unit/test_rote_client.py` 照 `重放已驗證流程.feature` 三條 Rule 寫（第一次新增 Workflow、之後 `replay_count` +1、escalated 不建立 Workflow）→ 全紅。
2. **後綠**：實作 `app/muscle/rote_client.py` 的 `on_deflected`，`has_play()` / `replay_play()` 先以 monkeypatch 驗證 → 轉綠。
3. **先紅**：`tests/unit/test_deflect_api.py` 用 FastAPI `TestClient` 寫 `POST /deflect` 與 `GET /health` → 紅。
4. **後綠**：實作 `deflect_api.py`，`pyproject.toml` 加 `fastapi`、`uvicorn` → 轉綠。
5. 寫 `scripts/run_deflect_api.sh`（port 8765），起 server。
6. **Rote 實跑（手動）**，順序如下：
   1. `rote adapter new deflect-api http://127.0.0.1:8765/openapi.json --yes`
   2. auth 被誤判成 Bearer → `rote adapter auth update deflect-api --none`
   3. `rote workspace` 開 `deflect-cancel-order`
   4. `deflect_api_call deflect_ticket` 實際打一次真 API
   5. `rote play pending write` → `rote play pending save`
   6. `rote play template create`
   7. 手改 frontmatter 把 `ticket_id` 參數化
   8. `rote play validate` → 0 errors
   9. `rote play lint`
   10. `rote play release support-deflect`
   11. `rote play index --rebuild`
7. 驗證單次重放：`rote play run support-deflect ticket_id=904` → 成功。
8. 端到端：丟第一張票 → Workflow captured；丟第二張同 UserProblem 的票 → replayed、`replay_count = 1`。
9. `.env` 追加 `ROTE_PLAY_NAME=support-deflect`、`DEFLECT_API_URL=http://127.0.0.1:8765`。
10. 清掉暖機用的 fixture（ticket id 901–905）避免污染 demo 數字。

---

## 3. 產出檔案

| 檔案 | 內容一句話 |
|---|---|
| `app/muscle/rote_client.py` | `on_deflected()`：第一次寫 Workflow 一列（中文 steps／`captured_at`／`replay_count=0`），之後查 `has_play()` 再 `rote play run` 重放並依資料狀態決定是否 +1 |
| `app/api/deflect_api.py` | FastAPI：`POST /deflect`（`operation_id=deflect_ticket`）與 `GET /health`，Rote adapter 的來源 spec |
| `scripts/run_deflect_api.sh` | 用 uvicorn 在 port 8765 起 deflect API |
| `pyproject.toml`（修改） | 加入 `fastapi>=0.141.1`、`uvicorn>=0.52.4` |
| `.env`（修改，git-ignored） | 追加 `ROTE_PLAY_NAME=support-deflect`、`DEFLECT_API_URL=http://127.0.0.1:8765` |
| Rote 側（不在 repo） | adapter `deflect-api`、workspace `deflect-cancel-order`、已 release 的 Play `support-deflect` |
| `tests/unit/test_rote_client.py` | 10 個測試，涵蓋捕捉／重放／escalated 不捕捉／重放失敗不 +1／降級計數 |
| `tests/unit/test_deflect_api.py` | 6 個測試，`POST /deflect` 成功與錯誤路徑、`GET /health` |

---

## 4. 測試方式

```bash
uv run pytest -q tests/unit/test_rote_client.py tests/unit/test_deflect_api.py

# 手動端到端（需要先開 API server）
./scripts/run_deflect_api.sh &
rote play run support-deflect ticket_id=904
```

對齊的 `.feature` Rule：

| Rule | 出處 | 驗在哪 |
|---|---|---|
| 某 UserProblem 第一次 deflected 成功時新增 Workflow | `重放已驗證流程.feature` | `test_rote_client.py`（Workflow 一列、`replay_count=0`、`captured_at` 有值） |
| 同 UserProblem 已有 Workflow 時再次 deflected 則 `replay_count` 加 1 | `重放已驗證流程.feature` | `test_rote_client.py` |
| escalated 不建立 Workflow | `重放已驗證流程.feature` | `test_rote_client.py` |
| UserProblem 已有 published Tutorial 時票單為 deflected | `自動回覆顧客.feature` | `test_deflect_api.py`（API 層），判斷邏輯本身在 Phase 2 的 `realtime.py` |
| 重放失敗不得灌水 | `docs/design/showme.md` §14 | `test_rote_client.py` |
| Play 未 crystallize 的降級 | `docs/design/showme.md` §17 | `test_rote_client.py`（`play_captured=False`） |

---

## 5. 遇到的問題與解法

| 問題 | 原因 | 怎麼解 |
|---|---|---|
| `rote adapter new` 之後每次呼叫都要 token | rote 從 OpenAPI 推測 auth，誤判成 Bearer | `rote adapter auth update deflect-api --none` |
| `rote play run support-deflect -y` 直接被拒 | rote 0.82.0 對**本機** Play 不接受 `--yes` | 拿掉 `-y`，改用非互動情境直接跑 |
| `rote play run` 找不到 Play | crystallize 出來的 template 沒有註冊進索引 | `rote play release support-deflect` 之後 `rote play index --rebuild` |
| Play 寫死了當初 crystallize 的 ticket_id | template 直接固化了實際請求參數 | 手改 frontmatter 把 `ticket_id` 宣告成參數，再 `rote play validate`（0 errors） |
| `rote play run` 從專案目錄跑會受 repo 狀態干擾 | rote 會掃當前目錄 | 固定 `cd /tmp && rote play run ...` |
| `curl` 打不到本機 API | 本機 curl 被環境擋掉 | 改用 `httpx` 在 Python 裡驗證 |
| demo 數字被暖機資料污染 | 測 Rote 時塞了 ticket id 901–905 | 從 `.state/local.db` 清掉這些列 |
| 重放「成功」但 DB 沒變 | 只看 exit code 會誤判 | 改成只認資料狀態：`Ticket.status == 'deflected'` 才 +1 |

---

## 6. 測試結果

重跑本 phase 兩支測試（2026-09-11）：

```
uv run pytest -q tests/unit/test_rote_client.py tests/unit/test_deflect_api.py
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
16 passed, 2 warnings in 1.40s
```

拆開來是 `test_rote_client.py` 10 個 ＋ `test_deflect_api.py` 6 個 = 16，與實作回報一致。
那 2 個 warning 是 starlette `TestClient` 的 `httpx` 棄用提醒與 anyio alias 提醒，與本專案程式無關。

全專案現況：

```
uv run pytest -q -m "not integration"
190 passed, 2 deselected, 2 warnings in 26.72s
```

Rote 端到端實跑：

| 動作 | 結果 |
|---|---|
| `rote play validate` | 0 errors |
| `rote play run support-deflect ticket_id=904` | 成功 |
| 第一張 `cancel_order` 新票 | Workflow captured，`replay_count = 0` |
| 第二張同 UserProblem 新票 | replayed，`replay_count = 1` |

---

## 7. 🖐️ 留給使用者的手動事項

| 項目 | 說明 |
|---|---|
| **demo 全程要開 deflect API** | `./scripts/run_deflect_api.sh`（port 8765）。關掉的話重放會走 §1 的降級路徑（計數 +1 但 `play_captured=False`），曲線還在但少了 Rote 的說服力 |
| 開機順序 | 先起 deflect API，再起 Streamlit，最後才丟票 |
| 驗證 API 活著 | 用 `httpx` 打 `GET /health`（本機 curl 在這台機器被擋） |
| Rote 資產 | adapter `deflect-api` / Play `support-deflect` 綁在目前登入的 rote 帳號；換帳號要照 §2 步驟 6 重做一次 |
| 彩排前 | 確認 `.state/local.db` 沒有 901–905 這批暖機票（已清過一次） |

---

## 8. 與計畫的偏差／hackathon 簡化

| 偏差 | 說明 |
|---|---|
| **多了一支 HTTP API** | 計畫沒規劃 `app/api/`。但 Rote 需要一個可 crystallize 的真實操作，不包 API 就只能假裝重放 |
| Workflow 的 `steps` 是**中文字串**，不是結構化步驟 | 規格只要求「有步驟」。demo 時是給人看的，字串就夠 |
| `has_play()` 快取不會失效 | demo 過程中 Play 不會被刪。加失效機制是為不存在的情境付費 |
| 失敗一律吞掉，只留 print | 黑客松沒有 retry／alerting 的必要 |
| 單元測試不碰真 rote CLI | 全 monkeypatch。真實路徑靠 §6 的手動端到端驗證 |
| Play 只有一支（`support-deflect`） | 規格只要求「第一次成功的固定流程之後直接重放」。Release Note 那條在 Phase 5 另議 |
