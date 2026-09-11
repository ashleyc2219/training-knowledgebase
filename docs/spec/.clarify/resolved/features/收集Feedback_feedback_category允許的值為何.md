# 釐清問題

feedback_category 允許的值為何？

# 定位

Feature：收集Feedback / Rule：每篇 Tutorial 可收集 Feedback Category

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 僅限 design-draft 列出的六類 |
| B | 任意非空字串都可 |
| C | 六類加上「其他」 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

收集Feedback Category Rule（#TODO）的值域 Example；Then 的 feedback_category 欄位允許清單。

# 優先級

Medium
---
# 解決記錄

- **回答**：C - 六類加上「其他」
- **更新的規格檔**：docs/spec/features/收集Feedback.feature
- **變更內容**：補齊 feedback_category Rule：允許值為指示不清楚／缺少資訊／UI 與 Tutorial 不一致／Tutorial 太長／Tutorial 沒有解決問題／缺少自己的使用情境／其他；Example 覆蓋指示不清楚、其他。
