# 釐清問題

規格裡的「使用者」是指員工、顧客，還是 IT Champion？

# 定位

ERM：無 `User` 實體；`Ticket` / `Feedback` / `UserProblem` 都以「使用者」描述來源，未區分角色
Feature：`收集Feedback` 的 When 為「使用者提交 Feedback」；`分析SupportTickets` 的票單口吻是「我要怎麼用 Copilot…」
來源衝突：design-draft.md 同時出現 IT / Copilot Champion（操作知識庫）、員工（Pitch：「員工需要學什麼」）、以及未限定的「使用者」；客服規格的行動者是顧客與真人客服

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 「使用者」= 員工（學 Copilot 的內部學員）；Champion 是操作者，不叫使用者 |
| B | 「使用者」= 顧客（開客服票、點教學連結的人） |
| C | 「使用者」= IT Champion（維護／核准教學的人）；學員或顧客另命名 |
| D | 三角色並存，禁止再用「使用者」統稱；規格改寫為員工／顧客／Champion |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定誰開 Ticket、誰打 Rating、誰 Publish、誰被攔截或轉真人，以及 ERM 要不要建角色。不先定角色，後續 Feature 的 Given／When 主詞會繼續漂。

# 優先級

High
---
# 解決記錄

- **回答**：B - 「使用者」= 顧客（開客服票、點教學連結的人）
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：不新增 User 或 Champion 表；Ticket、Feedback 的欄位 Note 一律以「顧客」描述行動者。
