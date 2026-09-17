# 釐清問題

RETIRE 之後的狀態應使用 retired 還是 obsolete？

# 定位

- 追蹤 ID：D21
- [TUTORIAL.status](../../../erm.dbml)，第 36 行。
- [依改版更新教學，Rule 15「RETIRE 將受影響教學標記為過期」](../../../features/依改版更新教學.feature)，第 144 行。

現況：ERD 列 active 與 retired，Release pipeline 使用標記 obsolete，沒有說明是否為同一生命週期。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | retired 是唯一資料狀態，obsolete 只是同一狀態的顯示文字。 |
| B | obsolete 與 retired 是同義詞，統一將資料枚舉改為 obsolete。 |
| C | 兩者是不同狀態：obsolete 表示內容過期仍可用，retired 表示停止提供；需補上各自轉換條件。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

影響查找現成教學、上架與回饋資格、退役頁面，以及各文件的統一術語。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - retired 是唯一資料狀態，obsolete 只是同一狀態的顯示文字。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/依改版更新教學.feature
- **變更內容**：Tutorial.status 枚舉為 active | retired；obsolete 僅作顯示別名。
