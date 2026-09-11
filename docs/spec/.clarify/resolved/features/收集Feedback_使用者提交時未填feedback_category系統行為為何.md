# 釐清問題

使用者提交 Feedback 時未填 feedback_category，系統行為為何？

# 定位

Feature：收集Feedback / Rule：每篇 Tutorial 可收集 Feedback Category

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | Then 操作失敗 |
| B | 允許提交，feedback_category 存成空字串 |
| C | 自動帶入預設類別「其他」並成功存檔 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

收集Feedback Category Rule（#TODO）與必填欄 Rule；需補未填 category 的成功或「操作失敗」Example。

# 優先級

High
---
# 解決記錄

- **回答**：B - 允許提交，feedback_category 存成空字串
- **更新的規格檔**：docs/spec/features/收集Feedback.feature
- **變更內容**：feedback_category Rule 新增未填 Example，Then feedback_category 為空字串。
