Feature: 展示學習指標
  系統計算 self-learning 指標：deflection rate、重放解決率、圖譜覆蓋。

  Rule: deflection rate 為 deflected 除以 deflected 加 escalated
    Example: 兩張 deflected 與兩張 escalated
      Given 系統已有以下 Ticket
        | id | status |
        | 1 | deflected |
        | 2 | deflected |
        | 3 | escalated |
        | 4 | escalated |
        | 5 | open |
      When 系統計算學習指標
      Then 學習指標為
        | metric | numerator | denominator | value |
        | deflection rate | 2 | 4 | 0.5 |

  Rule: 重放解決率為 Workflow.replay_count 總和除以 deflected 票數
    Example: replay_count 總和為 2 且 deflected 為 4
      Given 系統已有以下 UserProblem
        | id | topic |
        | 1 | cancel_order |
      And 系統已有以下 Workflow
        | id | user_problem_id | replay_count |
        | 1 | 1 | 2 |
      And 系統已有以下 Ticket
        | id | status |
        | 1 | deflected |
        | 2 | deflected |
        | 3 | deflected |
        | 4 | deflected |
      When 系統計算學習指標
      Then 學習指標為
        | metric | numerator | denominator | value |
        | 重放解決率 | 2 | 4 | 0.5 |

  Rule: 圖譜覆蓋為有 published Tutorial 的 UserProblem 數除以 UserProblem 總數
    Example: 兩個 UserProblem 其中一個有 published Tutorial
      Given 系統已有以下 UserProblem
        | id | topic |
        | 1 | cancel_order |
        | 2 | track_refund |
      And 系統已有以下 Tutorial
        | tutorial_id | user_problem_id | status |
        | 1 | 1 | published |
      When 系統計算學習指標
      Then 學習指標為
        | metric | numerator | denominator | value |
        | 圖譜覆蓋 | 1 | 2 | 0.5 |
