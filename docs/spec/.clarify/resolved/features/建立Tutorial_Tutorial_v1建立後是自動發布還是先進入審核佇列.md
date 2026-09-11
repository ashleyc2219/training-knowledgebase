# 釐清問題

Tutorial v1 建立後是自動發布還是先進入審核佇列？

# 定位

Feature：建立Tutorial / Rule：建立後發布 Tutorial

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 建立成功即自動發布為可用 Tutorial |
| B | 先進入審核佇列，審核通過才發布 |
| C | 建立為草稿，需另一次發布操作才發布 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

建立Tutorial 發布 Rule（#TODO）的後置條件；若選 B 或 C，需對齊審核教學草稿功能的狀態與 Then。

# 優先級

High
---
# 解決記錄

- **回答**：A - 建立成功即自動發布為可用 Tutorial
- **更新的規格檔**：docs/spec/features/建立Tutorial.feature
- **變更內容**：刪除獨立「建立後發布」Rule；建立成功 Then 為 status = published、current_version = v1、last_action = CREATE
