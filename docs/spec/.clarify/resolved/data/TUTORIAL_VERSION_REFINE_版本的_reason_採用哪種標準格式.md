# 釐清問題

REFINE 版本的 reason 採用哪種標準格式？

# 定位

- 追蹤 ID：D28
- [TUTORIAL_VERSION.reason](../../../erm.dbml)，第 52 行。
- [定期檢視回饋，Rule 7「REFINE 的下一版 reason 記錄回饋數與類別」](../../../features/定期檢視回饋.feature)，第 39 行。
- [建立教學版本，Rule 4「每次建立版本都記錄引起變更的 reason」](../../../features/建立教學版本.feature)，第 33 行。

現況：設計使用 feedback:<n> 則 <category>，ERD 出現 feedback:8；若介面與驗收解析字串，差異會直接影響追溯。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 使用設計格式 feedback:<n> 則 <category>，同時保存數量與類別。 |
| B | 使用 ERD 簡寫 feedback:<n>，類別只從回饋證據取得。 |
| C | reason 只保存穩定的回饋批次識別碼，數量與類別另外保存為結構化 Metadata。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

統一 REFINE 的輸出斷言與版本原因顯示；gap:<cluster_id> 與 release:<id> 已明確，無須重新決定。

前置釐清：D13（見 overview.md）。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：A - 使用設計格式 feedback:<n> 則 <category>，同時保存數量與類別。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/定期檢視回饋.feature、docs/spec/features/建立教學版本.feature
- **變更內容**：REFINE 的 reason 採 feedback:<n> 則 <category>；gap 與 release 格式不變。
