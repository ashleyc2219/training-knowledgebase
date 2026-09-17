# 釐清問題

教學與產品功能的識別範圍是否包含專案？

# 定位

- 追蹤 ID：D01
- [TUTORIAL.pk](../../../erm.dbml)，第 31 行。
- [FEATURE.pk](../../../erm.dbml)，第 91 行。
- [TICKET.project_id](../../../erm.dbml)，第 112 行。
- [提出教學規則，Rule 6「教學規則庫在平台層跨專案共享」](../../../features/提出教學規則.feature)，第 68 行。

現況：只有 Ticket 明列 project_id；Tutorial 與 Feature 的主鍵沒有專案區隔，但規則庫明定跨專案共享。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | MVP 固定單一專案，所有 Tutorial 與 Feature 識別碼在此範圍唯一；平台規則可使用明示的外部種子資料。 |
| B | MVP 支援多專案，Tutorial、Feature 與事件必須帶專案範圍；只有 Authoring Rule 可跨專案共享。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定識別碼、查詢隔離、alias 唯一性及跨專案同名功能的驗收資料。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - MVP 固定單一專案，所有 Tutorial 與 Feature 識別碼在此範圍唯一；平台規則使用明示的外部 seeded data 示範。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/提出教學規則.feature
- **變更內容**：將 Tutorial、Feature 與 Ticket 明定為單一專案範圍；跨專案規則只以明示的外部 seeded data 示範。
