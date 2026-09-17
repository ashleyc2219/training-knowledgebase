# 釐清問題

STABLE_KEYS 白名單依哪個範圍定義？

# 定位

- 追蹤 ID：F02
- [PROVEN_WORKFLOW.keys](../../../erm.dbml)，第 195 行。
- [接入來源事件，Rule 3「來源簽名使用來源網域、有意義的 header 名稱與穩定 payload key 計算」](../../../features/接入來源事件.feature)，第 21 行。
- [接入來源事件，Rule 4「ID、時間戳與標題等事件值不參與來源簽名」](../../../features/接入來源事件.feature)，第 29 行。
- [設計 7.2 簽名函數](../../../draft/training-kb-design-doc.md)，第 310 行。

現況：簽名函數引用 STABLE_KEYS 但沒有值；PROC.keys 範例與 event_keys 是否同樣排除選填欄位也未確定。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 每一種來源與事件類型有自己的固定必備 top-level key 清單。 |
| B | 所有來源共用一份 top-level key 白名單，依事件實際出現的 key 取交集。 |
| C | 由已核定的來源 schema 必填 top-level key 推導，不另維護手寫白名單。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定相同事件形狀的穩定性、各來源所需清單，以及增加選填 key 後的第一層與第二層測試；選定策略後仍須提供實際清單。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 每一種來源與事件類型有自己的固定必備 top-level key 清單。
- **更新的規格檔**：docs/spec/features/接入來源事件.feature（本批未回寫）
- **變更內容**：每來源／事件類型固定 STABLE_KEYS；MVP GitHub = `action`, `issue`, `repository`, `sender`。
