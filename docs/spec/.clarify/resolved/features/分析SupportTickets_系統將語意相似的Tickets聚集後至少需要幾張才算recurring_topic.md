# 釐清問題

系統將語意相似的 Tickets 聚集後，至少需要幾張才算 recurring topic？

# 定位

Feature：分析SupportTickets / Rule：系統可將語意相似的 Tickets 聚集在一起

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 至少 3 張才算 recurring topic，少於 3 張不得識別該 topic |
| B | 至少 20 張才算 recurring topic |
| C | 不設張數門檻，能聚成同一主題即算 recurring topic |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

分析SupportTickets 的聚集 Rule 與 CREATE 前置條件；需補「剛好達標／少一張不達標」Example，並決定現有 3 張 Example 是否仍算通過。

# 優先級

High
---
# 解決記錄

- **回答**：A - 至少 3 張才算 recurring topic，少於 3 張不得識別該 topic
- **更新的規格檔**：docs/spec/features/分析SupportTickets.feature
- **變更內容**：補剛好 3 張識別、只有 2 張空表的 Example
