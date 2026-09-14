# 來源：../draft/training-kb-design-doc.md §9、§9.1–§9.3、§11、§12.1、§20.B。
Feature: 套用教學規則
  各 pipeline 在產生教學或改寫步驟前呼叫 get_active_rules，將適用規則帶入寫作 prompt。

  # 來源：設計 §9、§9.1–§9.3。
  @Missing
  Rule: CREATE、UPDATE 與 REFINE 在寫作前讀取教學規則
    #TODO 原文未提供三種動作各自的完整規則查詢與 prompt 紀錄。

  # 來源：設計 §9、§11.2、§12.1；釐清 F27。
  @Missing
  Rule: 一般寫作路徑只取得 status 為 active 的規則
    # 正式寫作路徑不自動試用 candidate。
    # 黑客松只從明示種子試用版本帶入 candidate 成效，不把 candidate 改寫成 active。
    #TODO 原文未提供寫作當下只回傳 active 的查詢紀錄。

  # 來源：設計 §9.1、§11.1、§20.B；釐清 D16、F28。
  @Partial
  Rule: 依 step 型態與 applies_when 篩選規則
    #TODO 原文未提供 input、read 的規則集合與不適用案例。
    # MVP 的 applies_when 僅支援單一條件：step.type 等於 click_ui、input 或 read。
    # 不支援 AND/OR 組合；LLM 不產生任意運算式。
    # 多條衝突的 active 規則同一適用範圍時，只採用最近驗證通過的那條。
    # 舊規則保留歷史但本次不注入。不新增 priority 欄位。不停止寫作。

    Example: click_ui 步驟取得 R-007
      Given 教學規則庫具有下列規則
        | rule_id | status | applies_when          |
        | R-007   | active | step.type == click_ui |
      When 系統取得 "click_ui" 步驟的教學規則
      Then 取得的規則集合為
        | rule_id |
        | R-007   |

  # 來源：設計 §9、§11.1、§11.3；釐清 F28。
  @Missing
  Rule: 適用規則的內容注入教學寫作 prompt
    #TODO 原文有 R-007 規則文字，但沒有可核對的完整寫作 prompt。
    # 同一適用範圍有衝突時只注入最近驗證通過的規則；舊規則本次不注入。

  # 來源：設計 §11.1、§11.3、§12.1、§16 T2；釐清 F27。
  @Missing
  Rule: 既有教學衍生的適用規則可用於不同主題新教學的第一版
    # 正式寫作只讀 active。黑客松只從明示種子試用版本帶入 candidate 成效。
    # 不把 B v1 的套用改寫成已先驗證 active。
    #TODO 原文有 A → R-007 → B v1 的故事，沒有種子試用版本清單與寫入結果。

  # 來源：設計 §8.3、§11.1；ERD §4；釐清 D17。
  @Missing
  Rule: 套用規則的版本記錄於規則的 applied_to
    #TODO 原文列 R-007 已套用三版的快照，沒有單次套用前後的完整更新紀錄。
    # applied_to 與 APPLIED_TO 邊由各版本 rules_applied 重建。
    # 原文複製沿用的規則不因新版而追加到 applied_to。
    # 存在的關係例子：RULE#R-007 → APPLIED_TO#VERSION#share-summary@v1。

  # 來源：設計 §8.2、§9、§20.B；釐清 D17、F29。
  @Missing
  Rule: 版本的 rules_applied 記錄本次套用的規則
    #TODO 原文未提供特定版本的完整 rules_applied 輸出與寫入結果。
    # rules_applied 只記錄本次寫作 prompt 實際注入的規則。
    # 原文複製帶來的效果不計本次套用。
    # rules_applied 是套用關係的權威。

  # 來源：設計 §10.1、§11.1、§12.1、§16 T3；釐清 F29。
  @Missing
  Rule: 後續 Release 重寫仍注入適用的教學規則
    #TODO 原文 R-007 應保留至 A v3，但其在寫作當下是否已 active 有時序衝突，
    # 沒有將 demo 敘事轉成通過 active-only 條件的成功範例。
    # 未改寫步驟沿用的規則不計入本版 rules_applied。
