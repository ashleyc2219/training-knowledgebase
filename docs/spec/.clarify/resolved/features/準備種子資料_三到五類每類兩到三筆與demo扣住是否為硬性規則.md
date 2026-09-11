# 釐清問題

「挑 3–5 個主打類別、每類 2–3 筆建圖，其餘同批資料扣住到 demo 再餵」是否要寫成可驗證 Feature 規則？

# 定位

Feature：準備種子資料 / Rule：缺失功能
已有釐清：`分析SupportTickets_二十到三十張Tickets是否為分析功能的硬性前置條件`（張數，不是類別數與扣住）
來源：客服規格把種子／扣住當成 deflection 曲線可重現的資料策略
**依賴**：產品主軸題；`建構知識圖譜_歷史種子離線建圖是否為獨立於分析SupportTickets的功能`

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 是硬性規則；類別數或每類筆數不符、或誤用扣住集，則建圖／分析失敗 |
| B | 不是規則，只是 demo 資料安排，不進 Feature |
| C | 只驗「種子與 demo 不得用同一筆 Ticket」，不驗 3–5 類／2–3 筆 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

是否新增準備種子資料 Feature，以及 Ticket 是否要有 seed／holdout 標記。選 B 則 3–5／2–3 不能當 Example 前置。

# 優先級

Medium
---
# 解決記錄

- **回答**：B - 不是規則，只是 demo 資料安排，不進 Feature
- **更新的規格檔**：docs/spec/features/建構知識圖譜.feature
- **變更內容**：不進 Feature；已在 建構知識圖譜.feature 的 Feature 描述註明 demo 資料安排不列規則
