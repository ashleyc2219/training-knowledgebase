# 釐清問題

Feature 被 Deprecated 或 Removed 時，相關 Tutorial 是否必須先標記為 Obsolete？

# 定位

Feature：依ReleaseNote更新Tutorial / Rule：當 Feature 被 Deprecated 或 Removed 時找出相關 Tutorials 並標記為 Obsolete

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 必須先標記 Obsolete，再 RETIRE 或導向 |
| B | 直接做最終動作，不需 Obsolete 狀態 |
| C | 標記 Obsolete 即等同已 RETIRE |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

依ReleaseNote更新Tutorial 標記 Obsolete Rule（#TODO）；Then 是否出現 Obsolete 狀態，以及與 RETIRE 是否拆成兩步 Example。

# 優先級

High
---
# 解決記錄

- **回答**：C - 標記 Obsolete 即等同已 RETIRE
- **更新的規格檔**：docs/spec/features/依ReleaseNote更新Tutorial.feature
- **變更內容**：RETIRE Rule 同時寫 is_obsolete = true、status = retired、last_action = RETIRE，不拆成兩步。
