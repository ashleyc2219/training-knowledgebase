# 釐清問題

與 Release Note 同時要求修改同一篇 Tutorial 時，優先執行哪個動作？

# 定位

Feature：定期優化Tutorial / Rule：分析 Ratings 與 Comments 後找出較弱的部分並產生改善版本（REFINE）
Feature：依ReleaseNote更新Tutorial / Rule：更新受影響內容並發布新版本（UPDATE）
已有釐清：`依ReleaseNote更新Tutorial_同一則ReleaseNote同時需要UPDATE與CREATE時優先序為何`（不是 Feedback 與產品變更同時打同一篇）
design-draft：兩條 Trigger 分開畫，未定義併發

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 先 UPDATE 產品變更，REFINE 等到下一輪定期 Review |
| B | 合併成一次發新版，同時改過期步驟與弱段，動作記 UPDATE |
| C | 合併成一次發新版，動作同時記 UPDATE 與 REFINE |
| D | 先 REFINE 再 UPDATE，允許連續兩個新版本 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定兩檔 Feature 的衝突 Example：同一 Tutorial 能否在一次處理產出 vN+1 還是 vN+2，以及 `reason`／`action` 欄要寫哪個。影響版本號與審核佇列次數。

# 優先級

High
---
# 解決記錄

- **回答**：A - 先 UPDATE 產品變更，REFINE 等到下一輪定期 Review
- **更新的規格檔**：docs/spec/features/定期優化Tutorial.feature
- **變更內容**：新增 Rule：is_possibly_outdated = true 時本輪 Review 動作為 KEEP，current_version 不變。
