# 釐清問題

derived_from 可以記錄幾個來源版本？

# 定位

- 追蹤 ID：D18
- [AUTHORING_RULE.derived_from](../../../erm.dbml)，第 182 行。
- [AUTHORING_RULE.evidence](../../../erm.dbml)，第 179 行。
- [提出教學規則，Rule 4「Authoring Rule 記錄 derived_from 來源版本」](../../../features/提出教學規則.feature)，第 49 行。
- [提出教學規則，Rule 6「教學規則庫在平台層跨專案共享」](../../../features/提出教學規則.feature)，第 69 行。

現況：derived_from 是單一版本，跨專案累積的敘述卻可能要求一條規則彙整多版本證據。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 恰好一個；單條規則的證據只能來自同一版本，跨專案共享的是完成後的規則。 |
| B | 一到多個；跨版本歸納時保存全部來源版本。 |
| C | 一個主要來源版本；其他來源透過 evidence 追溯，主要來源有明確的選定規則。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定規則來源關係、跨版本聚合上限與主要來源選擇；若只允許一個來源，後續聚合範圍必須受此限制。

前置釐清：D03（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 恰好一個；單條規則的證據只能來自同一版本，跨專案共享的是完成後的規則。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/提出教學規則.feature
- **變更內容**：derived_from 恰好一個裸 version_id；證據只能來自該版本。
