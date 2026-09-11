# 釐清問題

Release 與 Feature 的多對多是否要獨立關聯表並記錄變更類型

# 定位

ERM：Release.changes Feature

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 維持現有無屬性 N:M，變更類型只存在 content 字串 |
| B | 新增關聯表，並加 change_type 字串欄 |
| C | 不建關聯列，只保留 Release.content |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Release、Feature 與可能的關聯表；依 Release Note 更新 Tutorial 擷取 new、changed、renamed、deprecated、UI changes 的入庫方式

# 優先級

Medium
---
# 解決記錄

- **回答**：B - 新增關聯表，並加 change_type 字串欄
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：新增 Table ReleaseFeatureChange（change_type／from_name／to_name）及 Ref 至 Release、Feature。
