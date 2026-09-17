# 釐清問題

第一版沒有前版時 diff 檔案如何表示？

# 定位

- 追蹤 ID：F50
- [建立教學版本，Rule 1「新 Tutorial 的版本從 v1 起算」](../../features/建立教學版本.feature)，第 9 行。
- [建立教學版本，Rule 7「與前版的 diff 儲存在 tutorials/<slug>/v<n>.diff」](../../features/建立教學版本.feature)，第 49 行。
- [TUTORIAL_VERSION.supersedes](../../erm.dbml)，第 51 行。

現況：一般版本的 diff 路徑已規定，但 v1 的 supersedes 為空，沒有對應檔案與呈現契約。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | v1 不建立 diff 檔，介面顯示沒有前一版可比較。 |
| B | 將 v1 相對空內容的完整新增差異存成 v1.diff。 |
| C | 建立空的 v1.diff，介面另外以版本號識別它沒有前版。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定首版資產清單、讀取不存在 diff 的行為及發布初版的驗收。

# 優先級

Low

- 影響展示細節或低風險輸出格式。

---
# 解決記錄

- **回答**：C - 建立空的 v1.diff，介面另外以版本號識別它沒有前版。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/建立教學版本.feature
- **變更內容**：v1 建立空的 v1.diff；介面以版本號識別沒有前版。
