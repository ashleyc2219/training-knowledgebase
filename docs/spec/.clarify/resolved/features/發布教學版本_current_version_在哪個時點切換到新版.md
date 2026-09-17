# 釐清問題

current_version 在哪個時點切換到新版？

# 定位

- 追蹤 ID：F37
- [TUTORIAL.current_version](../../erm.dbml)，第 33 行。
- [TUTORIAL_VERSION.published_at](../../erm.dbml)，第 55 行。
- [發布教學版本，Rule 4「Tutorial 的 current_version 指向目前教學版本」](../../features/發布教學版本.feature)，第 23 行。
- [發布教學版本，Rule 5「已上架的版本具有 published_at」](../../features/發布教學版本.feature)，第 28 行。

現況：目前版本與上架時間都有欄位，但來源沒有定義切換先後與新頁面不可讀時的行為。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | publish 成功回傳時切換；此時所需內容與關聯已完成寫入。 |
| B | create_version 完成時立即指向新版，publish 失敗時必須讓讀者看見待發布狀態。 |
| C | 維持舊版指標直到發布後的可讀性檢查成功，再切換到新版。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定讀者看到的版本、回饋提交目標與上架後可見性驗收；與 D25、F36 的版本生命週期保持一致。

前置釐清：D25、F36（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - publish 成功回傳時切換；此時所需內容與關聯已完成寫入。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/發布教學版本.feature
- **變更內容**：publish 成功回傳才切換 current_version；create_version 或 publish 失敗不切換。
