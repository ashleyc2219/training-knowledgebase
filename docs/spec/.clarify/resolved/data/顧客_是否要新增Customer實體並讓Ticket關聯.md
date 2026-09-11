# 釐清問題

是否要新增 Customer 實體並讓 Ticket 關聯？

# 定位

ERM：無 Customer／顧客表；`Ticket` 只有 id、content、feature_id
來源：客服規格 Cognee 圖譜含「顧客」；Cognee tickets 模板典型抽出 customers
已有相關：`使用者_使用者是指員工顧客還是IT_Champion`（問的是角色，不是要不要落地顧客實體）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不新增 Customer；顧客只存在 Cognee 抽出結果，不入作用中 ERM |
| B | 新增 Customer，Ticket 加可空 customer_id |
| C | 新增 Customer，Ticket.customer_id 必填 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

票單歸戶、同一顧客看完教學又開票、圖譜「顧客—問題」邊。選 A 則客服規格「顧客」節點無法用 ERM 驗收。

# 優先級

High
---
# 解決記錄

- **回答**：Short - Ticket.customer_ref 字串
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：不新增 Customer 表；Ticket 新增 customer_ref（可空），Note 註明日後要歸戶再升級成 FK。
