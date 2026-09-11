# 釐清問題

建立 Tutorial 時缺少 Title、Problem、Prerequisites、Steps、Expected Outcome 任一欄，系統行為為何？

# 定位

Feature：建立Tutorial / Rule：建立的 Tutorial 必須包含 Title、Problem、Prerequisites、Steps、Expected Outcome

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | Then 操作失敗，不建立任何 Tutorial |
| B | 仍建立 Tutorial，缺欄以空字串存檔 |
| C | 僅缺 Title 或 Steps 時操作失敗，其餘欄可空 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

建立Tutorial 必填欄 Rule（#TODO）需補齊欄成功 Example 與缺一欄失敗 Example；Then 須改為具體欄位值或「操作失敗」。

# 優先級

High
---
# 解決記錄

- **回答**：A - Then 操作失敗，不建立任何 Tutorial
- **更新的規格檔**：docs/spec/features/建立Tutorial.feature
- **變更內容**：補五個缺欄 Example，Then 皆為操作失敗
