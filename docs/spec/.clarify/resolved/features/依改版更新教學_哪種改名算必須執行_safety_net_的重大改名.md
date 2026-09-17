# 釐清問題

哪種改名算必須執行 safety_net 的重大改名？

# 定位

- 追蹤 ID：F16
- [依改版更新教學，Rule 5「反查為零或重大改名時使用 step 文字向量搜尋補漏」](../../features/依改版更新教學.feature)，第 49 行。
- [設計 9.2 Release Note Update](../../draft/training-kb-design-doc.md)，第 577 行。

現況：重大改名沒有定義；反查為零的觸發條件已明確，不需要重問。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 所有 kind=renamed 都執行 safety_net，即使已有 references 命中。 |
| B | 只有 alias 比對失敗的 renamed 才算重大改名；反查為零仍獨立觸發。 |
| C | 由 extract_change 輸出明確的 major_rename 判定，須補齊可驗證判準與範例。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 safety_net 的執行範圍、額外模型呼叫與有引用但可能漏抽步驟的測試。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：B - 只有 alias 比對失敗的 renamed 才算重大改名；反查為零仍獨立觸發。
- **更新的規格檔**：docs/spec/features/依改版更新教學.feature
- **變更內容**：alias 失敗的 renamed 才是重大改名並跑 safety_net；alias 已命中不算。反查為零仍獨立觸發。
