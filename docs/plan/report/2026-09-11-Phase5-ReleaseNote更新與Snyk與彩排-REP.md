# 2026-09-11 — Phase 5 Release Note 更新、Snyk 與彩排 完成報告

> ⚠️ 這只是 hackathon 作品，不要過度設計。

- 對應計畫：`docs/plan/unfinish/06-Phase5-ReleaseNote更新與Snyk與彩排.md`
- 對應規格：`docs/spec/features/輪詢ReleaseNote.feature`（3 條 Rule）、`docs/spec/features/依ReleaseNote更新Tutorial.feature`（7 條 Rule）
- 狀態：**完成**（程式面全數完成；未完成項只剩 🖐️ `snyk auth` 與 RocketRide deploy，見 §7）

---

## 1. 實作邏輯

### 這個 phase 解決什麼

Phase 5 補上學習迴圈的**第二個外部訊號**，也是收尾。

- Phase 4 的 REFINE 訊號來自**顧客**（評分低、同類抱怨多）——「教學寫得不好」。
- Phase 5 的 UPDATE／RETIRE 訊號來自**產品**（Release Note 改了按鈕名／砍了功能）——「教學寫得好，但世界變了」。

這一條是 demo 最有畫面的一步：貼一段 changelog 進去，`tutorials/cancel-order.md` 的 Step 3 從 `Click "Cancel Order"` 變成 `Click "Cancel Purchase"`，Feature 跟著改名，版本 +1。評審一眼就看懂「past outcomes change future system behavior」。

另外 Phase 5 還扛兩件收尾工作：**Snyk 安全掃描腳本**（評審明寫會掃）與**一鍵彩排腳本**（八小時黑客松最後一小時只有一次機會，不能靠手點）。

### 怎麼切

| 縱線 | 模組 | 負責 |
|---|---|---|
| 進料 | `app/ingest/changelog.py` | 輪詢 changelog（游標嚴格大於、去重）／貼一則文字入庫。**這一步只入庫，不做任何決策** |
| 決策 ＋ 執行 | `app/agent/release_update.py` | 擷取變更 → 找受影響 Tutorial → UPDATE／RETIRE／不動 → 蓋 `processed_at` |
| 畫面 | `app/demo/ui_release.py` | 左欄貼 changelog ＋ 入庫 ＋ 待處理列表；中欄處理 ＋ 動作表 ＋ 新舊 steps 並排 ＋ unified diff |
| 收尾 | `scripts/demo_rehearsal.py`、`scripts/snyk_scan.sh` | 一鍵彩排 0–7 步、安全掃描 |

**「入庫」與「處理」刻意分成兩個模組、兩個按鈕**：`輪詢ReleaseNote.feature` 明寫「本步不 UPDATE / RETIRE」。Demo 時也好講——先看到 Release 進來且 `processed_at` 為空，再按一次才動教學，兩段式比一鍵黑箱有說服力。

### 關鍵設計決定與理由

| 決定 | 理由 |
|---|---|
| `extract_changes` 先試 LLM，失敗**降級到 regex 五種句型** | changelog 是半結構化文字，LLM 抽得漂亮；但沒金鑰時 demo 不能停。regex 認得 renamed／changed／deprecated／removed／new 五種句型，結果標 `source` 讓人看得出走哪條 |
| 擷取不到任何變更 → `OperationFailed` | 「貼了一段字進去、什麼都沒發生」是最糟的 demo。寧可明確失敗 |
| 找受影響 Tutorial 走 **HydraDB 多跳**，失敗降級 SQL | 多跳查詢「這次 Release 影響哪些 Tutorial」正是 Memory 儲存層存在的理由，要讓評審看到圖在做事。但圖掛掉不能讓功能停 |
| `processed_at` 只在**整列處理成功後**才蓋 | 失敗的 Release 保持 `processed_at` 為 NULL，下次會重試。冪等的關鍵 |
| 已有 `processed_at` 的 Release **完全不碰** | `依ReleaseNote更新Tutorial.feature` 最後一條 Rule。彩排第 6 步「再處理一次 → `[]`」就是在驗這件事 |
| 彩排腳本每步印「👀 評審看到什麼」 | 這份腳本同時是**測試**與**講稿**。跑一次就知道現場該說什麼、畫面該指哪裡 |
| `snyk_scan.sh` 未登入時**寫出報告說明狀態**而不是靜默失敗 | 留下明確的「還缺這一步」證據給使用者，也給評審看得出不是忘了做 |

---

## 2. 步驟（TDD 先紅後綠）

1. **先紅**：`tests/unit/test_changelog.py` 照 `輪詢ReleaseNote.feature` 三條 Rule（只取 `created_at` 大於上次檢查／寫入的 `processed_at` 為空／相同 content ＋ created_at 不新增）寫 → 紅。
2. **後綠**：實作 `changelog.poll_changelog`（游標嚴格大於、`is_duplicate_release` 去重、`processed_at` 寫 NULL）與 `ingest_release_text`（貼一則，重複回 0）→ 8 綠。
3. **先紅**：`tests/unit/test_release.py` 照 `依ReleaseNote更新Tutorial.feature` 七條 Rule 全部寫一遍，外加 LLM 降級路徑 → 紅。
4. **後綠（a）**：實作 `extract_changes`（LLM → regex 降級 → 擷取不到就 `OperationFailed`）。
5. **後綠（b）**：實作 `process_unprocessed_releases(db, cognee, hydra, now)`：RFC 寫入 → HydraDB 多跳（失敗降級 SQL）找受影響 → 依 change_type 分流 UPDATE／RETIRE／不動 → 蓋 `processed_at` → 23 綠。
6. 接 Streamlit：`app/demo/ui_release.py` 左欄貼 changelog ＋ 入庫 ＋ 待處理列表，中欄處理 ＋ 動作表 ＋ 新舊 steps 並排 ＋ `difflib.unified_diff`；接進 `streamlit_app.py`。
7. 寫 `scripts/snyk_scan.sh`：`uv export` → `snyk test` → `snyk code test` → 輸出 `docs/plan/report/2026-09-11-snyk-scan.txt`。
8. 寫 `scripts/demo_rehearsal.py`：0–7 步一鍵彩排，每步印耗時、關鍵資料列、與「👀 評審看到什麼」。
9. **整合抓蟲**：彩排第 6 步的多跳查詢查不到受影響 Tutorial → 修 `hydradb_client` 的 key 正規化（見 §5）。
10. 全套回歸 → 全綠；彩排 8 步全綠。

---

## 3. 產出檔案

| 檔案 | 行數 | 內容 |
|---|---|---|
| `app/ingest/changelog.py` | 89 | `poll_changelog`（游標嚴格大於、`is_duplicate_release` 去重、`processed_at` NULL）、`ingest_release_text`（貼一則文字入庫，重複回 0） |
| `app/agent/release_update.py` | 418 | `extract_changes`（LLM → 降級 regex 五種句型，結果標 `source`；擷取不到 → `OperationFailed`）、`process_unprocessed_releases(db, cognee, hydra, now)`（RFC 寫入 → HydraDB 多跳／SQL 降級找受影響 → UPDATE 產 vN+1 ＋ Feature 改名 ＋ 重寫 `.md`／RETIRE 蓋三旗標 ＋ `Feature.status`／new 不動 → 蓋 `processed_at`；已處理的不碰；失敗列 `processed_at` 保持 NULL） |
| `app/demo/ui_release.py` | 111 | 左欄貼 changelog ＋ 入庫 ＋ 待處理列表；中欄處理 ＋ 動作表 ＋ 新舊 steps 並排 ＋ unified diff；已接進 `streamlit_app.py` |
| `scripts/demo_rehearsal.py` | 263 | 0–7 步一鍵彩排，每步印耗時與「👀 評審看到什麼」 |
| `scripts/snyk_scan.sh` | 116 | `uv export` → `snyk test` → `snyk code test` → 寫 `docs/plan/report/2026-09-11-snyk-scan.txt` |
| `docs/plan/report/2026-09-11-snyk-scan.txt` | — | 掃描報告（目前狀態：CLI 未登入，未執行掃描；含 `.env` 未進 git 的檢查結果 ✅） |
| `tests/unit/test_changelog.py` | 115 | 8 tests |
| `tests/unit/test_release.py` | 423 | 23 tests |

整合階段的順手修正：

| 檔案 | 改了什麼 | 為什麼 |
|---|---|---|
| `app/memory/hydradb_client.py` | 加 `_canon_key()`：scalar → `{"id"}`、Tutorial `{"id"}` → `{"tutorial_id"}`、Feature `{"id"}` → 對回 `{"name"}` | 見 §5 第一列 |

---

## 4. 測試方式（指令＋對齊 .feature Rule）

```bash
cd /Users/linjunting/AWS-Hackathon
uv run pytest -q tests/unit/test_changelog.py tests/unit/test_release.py
uv run python scripts/demo_rehearsal.py    # sqlite 一鍵彩排 0–7 步（安全）
bash scripts/snyk_scan.sh                  # 需先 snyk auth
```

| 測試檔 | 對齊的 Rule | 條數 |
|---|---|---|
| `test_changelog.py` | `輪詢ReleaseNote.feature` 全 3 條：只把 `created_at` 大於上次檢查的列寫入 Release／寫入的 Release `processed_at` 為空／相同 content 與 created_at 已存在時不新增列 | 8 |
| `test_release.py` | `依ReleaseNote更新Tutorial.feature` 全 7 條：擷取變更寫入 `ReleaseFeatureChange`／只依 `Tutorial.feature_id` 找受影響／renamed 或 changed → UPDATE／deprecated 或 removed → RETIRE／new feature 無對應 Tutorial 時不決定動作／找不到受影響只記 `processed_at`／已有 `processed_at` 不再處理。外加 LLM 降級與 regex 五句型 | 23 |

彩排腳本本身就是端到端驗收：0 重置 → 1 種子建圖 → 2 餵 3 張轉真人 CREATE v1 → 3 第 4 張 deflected ＋ Rote 捕捉 → 4 第 5 張重放 → 5 Feedback REFINE v2 → 6 貼 Release Note UPDATE v3 → 7 三條指標 ＋ Step 3 文字。

---

## 5. 遇到的問題與解法

| 問題 | 現象 | 解法 |
|---|---|---|
| **多跳查詢查不到受影響 Tutorial** | 彩排第 6 步 `process_unprocessed_releases` 走 HydraDB 多跳時回空，只能靠 SQL 降級才有結果——等於 Memory 儲存層在 demo 最關鍵的一步沒有作用 | 根因是三個寫入點（Phase 1 seed／Phase 2 create／Phase 5 release）給同一個節點用了不同的 key 形狀。在 `app/memory/hydradb_client.py` 加 `_canon_key()` 正規化：scalar → `{"id"}`、Tutorial `{"id"}` → `{"tutorial_id"}`、Feature `{"id"}` → 對回 `{"name"}`。修完 `affected_by_release` 多跳命中 |
| LLM 沒金鑰就抽不出變更 | `extract_changes` 全靠 LLM，沒金鑰時整個 Phase 5 停擺 | 降級到 regex 五種句型（renamed／changed／deprecated／removed／new），結果標 `source` 讓人看得出走哪條。彩排實跑即走降級路徑，仍然正確產出 UPDATE |
| 五欄驗證擋住 UPDATE | UPDATE 是「改寫既有版本的 steps」，硬套 CREATE 的五欄必填會把改寫擋掉 | 放寬成「改寫後 steps 非空」。見 §8，這是刻意的簡化 |
| 重複處理同一則 Release | 按兩次「處理」會產出兩個新版本 | `processed_at` 只在整列成功後才蓋；已有 `processed_at` 的直接跳過。彩排第 6 步加一行「再處理一次（冪等驗證）→ `[]`」把這件事變成可見的驗收 |
| 處理到一半失敗留下半套狀態 | RFC 寫了但 UPDATE 失敗 | 失敗列的 `processed_at` **保持 NULL**，下一輪會重試。不是完美交易，但方向對 |
| `snyk auth` 要瀏覽器 OAuth | Agent 無法代勞 | `snyk_scan.sh` 偵測未登入時**不靜默失敗**，改寫出一份說明狀態與後續步驟的報告到 `docs/plan/report/2026-09-11-snyk-scan.txt`，順便把「`.env` 未進 git」的檢查結果寫進去（兩項都 ✅） |

---

## 6. 測試結果（實跑數字）

```
$ uv run pytest -q tests/unit/test_changelog.py tests/unit/test_release.py
31 passed
```

| 測試檔 | 通過 |
|---|---|
| `test_changelog.py` | 8 |
| `test_release.py` | 23 |
| **Phase 5 小計** | **31** |

全套回歸：`uv run pytest -q -m "not integration"` → **190 passed, 2 deselected, 11.35s**。

彩排腳本實跑（`uv run python scripts/demo_rehearsal.py`）——8 步全綠，總耗時 **5.5 秒**（目標 ≤ 300 秒）：

```
✅ 0 重置：0.0s｜OK
✅ 1 種子建圖：0.0s｜OK
✅ 2 餵 3 張 cancel_order → 轉真人 → CREATE v1：3.8s｜OK
✅ 3 第 4 張 cancel_order 票 → deflected ＋ Rote 捕捉：0.5s｜OK
✅ 4 第 5 張 cancel_order 票 → 重放：1.1s｜OK
✅ 5 Feedback 種子 → Review → REFINE v2：0.1s｜OK
✅ 6 貼 Release Note → 入庫 → 處理 → UPDATE：0.0s｜OK
✅ 7 三條指標 ＋ Step 3：0.0s｜OK
```

第 6 步（本 phase 的主戲）的實際輸出：

```
入庫 Release #1（processed_at 為空）
process_unprocessed_releases → [{'release_id': 1, 'tutorial_id': 1, 'action': 'UPDATE'}]
Feature：[{'id': 1, 'name': 'Cancel Purchase', 'status': 'active'}, ...]
Tutorial #1 tutorials/cancel-order.md｜published｜v3｜UPDATE
再處理一次（冪等驗證）→ []（應為 []）
```

第 7 步收尾數字：deflection rate **1.00**、重放解決率 **0.50**、圖譜覆蓋 **0.33**，`tutorials/cancel-order.md` 標題與 Step 3 皆已變成 `Cancel Purchase`。

> 註：第 7 步的「平均 rating（current_version）」印 0.00 是**正確**的——v2 收過 5 筆 4.4 分回饋後，第 6 步把教學推到 v3，v3 還沒有任何回饋。指標定義本來就是「只算 `current_version`」。

`scripts/snyk_scan.sh` 實跑：偵測到 Snyk CLI **1.1307.2 已安裝但未登入**，依設計寫出報告說明狀態與後續步驟，未執行掃描。

---

## 7. 🖐️ 留給使用者的手動事項

完整版見 `docs/plan/todo/2026-09-11-手動設定清單.md`。與 Phase 5 直接相關的三項：

| # | 項目 | 影響 Phase 5 的什麼 | 沒做的降級 |
|---|---|---|---|
| 3 | **Snyk 登入 ＋ 掃描**（**必做**）：註冊免費帳號 → `snyk auth`（瀏覽器 OAuth，agent 代勞不了）→ `bash scripts/snyk_scan.sh` → 截圖網頁儀表板與 CLI 輸出存進 `docs/plan/report/` | 安全層有沒有證據 | **沒有降級**。`docs/hackathon.md` §2 明寫「Apps will be scanned with Snyk and vulnerabilities found will reduce points」。驗收只收 exit code 0；有 high 以上當場修 |
| 2 | **HydraDB instance ＋ 連線字串**：`.env` 填 `HYDRADB_URI` / `HYDRADB_APIKEY`（**注意不是** `HYDRADB_API_KEY`），拿到憑證後再叫 agent 接 `hydradb_client._post()` | Phase 5 的多跳查詢「這次 Release 影響哪些 Tutorial」跑在哪裡 | 落回本機 `.state/graph.json`，多跳用 `CYPHER_TEMPLATES` 具名模板在本機算。功能正常，但**五層裡的儲存層變成一個 JSON 檔**，這是最容易被評審抓的一層 |
| 4 | **RocketRide deploy**（見 Phase 2 報告 §7 同一項） | Motion 層 | 決策由本機 Python 跑 |

> 🚨 **紅線**：deploy／schedules／publishApp 只能用 `ROCKETRIDE_DEPLOY_URI` / `ROCKETRIDE_DEPLOY_APIKEY`，絕不 deploy 到 dev 連線。本 phase 的程式**完全沒有碰過 `ROCKETRIDE_DEPLOY_*`**。

---

## 8. 與計畫的偏差／hackathon 簡化

| 項目 | 計畫寫的 | 實際做的 | 為什麼 |
|---|---|---|---|
| UPDATE 的內容驗證 | 沿用 CREATE 的「五欄必填」 | 放寬成「**改寫後 steps 非空**」 | UPDATE 改的是既有版本的 steps，其餘四欄從上一版承接。硬套五欄必填會把正常的改寫擋掉 |
| `changelog.json` 筆數 | 多則 changelog 驗游標推進 | **只放 1 列** | Demo 只講一則 Release Note 的故事。游標「嚴格大於」的行為改由 `test_changelog.py` 的 8 個單元測試覆蓋，不必靠資料量 |
| 變更擷取 | LLM 擷取 | LLM → **regex 五句型降級** | 沒金鑰時 demo 不能停。彩排實跑走的就是降級路徑，仍正確產出 UPDATE |
| 處理失敗的回復 | 「交易式」 | `processed_at` 保持 NULL 等下輪重試 | 與 Phase 2 同樣的理由：沒有跨 backend 的交易介面 |
| Snyk | 「跑完掃描、貼結果」 | **腳本寫好、掃描未跑** | `snyk auth` 需要瀏覽器登入，只有使用者能做。腳本已備妥，登入後一行指令即可完成 |
| 彩排步數 | 六步 | **0–7 共八步** | 拆出獨立的「0 重置」與「7 指標收尾」，讓每次彩排都從乾淨狀態開始、以三條曲線結束 |
