# 釐清問題

聚集出 recurring topic 後，何時才識別為 Knowledge Gap？

# 定位

Feature：分析SupportTickets
- Rule：系統可將語意相似的 Tickets 聚集在一起 → Then recurring topic
- Rule：系統可判斷是否存在新的 Knowledge Gap → Then Knowledge Gap
兩條 Rule 的 Example 用同一批 Meeting Tickets，Then 欄名不同、判定條件相同
已有釐清：已有對應 Tutorial 時是否仍觸發 CREATE（問的是動作，不是 Gap 識別）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | recurring topic 等同 Knowledge Gap，只是同一結果兩種名稱 |
| B | 聚成 topic 後，僅當目前沒有可解決的 Tutorial 才標成 Knowledge Gap |
| C | 聚成 topic 後，還須通過額外缺口判定（例如無解法步驟或無功能節點）才是 Gap |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 Rule2 是否需要獨立 Given／Then，以及 CREATE 前置要寫 `recurring topic` 還是 `Knowledge Gap`。選 A 應合併規則；選 B／C 必須補「有 topic 但不是 Gap」的 Example。

# 優先級

High
---
# 解決記錄

- **回答**：B - 聚成 topic 後，僅當目前沒有可解決的 Tutorial 才標成 Knowledge Gap
- **更新的規格檔**：docs/spec/features/分析SupportTickets.feature
- **變更內容**：獨立 Knowledge Gap Rule；無 published Tutorial 才列 Gap，已有則空表
