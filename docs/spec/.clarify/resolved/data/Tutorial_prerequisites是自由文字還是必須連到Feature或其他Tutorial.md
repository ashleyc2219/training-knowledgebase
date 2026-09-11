# 釐清問題

Tutorial.prerequisites 是自由文字，還是必須連到 Feature 或其他 Tutorial？

# 定位

ERM：`Tutorial.prerequisites`（string，「Tutorial 內容欄位：Prerequisites」）
Feature：`建立Tutorial` 只驗 Prerequisites 欄位有沒有值，不驗它指向誰
來源：客服規格要求圖譜含「先備知識關係」，且 HydraDB 查詢「這個新問題的先備知識，有沒有現成教學可以連結」
已有相關：`建立Tutorial_缺少Title或Problem或Prerequisites或Steps或Expected_Outcome任一欄時行為為何`（只問缺欄）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只保留 prerequisites 字串，不建圖譜邊 |
| B | 保留字串，另建 Tutorial→Feature 或 Tutorial→Tutorial 先備知識關聯（可多個） |
| C | 刪字串，只保留先備知識關聯 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Release 只改 `feature_id` 時，步驟裡引用的其他功能找不到受影響教學；多跳查詢與「先備知識已有現成教學」的 Then 有沒有資料。選 A 則先備知識只能當非結構化本文。

# 優先級

High
---
# 解決記錄

- **回答**：A - 只保留 prerequisites 字串，不建圖譜邊
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：TutorialVersion.prerequisites Note 註明自由文字、不建先備知識關聯；未建 Tutorial→Feature 或 Tutorial→Tutorial 先備邊。
