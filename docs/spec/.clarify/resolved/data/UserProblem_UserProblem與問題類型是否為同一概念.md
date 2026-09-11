# 釐清問題

UserProblem 與問題類型是否為同一概念？

# 定位

ERM：`Table UserProblem`（Cognee 實體；`topic` 如 Recurring Topic「Meeting Preparation」；與 Ticket / Feature 無 FK）
Feature：`分析SupportTickets` 產出 recurring topic / Knowledge Gap；`建立Tutorial` 以 Knowledge Gap topic 建 Tutorial
來源衝突：design-draft.md 的 UserProblem / Recurring Topic / Knowledge Gap 是票單聚集後的「使用者想知道什麼」；客服規格的問題類型是圖譜節點，用來匹配新票並決定攔截或轉真人

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 同義，canonical 為 UserProblem；問題類型、recurring topic、Knowledge Gap 都指向同一實體 |
| B | 同義，canonical 為問題類型；ERM 改名並補上與 Ticket / 教學的對應 |
| C | 不同概念：UserProblem 是聚集主題／知識缺口；問題類型是客服分類與攔截鍵，需分開或定義明確衍生關係 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 Cognee 主節點、`分析SupportTickets` 的 Then、Tutorial 對應的是 topic 還是問題類型，以及新票匹配有沒有獨立鍵。選 A 卻做客服攔截，會把「想學 Meeting Preparation」與「這類票該不該轉真人」壓成同一個值。

# 優先級

High
---
# 解決記錄

- **回答**：A - 同義，canonical 為 UserProblem；問題類型、recurring topic、Knowledge Gap 都指向同一實體
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：UserProblem Note 註明同義詞為 recurring topic、Knowledge Gap、問題類型，規格一律用 UserProblem；topic 對應 Bitext intent。
