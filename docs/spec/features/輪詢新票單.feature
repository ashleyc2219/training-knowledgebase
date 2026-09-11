Feature: 輪詢新票單
  系統輪詢新票單，只處理 created_at 大於上次檢查時間且 status 為 open 的票。
  處理後每張被處理的票 status 為 deflected 或 escalated；自動回覆與升級細節見自動回覆顧客。
  Demo 現場餵入模擬即時票單與 hotdata 輪詢為同一功能，僅資料來源不同。

  Rule: 只處理 created_at 大於上次檢查時間且 status 為 open 的票
    Example: 過期票、剛好等於上次檢查時間的票與非 open 票維持原狀態
      Given 上次檢查時間為 "2026-09-11T10:00:00Z"
      And 系統沒有任何 Tutorial
      And 系統已有以下 UserProblem
        | id | topic |
        | 1 | cancel_order |
        | 2 | track_refund |
      And 系統已有以下 Ticket
        | id | content | category | customer_ref | user_problem_id | status | created_at |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | open | 2026-09-11T09:00:00Z |
        | 2 | I want to cancel order {{Order Number}} | ORDER | bob@example.com | 1 | open | 2026-09-11T10:00:00Z |
        | 3 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | open | 2026-09-11T10:30:00Z |
        | 4 | I want to track my refund | REFUND | bob@example.com | 2 | resolved | 2026-09-11T10:30:00Z |
      When 系統輪詢新票單
      Then Ticket 資料為
        | id | content | category | customer_ref | user_problem_id | status | created_at |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | open | 2026-09-11T09:00:00Z |
        | 2 | I want to cancel order {{Order Number}} | ORDER | bob@example.com | 1 | open | 2026-09-11T10:00:00Z |
        | 3 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | escalated | 2026-09-11T10:30:00Z |
        | 4 | I want to track my refund | REFUND | bob@example.com | 2 | resolved | 2026-09-11T10:30:00Z |
