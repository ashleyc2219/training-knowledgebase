# 釐清問題

Release Note 出現 new feature 且尚無對應 Tutorial 時，系統決定的動作為何？

# 定位

Feature：依ReleaseNote更新Tutorial / Rule：Release Notes 也可用來判斷是否需要建立新的 Tutorial

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 動作為 CREATE |
| B | 僅標記 Knowledge Gap，不在此功能建立 |
| C | 必須同時有相關 Tickets 才 CREATE |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

依ReleaseNote更新Tutorial 的 CREATE Rule（#TODO）；Then 的 action 以及是否呼叫建立Tutorial。

# 優先級

High
---
# 解決記錄

- **回答**：Short - 不動作，只記錄 processed_at（Release Note 不觸發 CREATE）
- **更新的規格檔**：docs/spec/features/依ReleaseNote更新Tutorial.feature
- **變更內容**：刪除「Release Notes 也可用來判斷是否需要建立新的 Tutorial」Rule；new feature 且無 Tutorial 只寫 processed_at，動作空表。
