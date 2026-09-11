# 釐清問題

找出受影響 Tutorial 時，是比對步驟文字還是功能節點關聯？

# 定位

Feature：依ReleaseNote更新Tutorial / Rule：將 Release Note 與既有 Tutorial Knowledge 比對並找出受影響的 Tutorials
現有 Example：Step 3 文字含「Meeting Summary」即命中 `prepare-meeting.md`
客服規格：「每一篇教學文章都要能連回它所引用的具體產品功能節點」
已有相關：`Tutorial_Tutorial的feature_id是否必填`（資料必填）；本題問比對演算法

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只比對 Tutorial 步驟或本文是否出現變更名稱 |
| B | 只透過 Tutorial 與 Feature 節點的關聯找出受影響篇 |
| C | 先用 Feature 關聯縮小範圍，再用步驟文字確認 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

改這條 Rule 的 Given（要不要先有 Feature 關聯）與 Then。選 B／C 會迫使 `建立Tutorial` 寫入功能關聯，否則 UPDATE 測不到。

# 優先級

High
---
# 解決記錄

- **回答**：B - 只透過 Tutorial 與 Feature 節點的關聯找出受影響篇
- **更新的規格檔**：docs/spec/features/依ReleaseNote更新Tutorial.feature
- **變更內容**：找受影響 Tutorial 只靠 Tutorial.feature_id 命中，不比對步驟文字。
