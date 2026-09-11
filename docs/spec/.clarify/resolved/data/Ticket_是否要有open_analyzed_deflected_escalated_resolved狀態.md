# 釐清問題

Ticket 是否要有 open、analyzed、deflected、escalated、resolved 等處理狀態？

# 定位

ERM：`Ticket` 無狀態欄
已有相關：`Ticket_是否要記錄該票被教學攔截的deflection結果`（只問攔截／升級結果，不問整張票生命週期）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不新增狀態；用 created_at 與 deflection 結果推導 |
| B | Ticket 新增 status，值含 open、analyzed、resolved |
| C | Ticket 新增 status，值含 open、analyzed、deflected、escalated、resolved |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

分析 Support Tickets 的冪等、種子歷史票 vs 新票、轉真人與攔截的資料狀態。與 deflection 題分開：deflection 是一次結果，status 是整張票生命週期。

# 優先級

High
---
# 解決記錄

- **回答**：C - Ticket 新增 status，值含 open、analyzed、deflected、escalated、resolved
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Ticket 新增 status，Note 限定值為 open / analyzed / deflected / escalated / resolved。
- **審查修正（2026-09-11）**：Feature 改寫後沒有任何交互會設定 `analyzed`，故從 `Ticket.status` 移除；最終值為 open / deflected / escalated / resolved
