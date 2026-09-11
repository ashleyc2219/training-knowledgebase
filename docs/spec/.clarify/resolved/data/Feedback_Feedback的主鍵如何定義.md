# 釐清問題

Feedback 的主鍵如何定義

# 定位

ERM：Feedback 主鍵

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 新增 id 整數主鍵 |
| B | 以 tutorial_id、tutorial_version、timestamp 複合主鍵 |
| C | 以 tutorial_id、tutorial_version、submitter_id 複合主鍵 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Feedback 唯一性與列識別；收集 Feedback 存進 Database 的插入與查詢測試

# 優先級

High
---
# 解決記錄

- **回答**：A - 新增 id 整數主鍵
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Feedback 以 id int 為主鍵。
