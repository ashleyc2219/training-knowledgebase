# 釐清問題

進入 Periodic Refinement 所需的 Feedback「數量足夠」門檻是幾筆？

# 定位

Feature：定期優化Tutorial / Rule：當 Tutorial rating 小於 3.5 且 Feedback 數量足夠且存在 recurring complaints 時進入 Periodic Refinement

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 至少 3 筆 |
| B | 至少 5 筆 |
| C | 不設數字門檻，有 recurring complaints 即可 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

定期優化Tutorial 的數量前置條件；需補剛好達標與少一筆不進入 REFINE 的 Example。

# 優先級

High
---
# 解決記錄

- **回答**：A - 至少 3 筆
- **更新的規格檔**：docs/spec/features/定期優化Tutorial.feature
- **變更內容**：獨立 Rule：current_version 的 Feedback 數量必須 ≥ 3；只有 2 筆時 Then 動作為 KEEP。
