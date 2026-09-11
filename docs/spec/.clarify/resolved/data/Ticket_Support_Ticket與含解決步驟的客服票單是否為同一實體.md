# 釐清問題

Support Ticket 與含解決步驟的客服票單是否為同一實體？

# 定位

ERM：`Table Ticket`（`content` 為問題本文，例如「我要怎麼用 Copilot 產生 Meeting Brief？」；`asks_about` Feature；無解決步驟欄）
Feature：`分析SupportTickets` 只聚集問題本文、找 recurring topic / Knowledge Gap
來源衝突：design-draft.md 的 Support Ticket 是「使用者想學什麼」的問題訊號；客服規格的歷史已解決票單含「顧客問題＋客服解決步驟」，並作為 Cognee 建圖輸入

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 同義且只存問題本文；解決步驟不進 Ticket，現有 ERM `Ticket.content` 維持 |
| B | 同義且必須含問題＋解決步驟；`Ticket` 需擴欄或拆子實體，分析規則改為「從已解決票單學解法」 |
| C | 不同實體：內部 Support Ticket（求學／求教）與顧客客服票單（求援／求解）分開，禁止共用同一 `Ticket` |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 `Ticket` 屬性、Cognee 輸入、`分析SupportTickets` 是找知識缺口還是重放解法，以及 Rote 有沒有「已驗證解法」可捕捉。選 B 或 C 都會改 ERM，不只改文案。

# 優先級

High
---
# 解決記錄

- **回答**：B - 同義且必須含問題＋解決步驟；`Ticket` 需擴欄或拆子實體，分析規則改為「從已解決票單學解法」
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Ticket 同時保存 content（顧客問題）與 resolution_steps（客服解決步驟）；Table Note 寫明同一實體含問題與解法。
