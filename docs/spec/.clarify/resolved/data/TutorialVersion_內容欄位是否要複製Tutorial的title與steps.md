# 釐清問題

TutorialVersion 內容欄位是否要複製 Tutorial 的 title 與 steps

# 定位

ERM：TutorialVersion 與 Tutorial.title、Tutorial.steps

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不複製，內容只存在 Tutorial，Version 只留版本鍵與 supersedes |
| B | TutorialVersion 複製 title、problem、prerequisites、steps、expected_outcome |
| C | 內容只存在 TutorialVersion，Tutorial 不再存 title 與 steps |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Tutorial、TutorialVersion；建立 Tutorial、定期優化 Tutorial、依 Release Note 更新 Tutorial 的版本快照與 diff 驗收

# 優先級

High
---
# 解決記錄

- **回答**：C - 內容只存在 TutorialVersion，Tutorial 不再存 title 與 steps
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：title／problem／prerequisites／steps／expected_outcome 只在 TutorialVersion；Tutorial Note 註明內容欄位不存在 Tutorial。
