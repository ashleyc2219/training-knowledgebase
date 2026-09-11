# 釐清問題

使用者提交 Feedback 時未填 rating，系統行為為何？

# 定位

Feature：收集Feedback / Rule：Feedback 必須包含 tutorial_id、tutorial_version、rating、feedback_category、comment、timestamp

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | Then 操作失敗 |
| B | 允許提交，rating 為空 |
| C | 自動帶入 3 並成功存檔 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

收集Feedback 必填欄 Rule（#TODO）的 rating 前置條件；需補未填 rating 的「操作失敗」或預設值 Example。

# 優先級

High
---
# 解決記錄

- **回答**：A - Then 操作失敗
- **更新的規格檔**：docs/spec/features/收集Feedback.feature
- **變更內容**：rating Rule 新增未填 rating 的 Example，When 不給 rating 欄，Then 操作失敗。
