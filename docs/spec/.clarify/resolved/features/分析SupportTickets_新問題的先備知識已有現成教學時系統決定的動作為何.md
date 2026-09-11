# 釐清問題

新問題的先備知識已有現成教學時，系統決定的動作為何？

# 定位

Feature：分析SupportTickets / Rule：當存在新的 recurring question 且目前沒有 Tutorial 可以解決時觸發 CREATE
客服規格 HydraDB：「這個新問題的先備知識，有沒有現成教學可以連結」
已有釐清：已有對應 Tutorial 時分析是否仍觸發 CREATE（同一主題覆蓋，不是先備知識）
現有 CREATE Example：沒有 Tutorial 可以解決「Meeting Preparation」——未測「主題是新的，但 Prerequisites 已有篇」
**依賴**：產品主軸題；`自動回覆顧客_新票單要符合什麼條件才自動回覆教學連結否則轉真人`；`Tutorial_prerequisites是自由文字還是必須連到Feature或其他Tutorial`

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 仍對新問題 CREATE，並把現成教學列為 Prerequisites 連結 |
| B | 不 CREATE，改為自動回覆現成教學連結 |
| C | 不 CREATE 也不自動回覆，只記錄可連結關係 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

分析的 Then 可能是 CREATE、自動回覆或只寫關係。影響 `建立Tutorial` 的 Prerequisites 是自由文字還是必須指向既有 Tutorial。

# 優先級

High
---
# 解決記錄

- **回答**：A - 仍對新問題 CREATE，現成教學寫在 prerequisites 文字
- **更新的規格檔**：docs/spec/features/分析SupportTickets.feature
- **變更內容**：新增「先備知識已有其他 published Tutorial 時新問題仍 CREATE」Example
