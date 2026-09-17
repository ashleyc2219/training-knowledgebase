# 釐清問題

退役時沒有後繼 Tutorial 要呈現什麼結果？

# 定位

- 追蹤 ID：F19
- [依改版更新教學，Rule 16「RETIRE 的教學導向後繼 Tutorial」](../../../features/依改版更新教學.feature)，第 142 行。
- [TUTORIAL.status](../../../erm.dbml)，第 36 行。
- [設計 B. Tool 介面](../../../draft/training-kb-design-doc.md)，第 883 行。

現況：工具允許 successor=None，功能規則卻只描述導向後繼；沒有替代教學時的可見結果不明。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 仍完成退役，顯示過期說明與原文，但不產生導向。 |
| B | 取得有效的後繼 Tutorial 前維持待處理，不完成退役發布。 |
| C | 完成退役後停止提供原文，顯示已移除且沒有替代教學。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定舊網址、widget 與退役完成條件；不默認 Release 可以建立新 Tutorial。

前置釐清：D21、D22（見 overview.md）。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：A - 仍完成退役，顯示過期說明與原文，但不產生導向。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/依改版更新教學.feature
- **變更內容**：沒有後繼仍完成 RETIRE；顯示過期說明與原文，successor 保持空，不卡住等待後繼。
