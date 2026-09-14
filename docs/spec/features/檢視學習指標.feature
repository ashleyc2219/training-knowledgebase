# 來源：../draft/training-kb-design-doc.md §11.2、§12.1、§15、§16。
# Demo 數字是 seeded 展示目標，不是量測結果或正式服務保證。
Feature: 檢視學習指標
  檢視教學與規則成效時，由 Analytics 聚合版本評分、重開票、規則套用與 Bedrock 呼叫資料。

  # 來源：設計 §15。
  @Missing
  Rule: 平均評分以每個 TutorialVersion 的 rating 計算
    #TODO 原文只有 demo 平均 2.9 與 4.4，沒有可重算的原始評分集合。
    # 版本沒有任何有效評分時顯示尚無評分，內部值為空；規則驗證不使用此版本平均。
    # 跨版本比較時先算每版平均再等權平均，每個 TutorialVersion 權重相同。

  # 來源：設計 §15；釐清 F43。
  @Missing
  Rule: 負面 Feedback 數計入 rating 不超過 2 或 category 屬負面的回饋
    #TODO 原文沒有完整回饋集合；不把兩個條件各算一次後相加。
    # 所有已核定的問題類別都屬負面：找不到按鈕、缺少資訊。
    # 待分類不因 category 計入負面。rating <= 2 仍獨立計入。

  # 來源：設計 §15；釐清 D23、D24、D29。
  @Missing
  Rule: 同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例
    # 同題以 Tutorial.cluster_id／首版 gap 為準，不比 topic 文字。
    # 分母來自 TUTORIAL_VIEW；同一人比對 TUTORIAL_VIEW.user、Feedback.user 與 Ticket.author 的同一穩定使用者 ID。
    # 分母是發布後 14 天窗口內的可識別瀏覽者。
    # 分子只計瀏覽之後、且窗口結束前同群開票的使用者。
    # 沒有可識別瀏覽者時顯示 N/A 與樣本不足，不把零分母當成改善或惡化。
    #TODO 原文沒有可重算的瀏覽與開票集合。
    # 7 → 2 是重開票數，不能當成百分比或已驗證的重開票率。

  # 來源：釐清 D24。
  @Missing
  Rule: 同題重開票率的分母取自教學瀏覽事件
    # 分母為 TUTORIAL_VIEW 中對應該 TutorialVersion 的瀏覽事件。
    #TODO 原文沒有瀏覽事件集合。

  # 來源：釐清 D23。
  @Missing
  Rule: 看過教學又開票的同一人比對穩定使用者 ID
    # TUTORIAL_VIEW.user、Feedback.user 與 Ticket.author 使用同一穩定使用者 ID。
    #TODO 原文沒有跨來源身分配對範例。

  # 來源：設計 §11.2、§15。
  @Missing
  Rule: 規則效果比較套用與未套用版本的評分及同題重開票率差
    #TODO 原文未定義比較組與重開票率所需原始資料。
    # 跨版本平均評分：先算每版平均再等權平均。
    # 零分母的重開票率不得用於規則驗證。

  # 來源：設計 §15。
  @Missing
  Rule: 已學規則數依 RULE item 的 status 分別計數
    #TODO 原文沒有包含各種 status 的完整規則集合。

  # 來源：設計 §11.1、§15。
  @Specified
  Rule: 規則套用次數等於 applied_to 清單長度
    Example: R-007 的三個套用版本計為三次
      Given 規則 "R-007" 的 applied_to 為
        | version_id         |
        | prepare-meeting@v2 |
        | share-summary@v1   |
        | prepare-meeting@v3 |
      When 系統計算規則 "R-007" 的套用次數
      Then 規則 "R-007" 的套用次數為 3

  # 來源：設計 §15。
  @Missing
  Rule: 每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫
    #TODO 原文只有總數 8、3、2，沒有兩層的逐次紀錄。
    # 計算每次實際送出的呼叫嘗試，包含重試、每個 Map item 與 Rote 呼叫。

  # 來源：設計 §15、§15.1、§16。
  @Specified
  Rule: Demo 指標以 seeded data 展示
    # 由完整 seeded 回饋、瀏覽與 Ticket 資料計算；2.9、4.4、7、2 是資料必須能重現的目標。
    # 7 與 2 仍是重開票筆數，不是比例。
    Example: Demo 顯示來源列出的 v1 與 v2 目標資料
      Given Demo 使用下列 seeded 指標資料
        | metric        | v1  | v2  |
        | 平均評分      | 2.9 | 4.4 |
        | 負面回饋數    | 8   | 2   |
        | 同題重開票數  | 7   | 2   |
        | 過期步驟數    | 1   | 0   |
        | Bedrock呼叫數 | 8   | 2   |
      When 使用者檢視 Demo 指標
      Then 顯示的指標資料為
        | metric        | v1  | v2  |
        | 平均評分      | 2.9 | 4.4 |
        | 負面回饋數    | 8   | 2   |
        | 同題重開票數  | 7   | 2   |
        | 過期步驟數    | 1   | 0   |
        | Bedrock呼叫數 | 8   | 2   |

  # 來源：設計 §15；釐清 D24。
  @Missing
  Rule: Demo 對同題重開票率標明 proxy 與精確定義
    # Demo 必須標明這是 seeded 筆數，不是即時重開票率。
    #TODO 原文要求此揭露，但沒有畫面文字或率值範例。

  # 來源：設計 §16 T2。
  @Missing
  Rule: Demo 以同一批 Ticket 並排展示規則關閉與開啟產生的 Tutorial B
    #TODO 原文未提供那批 Ticket、兩份 Tutorial B 或規則開關的輸入介面。
    # 兩份都只是隔離的 Demo 產物，不寫入正式教學、回饋與規則效果統計。
