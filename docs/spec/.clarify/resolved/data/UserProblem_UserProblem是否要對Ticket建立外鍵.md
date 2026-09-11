# 釐清問題

UserProblem 是否要對 Ticket 建立外鍵

# 定位

ERM：UserProblem 與 Ticket 的關係

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不建 FK，聚集關係不入庫 |
| B | Ticket 新增 user_problem_id，多張 Ticket 指向一個 UserProblem |
| C | 另建 TicketUserProblem 中介表做 N:M |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

UserProblem、Ticket；分析 Support Tickets 將相似票聚成 recurring topic 的持久化與追溯測試

# 優先級

High
---
# 解決記錄

- **回答**：B - Ticket 新增 user_problem_id，多張 Ticket 指向一個 UserProblem
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Ticket 新增 user_problem_id（可空）；Ref Ticket.user_problem_id > UserProblem.id。
