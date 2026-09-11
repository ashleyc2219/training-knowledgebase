# 釐清問題

「不得因單一使用者低分立刻修改 Tutorial」中的「單一」如何用 Example 驗證？

# 定位

Feature：定期優化Tutorial / Rule：不得因單一使用者低分立刻修改 Tutorial

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 僅 1 筆 rating 低於 3.5 時動作為 KEEP |
| B | 僅 1 筆 Feedback 時無論分數都 KEEP |
| C | 1 筆低分且無 recurring complaints 時 KEEP |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

定期優化Tutorial 單一低分 Rule（#TODO）；並需修正現有「僅 1 筆 comment 仍發布 v2」Example 是否違規。

# 優先級

High
---
# 解決記錄

- **回答**：B - 僅 1 筆 Feedback 時無論分數都 KEEP
- **更新的規格檔**：docs/spec/features/定期優化Tutorial.feature
- **變更內容**：「不得因單一低分立刻修改」Rule 以只有 1 筆 rating=1 的 Example 驗證 Then 動作為 KEEP。
