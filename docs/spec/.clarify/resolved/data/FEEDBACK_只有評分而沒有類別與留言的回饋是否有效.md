# 釐清問題

只有評分而沒有類別與留言的回饋是否有效？

# 定位

- 追蹤 ID：D12
- [FEEDBACK.category](../../erm.dbml)，第 153 行。
- [FEEDBACK.comment](../../erm.dbml)，第 154 行。
- [收集教學回饋，Rule 3「使用者勾選的 Feedback Category 優先於模型分類」](../../features/收集教學回饋.feature)，第 19 行。
- [收集教學回饋，Rule 4「需要分類的自由留言在接入時計算一次 Feedback Category」](../../features/收集教學回饋.feature)，第 24 行。

現況：rating 範圍已明確，但未說明沒有任何文字可分類時是否仍可提交。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 有效；category 為空、comment 為空，只參與評分計算，不送模型分類。 |
| B | 無效；category 與非空 comment 至少必須提供一項。 |
| C | 高於 2 分可只評分；1 或 2 分必須提供 category 或非空 comment。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

影響 widget 驗證、LLM 零輸入分支、樣本數與 recurring category 的計算。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：A - 有效；category 為空、comment 為空，只參與評分計算，不送模型分類。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/收集教學回饋.feature
- **變更內容**：只有評分的回饋有效，只計評分；類別與留言可空，不送模型分類。
