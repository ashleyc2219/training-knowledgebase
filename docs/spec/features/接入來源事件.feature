# 來源：../draft/training-kb-design-doc.md §5–§7、§8.5、§14、§17.3、§18、§20.A。
# 來源：../draft/training-kb-erd.md §5、§6。
# 狀態以規則標籤記錄；@Missing 的規則缺少原文範例，以 #TODO 保留。
# DataTable 欄位是驗收資料的投影，不表示增加持久化欄位或公開 API。
Feature: 接入來源事件
  GitHub、Discord、support email、PR、changelog 或 feedback widget 送入事件時，
  接入層選擇 adapter 並正規化為 Ticket、Release 或 Feedback。
  MVP 只開放一個已驗簽的 GitHub webhook；Discord、email、changelog 與 Feedback 以手動上傳接入，
  不開放未驗證公開入口。

  # 來源：設計 §17.3；釐清 F08。
  @Missing
  Rule: GitHub webhook 必須以 X-Hub-Signature-256 驗簽
    #TODO 原文未提供有效與無效簽名的請求範例；不補 HTTP 狀態碼。
    # MVP 只開放這一個 GitHub webhook。Discord、email、changelog 與 Feedback 以手動上傳接入。

  # 來源：設計 §17.3。
  @Missing
  Rule: 沒有簽名的 GitHub webhook 請求被拒絕
    #TODO 原文未提供無簽名請求範例；錯誤案例補齊時使用 Then 操作失敗。

  # 來源：設計 §7.2；釐清 F02。
  @Missing
  Rule: 來源簽名使用來源網域、有意義的 header 名稱與穩定 payload key 計算
    #TODO 原文只有函式，沒有輸入事件與預期簽名配對。
    # 每種來源與事件類型各有固定必備 top-level key。
    # MVP GitHub 清單為原文例子：action、issue、repository、sender。
    # 其他來源等手動上傳後再定，不預先發明 Discord 或 email 清單。
    # 計算式：sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]。
    # shape.headers 為 x-github / x-discord / x-zendesk 前綴的 header 名稱，轉小寫後排序。
    # shape.keys 為該來源／事件類型固定必備的 payload 最上層 key，排序；domain 缺省為空字串。

  # 來源：設計 §7.2。
  @Missing
  Rule: ID、時間戳與標題等事件值不參與來源簽名
    #TODO 原文未提供只有值不同的兩則事件及其簽名，不自行組造事件。

  # 來源：設計 §7.3。
  @Missing
  Rule: 第一層以 PROC 主鍵精確比對來源簽名
    #TODO §7.4 只有 PROC item，沒有可對照的完整事件。

  # 來源：設計 §6、§7.3。
  @Missing
  Rule: 第一層只允許 status 為 active 的流程重放
    #TODO 原文未提供相同事件對 active 與 retired 流程的對照範例。

  # 來源：設計 §6、§7.3。
  @Missing
  Rule: 第一層流程的 success_count 必須至少為 3
    #TODO 原文只有 success_count = 4 的已存流程，沒有 2 與 3 次的事件範例。

  # 來源：釐清 F05；設計 §7.6。
  @Missing
  Rule: 新流程每次完整成功才將 success_count 加 1
    #TODO 原文沒有首次成功與同簽名再次走完的計數紀錄。
    # 首次成功記 1。同簽名再由 Agent 走完同一可泛化序列，每次完整成功才加 1。
    # 達 3 才可被第一層或第二層重放。

  # 來源：設計 §7.3；ERD §6；釐清 D19、F03。
  @Missing
  Rule: 第一層未命中才在同寄件者的流程中以 Jaccard 至少 0.8 比對欄位
    #TODO 原文未提供兩組完整 key 集合。
    # 同寄件者範圍是來源網域加 adapter 類型；不新增獨立儲存欄位。
    # 第二層同樣必須 status 為 active 且 success_count >= 3。
    # 多個合格流程時選 Jaccard 最高者；同分選 last_used 最近的成功者；
    # 再同分則依流程穩定識別碼升序取第一個。
    # last_used 在成功重放或成功寫回時更新。

  # 來源：設計 §7.3、§7.5、§12.1 第 1 輪。
  @Missing
  Rule: 前兩層皆未命中時才由 Agent 選擇 adapter tool
    #TODO 原文只有首次 GitHub webhook 的敘述，缺少事件與 adapter 選擇結果的完整配對。

  # 來源：設計 §6、§7.1、§7.7。
  @Missing
  Rule: 接入層命中已驗證流程的重放路徑不呼叫 LLM
    #TODO 原文未提供可重放的完整事件；零次僅指接入層，不是整條 pipeline 的 Bedrock 呼叫數。

  # 來源：設計 §7.4、§7.5。
  @Missing
  Rule: 記錄的 tool 參數以 JSONPath 指向事件欄位或前一步輸出
    #TODO 原文有 parse_github_issue → normalize_ticket → validate 的 PROC 範例，
    # 但沒有對應 agent.messages 與實際輸入，不能驗收具體值轉 JSONPath 的結果。

  # 來源：設計 §7.6；釐清 F06。
  @Missing
  Rule: 寫回新流程前最後一個 tool 必須是通過的 validate
    #TODO 原文沒有最後一個 tool 或驗證結果不同的執行紀錄範例。
    # 此條適用 Ticket 與 Release 的 PROVEN_WORKFLOW 學習路徑。
    # Feedback 不納入 PROVEN_WORKFLOW 學習。

  # 來源：設計 §7.6；釐清 F06。
  @Missing
  Rule: 寫回新流程前 Step Functions 必須成功啟動
    #TODO 原文沒有啟動成功與失敗的執行範例。
    # 此條適用 Ticket 與 Release。Feedback 不啟動 Step Functions。

  # 來源：設計 §6、§7.6；釐清 D20。
  @Missing
  Rule: 每次重放失敗時 fail_count 增加 1
    #TODO 原文未提供失敗前後的流程紀錄。
    # fail_count 是連續失敗次數。

  # 來源：釐清 D20；設計 §6、§7.6。
  @Missing
  Rule: 重放成功時 fail_count 歸零
    #TODO 原文沒有失敗後成功重放的流程紀錄。

  # 來源：設計 §6、§7.6、§18。
  @Missing
  Rule: 重放或正規化驗證失敗時當次回退到 Agent
    #TODO 原文未提供配錯來源與回退結果的具體事件範例。

  # 來源：釐清 F07。
  @Missing
  Rule: Agent 最終仍無法產出合法物件時回傳失敗
    #TODO 原文沒有 Agent 耗盡後的來源可見結果。
    # 回傳失敗，由來源依既定重送方式重試。
    # 不得寫入合法 Ticket、Release、Feedback，也不得寫入成功的 PROVEN_WORKFLOW。

  # 來源：設計 §6、§7.6；釐清 D20。
  @Missing
  Rule: 同一流程連續三次重放失敗後 status 變為 retired
    #TODO 原文未提供連續失敗紀錄或中途成功的範例。
    # 成功重放會把 fail_count 歸零，不會把交錯失敗當成連續三次。

  # 來源：設計 §7.6；釐清 F03。
  @Missing
  Rule: 已退役流程在下次接入時視同未命中
    #TODO 原文未提供下次事件。
    # 第一層與第二層皆只重放 active 且 success_count >= 3 的流程。
    # 已退役簽名保持停用，不覆寫舊序列。
    # 重新學到的流程須由人工核定新序列後，再明確重置該流程。

  # 來源：設計 §20.A；釐清 D09、D10。
  @Missing
  Rule: 正規化物件必須具有 schema 的必填欄位
    #TODO 原文未提供缺欄位的輸入範例。
    # Ticket 必填 id、source、text、author、ts、project_id。
    # author 與 Feedback.user、TUTORIAL_VIEW.user 為同一穩定使用者 ID。
    # Release 必填 id、source、feature、kind、evidence、ts；renamed 另必填 old_name 與 new_name。

  # 來源：釐清 D09；設計 §20.A。
  @Missing
  Rule: Ticket 接入時 id、source、text、author、ts 與 project_id 必填
    #TODO 原文沒有缺作者或尚未計算 embedding 的完整接入範例。
    # author 為穩定使用者 ID，與 Feedback.user、TUTORIAL_VIEW.user 相同；此項覆寫 D09 的 author 可空。
    # embedding 與 cluster_id 由分析流程補入。

  # 來源：釐清 D10；設計 §20.A。
  @Missing
  Rule: Release 接入時即完成功能與種類解析
    #TODO 原文沒有 changed 或 removed 名稱欄位為空的完整接入範例。
    # renamed 必填 old_name 與 new_name；其他 kind 的名稱欄位可空。

  # 來源：釐清 D02；設計 §20.A。
  @Missing
  Rule: 正規化物件的 id 直接使用已全域唯一的上游識別碼
    #TODO 原文有 t_881、f_12 等例子，沒有來源碰撞或重送時的完整接入配對。
    # Ticket 使用 t_ 前綴、Release 使用 r_ 前綴、Feedback 使用 f_ 前綴。

  # 來源：設計 §20.A；ERD §2。
  @Missing
  Rule: 正規化物件的枚舉欄位必須使用合法值
    #TODO 原文列 Ticket.source、Release.source、Release.kind 等枚舉，沒有不合法值範例。
    # Feedback Category 核定值為找不到按鈕、缺少資訊；未知值寫入待分類。

  # 來源：設計 §6。
  @Missing
  Rule: 正規化成功的 Ticket 觸發 Ticket Analysis
    #TODO 附錄 Ticket 含省略值，未提供可用的完整接入事件。

  # 來源：設計 §6。
  @Missing
  Rule: 正規化成功的 Release 觸發 Release Note Update
    #TODO 原文有 PR #42 的改名內容，沒有完整 webhook 到正規化 Release 的配對。

  # 來源：設計 §6；釐清 F06。
  @Missing
  Rule: 正規化成功的 Feedback 寫入 FEEDBACK item
    #TODO 原文 Feedback 物件含省略值，沒有完整接入事件與寫入結果的配對。
    # Feedback 不納入 PROVEN_WORKFLOW 學習，只用固定保存路徑。
    # validate 通過並寫入 FEEDBACK 即接入成功，不啟動 Step Functions。
    # Feedback.user 接入必填，與 Ticket.author、TUTORIAL_VIEW.user 為同一穩定使用者 ID。

  # 來源：設計 §6；釐清 F06。
  @Missing
  Rule: 單筆 Feedback 接入不立即觸發教學改版
    #TODO 原文只描述等待每日 Review，沒有單筆接入前後的版本範例。

  # 來源：釐清 F09。
  @Missing
  Rule: 同一正規化事件重送時只處理一次
    #TODO 原文沒有重送事件與既有結果或未完成執行的配對。
    # 重送回傳既有結果，或接續尚未完成的執行。
    # 不因重送再建立教學版本，也不再計一筆 Feedback。

  # 來源：設計 §7.5、§8.5；ERD §5。
  @Missing
  Rule: 只有 Rote 接入層讀寫 PROVEN_WORKFLOW
    #TODO 原文未提供各 pipeline 執行時的 PROC 存取紀錄。
