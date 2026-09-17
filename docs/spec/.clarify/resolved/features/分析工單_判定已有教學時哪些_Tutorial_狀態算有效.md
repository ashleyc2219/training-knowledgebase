# 釐清問題

判定已有教學時哪些 Tutorial 狀態算有效？

# 定位

- 追蹤 ID：F12
- [TUTORIAL.status](../../../erm.dbml)，第 36 行。
- [TUTORIAL.current_version](../../../erm.dbml)，第 33 行。
- [分析工單，Rule 6「對應 Feature 已有教學時動作為 KEEP」](../../../features/分析工單.feature)，第 33 行。
- [分析工單，Rule 8「已識別且尚無現成教學的 Knowledge Gap 建立新的 Tutorial」](../../../features/分析工單.feature)，第 43 行。

現況：KEEP 的前提是該 Feature 已有教學，沒有界定待發布或退役的身分是否仍阻止 CREATE。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只有 active 且有已發布版本的 Tutorial 才算已有教學。 |
| B | active 的 Tutorial 即使仍待首次發布也算已有教學，避免重複建立。 |
| C | 任何既有 Tutorial 身分都算，包括 retired；需要另有重新啟用或後繼處理方式。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

影響缺口補齊與重複教學；需測試 active、未發布、retired 及沒有 current_version 的情況。

前置釐清：D21、D25（見 overview.md）。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：B - active 的 Tutorial 即使仍待首次發布也算已有教學，避免重複建立。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/分析工單.feature
- **變更內容**：status=active 即使尚無已發布版本也算已有教學；retired 不算，不阻止 CREATE。
