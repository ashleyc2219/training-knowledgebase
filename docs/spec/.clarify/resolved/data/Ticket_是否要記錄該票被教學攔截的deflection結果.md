# 釐清問題

是否要記錄該票被教學攔截的 deflection 結果

# 定位

ERM：Ticket 的 deflection 結果

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不入庫，deflection rate 只在查詢層計算 |
| B | Ticket 新增 deflection_result 字串欄，記錄攔截或升級真人 |
| C | 另建 DeflectionEvent 實體，指向 Ticket 與 Tutorial |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Ticket 或新實體；分析 Support Tickets 之後是否自動回覆教學連結；架構規格 deflection rate 曲線的資料來源與測試

# 優先級

High
---
# 解決記錄

- **回答**：Short - status＋deflected_tutorial 參照
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Ticket.status 含 deflected，並新增 deflected_tutorial_id、deflected_tutorial_version；Ref 指向 TutorialVersion。未建 DeflectionEvent。
