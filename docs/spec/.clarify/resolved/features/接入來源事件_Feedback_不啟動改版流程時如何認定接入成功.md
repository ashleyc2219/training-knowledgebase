# 釐清問題

Feedback 不啟動改版流程時如何認定接入成功？

# 定位

- 追蹤 ID：F06
- [接入來源事件，Rule 12「寫回新流程前最後一個 tool 必須是通過的 validate」](../../../features/接入來源事件.feature)，第 71 行。
- [接入來源事件，Rule 13「寫回新流程前 Step Functions 必須成功啟動」](../../../features/接入來源事件.feature)，第 76 行。
- [接入來源事件，Rule 22「正規化成功的 Feedback 寫入 FEEDBACK item」](../../../features/接入來源事件.feature)，第 123 行。
- [接入來源事件，Rule 23「單筆 Feedback 接入不立即觸發教學改版」](../../../features/接入來源事件.feature)，第 128 行。
- [設計 7.6 成功的定義與失敗處理](../../../draft/training-kb-design-doc.md)，第 372 行。

現況：通用成功定義要求 Step Functions 已啟動，但 Feedback 明定只保存、等每日 Review，兩者無法直接套用同一條件。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | Feedback 以 validate 通過且回饋與關聯持久化成功為完成條件，Ticket 與 Release 維持啟動 Step Functions 的條件。 |
| B | Feedback 也啟動只負責接入保存的 Step Functions，仍不執行教學改版。 |
| C | Feedback 不納入 PROVEN_WORKFLOW 學習，只使用固定接入保存流程。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 Feedback 能否建立或更新 PROC、成功計數與不立即改版的驗收。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：C - Feedback 不納入 PROVEN_WORKFLOW 學習，只使用固定接入保存流程。
- **更新的規格檔**：docs/spec/features/接入來源事件.feature（本批未回寫）
- **變更內容**：Feedback 不進 PROC；固定保存成功即認定接入成功。
