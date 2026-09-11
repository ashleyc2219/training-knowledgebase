# 釐清問題

Tutorial 是否要新增 published 或審核佇列狀態

# 定位

ERM：Tutorial 生命週期狀態

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不新增狀態欄，建立或改版後視為已發布 |
| B | Tutorial 新增 status，值僅含 draft 與 published |
| C | Tutorial 新增 status，值含 draft、in_review、published |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Tutorial；建立 Tutorial 的「建立後發布」、定期優化與依 Release Note 更新的 Publish；架構規格「發布前先進入審核佇列」

# 優先級

High
---
# 解決記錄

- **回答**：★Short - draft/published/retired
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Tutorial 新增 status，值限 draft / published / retired；Note 寫明建立成功即 published，RETIRE 後為 retired。
