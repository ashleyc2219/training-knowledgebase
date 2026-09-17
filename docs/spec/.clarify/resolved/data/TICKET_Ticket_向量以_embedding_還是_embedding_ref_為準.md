# 釐清問題

Ticket 向量以 embedding 還是 embedding_ref 為準？

# 定位

- 追蹤 ID：D08
- [TICKET.embedding](../../erm.dbml)，第 116 行。
- [TICKET.embedding_ref](../../erm.dbml)，第 113 行。
- [分析工單，Rule 1「每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding」](../../features/分析工單.feature)，第 8 行。

現況：設計列 embedding_ref，ERD §6 說向量直接放在 item；目前並列不代表已同意雙寫。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 以 Ticket.embedding 保存 1024 維向量，移除 embedding_ref 的持久化要求。 |
| B | 只保存 embedding_ref，向量內容放在可解析該參照的外部儲存。 |
| C | 兩者都保留，以 embedding 為權威資料，embedding_ref 僅為衍生索引參照。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定分群讀取契約、向量缺失處理與一次計算後的重用驗收。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：A - 以 Ticket.embedding 保存 1024 維向量，移除 embedding_ref 的持久化要求。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/分析工單.feature
- **變更內容**：向量以 Ticket.embedding 為準；ERM 不再持久化 embedding_ref。
