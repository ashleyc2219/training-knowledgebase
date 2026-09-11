# 釐清問題

Release Note 與模擬 changelog 表是否為同一產品變更訊號？

# 定位

ERM：`Table Release`（`content` 為 Release Note 本文；`changes` Feature）
Feature：`依ReleaseNote更新Tutorial` 以「系統收到 Release Note」為 When
來源衝突：design-draft.md 以自由文本 Release Note 觸發 UPDATE / CREATE / RETIRE；客服規格以 hotdata 輪詢「模擬 changelog 表」偵測產品新版本

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 同義，canonical 為 Release Note 自由文本；changelog 只是 demo 餵資料方式，不另建模 |
| B | 同義，canonical 為 changelog 列（時間、功能、變更類型）；`Release.content` 改為表列而非長文 |
| C | 同一語意、兩段表示：changelog 列是偵測來源，萃取後才寫成 `Release` 並驅動 Tutorial 更新 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 `Release` 形狀、`依ReleaseNote更新Tutorial` 的 Given／When 用詞，以及 Feature／UI 變更要從長文擷取還是從表欄讀取。不在此題決定是否使用 hotdata。

# 優先級

High
---
# 解決記錄

- **回答**：A - 同義，canonical 為 Release Note 自由文本；changelog 只是 demo 餵資料方式，不另建模
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Release Note 註明 demo 的模擬 changelog 表就是本表，一列一則；未另建 changelog 表。
