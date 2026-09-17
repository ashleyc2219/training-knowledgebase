# 釐清問題

recurring Feedback Category 的次數門檻是多少？

# 定位

- 追蹤 ID：F21
- [定期檢視回饋，Rule 4「弱教學必須具有 recurring Feedback Category」](../../../features/定期檢視回饋.feature)，第 24 行。
- [提出教學規則，Rule 1「同類 Feedback 至少 5 筆才可提出 candidate 規則」](../../../features/提出教學規則.feature)，第 8 行。

現況：weak_tutorials 的第三個條件沒有量化，不能直接推定等於 propose_rule 的 5 筆。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 同一類別至少 5 筆，與候選規則提出門檻一致。 |
| B | 同一類別至少 2 筆，即視為 recurring；規則提出仍維持至少 5 筆。 |
| C | 同一類別至少占該版本有效回饋的一半，另要求至少 2 筆。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定弱教學篩選、同分不同類的分布案例，以及 n 與平均分達標但沒有集中問題時的行為。

前置釐清：D13（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 同一類別至少 5 筆，與候選規則提出門檻一致。
- **更新的規格檔**：docs/spec/features/定期檢視回饋.feature（本批未回寫）
- **變更內容**：recurring Feedback Category 門檻為同一類別至少 5 筆。
