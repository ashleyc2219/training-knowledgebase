# 釐清問題

產品功能更名後，Feature 的 name 要改成新名稱，還是保留舊名稱？

# 定位

ERM：`Feature.name`（範例同時出現 "Meeting Summary" 與 "Prepare"）
Feature：依ReleaseNote更新Tutorial / Rule：從 Release Note 擷取 renamed features
關係：`Ticket.asks_about`、`Tutorial.explains`、`Release.changes` 都指向 `Feature`

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 更名後把 `Feature.name` 改成新名稱；舊名稱只留在 Release Note 本文 |
| B | 保留舊名稱為 `Feature.name`；新名稱只寫進 Tutorial 步驟文字 |
| C | 同一 Feature 同時保存舊名稱與新名稱（需新增欄位）；查詢任一名稱都指向同一筆 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 rename 後 Ticket / Tutorial / Release 還能否對到同一 Feature，以及 `依ReleaseNote更新Tutorial` 的擷取 Example 要寫 `from_name` / `to_name` 還是只改 `Feature.name`。

# 優先級

High
---
# 解決記錄

- **回答**：A - 更名後把 `Feature.name` 改成新名稱；舊名稱只留在 Release Note 本文
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Feature.name Note 註明 Release Note 更名後直接改成新名稱，舊名稱只留在 Release.content。
