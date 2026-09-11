# 釐清問題

TutorialVersion.supersedes 是否只能指向同一篇 Tutorial 的上一版？

# 定位

ERM：`TutorialVersion.supersedes_tutorial_id` + `supersedes_tutorial_version`（`Ref` 連到任意 TutorialVersion）
來源：design-draft RETIRE「Retire 或導向新的 Tutorial」；Feature 更名可能要換篇
已有相關：`TutorialVersion_第一版的supersedes欄位是否允許空值`（只問空值）；`依ReleaseNote更新Tutorial_Feature被Deprecated或Removed後相關Tutorial的最終動作為何`

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只能指向同一 tutorial_id 的上一版；跨篇導向不入庫 |
| B | 可以指向另一篇 Tutorial 的某版，作為 RETIRE 或更名後的導向 |
| C | 同一篇用 supersedes；跨篇導向另建欄位或關聯 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

RETIRE、Feature 更名後舊教學怎麼指到新篇、Version 鏈完整性與測試。選 B 則 PK／唯一性與「第一版 supersedes 可空」要一起看。

# 優先級

High
---
# 解決記錄

- **回答**：A - 只能指向同一 tutorial_id 的上一版；跨篇導向不入庫
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Ref TutorialVersion.(tutorial_id, supersedes_version) - TutorialVersion.(tutorial_id, tutorial_version)；Note 註明只能指向同一 tutorial_id。
