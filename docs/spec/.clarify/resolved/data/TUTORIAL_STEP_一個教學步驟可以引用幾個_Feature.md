# 釐清問題

一個教學步驟可以引用幾個 Feature？

# 定位

- 追蹤 ID：D05
- [TUTORIAL_STEP.target](../../../erm.dbml)，第 76 行。
- [TUTORIAL_STEP.sk](../../../erm.dbml)，第 75 行。
- [分析工單，Rule 11「產生新教學時同時輸出每步提到的 Feature」](../../../features/分析工單.feature)，第 59 行。
- [建立教學版本，Rule 8「建立 TutorialStep 時保存 references Feature 邊」](../../../features/建立教學版本.feature)，第 54 行。

現況：ERM 目前每步有一個必要 target；寫作規則只說輸出每步提到的 Feature，未交代 read 步驟或多功能步驟。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 恰好一個；無 Feature 或多 Feature 的內容須先拆解或驗證失敗。 |
| B | 零到多個；步驟本體與 REFERENCES 邊分開，沒有引用也可保存步驟。 |
| C | 至少一個；允許多條 REFERENCES 邊，但不接受沒有 Feature 的步驟。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

影響步驟儲存、反查去重、只改命中步驟，以及 0、1、2 個 Feature 的驗收案例。

已解決前置：D01（MVP 固定單一專案）。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 恰好一個；無 Feature 或多 Feature 的內容須先拆解或驗證失敗。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/分析工單.feature、docs/spec/features/建立教學版本.feature
- **變更內容**：每個教學步驟恰好引用一個 Feature；零個或多個時不可保存。
