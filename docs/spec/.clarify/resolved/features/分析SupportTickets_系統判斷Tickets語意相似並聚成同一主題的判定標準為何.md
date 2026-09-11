# 釐清問題

系統判斷 Tickets 語意相似並聚成同一主題的判定標準為何？

# 定位

Feature：分析SupportTickets / Rule：系統可將語意相似的 Tickets 聚集在一起

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | Given 已標同一 topic 的 Tickets，Then 必須輸出該 topic |
| B | Tickets 必須出現相同產品功能關鍵字才可聚成同一主題 |
| C | 只要分析結果輸出同一個 topic 名稱即視為語意相似 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

分析SupportTickets 聚集 Rule 的可驗證 Then；決定 Example 要用預先標註、關鍵字還是只驗輸出 topic。

# 優先級

High
---
# 解決記錄

- **回答**：A - Given 已標同一 topic 的 Tickets，Then 必須輸出該 topic
- **更新的規格檔**：docs/spec/features/分析SupportTickets.feature
- **變更內容**：Given Ticket 直接給 user_problem_id（Bitext intent），不驗演算法
