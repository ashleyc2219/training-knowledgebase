# 釐清問題

一次分析識別出多個 Knowledge Gap 時，系統行為為何？

# 定位

Feature：分析SupportTickets / Rule：系統可判斷是否存在新的 Knowledge Gap
現有 Example 都只產出一個 topic「Meeting Preparation」
後置：觸發 CREATE 的 Rule 未說明一次可觸發幾次建立

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 一次分析可識別多個 Knowledge Gap，每個符合條件的 gap 都觸發 CREATE |
| B | 一次分析只保留票量最多的一個 Knowledge Gap，其餘忽略 |
| C | 一次分析可識別多個，但本次只建立第一個；其餘留待下次分析 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 `分析SupportTickets` 的 Then 是 1 列還是 N 列 topic，以及 `建立Tutorial` 是否要支援一次產出多篇 Tutorial。影響 demo 資料安排與測試案例數。

# 優先級

Medium
---
# 解決記錄

- **回答**：A - 一次分析可識別多個 Knowledge Gap，每個符合條件的 gap 都觸發 CREATE
- **更新的規格檔**：docs/spec/features/分析SupportTickets.feature
- **變更內容**：新增 cancel_order 與 track_refund 兩個 gap 皆 CREATE 的 Example
