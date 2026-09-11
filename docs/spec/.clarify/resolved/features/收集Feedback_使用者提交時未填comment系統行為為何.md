# 釐清問題

使用者提交 Feedback 時未填 comment，系統行為為何？

# 定位

Feature：收集Feedback / Rule：每篇 Tutorial 可收集 Optional Comment

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 允許提交，comment 存成空字串 |
| B | Then 操作失敗 |
| C | 僅當 rating 與 feedback_category 都有值時才允許空 comment |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

收集Feedback 的 Optional Comment 與「必須包含 comment」Rule 衝突如何改寫；需補未填 comment 的 Example。

# 優先級

High
---
# 解決記錄

- **回答**：A - 允許提交，comment 存成空字串
- **更新的規格檔**：docs/spec/features/收集Feedback.feature
- **變更內容**：comment Rule 新增未填 Example，Then comment 為空字串；並保留三則 Bitext comment 成功 Example。
