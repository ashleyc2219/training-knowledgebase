# 釐清問題

CREATE UPDATE REFINE KEEP RETIRE 如何對應 is_possibly_outdated 與 is_obsolete

# 定位

ERM：Tutorial.is_possibly_outdated、Tutorial.is_obsolete

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不另存動作欄，只靠兩個布林旗標推導狀態 |
| B | 新增 lifecycle_action 字串欄存最後一次動作，兩個布林旗標仍保留 |
| C | 以單一 status 字串欄取代兩個布林旗標 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Tutorial 欄位與跨屬性不變條件；建立 Tutorial、依 Release Note 更新 Tutorial、定期優化 Tutorial 的動作與旗標驗收

# 優先級

High
---
# 解決記錄

- **回答**：B - 新增 lifecycle_action 字串欄存最後一次動作，兩個布林旗標仍保留
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Tutorial 新增 last_action（值限 CREATE / UPDATE / REFINE / KEEP / RETIRE），並保留 is_possibly_outdated 與 is_obsolete。
