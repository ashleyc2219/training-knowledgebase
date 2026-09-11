# 釐清問題

Feature 被 Deprecated 或 Removed 後，相關 Tutorial 的最終動作為何？

# 定位

Feature：依ReleaseNote更新Tutorial / Rule：標記為 Obsolete 後 Retire 或導向新的 Tutorial

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 一律 RETIRE |
| B | 一律導向新的 Tutorial |
| C | 有替代功能則導向，否則 RETIRE |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

依ReleaseNote更新Tutorial 的 Obsolete／RETIRE Rule（#TODO）；Then 的 action 與是否新增導向目標欄位。

# 優先級

High
---
# 解決記錄

- **回答**：A - 一律 RETIRE
- **更新的規格檔**：docs/spec/features/依ReleaseNote更新Tutorial.feature
- **變更內容**：deprecated / removed 一律 RETIRE；不做導向。
