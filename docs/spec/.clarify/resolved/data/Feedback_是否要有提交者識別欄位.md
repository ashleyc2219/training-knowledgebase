# 釐清問題

Feedback 是否要有提交者識別欄位

# 定位

ERM：Feedback.submitter_id

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不新增，回饋匿名 |
| B | 新增 submitter_id 字串欄且必填 |
| C | 新增 submitter_id 字串欄但允許空值 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Feedback 屬性；收集 Feedback；同一使用者重複評分規則是否有欄位可驗證

# 優先級

High
---
# 解決記錄

- **回答**：C - 新增 submitter_id 字串欄但允許空值
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Feedback 新增 submitter_id（可空），Note 註明對應 Ticket.customer_ref。
