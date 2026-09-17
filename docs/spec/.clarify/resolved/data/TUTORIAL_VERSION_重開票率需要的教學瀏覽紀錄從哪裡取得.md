# 釐清問題

重開票率需要的教學瀏覽紀錄從哪裡取得？

# 定位

- 追蹤 ID：D24
- [TUTORIAL_VERSION.published_at](../../../erm.dbml)，第 55 行。
- [檢視學習指標，Rule 3「同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例」](../../../features/檢視學習指標.feature)，第 18 行。
- [檢視學習指標，Rule 9「Demo 對同題重開票率標明 proxy 與精確定義」](../../../features/檢視學習指標.feature)，第 71 行。

現況：ERM 明示缺少閱覽紀錄；設計定義的分母需要看過教學的人，單靠 Ticket 與 Feedback 無法推得。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 在 MVP 新增瀏覽事件，至少記錄版本、使用者與瀏覽時間，作為指標來源。 |
| B | MVP 匯入具備版本、使用者與時間的 seeded 瀏覽紀錄，介面明示非即時測量。 |
| C | MVP 暫不提供重開票率，只展示明示為 seeded 的重開票筆數，並修正對應驗收範圍。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定是否新增資料概念、埋點或匯入契約；避免把重開票數字 7 與 2 當成已計算的比例。

前置釐清：D23（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 在 MVP 新增瀏覽事件，至少記錄版本、使用者與瀏覽時間，作為指標來源。
- **先前回答**：C - MVP 暫不提供重開票率，只展示明示為 seeded 的重開票筆數，並修正對應驗收範圍。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/檢視學習指標.feature、docs/spec/features/接入來源事件.feature、docs/spec/features/驗證教學規則.feature
- **變更內容**：新增 TUTORIAL_VIEW，必填 tutorial_version、user、ts，作為重開票率分母。Demo 的 7 與 2 仍是筆數，不能直接當成比例。PK 格式未指定。
