# 釐清問題

建立對應 Tutorial 後，UserProblem 是否要標記已填補或關閉？

# 定位

ERM：`UserProblem` 只有 id、topic，無狀態
Feature：`分析SupportTickets` 已有「已有對應 Tutorial 時是否仍 CREATE」；本體問的是缺口實體要不要閉合
已有相關：`Tutorial_Tutorial是否要關聯UserProblem或問題類型`、`UserProblem_UserProblem與問題類型是否為同一概念`

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不新增狀態；有沒有對應教學只靠查 Tutorial 關聯 |
| B | UserProblem 新增 status，值含 open 與 filled |
| C | 新增 closed_at；填補後保留 topic 供後續票匹配 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Knowledge Gap 是否可重開、hotdata「哪些問題完全沒有對應教學」、CREATE 閘門用狀態還是 join。選 A 則「缺口已填」不是一等欄位。

# 優先級

Medium
---
# 解決記錄

- **回答**：A - 不新增狀態；有沒有對應教學只靠查 Tutorial 關聯
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：不新增欄位；UserProblem Note 已註明是否已有教學不落欄，以 Tutorial.user_problem_id 查詢。
