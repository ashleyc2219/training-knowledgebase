# 釐清問題

沒有對應 TutorialVersion 時，提交 Feedback 的行為為何？

# 定位

Feature：收集Feedback / Rule：Feedback 參照 TutorialVersion

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | Then 操作失敗 |
| B | 仍存檔但不關聯任何 TutorialVersion |
| C | 自動關聯該 Tutorial 最新版本並成功存檔 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

收集Feedback 參照 TutorialVersion Rule（#TODO）與必填 tutorial_version；需補無版本的錯誤或自動關聯 Example。

# 優先級

High
---
# 解決記錄

- **回答**：A - Then 操作失敗
- **更新的規格檔**：docs/spec/features/收集Feedback.feature
- **變更內容**：參照 TutorialVersion Rule 新增指定不存在的 v9 時 Then 操作失敗。
