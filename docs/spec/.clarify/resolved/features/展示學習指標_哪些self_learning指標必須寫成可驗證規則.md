# 釐清問題

哪些 self-learning 指標必須寫成可驗證 Feature 規則，而不只是 demo 解說？

# 定位

Feature：展示學習指標 / Rule：缺失功能
design-draft §14：Average Rating、Negative Feedback、Repeated Questions、Outdated Steps（v1→v2）
客服規格／黑客松：deflection rate、重放解決率、圖譜覆蓋範圍
`定期優化Tutorial` 已有 v1／v2 評分表 Example；五檔都沒有 deflection／重放率 Then
資料題已問 Ticket 是否記錄 deflection 結果；未問規格要驗哪一組指標
**依賴**：產品主軸題

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只驗 design-draft 的 Tutorial 評分與抱怨改善表 |
| B | 只驗 deflection rate、重放解決率、圖譜覆蓋（含分子分母） |
| C | 兩組都要，且各自有可驗證 Then |
| D | 指標只做 Demo 畫面，不進入作用中 Feature |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

是否新增 `展示學習指標` Feature，以及自動回覆／重放／定期優化的 Then 要不要產出曲線數字。選 D 則不建 Feature 檔。

# 優先級

High
---
# 解決記錄

- **回答**：B - 只驗 deflection rate、重放解決率、圖譜覆蓋（含分子分母）
- **更新的規格檔**：docs/spec/features/展示學習指標.feature
- **變更內容**：新建展示學習指標.feature；三條 Rule 各一個含分子分母的 Example。
