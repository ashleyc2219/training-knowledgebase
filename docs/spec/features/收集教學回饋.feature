# 來源：../draft/training-kb-design-doc.md §6、§9.3、§20.A。
# 來源：../draft/training-kb-erd.md §2、§4、§6。
Feature: 收集教學回饋
  使用者透過 feedback widget 提交指定 TutorialVersion 的評分、類別與留言。

  # 來源：設計 §20.A；ERD §2；釐清 D25。
  @Missing
  Rule: Feedback 的 tutorial_version 必須存在於圖譜
    # 版本可未發布（published_at 空）但仍可存在於圖譜。
    #TODO 原文有版本識別碼範例，但沒有不存在版本的回饋請求。
    # 錯誤案例補齊時使用 Then 操作失敗，不自行指定錯誤訊息或 HTTP 狀態碼。
    # 不合法回饋立即拒絕並指出不合法欄位，允許提交者修正。
    # 不建立 FEEDBACK，也不回傳成功回執。

  # 來源：釐清 F39。
  @Missing
  Rule: 已退役教學的既有版本拒絕新回饋
    #TODO 原文沒有對 retired Tutorial 既有版本提交回饋的請求。
    # 已退役教學的既有版本拒絕新回饋；既有回饋保留供歷史查詢。
    # 錯誤案例使用 Then 操作失敗。

  # 來源：ERD §2。
  @Missing
  Rule: Feedback 的 rating 只能為 1 到 5 的整數
    #TODO 原文只有 rating = 2 的省略版物件，沒有 1、5、區間外或非整數的提交範例。

  # 來源：設計 §9.3。
  @Missing
  Rule: 使用者勾選的 Feedback Category 優先於模型分類
    #TODO 原文沒有勾選類別與模型分類不同的具體輸入。

  # 來源：釐清 D13；設計 §9.3。
  @Missing
  Rule: Feedback Category 必須屬於核定類別表或待分類
    #TODO 原文沒有未知類別寫入待分類的提交範例。
    # 初始核定類別：找不到按鈕、缺少資訊。未知值寫入待分類，不自動新增核定類別。

  # 來源：設計 §9.3。
  @Missing
  Rule: 需要分類的自由留言在接入時計算一次 Feedback Category
    #TODO 原文沒有完整留言到 category 的配對。
    # 只有評分、類別與留言皆空仍有效；只參與評分，不送模型分類。
    # 非空留言且未勾選類別時才計算一次 Feedback Category。

  # 來源：設計 §6、§20.A；ERD §4；釐清 D03。
  @Missing
  Rule: 回饋關聯到提交時指定的 TutorialVersion
    #TODO 原文提供 prepare-meeting@v2 與不同版本的邊例子，沒有完整提交與寫入配對。
    # 邏輯欄位使用裸 version_id；不把 Feedback 改綁至之後的 current_version。

  # 來源：設計 §6、§9.3。
  @Missing
  Rule: 收到單筆低分 Feedback 時不立即修改 Tutorial
    #TODO 原文明示等待每日 Review，未提供單筆低分提交前後的版本資料。

  # 來源：釐清 D23。
  @Missing
  Rule: Feedback 接入時必須提供穩定使用者 ID
    # 不允許沒有穩定使用者識別碼；缺 user 則操作失敗。
    # user 接入必填，與 Ticket.author、TUTORIAL_VIEW.user 為同一穩定使用者 ID；不以顯示名稱推定同一人。
    #TODO 原文 Feedback 物件有 user 欄位，沒有缺 user 的提交範例。

  # 來源：釐清 D14。
  @Missing
  Rule: 同一使用者對同一版本的每次新提交都計一筆
    #TODO 原文沒有同一人連續提交兩筆不同 id 的配對。
    # 每個新的 Feedback.id 計一筆有效回饋。
    # 同一提交重送只處理一次，不另計樣本。
