# 釐清問題

哪些 Feedback Category 應算入負面回饋？

# 定位

- 追蹤 ID：F43
- [FEEDBACK.category](../../erm.dbml)，第 153 行。
- [檢視學習指標，Rule 2「負面 Feedback 數計入 rating 不超過 2 或 category 屬負面的回饋」](../../features/檢視學習指標.feature)，第 13 行。

現況：rating<=2 的條件已明確，但 category 屬負面的集合未列出。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 所有已核定的問題類別都屬負面，未分類不因 category 計入；rating<=2 仍獨立計入。 |
| B | 類別表明列 negative 標記，只有該標記為真的類別計入。 |
| C | 類別本身不固定情緒，另由一次性的分類結果提供 polarity，再決定是否為負面。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定高分但選問題類別的回饋、未知分類與雙重命中只計一次的驗收。

前置釐清：D13（見 overview.md）。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：A - 所有已核定的問題類別都屬負面，未分類不因 category 計入；rating<=2 仍獨立計入。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/檢視學習指標.feature
- **變更內容**：核定類別找不到按鈕、缺少資訊皆為負面；待分類不因類別計入。
