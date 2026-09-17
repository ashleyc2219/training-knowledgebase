# 釐清問題

Ticket 接入驗證的必填欄位採哪套契約？

# 定位

- 追蹤 ID：D09
- [TICKET.id](../../../erm.dbml)，第 107 行。
- [TICKET.text](../../../erm.dbml)，第 109 行。
- [TICKET.author](../../../erm.dbml)，第 110 行。
- [TICKET.ts](../../../erm.dbml)，第 111 行。
- [TICKET.project_id](../../../erm.dbml)，第 112 行。
- [接入來源事件，Rule 18「正規化物件必須具有 schema 的必填欄位」](../../../features/接入來源事件.feature)，第 102 行。
- [分析工單，Rule 1「每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding」](../../../features/分析工單.feature)，第 8 行。

現況：附錄是示意物件而非 required schema；接入必填驗證與接入後才計算 embedding 的先後仍需一致。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | id、source、text、ts、project_id 必填；author 可空，embedding 與分群結果由分析流程補入。 |
| B | id、source、text、author、ts、project_id 必填；embedding 與分群結果由分析流程補入。 |
| C | 附錄 Ticket 所列欄位全部必須出現；cluster_id 可為 null，feature_ids 可為空，embedding_ref 必須先備妥。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

影響 normalize_ticket、validate、缺少作者的來源，以及衍生欄位尚未建立時能否觸發分析。

前置釐清：D02（見 overview.md）。
已解決前置：D01（MVP 固定單一專案）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - id、source、text、ts、project_id 必填；author 可空，embedding 與分群結果由分析流程補入。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/接入來源事件.feature、docs/spec/features/分析工單.feature
- **變更內容**：明定 Ticket 接入必填欄位；向量與分群改由分析補入。

---
# 後續覆寫

- **覆寫來源**：D23（改選 A）
- **變更**：Ticket.author 改為接入必填，並與 Feedback.user、TUTORIAL_VIEW.user 共用穩定使用者 ID。
