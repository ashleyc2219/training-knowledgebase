# 釐清問題

TutorialVersion 是否要有獨立於 Tutorial 的 draft 或 published 狀態？

# 定位

ERM：`TutorialVersion`（只有 tutorial_id、tutorial_version、supersedes_*，無狀態欄）
已有相關：`Tutorial_是否要新增published或審核佇列狀態`（Tutorial 列級）；`Tutorial_rating小於3點5是用最新版全歷史還是當前published版計算`（已假設存在「當前 published 版」）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 不新增；Tutorial 一顆 status 代表整篇，最新 Version 即當前版 |
| B | TutorialVersion 新增 status，值含 draft 與 published；允許 v1 published 且 v2 draft 並存 |
| C | 只在最新 Version 推導狀態，不落地；published 仍只存在 Tutorial |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

審核佇列、rating「當前 published 版」、Release 更新時舊版是否仍可被引用。選 A 無法同時「對外仍是 v1、對內在審 v2」。

# 優先級

High
---
# 解決記錄

- **回答**：A - 不新增；Tutorial 一顆 status 代表整篇，最新 Version 即當前版
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：不新增欄位；TutorialVersion 無 status，以 Tutorial.status 與 current_version 代表當前版。
