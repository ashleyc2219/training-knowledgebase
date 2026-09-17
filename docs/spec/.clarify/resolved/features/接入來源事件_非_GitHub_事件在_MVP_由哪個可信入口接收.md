# 釐清問題

非 GitHub 事件在 MVP 由哪個可信入口接收？

# 定位

- 追蹤 ID：F08
- [TICKET.source](../../../erm.dbml)，第 108 行。
- [RELEASE.source](../../../erm.dbml)，第 132 行。
- [接入來源事件，Rule 1「GitHub webhook 必須以 X-Hub-Signature-256 驗簽」](../../../features/接入來源事件.feature)，第 11 行。
- [接入來源事件，Rule 20「正規化成功的 Ticket 觸發 Ticket Analysis」](../../../features/接入來源事件.feature)，第 113 行。
- [接入來源事件，Rule 22「正規化成功的 Feedback 寫入 FEEDBACK item」](../../../features/接入來源事件.feature)，第 123 行。

現況：只有 GitHub webhook 的驗簽被定義，其餘來源包含會影響教學與規則評分的外部輸入。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | Discord、email、changelog 與 Feedback 僅由本機或受控種子匯入提供，不開放未驗證的公開接入。 |
| B | 所有非 GitHub 事件只能經過已驗證的 adapter 或應用入口，公開端點不直接接受正規化事件。 |
| C | 公開提供來源專用入口，各自使用供應商驗證或 widget 的應用憑證；需逐來源補齊契約。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 MVP 來源接入範圍、冒名事件拒絕方式與可測的身分界線；實際 secret 與部署設定留待實作。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - Discord、email、changelog 與 Feedback 僅由本機或受控種子匯入提供，不開放未驗證的公開接入。
- **更新的規格檔**：docs/spec/features/接入來源事件.feature（本批未回寫）
- **變更內容**：MVP 僅一個 GitHub webhook；其餘來源以手動上傳／受控匯入接收。
