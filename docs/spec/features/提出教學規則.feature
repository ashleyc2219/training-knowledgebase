# 來源：../draft/training-kb-design-doc.md §9.3、§11.1–§11.4、§20.B。
# 此 Feature 的交互點是 Feedback Review 呼叫 propose_rule；不表示 8 筆可通過弱教學的 n >= 10 門檻。
Feature: 提出教學規則
  Feedback Review 呼叫 propose_rule，將同類回饋歸納為帶證據與範圍的 Authoring Rule；MVP 固定單一專案。

  # 來源：設計 §9.3、§11.1、§11.2、§20.B；釐清 F25、F26。
  @Partial
  Rule: 同類 Feedback 至少 5 筆才可提出 candidate 規則
    #TODO 原文提供 8 筆證據，沒有 4 與 5 筆的邊界範例。
    # 五筆同類回饋只算同一教學版本，對齊 derived_from 恰好一版。
    # 跨版本 3+2 未達標。規則完成後才可套用到其他教學。
    # 提出 candidate 不必先通過弱教學門檻。
    # 平均評分或總筆數未達 REFINE 門檻也可提出。

    Example: 八筆找不到按鈕的證據產生 R-007 candidate
      Given 規則 R-007 的回饋證據如下
        | category   | feedback_ids                       |
        | 找不到按鈕 | f_12,f_15,f_19,f_23,f_27,f_31,f_34,f_40 |
      When Feedback Review 提出規則 "R-007"
      Then 規則 "R-007" 的 status 為 "candidate"

  # 來源：設計 §11.1；釐清 D15。
  @Partial
  Rule: Authoring Rule 保留可追溯的 Feedback 證據
    # evidence 只存 Feedback ID 清單；category 由被引用的回饋取得，不另存提出時類別快照。
    #TODO 原文提供 8 個回饋識別碼集合，沒有缺 ID 或非清單形狀的提出範例。

    Example: R-007 保留八個回饋識別碼
      Given 規則 R-007 的回饋證據如下
        | category   | feedback_ids                       |
        | 找不到按鈕 | f_12,f_15,f_19,f_23,f_27,f_31,f_34,f_40 |
      When Feedback Review 提出規則 "R-007"
      Then 規則 "R-007" 的回饋證據集合為
        | feedback_id |
        | f_12        |
        | f_15        |
        | f_19        |
        | f_23        |
        | f_27        |
        | f_31        |
        | f_34        |
        | f_40        |

  # 來源：設計 §11.1；釐清 D16。
  @Specified
  Rule: Authoring Rule 記錄 applies_when 適用範圍
    # MVP 僅支援單一條件：step.type 等於 click_ui、input 或 read。
    # 不支援 AND/OR 組合；LLM 不產生任意運算式。
    Example: R-007 的範圍是 click_ui 步驟
      Given 規則 "R-007" 從 "找不到按鈕" 的回饋歸納點擊 UI 的教學要求
      When Feedback Review 提出規則 "R-007"
      Then 規則 "R-007" 的 applies_when 為 "step.type == click_ui"

  # 來源：設計 §11.1；釐清 D18。
  @Specified
  Rule: Authoring Rule 記錄 derived_from 來源版本
    # derived_from 恰好一個版本；跨專案共享的是完成後的規則，不把多版寫進此欄。
    Example: R-007 源自準備會議的第一版
      Given 規則 "R-007" 的八筆證據來自 "prepare-meeting@v1"
      When Feedback Review 提出規則 "R-007"
      Then 規則 "R-007" 的 derived_from 為 "prepare-meeting@v1"

  # 來源：設計 §11.1。
  @Specified
  Rule: Authoring Rule 記錄歸納出的寫作要求
    Example: R-007 記錄點 UI 時需要的資訊
      Given 規則 "R-007" 從 "找不到按鈕" 的八筆回饋歸納點擊 UI 的教學要求
      When Feedback Review 提出規則 "R-007"
      Then 規則 "R-007" 的 rule 為
        """
        步驟要求點擊 UI 元件時，必須寫出：在哪個頁面、按鈕位置、點完會看到什麼
        """

  # 來源：設計 §11.4；釐清 D01、D27。
  @Missing
  Rule: MVP 的教學與產品功能識別碼在單一專案範圍內唯一
    # 跨專案共享只接受明示合成種子證據；真實專案證據暫不進共享庫。
    #TODO 尚未提供具名的合成種子規則與套用範例。
