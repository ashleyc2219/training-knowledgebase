# 釐清問題

UserProblem 是否要對 Feature 建立外鍵

# 定位

ERM：UserProblem 與 Feature 的關係

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不建 FK，問題與功能只透過 Ticket 或 Tutorial 間接相連 |
| B | UserProblem 新增 feature_id，一個問題對應一個 Feature |
| C | 另建中介表，一個 UserProblem 可對應多個 Feature |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

UserProblem、Feature；分析 Support Tickets 與建立 Tutorial 時「問題經常與哪個功能有關」的查詢與測試

# 優先級

High
---
# 解決記錄

- **回答**：B - UserProblem 新增 feature_id，一個問題對應一個 Feature
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：UserProblem 新增 feature_id（可空）；Ref UserProblem.feature_id > Feature.id。
