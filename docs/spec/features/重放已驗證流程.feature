Feature: 重放已驗證流程
  系統在自動回覆顧客時，將第一次成功攔截的流程捕捉為 Workflow，並在同類票重放。
  Then 中的 captured_at 等於 Given 的系統目前時間。

  Rule: 某 UserProblem 第一次 deflected 成功時新增 Workflow
    Example: 第一次攔截 cancel_order
      Given 系統目前時間為 "2026-09-11T12:00:00Z"
      And 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic | feature_id |
        | 1 | cancel_order | 1 |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | user_problem_id | path | status | current_version |
        | 1 | 1 | 1 | tutorials/cancel-order.md | published | v1 |
      And 系統已有以下 Ticket
        | id | content | category | customer_ref | user_problem_id | status |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | open |
      And 系統沒有任何 Workflow
      When 系統自動回覆顧客
      Then Workflow 資料為
        | id | user_problem_id | steps | captured_at | replay_count |
        | 1 | 1 | 匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket | 2026-09-11T12:00:00Z | 0 |

  Rule: 同 UserProblem 已有 Workflow 時再次 deflected 則 replay_count 加 1
    Example: 第二次攔截 cancel_order
      Given 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic | feature_id |
        | 1 | cancel_order | 1 |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | user_problem_id | path | status | current_version |
        | 1 | 1 | 1 | tutorials/cancel-order.md | published | v1 |
      And 系統已有以下 Ticket
        | id | content | category | customer_ref | user_problem_id | status |
        | 2 | I want to cancel order {{Order Number}} | ORDER | bob@example.com | 1 | open |
      And 系統已有以下 Workflow
        | id | user_problem_id | steps | captured_at | replay_count |
        | 1 | 1 | 匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket | 2026-09-11T10:05:00Z | 0 |
      When 系統自動回覆顧客
      Then Workflow 資料為
        | id | user_problem_id | steps | captured_at | replay_count |
        | 1 | 1 | 匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket | 2026-09-11T10:05:00Z | 1 |

  Rule: escalated 不建立 Workflow
    Example: 無 Tutorial 時不新增 Workflow
      Given 系統已有以下 UserProblem
        | id | topic |
        | 1 | cancel_order |
      And 系統沒有任何 Tutorial
      And 系統已有以下 Ticket
        | id | content | category | customer_ref | user_problem_id | status |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | open |
      And 系統沒有任何 Workflow
      When 系統自動回覆顧客
      Then Workflow 資料為
        | id | user_problem_id | steps | captured_at | replay_count |
