# 釐清問題

系統是否定期把 Release Note 寫入資料庫？

# 定位

Feature：輪詢ReleaseNote（2026-09-11 使用者補件）
已有釐清：`依ReleaseNote更新Tutorial_系統如何取得並處理Release_Note`（只定處理批次，未寫入庫）
已有釐清：`Release_Release_Note與模擬changelog表是否為同一產品變更訊號`（Release 表 = changelog 表，不另建模）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不另建入庫功能；Release 列由 demo 直接插入後再處理 |
| B | 定期輪詢 changelog 來源並寫入 Release，再由依ReleaseNote更新Tutorial 處理 |
| C | 入庫與 UPDATE / RETIRE 合成同一個 When |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

是否新增 `輪詢ReleaseNote.feature`；與 `依ReleaseNote更新Tutorial` 的入庫／處理分界。

# 優先級

High
---
# 解決記錄

- **回答**：B - 定期輪詢 changelog 來源並寫入 Release，再由依ReleaseNote更新Tutorial 處理
- **來源**：使用者 2026-09-11 補件「Release Note 應該是會定期更新到 db」
- **更新的規格檔**：docs/spec/features/輪詢ReleaseNote.feature、docs/spec/features/依ReleaseNote更新Tutorial.feature、docs/spec/erm.dbml、docs/客服自助教學生成器 — 系統架構規格.md
- **變更內容**：新建輪詢ReleaseNote.feature。When：`系統輪詢 Release Note`。只寫入 `created_at` > 上次檢查時間的新列，`processed_at` 為空；相同 content + created_at 不重複寫入。Demo 餵入與 hotdata 輪詢同一功能。不另建 changelog 表。
