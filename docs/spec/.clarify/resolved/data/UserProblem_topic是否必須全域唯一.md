# 釐清問題

UserProblem.topic 是否必須全域唯一？

# 定位

ERM：`UserProblem.topic`（string，範例 Recurring Topic「Meeting Preparation」；無 unique）
Feature：`分析SupportTickets` 的聚集與 recurring topic 門檻

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 必須全域唯一；同一 topic 重跑分析要重用既有列 |
| B | 不唯一；每次聚集都可新增一列 |
| C | 不在 ERM 強制唯一；以正規化後的 topic key 做邏輯去重 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

分析結果是 update 還是 insert、Tutorial／Ticket 掛到哪一列、測試「同一主題第二次出現」。選 B 會讓 Knowledge Gap 計數膨脹。

# 優先級

Medium
---
# 解決記錄

- **回答**：A - 必須全域唯一；同一 topic 重跑分析要重用既有列
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：UserProblem.topic Note 註明全域唯一，同一 topic 重跑分析必須重用既有列。
