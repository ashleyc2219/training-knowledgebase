# 釐清問題

一張 Ticket 可以對應幾個 Feature？

# 定位

- 追蹤 ID：D04
- [TICKET.feature_ids](../../../erm.dbml)，第 115 行。
- [FEATURE.name](../../../erm.dbml)，第 92 行。
- [分析工單，Rule 5「Knowledge Gap 的命名結果包含對應 Feature」](../../../features/分析工單.feature)，第 28 行。

現況：ERD 的 TICKET N:0..1 FEATURE 與正規化 schema 的 feature_ids 清單未取得一致解釋。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 零或一個；feature_ids 的長度限制為 0..1，維持 ERD 的基數。 |
| B | 零到多個；feature_ids 與 asks_about 邊均允許多個不同 Feature。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 asks_about 關係、Knowledge Gap 對應方式與多功能工單的 CREATE 或 KEEP 判定。

已解決前置：D01（MVP 固定單一專案）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 零或一個；feature_ids 的長度限制為 0..1，維持 ERD 的基數。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/分析工單.feature
- **變更內容**：TICKET N:0..1 FEATURE；feature_ids 長度 0 或 1，不另增 scalar feature_id。
