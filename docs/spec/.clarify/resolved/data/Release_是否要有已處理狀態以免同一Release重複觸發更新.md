# 釐清問題

Release 是否要有已處理狀態，以免同一筆 Release 重複觸發更新？

# 定位

ERM：`Release` 只有 id、content；已有 `Release_Release是否要有created_at`（輪詢窗），不問處理狀態
Feature：`依ReleaseNote更新Tutorial` 的觸發與冪等

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不新增；只靠 created_at 輪詢，同一筆可被多次處理 |
| B | Release 新增 processed_at；有值視為已跑過 UPDATE pipeline |
| C | Release 新增 status，值含 pending 與 processed |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

輪詢 changelog／Release 的 Exactly-once、測試「同一 Release 再輪詢一次」。沒有狀態則 demo 重跑或輪詢重疊會重複產 Version。

# 優先級

Medium
---
# 解決記錄

- **回答**：B - Release 新增 processed_at；有值視為已跑過 UPDATE pipeline
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Release 新增 processed_at（可空）；Note 註明有值代表已跑過更新流程，不得重複觸發。
