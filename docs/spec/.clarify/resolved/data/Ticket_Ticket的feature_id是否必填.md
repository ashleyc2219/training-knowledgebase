# 釐清問題

Ticket 的 feature_id 是否必填

# 定位

ERM：Ticket.feature_id

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 必填，每張 Ticket 寫入時就必須指向一個 Feature |
| B | 可為空，分析前或無法對應功能時允許 null |
| C | 可為空，但進入聚集或觸發 CREATE 前必須補上 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Ticket、Feature；分析 Support Tickets 的 asks_about 關聯與測試資料是否允許無功能票

# 優先級

High
---
# 解決記錄

- **回答**：B - 可為空，分析前或無法對應功能時允許 null
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Ticket.feature_id Note 註明可空；Ref Ticket.feature_id > Feature.id 維持。
