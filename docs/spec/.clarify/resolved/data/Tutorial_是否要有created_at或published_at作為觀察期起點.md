# 釐清問題

Tutorial 是否要有 created_at 或 published_at，作為「觀察一段時間」的起點？

# 定位

ERM：`Tutorial` 無任何時間欄；`Feedback.timestamp` 是 string
Feature：`定期優化Tutorial_觀察一段時間的最短累積期間為何`（問期間長度，不問錨點欄位）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不新增；觀察期用該篇最早一筆 Feedback.timestamp |
| B | Tutorial 新增 created_at，觀察期從建立起算 |
| C | Tutorial 新增 published_at，觀察期從發布起算 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

KEEP／REFINE 的時間前置、Example 的 Given 時鐘、與 Tutorial published 狀態的配合。沒有錨點則「觀察一段時間」無法寫成可驗證規則。

# 優先級

Medium
---
# 解決記錄

- **回答**：A - 不新增；觀察期用該篇最早一筆 Feedback.timestamp
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：不新增欄位；Tutorial 無 created_at／published_at。觀察期改由 Feedback 筆數判定（見功能題），不依時間欄。
