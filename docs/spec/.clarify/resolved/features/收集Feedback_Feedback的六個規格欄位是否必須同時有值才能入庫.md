# 釐清問題

Feedback 的六個規格欄位是否必須同時有值才能入庫？

# 定位

Feature：收集Feedback / Rule：Feedback 必須包含 tutorial_id、tutorial_version、rating、feedback_category、comment、timestamp
ERM：`Table Feedback` 六欄皆無 null / 必填標註；`comment` note 寫 Optional Comment
此 Rule 目前 `#TODO` / Missing Example

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 六欄都必須有值才能入庫；缺任一欄則 `Then 操作失敗` |
| B | 只有 tutorial_id、tutorial_version、rating、timestamp 必填；category 與 comment 可空 |
| C | 只有 tutorial_id、tutorial_version、timestamp 必填；rating、category、comment 可空 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 `收集Feedback` 的 Missing Example、與「未填 rating / category / comment」三題的驗收是否衝突，以及 `Feedback` 能否以不完整列進入 `定期優化Tutorial`。

# 優先級

High
---
# 解決記錄

- **回答**：B - 只有 tutorial_id、tutorial_version、rating、timestamp 必填；category 與 comment 可空
- **更新的規格檔**：docs/spec/features/收集Feedback.feature
- **變更內容**：改寫必填欄 Rule：四欄必填；缺 tutorial_id 或 timestamp 則操作失敗。category 與 comment 可空改由對應 Rule 驗證。
