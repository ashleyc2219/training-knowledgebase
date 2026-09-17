# 釐清問題

同題重開票的教學與 cluster 對應以何者為準？

# 定位

- 追蹤 ID：D29
- [TUTORIAL.topic](../../../erm.dbml)，第 34 行。
- [TICKET.cluster_id](../../../erm.dbml)，第 114 行。
- [TUTORIAL_VERSION.reason](../../../erm.dbml)，第 52 行。
- [檢視學習指標，Rule 3「同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例」](../../../features/檢視學習指標.feature)，第 18 行。

現況：Ticket 有 cluster_id，Tutorial 只有 topic 與 feature_ids；首版 reason 可能保留 gap ID，但更新後 reason 會改變，沒有指定指標使用的穩定對應。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 以該教學首版的 gap:<cluster_id> 作為固定對應，後續分群需保留此 cluster 的可追溯身分。 |
| B | 另保存 Tutorial 與 cluster 的明確關係，改版與分群調整時依核定規則維護。 |
| C | MVP 只由 seeded 指標資料提供教學到 cluster 的明示對照，正式模型暫不支援自動連結。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定同題的可計算定義、cluster 合併或重新命名後的追溯，以及同 Feature 但不同問題是否算重開票；不能只比對主題顯示文字。

前置釐清：D04（見 overview.md）。
已解決前置：D01（MVP 固定單一專案）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 以該教學首版的 gap:<cluster_id> 作為固定對應，後續分群需保留此 cluster 的可追溯身分。
- **更新的規格檔**：docs/spec/erm.dbml（本批未回寫）
- **變更內容**：同題以教學首版 `gap:<cluster_id>` 為固定對應，對應值落在 `Tutorial.cluster_id`。
