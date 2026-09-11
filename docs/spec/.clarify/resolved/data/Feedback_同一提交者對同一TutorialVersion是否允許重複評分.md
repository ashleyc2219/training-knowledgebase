# 釐清問題

同一提交者對同一 TutorialVersion 是否允許重複評分

# 定位

ERM：Feedback 對 TutorialVersion 的唯一性

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 允許重複列，每次提交都新增一筆 |
| B | 不允許，同一提交者同一版本只能有一筆 |
| C | 允許重複，但定期優化只取同一提交者最新一筆 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Feedback 唯一約束；收集 Feedback 的插入行為；定期優化 Tutorial 的 feedback_count 與平均評分測試

# 優先級

Medium
---
# 解決記錄

- **回答**：A - 允許重複列，每次提交都新增一筆
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Feedback.submitter_id Note 註明同一提交者可對同一版本重複評分，每次新增一筆；未建唯一約束。
