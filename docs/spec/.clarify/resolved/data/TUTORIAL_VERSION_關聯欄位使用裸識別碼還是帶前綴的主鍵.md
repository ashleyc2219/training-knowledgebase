# 釐清問題

關聯欄位使用裸識別碼還是帶前綴的主鍵？

# 定位

- 追蹤 ID：D03
- [TUTORIAL.current_version](../../../erm.dbml)，第 33 行。
- [TUTORIAL_VERSION.supersedes](../../../erm.dbml)，第 51 行。
- [FEEDBACK.tutorial_version](../../../erm.dbml)，第 151 行。
- [AUTHORING_RULE.applied_to](../../../erm.dbml)，第 175 行。

現況：ERM 的 Ref 使用裸 version_id；實體邊使用 VERSION# 前綴，目前沒有一致的序列化契約。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 所有邏輯關聯欄位使用裸 ID，僅在 DynamoDB 邊與查詢時加上型別前綴。 |
| B | 所有持久化關聯欄位都使用帶型別前綴的 PK，介面另提供裸 ID。 |
| C | 維持欄位各自格式，但必須建立逐欄對照契約，禁止呼叫端自行猜測。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

影響 validate 的參照完整性、版本與規則關聯、adapter 轉換，以及重複加前綴的負向測試。

# 優先級

High

- 阻礙核心資料契約或主要流程定義。

---
# 解決記錄

- **回答**：A - 所有邏輯關聯欄位使用裸 ID，僅在 DynamoDB 邊與查詢時加上型別前綴。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/收集教學回饋.feature
- **變更內容**：current_version、supersedes、tutorial_version、applied_to、derived_from 明定使用裸 version_id。
