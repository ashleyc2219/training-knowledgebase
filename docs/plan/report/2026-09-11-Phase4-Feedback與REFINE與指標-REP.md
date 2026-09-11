# 2026-09-11 — Phase 4 Feedback 與 REFINE 與指標 完成報告

> ⚠️ 這只是 hackathon 作品，不要過度設計。

- 對應計畫：`docs/plan/unfinish/05-Phase4-Feedback與REFINE與指標.md`
- 狀態：**部分完成**
  - 未完成項：REFINE 目前走**模板降級**（沒有 `ANTHROPIC_API_KEY` / `ROCKETRIDE_PROJECT_ID`），真 LLM 改寫要等金鑰。
  - 未完成項：`.md` 版型沒有與 `create_tutorial` 共用 renderer（見 §8）。

---

## 1. 實作邏輯

### 這個 phase 解決什麼

這是整個專案「**self-learning**」四個字的證據所在。
`CLAUDE.md` 說 self-learning 的定義是 *past outcomes change future system behavior*——Phase 4 就是把「past outcomes」（顧客評分）變成「future behavior」（Tutorial 換了新版本、之後的顧客拿到不同內容）的那條線，並且把這件事畫成曲線給評審看。

三件事串成一條：**收 Feedback → 定期 Review 決定 REFINE/KEEP → 指標快照與歷史曲線**。

### 怎麼切

| 模組 | 職責 |
|---|---|
| `app/ingest/feedback.py` | 只負責「收得對不對」：驗證 → 存。任一關卡失敗就 `OperationFailed`，**不入庫** |
| `app/agent/feedback_review.py` | 只負責「該不該改」：算統計 → 呼叫 `rules` → REFINE 就產新版 |
| `app/analytics/metrics.py`（擴充） | 只負責「數字長怎樣」：`snapshot` 算現況、`append_history`／`load_history` 存曲線 |
| `app/demo/ui_feedback.py` / `ui_metrics.py` | 只負責「看得到」 |

### 關鍵設計決定與理由

| 決定 | 理由 |
|---|---|
| **驗證失敗一律不入庫**（不做部分寫入） | 對齊 `收集Feedback.feature` 的「Then 操作失敗」。半筆髒資料會讓 avg 算錯，進而讓 REFINE 判斷錯 |
| 未指定版本時**自動填 `current_version`** | `收集Feedback.feature` 要求 Feedback 參照 TutorialVersion。顧客不會知道版本號，系統補 |
| avg 只算 `current_version` | `定期優化Tutorial.feature` 明文規定。這條也是「v2 上線後 avg 從 2.9 跳到 4.4」能成立的關鍵——舊版的爛分數不該拖累新版 |
| 同 category 計數**空字串不算** | `收集Feedback.feature` 說 category 未填存空字串。空字串若參與計數，「≥2 筆同類抱怨」會被一堆沒填的灌滿 |
| `is_possibly_outdated = true` **一律 KEEP** | `定期優化Tutorial.feature` 最後一條 Rule。這種 Tutorial 該等 Release Note 流程（Phase 5）處理，不該讓 Feedback 流程搶著改 |
| REFINE 的 LLM 失敗 → **模板改寫**，並標 `source="template"` | `showme.md` 的降級要求。demo 不能因為沒金鑰就走不下去；標 source 讓人一眼知道這版不是 LLM 寫的 |
| 新版本用 `supersedes_version` 指上一版，**不覆寫舊版** | `CLAUDE.md`：TutorialVersion 是快照。舊版要留著，因為 v1 的 avg 2.9 是 demo 敘事的一半 |
| `.md` 頁尾埋 `<!-- version: vN -->` | demo 時打開檔案就看得到版本，不用去查 DB |
| `metrics_history.json` 存在 `.state/` | 曲線要跨執行累積，但不該進 DB（不是領域資料）也不該進 git |
| 記憶層參數 `cognee=None, hydra=None` 就跳過 | 與 Phase 1 同一個降級哲學：外部服務不可用時，核心流程照跑 |

---

## 2. 步驟（TDD 先紅後綠）

1. **先紅**：`tests/unit/test_feedback.py` 照 `收集Feedback.feature` 七條 Rule 寫（rating 1–5 整數、六類＋其他、comment 可空、必填欄位、存進 DB、參照 TutorialVersion、submitter 可空且可重複）→ 全紅。
2. **後綠**：實作 `app/ingest/feedback.py` 的 `collect_feedback` / `seed_feedback` / CLI → 轉綠。
3. **先紅**：`tests/unit/test_review.py` 照 `定期優化Tutorial.feature` 十條 Rule 寫 → 紅。
4. **後綠**：實作 `app/agent/feedback_review.py` 的 `review_all`，統計 → `rules.decide_review_action` → REFINE 產版 → 轉綠。
5. 加 LLM 路徑：`llm.complete_json`；`LLMUnavailable` 時走模板改寫（`reason` 固定 `"Repeated feedback indicates Step 3 lacks context."`、`source="template"`）。
6. **先紅**：`tests/unit/test_metrics_snapshot.py` 照 `展示學習指標.feature` 三條 Rule 寫 → 紅。
7. **後綠**：`metrics.py` 追加 `snapshot` / `append_history` / `load_history` → 轉綠。
8. 寫 `app/demo/ui_feedback.py` 與 `ui_metrics.py`（四個 `st.metric`、分母 0 顯示 `—`、兩張 `line_chart`）。
9. 寫 `scripts/phase4_smoke.py` 走完整劇本，實跑驗證數字。
10. 全套 `uv run pytest -q -m "not integration"` 確認沒打壞其他 phase。

---

## 3. 產出檔案

| 檔案 | 內容一句話 |
|---|---|
| `app/ingest/feedback.py` | `collect_feedback`（補版本 → 驗證 → 檢查 TutorialVersion 存在 → insert，任一關卡失敗 `OperationFailed` 不入庫）、`seed_feedback`、CLI `python -m app.ingest.feedback --file ...` |
| `app/agent/feedback_review.py` | `review_all(db, cognee=None, hydra=None)`：掃 published Tutorial → 算 `current_version` 的 avg／count／同 category 最大數 → `rules.decide_review_action` → REFINE 產 vN+1、改 `current_version`／`last_action`、重寫 `.md`；CLI `python -m app.agent.feedback_review` |
| `app/analytics/metrics.py`（修改） | 追加 `snapshot`（四個數字一次算完）、`append_history`／`load_history`（`.state/metrics_history.json`） |
| `app/demo/ui_feedback.py` | Streamlit 送 Feedback 與看歷史評分的分頁 |
| `app/demo/ui_metrics.py` | 四個 `st.metric`（分母 0 顯示 `—`）＋ 兩張 `line_chart` |
| `scripts/phase4_smoke.py` | 端到端劇本：avg 2.9 → REFINE v1→v2 → 匯 v2 高分 → 再 Review 得 KEEP，最後印 snapshot |
| `tests/unit/test_feedback.py` | 對齊 `收集Feedback.feature` 七條 Rule |
| `tests/unit/test_review.py` | 對齊 `定期優化Tutorial.feature` 十條 Rule |
| `tests/unit/test_metrics_snapshot.py` | 對齊 `展示學習指標.feature` 三條 Rule ＋ 歷史存取 |

---

## 4. 測試方式

```bash
uv run pytest -q tests/unit/test_feedback.py tests/unit/test_review.py tests/unit/test_metrics_snapshot.py
uv run python scripts/phase4_smoke.py       # 端到端劇本
python -m app.agent.feedback_review         # 手動跑一輪 Review
```

對齊的 `.feature` Rule：

| Feature | Rule 數 | 重點 |
|---|---|---|
| `收集Feedback.feature` | 7 | rating 1–5 整數／六類＋其他（未填空字串）／comment 可空／必填四欄／存進 Database／參照 TutorialVersion／submitter 可空且可重複 |
| `定期優化Tutorial.feature` | 10 | avg < 3.5 才 REFINE／只算 `current_version`／count ≥ 3／同 category ≥ 2／不因單一低分立刻改／看 pattern 不看日曆天／三條件齊備才發新版／表現好就 KEEP／**過去結果會改變系統下一次行為**／`is_possibly_outdated` 本輪 KEEP |
| `展示學習指標.feature` | 3 | deflection rate／重放解決率／圖譜覆蓋 |

---

## 5. 遇到的問題與解法

| 問題 | 原因 | 怎麼解 |
|---|---|---|
| 沒 LLM 金鑰，REFINE 整條走不下去 | `.env` 沒有 `ANTHROPIC_API_KEY` / `ROCKETRIDE_PROJECT_ID` | 接 `LLMUnavailable`，改走模板改寫並標 `source="template"`（`showme.md` 降級） |
| 同 category 門檻一直被誤觸發 | 未填的 category 存空字串，全部被算成同一類 | 計數時排除空字串 |
| REFINE 後 avg 沒變 | 一開始把所有版本的 Feedback 一起平均 | 改成只算 `current_version`，對齊 `定期優化Tutorial.feature` 第二條 Rule |
| v2 高分匯進去卻觸發第二次 REFINE | 種子匯入順序錯了——v2 的 Feedback 指向還不存在的版本 | 固定順序：先 Review 產出 v2，**再**匯 v2 的高分種子（列入 §7 手動事項） |
| 指標曲線每次重跑都接在舊資料後面 | `.state/metrics_history.json` 會累積 | 彩排前 `rm -f .state/metrics_history.json` |
| 分母 0 時 UI 顯示 `NaN` | 沒有票就沒有 deflection rate | `metrics` 回 `None`，UI 顯示 `—` |
| `.md` 看不出是第幾版 | 檔名不帶版本 | 頁尾埋 `<!-- version: vN -->` |

---

## 6. 測試結果

重跑本 phase 三支測試（2026-09-11）：

```
uv run pytest -q tests/unit/test_feedback.py tests/unit/test_review.py tests/unit/test_metrics_snapshot.py
................................................                         [100%]
48 passed in 1.86s
```

48 = `收集Feedback` 7 Rule ＋ `定期優化Tutorial` 10 Rule ＋ `展示學習指標` 3 Rule 展開的案例數，與實作回報一致。

全專案現況：

```
uv run pytest -q -m "not integration"
190 passed, 2 deselected, 2 warnings in 26.72s
```

`scripts/phase4_smoke.py` 端到端劇本的實際數字：

| 步驟 | 結果 |
|---|---|
| 匯入 v1 的 10 筆 Feedback | avg 2.9（< 3.5、≥ 3 筆、同 category ≥ 2） |
| 第一次 Review | **REFINE**，v1 → v2，`last_action='REFINE'`，`reason` 走模板 |
| 匯入 v2 的 5 筆 Feedback | avg 4.4 |
| 第二次 Review | **KEEP**（avg 4.4 ≥ 3.5） |
| snapshot | deflection rate 0.5／重放解決率 0.5／圖譜覆蓋 0.5／avg rating 4.4 |

這組數字就是 demo 要講的那條「過去結果改變未來行為」：同一支 Review 程式，第一次判 REFINE、第二次判 KEEP，差別只在累積的 Feedback。

---

## 7. 🖐️ 留給使用者的手動事項

| 項目 | 說明 |
|---|---|
| **種子匯入順序（M1/M3）** | 必須「先 Review 產出 v2，再匯 v2 的高分種子」。順序反了會觸發第二次 REFINE。demo 劇本要**口頭講明**這是兩個時間點的事 |
| **demo 時按一次 Review** | 曲線的轉折點靠這一下。別忘了按，也別按兩次 |
| **彩排前清掉歷史** | `rm -f .state/metrics_history.json`，否則曲線會接在上一輪後面 |
| **要真 LLM 改寫就補金鑰** | `.env` 補 `ANTHROPIC_API_KEY` 或 `ROCKETRIDE_PROJECT_ID`。沒補的話 REFINE 照跑，但 `reason` 是固定模板字串 |
| 驗收畫面 | Streamlit 的 Feedback 分頁與 Metrics 分頁（四個 metric ＋ 兩張曲線） |

---

## 8. 與計畫的偏差／hackathon 簡化

| 偏差 | 說明 |
|---|---|
| **REFINE 走模板降級** | 沒金鑰。介面（`llm.complete_json`）已經接好，補金鑰即切換，`source` 欄位會從 `template` 變 LLM |
| **`.md` 版型沒與 `create_tutorial` 共用 renderer** | 兩邊各自組字串，版型可能微幅不一致。抽共用 renderer 是重構，不是 demo 需求 |
| `reason` 在模板路徑是固定字串 | `"Repeated feedback indicates Step 3 lacks context."`。對齊 demo 敘事（Step 3 就是被 Release Note 改名的那一步） |
| 指標歷史存 JSON 檔不存 DB | 不是領域資料，`erm.dbml` 9 表裡沒有它的位置。存 `.state/` 最短路徑 |
| Review 沒有排程 | 「定期」在 demo 裡＝按一次按鈕。加 cron／scheduler 對八小時的 demo 沒有價值 |
| UI 只有 `st.metric` ＋ `st.line_chart` | Scope guardrail 明文寫「不做複雜 dashboard」 |
| 記憶層 `None` 就跳過 | 與 Phase 1 同一個降級哲學，不為此另寫 mock |
