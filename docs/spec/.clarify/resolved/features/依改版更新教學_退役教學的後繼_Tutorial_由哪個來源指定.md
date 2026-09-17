# 釐清問題

退役教學的後繼 Tutorial 由哪個來源指定？

# 定位

- 追蹤 ID：F54
- [依改版更新教學，Rule 16「RETIRE 的教學導向後繼 Tutorial」](../../features/依改版更新教學.feature)，第 142 行。
- [RELEASE.feature](../../erm.dbml)，第 133 行。
- [設計 B. Tool 介面](../../draft/training-kb-design-doc.md)，第 883 行。

現況：retire 工具接受 successor，但 Release schema 沒有該欄位，也沒有選擇後繼的節點；只有 Ticket Analysis 能建立新教學。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 來源事件直接提供既有 Tutorial ID，系統只驗證它存在且可公開。 |
| B | 由維護者選定既有 Tutorial，未選定時依無後繼分支處理。 |
| C | 系統依圖譜推薦既有 Tutorial，再由維護者確認後設定導向。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定新增輸入或操作入口、導向正確性的責任與錯誤後繼驗收；沒有後繼時的結果由 F19 單獨決定。

前置釐清：D22（見 overview.md）。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：B - 由維護者選定既有 Tutorial，未選定時依無後繼分支處理。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/依改版更新教學.feature
- **變更內容**：後繼由維護者在 RETIRE 當次指定；未選定則空，對齊 F19。
