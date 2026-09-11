# 釐清問題

Workflow 要關聯 Tutorial、Ticket 還是問題類型

# 定位

ERM：Workflow 與其他實體的關係

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不建任何 FK，Workflow 只存 steps |
| B | 只對 Tutorial 建 FK |
| C | 只對 UserProblem 或問題類型建 FK |
| D | 只對 Ticket 建 FK |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Workflow 外鍵；Rote 重放要綁定哪種業務對象；分析 Support Tickets 與建立 Tutorial 後能否重用已驗證流程

# 優先級

High
---
# 解決記錄

- **回答**：C - 只對 UserProblem 或問題類型建 FK
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Workflow 新增 user_problem_id（必填且唯一）；Ref Workflow.user_problem_id - UserProblem.id（1:1）。未對 Tutorial 或 Ticket 建 FK。
