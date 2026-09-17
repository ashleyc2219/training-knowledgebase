# 釐清問題

規則與版本的套用關係以哪份資料為權威？

# 定位

- 追蹤 ID：D17
- [AUTHORING_RULE.applied_to](../../../erm.dbml)，第 175 行。
- [TUTORIAL_VERSION.rules_applied](../../../erm.dbml)，第 53 行。
- [套用教學規則，Rule 6「套用規則的版本記錄於規則的 applied_to」](../../../features/套用教學規則.feature)，第 43 行。
- [套用教學規則，Rule 7「版本的 rules_applied 記錄本次套用的規則」](../../../features/套用教學規則.feature)，第 49 行。
- [查詢知識圖譜，Rule 5「可查詢某條 Authoring Rule 套用的版本」](../../../features/查詢知識圖譜.feature)，第 37 行。

現況：兩份清單與實體邊表示同一關係；來源沒有不一致時的判準，applied_to 長度又直接作為指標。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 以版本的 rules_applied 為權威，規則清單與 APPLIED_TO 邊可由它重建。 |
| B | 以規則的 APPLIED_TO 邊為權威，兩端清單皆為可重建投影。 |
| C | 兩端清單與 APPLIED_TO 邊是一個不可分割的寫入契約，任何部分失敗皆不承認本次套用。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定寫入失敗修復、重送去重與規則套用次數；必須能驗證一個 rule-version 配對不會被重複計數。

前置釐清：D03（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 以版本的 rules_applied 為權威，規則清單與 APPLIED_TO 邊可由它重建。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/套用教學規則.feature、docs/spec/features/查詢知識圖譜.feature
- **變更內容**：rules_applied 為套用關係權威；applied_to 與邊改為重建投影。
