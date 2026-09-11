# 釐清問題

Tutorial 的 feature_id 是否必填？

# 定位

ERM：`Tutorial.feature_id`（explains → Feature；`Ref: Tutorial.feature_id > Feature.id`）
Feature：`建立Tutorial` 現有 Then 只有 path / tutorial_version，沒有 Feature
來源：客服規格「每一篇教學都要能連回它所引用的具體產品功能節點」；design-draft `Tutorial -> explains -> Feature`
已有相關：`Ticket_Ticket的feature_id是否必填`（只問 Ticket）；`Tutorial_Tutorial是否要關聯UserProblem或問題類型`

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 必填，沒有 Feature 就不能建立 Tutorial |
| B | 可空，允許先依 UserProblem／Knowledge Gap 建教學，之後再補 Feature |
| C | 草稿可先建，發布前必須補 Feature，否則不得 published |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Tutorial 建立前置、Release 影響範圍查詢、Cognee／HydraDB「教學必須連回 Feature」能否驗收。選 B 時「依 Release Note 找受影響教學」若只靠 Feature 邊會漏篇。

# 優先級

High
---
# 解決記錄

- **回答**：A - 必填，沒有 Feature 就不能建立 Tutorial
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Tutorial.feature_id Note 註明必填；沒有 Feature 不得建立 Tutorial。Ref Tutorial.feature_id > Feature.id。
