# 釐清問題

觸發 CREATE 的決策應屬於分析SupportTickets 還是建立Tutorial？

# 定位

Feature：分析SupportTickets / Rule：當存在新的 recurring question 且目前沒有 Tutorial 可以解決時觸發 CREATE

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 僅屬分析SupportTickets，建立Tutorial 只負責產出 v1 |
| B | 僅屬建立Tutorial，分析只輸出 Knowledge Gap |
| C | 兩功能都保留同一條觸發 CREATE 的 Rule |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

分析SupportTickets 與建立Tutorial 的功能界線；決定 CREATE 的 When／Then 寫在哪一份 feature。

# 優先級

Medium
---
# 解決記錄

- **回答**：A - 僅屬分析SupportTickets，建立Tutorial 只負責產出 v1
- **更新的規格檔**：docs/spec/features/分析SupportTickets.feature
- **變更內容**：CREATE 決策 Rule 只留在本檔；建立 Tutorial 只產 v1，不再寫觸發 CREATE
