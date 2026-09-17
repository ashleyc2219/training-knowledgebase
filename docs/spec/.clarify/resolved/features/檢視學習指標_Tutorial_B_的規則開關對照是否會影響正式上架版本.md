# 釐清問題

Tutorial B 的規則開關對照是否會影響正式上架版本？

# 定位

- 追蹤 ID：F47
- [檢視學習指標，Rule 10「Demo 以同一批 Ticket 並排展示規則關閉與開啟產生的 Tutorial B」](../../features/檢視學習指標.feature)，第 76 行。
- [建立教學版本，Rule 1「新 Tutorial 的版本從 v1 起算」](../../features/建立教學版本.feature)，第 9 行。
- [套用教學規則，Rule 5「既有教學衍生的適用規則可用於不同主題新教學的第一版」](../../features/套用教學規則.feature)，第 37 行。
- [發布教學版本，Rule 1「publish 上架指定的 TutorialVersion」](../../features/發布教學版本.feature)，第 8 行。

現況：同一批 Ticket 生成規則開與關兩份 B，卻未定義其版本身分與是否污染 rules_applied、applied_to 或後續回饋。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只有開啟規則的 B v1 正式上架，關閉規則的產物是隔離預覽。 |
| B | 兩份都作為明示的實驗變體保存，正式 Tutorial 的 current_version 另外指定。 |
| C | 兩份都只是隔離的 Demo 產物，不寫入正式教學、回饋與規則效果統計。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定展示資料隔離、版本號及對照可比性；不可把兩份輸出都默認成同一個正式 B v1。

前置釐清：F27、F38（見 overview.md）。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：C - 兩份都只是隔離的 Demo 產物，不寫入正式教學、回饋與規則效果統計。
- **更新的規格檔**：docs/spec/features/檢視學習指標.feature
- **變更內容**：規則開關對照的兩份 Tutorial B 只做 Demo 隔離，不寫入正式教學。
