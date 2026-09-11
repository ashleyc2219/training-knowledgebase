# 釐清問題

Rote 重放的對象是解票步驟還是教學工作流？

# 定位

Feature：重放已驗證流程 / Rule：缺失功能

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只重放解決該類客服問題的操作步驟 |
| B | 只重放分析票單到發布教學的工作流 |
| C | 兩種已驗證流程都要可重放 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

重放已驗證流程的功能範圍與 When／Then；避免與自動回覆顧客、依ReleaseNote更新Tutorial 重疊。

# 優先級

High
---
# 解決記錄

- **回答**：A - 只重放攔截流程（匹配 UserProblem → 取 Tutorial → 回覆 → 更新 Ticket），以 UserProblem 為鍵
- **更新的規格檔**：docs/spec/features/重放已驗證流程.feature
- **變更內容**：新建重放已驗證流程.feature；When 為系統自動回覆顧客；Workflow 以 user_problem_id 為鍵。
