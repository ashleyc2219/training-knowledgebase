# 釐清問題

回饋訊號是評分留言，還是看完教學後是否又開新票？

# 定位

ERM：`Table Feedback`（`rating` 1–5、`feedback_category`、`comment`；用途是決定哪些 Tutorial 該 REFINE）
Feature：`收集Feedback`、`定期優化Tutorial` 以 Average Rating 與 comment pattern 驅動 REFINE / KEEP
來源衝突：design-draft.md 的 User Feedback / Ratings 是結構化評分與留言；客服規格以「顧客看完教學後是否又開新票」當教學是否有效的訊號

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只採用 rating / category / comment；不把再開新票當成 Feedback |
| B | 只採用「看完教學後是否又開新票」；ERM `Feedback.rating` / `comment` 不進作用中規格 |
| C | 兩者都要，但是不同訊號：顯性問卷進 `Feedback`，隱性再開票另建 outcome，禁止把再開票寫進 `rating` |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 `Feedback` 是否仍是 Tutorial 品質實體、`定期優化Tutorial` 的進入條件，以及 demo 是評分曲線還是再開票／deflection。選 B 會讓現有 Feedback Feature 與 `rating < 3.5` 規則失去標的。

# 優先級

High
---
# 解決記錄

- **回答**：★C - 兩者都要，但是不同訊號：顯性問卷進 `Feedback`，隱性再開票另建 outcome，禁止把再開票寫進 `rating`
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：顯性回饋在 Feedback（rating／feedback_category／comment）；隱性再開票記在 Ticket.reopened_from_ticket_id。Feedback Note 註明再開票不寫進本表。
