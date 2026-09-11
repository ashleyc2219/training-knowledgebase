# 釐清問題

rating 小於 3.5 是用最新版、全歷史還是當前 published 版計算

# 定位

ERM：Tutorial 與 Feedback.rating 的聚合範圍

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只算該 Tutorial 最新 TutorialVersion 的 Feedback |
| B | 算該 Tutorial 全歷史所有版本的 Feedback |
| C | 只算當前 published 版的 Feedback |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Tutorial、TutorialVersion、Feedback；定期優化 Tutorial 的「rating 小於 3.5」前置條件與 Hotdata 聚合測試

# 優先級

High
---
# 解決記錄

- **回答**：C - 只算當前 published 版的 Feedback
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Tutorial.current_version Note 與 Feedback Note 註明平均 rating／feedback_count 只算 current_version 那一版。
