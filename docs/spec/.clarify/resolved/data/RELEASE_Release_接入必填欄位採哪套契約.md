# 釐清問題

Release 接入必填欄位採哪套契約？

# 定位

- 追蹤 ID：D10
- [RELEASE.feature](../../../erm.dbml)，第 133 行。
- [RELEASE.kind](../../../erm.dbml)，第 134 行。
- [RELEASE.old_name](../../../erm.dbml)，第 135 行。
- [RELEASE.new_name](../../../erm.dbml)，第 136 行。
- [RELEASE.evidence](../../../erm.dbml)，第 137 行。
- [接入來源事件，Rule 18「正規化物件必須具有 schema 的必填欄位」](../../../features/接入來源事件.feature)，第 102 行。
- [依改版更新教學，Rule 1「從 PR diff 或 changelog 抽出 feature、kind、old_name 與 new_name」](../../../features/依改版更新教學.feature)，第 7 行。

現況：Release.feature 在 ERM 必填，但 pipeline 又負責抽出 feature；各 kind 的 old_name、new_name 空值規則未定義。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 接入即完成解析：id、source、feature、kind、evidence、ts 必填；renamed 另要求 old_name 與 new_name，其他 kind 允許名稱欄位為空。 |
| B | 接入即完成解析：id、source、feature、kind、evidence、ts 必填；renamed 要新舊名稱，removed 要 old_name，changed 的名稱欄位可空。 |
| C | 接入只要求 id、source、evidence、ts；feature、kind 與名稱欄位由 extract_change 補完後再驗證，需區分原始事件與正規化 Release。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定接入與 extract_change 的邊界、各 kind 的 schema，以及 removed 沒有 new_name 時的處理。

前置釐清：D02（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 接入即完成解析：id、source、feature、kind、evidence、ts 必填；renamed 另要求 old_name 與 new_name，其他 kind 允許名稱欄位為空。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/接入來源事件.feature
- **變更內容**：Release 接入時即帶功能與種類；僅 renamed 必填新舊名稱。
