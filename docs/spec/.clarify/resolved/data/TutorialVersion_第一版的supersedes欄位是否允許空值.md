# 釐清問題

第一版的 supersedes 欄位是否允許空值

# 定位

ERM：TutorialVersion.supersedes_tutorial_id、TutorialVersion.supersedes_tutorial_version

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | v1 必須為空，後續版本必填且指向上一版 |
| B | 兩欄皆可空，不強制版本鏈連續 |
| C | 改為單一可空的前一版複合外鍵，v1 為空 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

TutorialVersion 空值與 1:1 supersedes 關係；建立 Tutorial v1 與後續 UPDATE 或 REFINE 的版本鏈測試

# 優先級

Medium
---
# 解決記錄

- **回答**：Short - 單欄 supersedes_version，v1 空
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：TutorialVersion 只留 supersedes_version（v1 必為空，v2 起必填）；已移除 supersedes_tutorial_id。
