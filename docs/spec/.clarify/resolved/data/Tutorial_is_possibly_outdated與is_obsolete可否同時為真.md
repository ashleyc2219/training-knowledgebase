# 釐清問題

is_possibly_outdated 與 is_obsolete 可否同時為真

# 定位

ERM：Tutorial.is_possibly_outdated、Tutorial.is_obsolete

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 禁止同時為真，obsolete 時必須把 is_possibly_outdated 設為假 |
| B | 允許同時為真，兩旗標獨立 |
| C | obsolete 為真時系統不讀取 is_possibly_outdated |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Tutorial 跨屬性不變條件；依 Release Note 更新 Tutorial 的過期與 Obsolete 標記規則與測試

# 優先級

Medium
---
# 解決記錄

- **回答**：A - 禁止同時為真，obsolete 時必須把 is_possibly_outdated 設為假
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Tutorial Note 不變條件：is_obsolete = true 時 is_possibly_outdated 必為 false、status 必為 retired、last_action 必為 RETIRE。
