# 釐清問題

提出 candidate 是否必須先滿足弱教學門檻？

# 定位

- 追蹤 ID：F26
- [定期檢視回饋，Rule 8「Feedback Review 是唯一提出 Authoring Rule 的 pipeline」](../../../features/定期檢視回饋.feature)，第 44 行。
- [提出教學規則，Rule 1「同類 Feedback 至少 5 筆才可提出 candidate 規則」](../../../features/提出教學規則.feature)，第 8 行。
- [設計 9.3 Periodic Feedback Review](../../../draft/training-kb-design-doc.md)，第 589 行。

現況：propose_rule 排在 REFINE 後面，但它的 5 筆門檻低於弱教學的 n>=10，是否能獨立運作未定義。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 必須；只有進入弱教學處理分支的證據才可提出 candidate。 |
| B | 不必；Feedback Review 另外掃描同類至少 5 筆的證據，即使平均分或總樣本未達改版門檻。 |
| C | 必須先成功完成 REFINE 與發布，再從本次處理證據提出 candidate。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定流程分支與失敗後是否還提出規則；需驗證高平均分但同類 5 筆、改寫失敗及發布失敗的情況。

前置釐清：F20、F21、F25（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：B - 不必；Feedback Review 另外掃描同類至少 5 筆的證據，即使平均分或總樣本未達改版門檻。
- **更新的規格檔**：docs/spec/features/定期檢視回饋.feature、docs/spec/features/提出教學規則.feature（本批未回寫）
- **變更內容**：提出 candidate 不必先滿足弱教學門檻；Feedback Review 可獨立掃描同類至少 5 筆的證據。
