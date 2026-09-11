# 釐清問題

Feature 是否要有 deprecated 或 removed 狀態

# 定位

ERM：Feature 生命週期狀態

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不新增狀態欄，只從 Release content 推導 |
| B | Feature 新增 status，值含 active、deprecated、removed |
| C | Feature 新增 is_deprecated 與 is_removed 兩個布林欄 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Feature；依 Release Note 更新 Tutorial 的 RETIRE 與 Obsolete 標記；Tutorial 找相關功能是否仍有效

# 優先級

Medium
---
# 解決記錄

- **回答**：B - Feature 新增 status，值含 active、deprecated、removed
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Feature 新增 status，Note 限定值為 active / deprecated / removed。
