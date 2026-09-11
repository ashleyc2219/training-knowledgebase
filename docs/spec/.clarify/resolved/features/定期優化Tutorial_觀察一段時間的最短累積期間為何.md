# 釐清問題

「必須觀察一段時間累積下來的 pattern」的最短累積期間為何？

# 定位

Feature：定期優化Tutorial / Rule：必須觀察一段時間累積下來的 pattern 才決定是否優化

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 至少 1 天 |
| B | 至少 7 天 |
| C | 不看日曆期間，只看 Feedback 筆數與 pattern |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

定期優化Tutorial 時間前置 Rule（#TODO）；Given 需寫經過天數或改為只驗筆數。

# 優先級

Medium
---
# 解決記錄

- **回答**：C - 不看日曆期間，只看 Feedback 筆數與 pattern
- **更新的規格檔**：docs/spec/features/定期優化Tutorial.feature
- **變更內容**：觀察期間 Rule 不寫日曆天數；以只有 2 筆 Feedback 的 KEEP Example 落地。
