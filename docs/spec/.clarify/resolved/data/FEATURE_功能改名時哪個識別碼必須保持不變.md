# 釐清問題

功能改名時哪個識別碼必須保持不變？

# 定位

- 追蹤 ID：D06
- [FEATURE.pk](../../../erm.dbml)，第 91 行。
- [FEATURE.name](../../../erm.dbml)，第 92 行。
- [FEATURE.aliases](../../../erm.dbml)，第 93 行。
- [依改版更新教學，Rule 2「改名前後的 alias 對應同一個 Feature 節點」](../../../features/依改版更新教學.feature)，第 12 行。
- [依改版更新教學，Rule 14「UPDATE 完成時更新 Feature 的 aliases」](../../../features/依改版更新教學.feature)，第 132 行。

現況：來源要求新舊名稱指向同一節點，但 PK 是 FEATURE#<name>，Prepare 範例未說明原節點如何演變。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 保留第一次建立的 FEATURE PK，改名只更新顯示名稱與 aliases。 |
| B | 改用不隨名稱改變的 Feature ID，名稱與 aliases 都是屬性。 |
| C | 改成新名稱的 FEATURE PK，並同步遷移所有既有引用。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定改名是否遷移引用、舊版能否追溯，以及連續改名後的反查結果。

前置釐清：D03（見 overview.md）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 保留第一次建立的 FEATURE PK，改名只更新顯示名稱與 aliases。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/依改版更新教學.feature
- **變更內容**：Feature PK 於第一次寫入後不變；name 為目前顯示名稱，aliases 記曾用名稱。
