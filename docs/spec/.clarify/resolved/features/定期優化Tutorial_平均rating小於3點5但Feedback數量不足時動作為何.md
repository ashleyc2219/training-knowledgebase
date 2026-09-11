# 釐清問題

平均 rating 小於 3.5 但 Feedback 數量不足時，系統決定的動作為何？

# 定位

Feature：定期優化Tutorial / Rule：當 Tutorial rating 小於 3.5 且 Feedback 數量足夠且存在 recurring complaints 時進入 Periodic Refinement

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 動作為 KEEP |
| B | Then 操作失敗 |
| C | 標記待觀察，不改 tutorial_version |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

定期優化Tutorial 組合邊界 Example；釐清低分但樣本不足時的 Then 動作。

# 優先級

Medium
---
# 解決記錄

- **回答**：A - 動作為 KEEP
- **更新的規格檔**：docs/spec/features/定期優化Tutorial.feature
- **變更內容**：數量門檻 Rule 以平均 < 3.5 但只有 2 筆的 Example 驗證 Then 動作為 KEEP。
