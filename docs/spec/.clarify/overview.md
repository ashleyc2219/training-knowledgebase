# Clarify 釐清策略總覽

狀態：**Clarify 已完成（2026-09-11）**。所有釐清項目皆已解決並歸檔，`data/` 與 `features/` 目前為空。

- 決策總表：`resolved/決策總表.md`（四題使用者拍板 ★，其餘依黑客松原則自答）
- 個別解決記錄：`resolved/data/*.md`（43 題）、`resolved/features/*.md`（54 題）
- 2026-09-11 使用者補件：Release Note 定期入庫，新增 Feature `輪詢ReleaseNote`（不推翻既有決策）

---

## 3.1 釐清項目統計

- 資料模型相關：0 項待處理（43 項已解決）
- 功能模型相關：0 項待處理（54 項已解決）
- 總計：0 項待處理（97 項已解決）

## 3.2 優先級分佈（待處理）

- High：0
- Medium：0
- Low：0

## 3.3 建議釐清順序

無待處理項目。

## 3.4 本輪定案的核心方向

1. 產品主軸 = 客服 deflection 教學生成器（`docs/客服自助教學生成器 — 系統架構規格.md` 為準）；Tutorial 生命週期 CREATE / UPDATE / REFINE / KEEP / RETIRE 保留為內核。
2. Demo 領域 = Bitext Customer Support 資料集；主打 `cancel_order` / `track_refund` / `change_shipping_address`。
3. Tutorial 建立即 published；`status` 保留 draft / published / retired。
4. 回饋雙訊號：顯性 `Feedback`（rating / category / comment）＋隱性再開票（`Ticket.reopened_from_ticket_id`）。
5. Release Note 只驅動 UPDATE / RETIRE；CREATE 只由分析 Ticket 決定。
6. Release Note 定期入庫：輪詢 changelog 來源寫入 `Release`（`processed_at` 為空），再處理。

## 3.5 覆蓋度摘要（最終）

| 分類 | 狀態 | 說明 |
|------|------|------|
| A1. 實體完整性 | Resolved | 9 表：Ticket / UserProblem / Feature / Tutorial / TutorialVersion / Feedback / Release / ReleaseFeatureChange / Workflow。Customer、ProductDocument、Slack 決議不入庫 |
| A2. 屬性定義 | Resolved | 每欄有型別與 note；Feedback 有 `id` PK；內容欄只在 TutorialVersion |
| A3. 屬性值邊界 | Resolved | rating 1–5、avg < 3.5、feedback_count ≥ 3、同 category ≥ 2、recurring topic ≥ 3 張皆有臨界 Example |
| A4. 跨屬性不變條件 | Resolved | Ticket deflected ⇔ 兩個 deflected_* 欄有值；is_obsolete ⇒ retired / RETIRE / outdated=false；published ⇒ current_version 有值 |
| A5. 關係與唯一性 | Resolved | 13 條 Ref；UserProblem.topic 唯一；Tutorial 1:1 UserProblem；Workflow 1:1 UserProblem |
| A6. 生命週期與狀態 | Resolved | Ticket open → deflected / escalated → resolved；Tutorial draft / published / retired；Feature active / deprecated / removed；Release processed_at |
| B1. 功能識別 | Resolved | 11 個 Feature：建構知識圖譜、輪詢新票單、輪詢ReleaseNote、自動回覆顧客、重放已驗證流程、分析SupportTickets、建立Tutorial、收集Feedback、定期優化Tutorial、依ReleaseNote更新Tutorial、展示學習指標。審核教學草稿、監測即時票務決議不建 |
| B2. 規則完整性 | Resolved | 58 條 Rule，0 條 `#TODO` |
| B3. 例子覆蓋度 | Resolved | 81 個 Example，共用 step 句型 40 句 |
| B4. 邊界條件覆蓋 | Resolved | 剛好 3 張／2 張、rating 1／5／0／6、avg = 3.5、REFINE×UPDATE 衝突、已處理 Release、retired Tutorial、再開票 |
| B5. 錯誤與異常處理 | Resolved | 前置失敗一律 `Then 操作失敗`（14 處）；空結果用空表 |
| C1. 詞彙表 | Resolved | 見 `resolved/決策總表.md` §術語正規化 |
| C2. 術語衝突 | Resolved | 使用者→顧客；教學文章→Tutorial；問題類型→UserProblem；changelog→Release |
| D1. 待決事項 | Resolved | 0 條 `#TODO`、0 題待釐清 |
| D2. 模糊描述 | Resolved | 「數量足夠」「表現良好」「一段時間」「語意相似」「recurring complaints」皆已量化 |

## 3.6 後續建議

- Design 已寫入 `docs/design/showme.md`；畫面草圖在 `docs/design/architecture.md`。
- 若實作時發現新歧義，再執行 Discovery；不要直接改 `resolved/` 內的決策。
