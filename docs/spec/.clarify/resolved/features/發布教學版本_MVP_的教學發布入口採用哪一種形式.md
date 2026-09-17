# 釐清問題

MVP 的教學發布入口採用哪一種形式？

# 定位

- 追蹤 ID：F38
- [發布教學版本，Rule 2「發布的教學透過 S3 靜態 docs 站或 in-app 提供」](../../features/發布教學版本.feature)，第 13 行。
- [發布教學版本，Rule 3「發布的教學提供 feedback widget」](../../features/發布教學版本.feature)，第 18 行。

現況：來源使用 S3 靜態 docs 站或 in-app，尚未選定使用者實際到達教學與提交回饋的介面。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 只提供 S3 靜態 docs 站，頁面包含版本化內容與 feedback widget。 |
| B | 只提供 in-app 教學頁，內嵌版本內容與 feedback widget。 |
| C | 兩個入口都提供，必須明確共用版本識別與回饋歸屬。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 MVP 頁面範圍、publish 的完成條件與需要驗收的使用者旅程；不是重新選擇 S3 內容儲存。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 只提供 S3 靜態 docs 站，頁面包含版本化內容與 feedback widget。
- **更新的規格檔**：docs/spec/features/發布教學版本.feature
- **變更內容**：MVP 只提供 S3 靜態 docs 站與 feedback widget，不另做 in-app 教學頁。
