# 釐清問題

applies_when 的可表達條件範圍為何？

# 定位

- 追蹤 ID：D16
- [AUTHORING_RULE.applies_when](../../../erm.dbml)，第 172 行。
- [TUTORIAL_STEP.type](../../../erm.dbml)，第 77 行。
- [套用教學規則，Rule 3「依 step 型態與 applies_when 篩選規則」](../../../features/套用教學規則.feature)，第 18 行。

現況：唯一例子是 step.type == click_ui；沒有定義其他條件是否有效或如何驗證。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | MVP 僅支援 step.type 等於 click_ui、input 或 read 的單一條件。 |
| B | 支援經核定欄位的 AND 與 OR 組合，必須補列允許欄位、運算子與不合法條件行為。 |
| C | 只引用預先註冊的適用情境名稱，由固定函式判斷，LLM 不產生可執行運算式。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

影響規則篩選、衝突範圍判斷與 predicate 的正反案例；不得直接執行任意規則字串。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：A - MVP 僅支援 step.type 等於 click_ui、input 或 read 的單一條件。
- **更新的規格檔**：docs/spec/erm.dbml、docs/spec/features/套用教學規則.feature、docs/spec/features/提出教學規則.feature
- **變更內容**：applies_when 僅支援單一 step.type 條件；不支援 AND/OR，LLM 不產生任意運算式。
