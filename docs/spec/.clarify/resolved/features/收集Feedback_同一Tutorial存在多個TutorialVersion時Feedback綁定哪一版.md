# 釐清問題

同一 Tutorial 存在多個 TutorialVersion 時，Feedback 綁定哪一版？

# 定位

Feature：收集Feedback / Rule：Feedback 參照 TutorialVersion（`#TODO` / Missing）
現有 Comment Example 的 Given 只有 title，沒有 version
已有釐清：沒有對應 TutorialVersion 時提交行為；rating 用最新版全歷史還是當前 published 算
未問：提交當下預設綁哪一版

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 一律綁該 Tutorial 當前已發布的最新版 |
| B | 綁使用者實際閱讀的那一版，提交時必須帶 version |
| C | 未指定 version 就綁最新已發布版；有指定則綁指定版 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

Missing Rule「Feedback 參照 TutorialVersion」的 Given／Then，以及 `定期優化Tutorial` 聚合時哪些列算進平均 rating。與「無 Version」題互補。

# 優先級

Medium
---
# 解決記錄

- **回答**：C - 未指定 version 就綁最新已發布版；有指定則綁指定版
- **更新的規格檔**：docs/spec/features/收集Feedback.feature
- **變更內容**：參照 TutorialVersion Rule 新增兩則 Example：未指定綁 current_version（v2）；有指定綁指定版（v1）。
