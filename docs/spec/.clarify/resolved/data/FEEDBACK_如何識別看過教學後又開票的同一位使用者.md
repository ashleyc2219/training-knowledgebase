# 釐清問題

如何識別看過教學後又開票的同一位使用者？

# 定位

- 追蹤 ID：D23
- [FEEDBACK.user](../../../erm.dbml)，第 155 行。
- [TICKET.author](../../../erm.dbml)，第 110 行。
- [檢視學習指標，Rule 3「同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例」](../../../features/檢視學習指標.feature)，第 18 行。

現況：Feedback.user、Ticket.author 與教學閱覽者之間沒有對應規則，不能以相同顯示名稱推定同一人。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 瀏覽、回饋與 Ticket 共用同一個穩定使用者 ID，由來源接入時直接提供。 |
| B | 保存明確的跨來源身分對照，把 viewer、Feedback.user 與 Ticket.author 連到同一人。 |
| C | MVP 只使用種子資料中明示的身分對照，真實來源無法連結者不計此指標。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定重開票率是否可計算、必要的身分資料與未識別使用者排除方式。

已解決前置：D01（MVP 固定單一專案）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 瀏覽、回饋與 Ticket 共用同一個穩定使用者 ID，由來源接入時直接提供。
- **先前回答**：C - MVP 只使用種子資料中明示的身分對照，真實來源無法連結者不計此指標。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/檢視學習指標.feature、docs/spec/features/接入來源事件.feature、docs/spec/features/收集教學回饋.feature
- **變更內容**：TUTORIAL_VIEW.user、Feedback.user 與 Ticket.author 共用穩定使用者 ID，接入必填。覆寫 D09 的 author 可空。不新增 User 實體或跨來源對照表。
