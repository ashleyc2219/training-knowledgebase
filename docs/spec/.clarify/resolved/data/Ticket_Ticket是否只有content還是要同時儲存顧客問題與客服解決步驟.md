# 釐清問題

Ticket 是否只有 content，還是要同時儲存顧客問題與客服解決步驟

# 定位

ERM：Ticket.content

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只保留 content 一個字串欄，顧客問題與解決步驟都寫進同一欄 |
| B | 刪除或降級 content，改為 customer_problem 與 resolution_steps 兩個字串欄 |
| C | 保留 content，另外新增 customer_problem 與 resolution_steps |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Ticket 欄位；分析 Support Tickets、建立 Tutorial；架構規格「歷史已解決票單＝顧客問題＋客服解決步驟」能否入庫與驗收

# 優先級

High
---
# 解決記錄

- **回答**：Short - content＋resolution_steps
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Ticket.content 為顧客問題本文；新增 Ticket.resolution_steps（可空，新進票尚未解決時為空）。
