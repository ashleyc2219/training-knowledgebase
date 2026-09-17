# 釐清問題

尚未發布的版本如何與已發布版本區分？

# 定位

- 追蹤 ID：D25
- [TUTORIAL_VERSION.published_at](../../../erm.dbml)，第 55 行。
- [TUTORIAL.current_version](../../../erm.dbml)，第 33 行。
- [發布教學版本，Rule 1「publish 上架指定的 TutorialVersion」](../../../features/發布教學版本.feature)，第 8 行。
- [發布教學版本，Rule 5「已上架的版本具有 published_at」](../../../features/發布教學版本.feature)，第 28 行。

現況：create_version 與 publish 分開，ERM 卻未定義未上架時 published_at 的值或版本可見性。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 版本可以先建立，published_at 為 null 代表未發布；只有非空值才表示已上架。 |
| B | 增加明確的版本狀態，區分待發布、已發布與失敗；published_at 只在發布成功後填入。 |
| C | 只有發布成功才建立正式 TutorialVersion，準備中的內容留在另一個暫存範圍。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定圖譜查詢、回饋驗證、失敗重試與 current_version 切換所依賴的生命週期。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 版本可以先建立，published_at 為 null 代表未發布；只有非空值才表示已上架。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/發布教學版本.feature
- **變更內容**：TUTORIAL_VERSION.published_at 空＝未發布，非空＝已上架；版本可先建立再發布。規格回寫由並行 agent 處理。
