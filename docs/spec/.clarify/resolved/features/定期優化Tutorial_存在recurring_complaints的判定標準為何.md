# 釐清問題

存在 recurring complaints 的判定標準為何？

# 定位

Feature：定期優化Tutorial / Rule：當 Tutorial rating 小於 3.5 且 Feedback 數量足夠且存在 recurring complaints 時進入 Periodic Refinement
此 Rule 三個合取條件；rating 門檻與 Feedback 數量已有釐清，第三合取未量化
現有 Example：四則不同抱怨即進入 REFINE，未定義「反覆」次數或是否須同一主題

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 至少 N 則 Feedback 指向同一弱點（N 用 Short 給數字）即算 recurring |
| B | 不計則數，只要出現相同弱點關鍵詞或同一 category 即算 |
| C | 規格不單獨驗 recurring complaints；有足夠低分即 REFINE |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

補這條 Rule 的邊界 Example（剛好達標／差一則）。影響 REFINE vs KEEP 的 Then，以及 Comments 要不要先分類才能進定期優化。

# 優先級

High
---
# 解決記錄

- **回答**：Short：同一 feedback_category ≥ 2 筆
- **更新的規格檔**：docs/spec/features/定期優化Tutorial.feature
- **變更內容**：獨立 Rule：同一 feedback_category 至少 2 筆才算 recurring complaints；3 筆但各不同 category 時 Then 動作為 KEEP。
