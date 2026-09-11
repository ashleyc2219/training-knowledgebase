# 釐清問題

Tickets 無法聚成同一主題時，分析的結果為何？

# 定位

Feature：分析SupportTickets / Rule：系統可將語意相似的 Tickets 聚集在一起
現有 Example 只有成功聚成「Meeting Preparation」
已有釐清：沒有任何 Ticket 時分析結果；語意相似判定標準；至少幾張才算 recurring topic
未問：有票、但兩兩都不相似或未達成團張數

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | Then 為空的 recurring topic，且不觸發 CREATE |
| B | 每張未成團 Ticket 各自成為獨立 topic，但不標 Knowledge Gap |
| C | 視為分析失敗，操作失敗 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Rule1 的失敗／負向 Example。與「至少幾張才算 recurring topic」銜接：張數門檻之下的 Then 寫空表、失敗還是單張 topic。不重問空庫。

# 優先級

Medium
---
# 解決記錄

- **回答**：A - Then 為空的 recurring topic，且不觸發 CREATE
- **更新的規格檔**：docs/spec/features/分析SupportTickets.feature
- **變更內容**：新增三張各不同 topic 的空 recurring topic 與空動作表 Example
