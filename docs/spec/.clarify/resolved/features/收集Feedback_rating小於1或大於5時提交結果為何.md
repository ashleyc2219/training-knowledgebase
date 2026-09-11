# 釐清問題

rating 小於 1 或大於 5 時，提交 Feedback 的結果為何？

# 定位

Feature：收集Feedback / Rule：每篇 Tutorial 可收集 1 到 5 的 Rating

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | Then 操作失敗 |
| B | 自動裁切到 1 或 5 後存檔 |
| C | 仍存檔並保留原值 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

收集Feedback Rating 越界 Example；決定 Then 是「操作失敗」還是寫出裁切後／原值。

# 優先級

High
---
# 解決記錄

- **回答**：A - Then 操作失敗
- **更新的規格檔**：docs/spec/features/收集Feedback.feature
- **變更內容**：rating Rule 新增 rating 為 0 與 6 的 Example，Then 操作失敗。
