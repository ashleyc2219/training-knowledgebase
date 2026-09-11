# 釐清問題

Tutorial 平均 rating 剛好等於 3.5 且其他條件成立時，系統決定的動作為何？

# 定位

Feature：定期優化Tutorial / Rule：當 Tutorial rating 小於 3.5 且 Feedback 數量足夠且存在 recurring complaints 時進入 Periodic Refinement

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不進入 REFINE，動作為 KEEP |
| B | 進入 REFINE |
| C | 標記待觀察，本輪不改 tutorial_version |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

定期優化Tutorial 的 3.5 含端點 Example；Rule 若維持「小於 3.5」則 Then 動作應為 KEEP。

# 優先級

High
---
# 解決記錄

- **回答**：A - 不進入 REFINE，動作為 KEEP
- **更新的規格檔**：docs/spec/features/定期優化Tutorial.feature
- **變更內容**：平均 rating Rule 新增剛好 3.5（4 筆、同一 category）的 Example，Then 動作為 KEEP。
