# 來源：../draft/training-kb-design-doc.md §3.2、§5.2、§9、§14、§17.3、§18、§20.C。
# 此檔保留原文已明列的共用執行限制；不把架構說明或 AWS 費用敘述改寫成新業務功能。
Feature: 執行教學流程
  Ticket、Release 或每日排程啟動對應的教學 pipeline，由固定流程呼叫所需工具。

  # 來源：釐清 F01。
  @Missing
  Rule: 缺少原始 Example 時可用明示合成且經確認的驗收資料
    #TODO 各 @Missing 規則仍待補例，本題只決定資料來源，不代替實際補例。
    # 允許新增明示為合成且經確認的驗收資料。
    # 不得把合成資料描述為原始觀測或實測結果。

  # 來源：設計 §5.2、§9、§14.2。
  @Missing
  Rule: 教學 pipeline 依 Step Functions 預定義節點執行
    #TODO 原文未提供三條流程的完整執行紀錄；一個 Choice 分三路與三個 state machine 都是原文明列方案。

  # 來源：設計 §3.2、§14.1、§14.2。
  @Missing
  Rule: Agent 的工具選擇自由度只用於接入層
    #TODO 原文沒有具體執行 trace；核心流程不新增 multi-agent 協作。

  # 來源：設計 §17.3。
  @Missing
  Rule: 每個 Bedrock 呼叫設定 max_tokens
    #TODO 原文沒有數值或設定範例，不自行指定 token 上限。

  # 來源：設計 §17.3。
  @Missing
  Rule: 每個 Bedrock 呼叫設定逾時
    #TODO 原文沒有逾時數值與逾時結果範例。

  # 來源：設計 §17.3、§20.C。
  @Missing
  Rule: 每個 Step Functions Task 設定 Retry
    #TODO 附錄只示範 ExtractChange 的 States.ALL、MaxAttempts = 2，
    # 其他 Task 沒有 Retry；不把這個局部數值擴成所有 Task 的預設。

  # 來源：設計 §17.3、§20.C。
  @Missing
  Rule: 每個 Step Functions Task 設定 Catch
    #TODO 附錄骨架未列 Catch；錯誤種類與 Retry 次數未定義。
    # Task 重試耗盡並進入 Catch 後，整次執行以失敗結束，不發布新版本。
    # 來源可依既定重試契約重新執行。不另建可恢復待處理執行或重新處理入口。

  # 來源：設計 §18。
  @Missing
  Rule: LLM 輸出遵循指定 JSON schema
    #TODO 原文未列各判斷節點的完整輸出 schema 與不合法輸出案例。
    # 通過 schema 但違反業務規則時，以業務驗證拒絕，進入有限重試與最終失敗路徑。
    # 不寫入、不發布不合規內容。不另建待審狀態。

  # 來源：設計 §18。
  @Missing
  Rule: 判斷節點使用低 temperature
    #TODO 原文未量化低 temperature，不把描述替換為任意數值。

  # 來源：設計 §8.4；ERD §1。
  @Missing
  Rule: Step Functions 的 ASL 版本快照存於 stepfunctions/<pipeline>/v<n>.json
    #TODO 原文未定義保存時機、pipeline 的命名與快照範例；不與教學版本號混用。
