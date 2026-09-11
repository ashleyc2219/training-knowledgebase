# 釐清問題

「將受影響的 Tutorials 標記為可能過期」是否為獨立於 UPDATE 的後置條件？

# 定位

Feature：依ReleaseNote更新Tutorial / Rule：將受影響的 Tutorials 標記為可能過期

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 是，先標記可能過期，UPDATE 是另一次操作 |
| B | 否，UPDATE 當下同時標記並改內容 |
| C | 標記後若決定 KEEP 則不改內容 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

依ReleaseNote更新Tutorial 標記 Rule（#TODO）是否需要獨立 Example；When 是「處理 Release Note」還是後續另一次更新。

# 優先級

High
---
# 解決記錄

- **回答**：B - 否，UPDATE 當下同時標記並改內容
- **更新的規格檔**：docs/spec/features/依ReleaseNote更新Tutorial.feature
- **變更內容**：刪除獨立「標記可能過期」Rule；同一次處理內先 true 再 false，Then 寫最終 is_possibly_outdated = false。
