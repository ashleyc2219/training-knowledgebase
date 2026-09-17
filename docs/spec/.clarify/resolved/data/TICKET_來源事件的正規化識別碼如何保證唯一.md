# 釐清問題

來源事件的正規化識別碼如何保證唯一？

# 定位

- 追蹤 ID：D02
- [TICKET.id](../../../erm.dbml)，第 107 行。
- [RELEASE.id](../../../erm.dbml)，第 131 行。
- [FEEDBACK.id](../../../erm.dbml)，第 150 行。
- [接入來源事件，Rule 18「正規化物件必須具有 schema 的必填欄位」](../../../features/接入來源事件.feature)，第 102 行。

現況：t_、r_、f_ 只是範例；FEEDBACK 另有 f12 與 f_12 差異，沒有來源碰撞與重送時的識別契約。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 上游 ID 已全域唯一，正規化 id 直接使用上游 ID。 |
| B | 以來源、專案與上游 ID 組合產生穩定 id；Feedback 使用提交識別碼。 |
| C | 接入層產生新 id，另保存上游識別碼到正規化 id 的穩定對照。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

影響事件去重、規則 evidence 引用，以及同一上游 ID 出現在不同來源的測試。

已解決前置：D01（MVP 固定單一專案）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 上游 ID 已全域唯一，正規化 id 直接使用上游 ID。接入層產出 t_、r_、f_ 前綴且不撞號。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/接入來源事件.feature、docs/spec/features/提出教學規則.feature
- **變更內容**：Ticket / Release / Feedback 的 id 改為直接使用全域唯一上游識別碼；回饋識別碼統一為 f_<n>。
