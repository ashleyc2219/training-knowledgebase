# 釐清問題

Tutorial 是否要關聯 UserProblem 或問題類型

# 定位

ERM：Tutorial 與 UserProblem

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不建關聯，Tutorial 只透過 feature_id 連 Feature |
| B | Tutorial 新增 user_problem_id，一篇教學對應一個 UserProblem |
| C | 另建中介表，一篇 Tutorial 可對應多個 UserProblem |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Tutorial、UserProblem；建立 Tutorial、分析 Support Tickets 的 Knowledge Gap 對應；架構規格「教學與問題類型的對應」

# 優先級

High
---
# 解決記錄

- **回答**：B - Tutorial 新增 user_problem_id，一篇教學對應一個 UserProblem
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Tutorial 新增 user_problem_id（必填）；Ref Tutorial.user_problem_id - UserProblem.id（1:1）。
