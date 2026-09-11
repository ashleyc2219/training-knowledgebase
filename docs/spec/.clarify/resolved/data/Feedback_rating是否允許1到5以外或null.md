# 釐清問題

Feedback.rating 是否允許 1 到 5 以外或 null

# 定位

ERM：Feedback.rating

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 必填且只允許 1 到 5 的整數 |
| B | 允許 null，有值時只允許 1 到 5 |
| C | 允許 null，也允許 1 到 5 以外的整數 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Feedback.rating 邊界；收集 Feedback 的 1 到 5 Rating 規則；定期優化 Tutorial 的平均評分計算

# 優先級

High
---
# 解決記錄

- **回答**：A - 必填且只允許 1 到 5 的整數
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Feedback.rating Note 註明 1–5 整數必填；小於 1 或大於 5 則提交失敗。
