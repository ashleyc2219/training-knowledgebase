# 釐清問題

backfill 發現既有 Feature 引用錯誤時如何更新？

# 定位

- 追蹤 ID：F40
- [查詢知識圖譜，Rule 7「定期 backfill 漏抽的 Feature 引用邊」](../../../features/查詢知識圖譜.feature)，第 58 行。
- [TUTORIAL_STEP.target](../../../erm.dbml)，第 76 行。
- [建立教學版本，Rule 8「建立 TutorialStep 時保存 references Feature 邊」](../../../features/建立教學版本.feature)，第 54 行。

現況：定期 backfill 漏抽引用已列出，但沒有說明圖譜關係是不是不可變版本的一部分。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只增加缺少的邊，不移除或替換既有引用；錯誤邊另列待處理。 |
| B | 允許修正既有版本的引用邊，但保持該版本教學文字不變並留下修正紀錄。 |
| C | 任何引用修正都建立新 TutorialVersion，歷史版本的引用也保持不變。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定歷史反查、假 KEEP 的修復與錯邊修正是否消耗版本號；排程頻率可留到規劃。

前置釐清：D05、F17（見 overview.md）。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：A - 只增加缺少的邊，不移除或替換既有引用；錯誤邊另列待處理。
- **更新的規格檔**：docs/spec/features/查詢知識圖譜.feature
- **變更內容**：backfill 只補漏邊，不移除或替換既有引用；錯誤邊另列待處理，不因此建新 TutorialVersion。
