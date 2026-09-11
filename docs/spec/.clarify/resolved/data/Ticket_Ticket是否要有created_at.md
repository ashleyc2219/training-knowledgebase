# 釐清問題

Ticket 是否要有 created_at

# 定位

ERM：Ticket.created_at

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 新增 created_at 字串欄且必填，供輪詢新票 |
| B | 新增 created_at 但允許空值 |
| C | 不新增，新票偵測不依時間欄位 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Ticket；架構規格對票單表 `WHERE created_at > 上次檢查時間` 的輪詢；分析 Support Tickets 的時間邊界測試

# 優先級

High
---
# 解決記錄

- **回答**：A - 新增 created_at 字串欄且必填，供輪詢新票
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Ticket 新增 created_at（必填）；Note 註明輪詢新票用 created_at > 上次檢查時間。
