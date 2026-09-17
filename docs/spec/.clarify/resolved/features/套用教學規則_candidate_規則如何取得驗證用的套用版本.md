# 釐清問題

candidate 規則如何取得驗證用的套用版本？

# 定位

- 追蹤 ID：F27
- [套用教學規則，Rule 2「一般寫作路徑只取得 status 為 active 的規則」](../../../features/套用教學規則.feature)，第 12 行。
- [套用教學規則，Rule 5「既有教學衍生的適用規則可用於不同主題新教學的第一版」](../../../features/套用教學規則.feature)，第 37 行。
- [驗證教學規則，Rule 2「candidate 在套用版本成效優於未套用版本後變為 active」](../../../features/驗證教學規則.feature)，第 13 行。
- [設計 12.1 五輪循環](../../../draft/training-kb-design-doc.md)，第 704 行。

現況：R-007 在 A v2 與 B v1 已套用，卻到第 4 輪才變 active；目前規則使 candidate 無法取得 applied_to 證據。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 增加明確受控的 candidate 試用路徑，只對選定版本套用；一般寫作仍只用 active。 |
| B | MVP 從明示的種子試用版本匯入 candidate 成效，正式寫作不自動試用 candidate。 |
| C | 一般寫作也納入 candidate，待 Analytics 決定啟用或退役，並修改目前 active-only 規則。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定學習閉環、規則選取介面與試用版本標記；不可把尚未驗證的規則默認為 active。

前置釐清：D17、F26（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：B - MVP 從明示的種子試用版本匯入 candidate 成效，正式寫作不自動試用 candidate。
- **更新的規格檔**：docs/spec/features/套用教學規則.feature、docs/spec/features/驗證教學規則.feature（本批未回寫）
- **變更內容**：MVP 以明示種子試用版本匯入 candidate 成效；一般寫作仍只用 active，不自動試用 candidate。
