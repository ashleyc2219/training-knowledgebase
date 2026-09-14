# 來源：../draft/training-kb-design-doc.md §4、§9、§9.1、§10、§16。
# 來源：../draft/training-kb-erd.md §6。
Feature: 分析工單
  新的正規化 Ticket 觸發 Ticket Analysis，從重複問題決定 CREATE 或 KEEP。

  # 來源：設計 §9.1；ERD §6。
  @Missing
  Rule: 每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding
    #TODO 原文沒有 Ticket 文字與完整向量結果，無法產出數值範例。
    # 以 Ticket.embedding 為權威資料，不持久化 embedding_ref。
    # embedding 不是接入必填，由本分析流程補入。

  # 來源：設計 §9.1；釐清 F10。
  @Missing
  Rule: demo 分群以 cosine 至少 0.85 為同群門檻
    #TODO 原文未提供相似度位於門檻兩側的 Ticket 配對；0.85 是可調 demo 值。
    # 比較 Ticket 與每個群的中心向量；達 0.85 的群中選相似度最高者。
    # 沒有達標的群則開新群。同分排序未指定。

  # 來源：設計 §9.1；釐清 F11。
  @Missing
  Rule: 同群在 14 天內至少有 5 筆 Ticket 才算 recurring
    #TODO 原文沒有含時間戳的 4 筆與 5 筆工單範例。
    # 窗口以每日 UTC 日界線計算當日及前 13 個日期。
    # Ticket.ts 先換成 UTC 日期，該日內事件歸同一日。

  # 來源：設計 §9.1。
  @Missing
  Rule: 只有達 recurring 門檻的群才交給模型命名 Knowledge Gap
    #TODO 原文未提供未達與已達門檻的群及 name_gap 呼叫紀錄。

  # 來源：設計 §9.1；釐清 F13。
  @Missing
  Rule: Knowledge Gap 的命名結果包含對應 Feature
    #TODO 原文未提供同群 tickets、gap 名稱與 Feature 的完整配對。
    # 一張 Ticket 對應零或一個 Feature。
    # 對不到既有 Feature 時保留待釐清 gap；Ticket Analysis 不新建 Feature。

  # 來源：釐清 D04；ERD §2。
  @Missing
  Rule: 一張 Ticket 對應零或一個 Feature
    #TODO 附錄 Ticket 的 feature_ids 為空清單，沒有對到一個 Feature 的完整工單範例。

  # 來源：設計 §9.1、§10；釐清 F12。
  @Missing
  Rule: 對應 Feature 已有教學時動作為 KEEP
    #TODO 原文未提供既有教學與新 Ticket 的具體範例。
    # 已有教學：status=active 的 Tutorial，即使尚無已發布版本（published_at 空／尚待首次發布）也算。
    # retired 不算已有教學。

  # 來源：設計 §9.1。
  @Missing
  Rule: KEEP 只記錄 log 而不寫入教學內容
    #TODO 原文未提供 KEEP 前後的教學狀態或 log 格式。

  # 來源：設計 §4、§9、§9.1、§16 T0；釐清 F13、F12。
  @Missing
  Rule: 已識別且尚無現成教學的 Knowledge Gap 建立新的 Tutorial
    #TODO T0 提供 20 則 seeded tickets → Tutorial A v1，
    # 但缺少工單內容、時間戳、群組與 Feature；不補成可直接執行的端到端範例。
    # 取得有效 Feature 對應前不建立 Tutorial。
    # 對應 Feature 已有 status=active 的 Tutorial 時不建立新 Tutorial，即使該篇尚待首次發布。
    # retired 不算已有教學，不阻止 CREATE。

  # 來源：設計 §9、§9.1。
  @Missing
  Rule: Ticket Analysis 是唯一建立新 Tutorial 身分的 pipeline
    #TODO 原文沒有以同一輸入對三條 pipeline 的建立紀錄；不自行新增拒絕情境。

  # 來源：設計 §9.1。
  @Missing
  Rule: 新教學的完整內容包含 Title、Problem、Prerequisites、Steps 與 Expected Outcome
    #TODO 原文列出結構，沒有一篇包含五個區塊的完整教學範例。

  # 來源：設計 §9.1。
  @Missing
  Rule: 產生新教學時同時輸出每步提到的 Feature
    #TODO 原文只有單一步驟與 Feature 邊，沒有完整新教學的抽取結果。

  # 來源：釐清 D05；ERD §2。
  @Missing
  Rule: 新教學的每個步驟恰好引用一個 Feature
    #TODO 原文只有單一步驟與一個 Feature 邊；沒有零個或多個 Feature 的步驟範例。
    # 沒有 Feature 或引用多個 Feature 時須先拆解步驟或驗證失敗。

  # 來源：設計 §9.1；ERD §2 的 reason 範例；釐清 D29。
  @Missing
  Rule: 新教學第一版的 reason 使用 gap 加上來源 cluster_id
    #TODO ERD 提供 gap:c12 字串，但沒有 c12 的 Ticket 群與新版本配對。
    # 格式：gap:<cluster_id>。
    # 此值同時寫入 Tutorial.cluster_id，作為同題固定對應。
    # 後續版本 reason 改變不改此對應；後續分群須保留可追溯到此 cluster_id。
