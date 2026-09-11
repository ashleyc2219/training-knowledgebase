# 釐清問題

本系統的產品主軸是 Copilot IT Enablement 知識庫、客服 deflection 教學生成器，還是同一系統的不同 persona？

# 定位

ERM：`Project TrainingKnowledgeBase`（自我優化的 Copilot 教學知識庫）
Feature：五份 `docs/spec/features/*.feature` 皆依 Tutorial 生命週期（CREATE / UPDATE / REFINE / KEEP / RETIRE）建模，無票單攔截或轉真人規則
來源衝突：design-draft.md（IT / Copilot Enablement、員工培訓、單一 Agent 知識庫）vs 客服自助教學生成器 — 系統架構規格.md（顧客票單 deflection、自動攔截重複問題、轉真人）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只做 Copilot IT Enablement 知識庫；design-draft 與現有 ERM / Features 為準，客服規格不進入作用中規格 |
| B | 只做客服 deflection 教學生成器；客服規格為準，ERM / Features 依票單攔截與轉真人改寫 |
| C | 同一系統、不同 persona：Champion 維護 Tutorial，員工或顧客被教學；兩條敘事共用生命週期，但互動入口分開 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定核心行動者、Ticket / Tutorial / Feedback 語意、demo 曲線，以及後續所有 clarify 是否仍以現有 ERM 為準。選 B 會讓現有五份 Feature 與 `Ticket` / `Feedback` / `Tutorial` 生命週期幾乎整批失效。選 A 或 C 才可能沿用現有 Feature 名稱。

# 優先級

High
---
# 解決記錄

- **回答**：★B - 只做客服 deflection 教學生成器；客服規格為準，ERM / Features 依票單攔截與轉真人改寫
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Project 改名為 SupportTutorialGenerator；Project Note 改寫為客服自助教學生成器，並描述 Ticket → UserProblem → Tutorial → deflection → Feedback／再開票的生命週期。
