# 釐清問題

一張 Ticket 是否只能對應一個 Feature

# 定位

ERM：Ticket.asks_about Feature

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 維持 N:1，一張 Ticket 只指向一個 Feature |
| B | 改為 N:M，一張 Ticket 可指向多個 Feature |
| C | 維持一個主 Feature 外鍵，其餘功能只寫在 content 字串裡 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Ticket、Feature 與可能的中介表；分析 Support Tickets 的 asks_about 基數與測試案例

# 優先級

High
---
# 解決記錄

- **回答**：A - 維持 N:1，一張 Ticket 只指向一個 Feature
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：維持 Ticket N:1 Feature（asks_about）；Ref Ticket.feature_id > Feature.id，未建中介表。
