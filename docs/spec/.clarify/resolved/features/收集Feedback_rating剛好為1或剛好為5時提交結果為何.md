# 釐清問題

rating 剛好為 1 或剛好為 5 時，提交 Feedback 的結果為何？

# 定位

Feature：收集Feedback / Rule：每篇 Tutorial 可收集 1 到 5 的 Rating

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 1 與 5 都提交成功 |
| B | 僅 2 到 4 成功，1 與 5 操作失敗 |
| C | 1 成功、5 操作失敗 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

收集Feedback Rating Rule（#TODO）的含端點 Example；Then 需寫出 rating 值為 1 與 5。

# 優先級

High
---
# 解決記錄

- **回答**：A - 1 與 5 都提交成功
- **更新的規格檔**：docs/spec/features/收集Feedback.feature
- **變更內容**：rating Rule 新增剛好為 1、剛好為 5 的成功 Example，Then Feedback.rating 分別為 1 與 5。
