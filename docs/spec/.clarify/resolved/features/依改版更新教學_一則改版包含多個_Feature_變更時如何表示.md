# 釐清問題

一則改版包含多個 Feature 變更時如何表示？

# 定位

- 追蹤 ID：F14
- [RELEASE.feature](../../../erm.dbml)，第 133 行。
- [RELEASE.kind](../../../erm.dbml)，第 134 行。
- [依改版更新教學，Rule 1「從 PR diff 或 changelog 抽出 feature、kind、old_name 與 new_name」](../../../features/依改版更新教學.feature)，第 7 行。

現況：目前 Release 只有一個 feature 與 kind；實際 PR diff 或 changelog 可以同時改名與移除不同功能。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 一個 Release 保存多筆 change，每筆各有 Feature 與 kind。 |
| B | 依變更拆成多個子 Release，保留相同的父來源事件識別碼。 |
| C | 接入只接受單一 Feature 變更，多變更輸入必須由來源先拆分。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 Release 基數、改動 reason、同一教學多個命中如何彙整成版本，以及部分變更失敗的處理範圍。

前置釐清：D02、D10（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：B - 依變更拆成多個子 Release，保留相同的父來源事件識別碼。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/依改版更新教學.feature（本批未回寫）
- **變更內容**：多個 Feature 變更拆成子 Release，共用父來源事件 ID（`source_event_id`）。
