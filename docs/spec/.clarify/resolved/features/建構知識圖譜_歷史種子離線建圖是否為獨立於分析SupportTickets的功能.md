# 釐清問題

歷史種子離線建圖，是否為獨立於分析 Support Tickets 的功能？

# 定位

Feature：建構知識圖譜 / Rule：缺失功能
客服規格 Demo：先用歷史種子離線建圖，再現場餵即時票
design-draft：Cognee 消化 Tickets／RN／Tutorial／Feedback，但無獨立「建圖」Feature
已有釐清：`輪詢新票單_Demo現場餵入模擬即時票單是否與hotdata輪詢新票為同一功能`（問的是進票，不是離線建圖）
**依賴**：產品主軸題

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 是獨立功能：離線種子建圖有自己的 When／Then，分析只跑在已建圖之後 |
| B | 不是獨立功能：建圖就是分析 Support Tickets 的實作細節，不另建 Feature |
| C | 建圖只是 Demo 準備步驟，不進入作用中規格 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

B1：要不要新增 `建構知識圖譜`。選 A 則分析的 Given 必須是「圖譜已存在」；選 B／C 則種子資料只當分析的 Given Tickets。不在此題決定用哪個 SDK。

# 優先級

High
---
# 解決記錄

- **回答**：A - 是獨立功能：離線種子建圖有自己的 When／Then，分析只跑在已建圖之後
- **更新的規格檔**：docs/spec/features/建構知識圖譜.feature
- **變更內容**：新增獨立 Feature，When 系統匯入歷史票單，Then 驗 Ticket、UserProblem、Feature 資料狀態
