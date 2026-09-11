# 釐清問題

Ticket 是否要有 SLA 期限或問題類別欄位？

# 定位

ERM：`Ticket` 無 SLA、無 category
來源：客服規格 hotdata「哪一類問題票量暴增」「SLA 快超時的類別」
已有相關：`UserProblem_UserProblem與問題類型是否為同一概念`；`Ticket_Ticket是否要有created_at`

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 都不新增；類別用 UserProblem／Feature 推導，SLA 不做 |
| B | 只新增 category 字串；SLA 不做 |
| C | 新增 sla_due_at；類別不落地 |
| D | 同時新增 category 與 sla_due_at |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

即時監測與 demo 曲線維度。選 A 則「SLA 快超時」無法用 ERM 驗收。類別若等於 UserProblem，應選 A 或只加 SLA。

# 優先級

Medium
---
# 解決記錄

- **回答**：B - 只新增 category 字串；SLA 不做
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Ticket 新增 category（可空，對應 Bitext category）；未新增 SLA 或 sla_due_at 欄位。
