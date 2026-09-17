# 釐清問題

Knowledge Gap 無法對應既有 Feature 時如何處理？

# 定位

- 追蹤 ID：F13
- [FEATURE.first_seen](../../../erm.dbml)，第 94 行。
- [分析工單，Rule 5「Knowledge Gap 的命名結果包含對應 Feature」](../../../features/分析工單.feature)，第 28 行。
- [分析工單，Rule 8「已識別且尚無現成教學的 Knowledge Gap 建立新的 Tutorial」](../../../features/分析工單.feature)，第 43 行。

現況：name_gap 要回傳 Feature，但 Feature 的建立者與無法命名時的分支未定義。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 保留待釐清的 gap，取得有效 Feature 對應前不建立 Tutorial。 |
| B | 允許 Ticket Analysis 建立新的 Feature，再建立引用它的 Tutorial。 |
| C | 本次分析以失敗結束，由來源或操作人員修正資料後重新處理。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 Feature 初始建立責任、無引用教學是否可出現，以及低信心或不存在功能的負向案例。

前置釐清：D04、D05（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 保留待釐清的 gap，取得有效 Feature 對應前不建立 Tutorial。
- **更新的規格檔**：docs/spec/features/分析工單.feature（本批未回寫）
- **變更內容**：對不到既有 Feature 時保留 gap，不建立 Tutorial。
