# 釐清問題

same_sender 以哪個來源範圍識別流程？

# 定位

- 追蹤 ID：D19
- [PROVEN_WORKFLOW.pk](../../../erm.dbml)，第 199 行。
- [PROVEN_WORKFLOW.keys](../../../erm.dbml)，第 201 行。
- [接入來源事件，Rule 8「第一層未命中才在同寄件者的流程中以 Jaccard 至少 0.8 比對欄位」](../../../features/接入來源事件.feature)，第 49 行。

現況：第二層呼叫 table.same_sender(event)，但 PROC item 沒有來源範圍欄位，簽名雜湊也無法反推出它。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 來源網域、adapter 類型與專案共同構成範圍，跨專案不共用重放流程。 |
| B | 來源網域與 adapter 類型共同構成範圍，同類來源可跨專案共用不含事件值的流程。 |
| C | 使用已驗證的來源帳號或 webhook 訂閱識別碼，同一網域內的不同寄件者仍分開。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定必要的持久化來源資訊、第二層候選集合及不同寄件者同形 payload 的隔離測試。

已解決前置：D01（MVP 固定單一專案）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：B - 來源網域與 adapter 類型共同構成範圍，同類來源可跨專案共用不含事件值的流程。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/接入來源事件.feature
- **變更內容**：同寄件者範圍是來源網域加 adapter 類型；不新增 sender、domain 或專案欄位。
