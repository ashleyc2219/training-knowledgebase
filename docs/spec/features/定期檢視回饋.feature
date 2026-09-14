# 來源：../draft/training-kb-design-doc.md §6、§9.3、§11.3、§12.1、§16。
Feature: 定期檢視回饋
  EventBridge 每日觸發 Periodic Feedback Review，依累積回饋選出弱教學並 REFINE。

  # 來源：設計 §5.2、§6；釐清 F22。
  @Missing
  Rule: Periodic Feedback Review 每日執行
    #TODO 原文沒有排程的時間、時區或觸發紀錄範例。
    # 每日只檢視 current_version，且該版 published_at 必須非空。
    # 以該版截至本次的全部有效回饋計算平均、筆數與類別。
    # 不掃舊版，也不做「上次檢視之後」的浮水印切分。

  # 來源：設計 §9.3；釐清 F20、F22。
  @Missing
  Rule: 弱教學的版本平均評分必須小於 3.5
    #TODO 原文未提供完整評分集合，不能把 demo 平均 2.9 當成門檻邊界案例。
    # 平均以該 current_version 的全部有效回饋計算。
    # 此條與樣本數及 recurring category 兩條規則同時成立才進入診斷。
    # Demo 隔離門檻仍須平均 < 3.5。

  # 來源：設計 §9.3；對照 §11.3、§12.1、§16 T1；釐清 F20、F22。
  @Missing
  Rule: 弱教學的版本回饋樣本數必須至少為 10
    #TODO 原文沒有正式 n = 10 的完整回饋集合；demo 的 8 則不可當成正式門檻已滿足。
    # 正式弱教學樣本門檻維持 n >= 10。
    # Demo 另用明示隔離的 n >= 8，不假裝已達正式門檻。
    # 平均仍須 < 3.5。

  # 來源：設計 §9.3；釐清 F21。
  @Missing
  Rule: 弱教學必須具有 recurring Feedback Category
    #TODO 原文沒有 4 與 5 筆的邊界範例。
    # recurring 指同一 Feedback Category 至少 5 筆，與提出 candidate 的同類門檻相同。

  # 來源：設計 §9.3、§11.3、§12.1。
  @Missing
  Rule: 診斷結果包含需要改寫的步驟編號與原因
    #TODO 原文指出 A v1 的 step 3 與找不到按鈕，但缺少 8 則完整留言與診斷原因資料。

  # 來源：釐清 F24。
  @Missing
  Rule: 診斷找不到有效步驟時不建立新版
    #TODO 原文沒有空命中、越界步驟編號或只談整體主題的診斷結果。
    # 記錄「無可改步驟」；本次不建立 TutorialVersion。
    # 既有回饋保留，供後續分析或提出規則。不整篇重寫。

  # 來源：設計 §9.3、§10；釐清 F23。
  @Missing
  Rule: REFINE 只重寫診斷命中的步驟
    #TODO A v1 → A v2 的 step 3 敘事與 n >= 10 的資格衝突，未轉成無條件成功範例。
    # REFINE 完成後必須記錄已處理的有效證據集合。
    # 沒有新的有效證據時，同一批回饋不可再次觸發 REFINE。
    # 已處理證據的儲存形狀未指定，不假設新欄位或新實體。

  # 來源：設計 §9.3；釐清 D28。
  @Missing
  Rule: REFINE 的下一版 reason 記錄回饋數與類別
    # 格式：feedback:<n> 則 <category>，同時保存數量與類別。
    # gap:<cluster_id> 與 release:<id> 格式不變。
    #TODO 原文沒有完整 REFINE 輸入輸出與 reason 字串配對。

  # 來源：設計 §8.5、§9.3、§11.2；ERD §5；釐清 F26。
  @Missing
  Rule: Feedback Review 是唯一提出 Authoring Rule 的 pipeline
    # 提出 candidate 不必先通過弱教學門檻。
    # Feedback Review 另外掃描同一版本同類至少 5 筆的證據；
    # 平均評分或總筆數未達 REFINE 門檻也可提出。
    #TODO 原文沒有三條 pipeline 的規則寫入紀錄；提出動作的局部範例見提出教學規則.feature。
