# 釐清問題

規則 evidence 使用識別碼清單還是含類別的物件？

# 定位

- 追蹤 ID：D15
- [AUTHORING_RULE.evidence](../../../erm.dbml)，第 173 行。
- [提出教學規則，Rule 2「Authoring Rule 保留可追溯的 Feedback 證據」](../../../features/提出教學規則.feature)，第 20 行。

現況：ERD 的 ID list 與 R-007 YAML 的巢狀物件不同；這是來源形狀衝突，並非要求將原生 Map 改存字串。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只存 Feedback ID 清單，category 由被引用的回饋取得。 |
| B | 保存含 feedback_ids 與 category 的物件，以規則提出時的類別作為證據快照。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定規則 schema、propose_rule 輸入輸出，以及回饋分類變更後證據如何解讀。

前置釐清：D03、D13（見 overview.md）。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：A - 只存 Feedback ID 清單，category 由被引用的回饋取得。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/提出教學規則.feature
- **變更內容**：evidence 只存 Feedback ID 清單；category 由被引用的回饋取得，不另存提出時類別快照。
