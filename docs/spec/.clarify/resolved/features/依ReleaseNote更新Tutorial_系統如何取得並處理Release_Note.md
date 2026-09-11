# 釐清問題

系統如何取得並處理 Release Note？

# 定位

Feature：依ReleaseNote更新Tutorial / Rule：從 Release Note 擷取 new features、changed features、renamed features、deprecated features、UI changes

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 一次處理一則已到達的 Release Note |
| B | 輪詢 changelog 表，一次處理上次檢查後的全部新列 |
| C | 輪詢 changelog 表，但每輪只處理一則 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

依ReleaseNote更新Tutorial 的 When 與批次邊界；決定是否另建 changelog 輪詢功能或維持「系統處理 Release Note」。

# 優先級

High
---
# 解決記錄

- **回答**：B - 輪詢 changelog 表，一次處理上次檢查後的全部新列
- **更新的規格檔**：docs/spec/features/依ReleaseNote更新Tutorial.feature
- **變更內容**：When 系統處理 Release Note 處理所有 processed_at 為空的 Release；已有 processed_at 者不再處理。
