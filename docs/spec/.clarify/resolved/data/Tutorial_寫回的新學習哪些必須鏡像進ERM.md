# 釐清問題

寫回的新學習之中，哪些必須鏡像進作用中 ERM，才能被 Feature Then 驗證？

# 定位

ERM：已有 `TutorialVersion`、`Feedback`；無圖譜擴張計數、無寫回事件
Feature：無「寫回新學習」功能
來源：客服規格要持久化圖譜、教學版本、教學↔問題類型、回饋成效；黑客松要求動作層 writes back new learnings
已有相關：Tutorial↔UserProblem、Workflow 關聯、Feedback 訊號（各問一塊，沒問寫回集合）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只鏡像教學版本與教學↔問題類型；成效與圖譜擴張不進 ERM |
| B | 再鏡像成效（評分或再開票結果）；圖譜 node／edge 數不進 ERM |
| C | 版本、對應、成效、圖譜擴張四類都要有可點名的 ERM 實體或欄位 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

是否新增 Writeback／GraphSnapshot 或只加計數欄；「記憶有在累積」能不能寫成 Then。不問用哪個 SDK 或 Knowledge／Memories bucket。

# 優先級

High
---
# 解決記錄

- **回答**：B - 再鏡像成效（評分或再開票結果）；圖譜 node／edge 數不進 ERM
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：版本（TutorialVersion）、對應（Tutorial.user_problem_id）與成效（Feedback、Ticket.status／reopened_from_ticket_id）已入 ERM；未新增圖譜 node／edge 計數欄。
