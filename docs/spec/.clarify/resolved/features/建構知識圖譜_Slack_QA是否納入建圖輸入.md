# 釐清問題

Slack Q&A 是否納入建圖輸入？

# 定位

Feature：建構知識圖譜（若「離線建圖是否獨立功能」選 B，則改掛分析SupportTickets 的前置輸入）
客服規格 Cognee 輸入：歷史已解決票單、產品文件／API 說明、Slack Q&A
design-draft Cognee 輸入：Support Tickets、Release Notes、Tutorial Content、User Feedback——無 Slack
資料題已問是否新增產品文件實體；未問 Slack
**依賴**：產品主軸題；`建構知識圖譜_歷史種子離線建圖是否為獨立於分析SupportTickets的功能`（若建圖不入規格，此題可終止）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 必須納入，建圖／分析的 Given 可含 Slack Q&A |
| B | 不納入，輸入僅票單與已決議的產品文件／Release／Feedback |
| C | Demo 可用 Slack 檔當票單來源，但不另建 Slack 輸入規則 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定建圖或分析的輸入 Example 要不要 Slack 列，以及 ERM 是否需要來源類型。選 A 才會新增 Slack 相關 Rule。

# 優先級

Medium
---
# 解決記錄

- **回答**：B - 不納入，輸入僅票單與已決議的產品文件／Release／Feedback
- **更新的規格檔**：docs/spec/features/建構知識圖譜.feature
- **變更內容**：不進 Feature；已在 建構知識圖譜.feature 的 Feature 描述註明 demo 資料安排不列規則
