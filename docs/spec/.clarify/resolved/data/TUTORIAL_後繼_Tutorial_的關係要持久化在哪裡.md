# 釐清問題

後繼 Tutorial 的關係要持久化在哪裡？

# 定位

- 追蹤 ID：D22
- [TUTORIAL.status](../../../erm.dbml)，第 36 行。
- [TUTORIAL.successor](../../../erm.dbml)，第 37 行。
- [依改版更新教學，Rule 16「RETIRE 的教學導向後繼 Tutorial」](../../../features/依改版更新教學.feature)，第 150 行。

現況：retire(slug, successor) 接受參數，但九實體 ERM 未定義後繼關係；重啟後無法由現有欄位還原導向。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 在 Tutorial metadata 保存可空的 successor Tutorial ID。 |
| B | 保存獨立的 SUCCESSOR 關係邊，沒有後繼時不建立邊。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定圖譜新增關係或欄位，以及自我導向、循環導向與不存在後繼的驗證。

前置釐清：D03、D21（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 在 Tutorial metadata 保存可空的 successor Tutorial ID。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/依改版更新教學.feature
- **變更內容**：TUTORIAL 新增可空 successor（裸 slug）；沒有後繼時保持空值；新增 tutorial_successor Ref。無後繼時的呈現留給 F19。
