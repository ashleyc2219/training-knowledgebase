Feature: 自動回覆顧客
  系統對 status 為 open 的 Ticket 嘗試自動回覆教學連結。

  Rule: UserProblem 已有 published Tutorial 時票單為 deflected
    Example: cancel_order 已有 published Tutorial
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
        | id | content | category | customer_ref | user_problem_id | status | deflected_tutorial_id | deflected_tutorial_version |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | open |  |  |
      When 系統自動回覆顧客
      Then Ticket 資料為
        | id | content | category | customer_ref | user_problem_id | status | deflected_tutorial_id | deflected_tutorial_version |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | deflected | 1 | v1 |

  Rule: 沒有 published Tutorial 時票單為 escalated
    Example: UserProblem 尚無 Tutorial
      Given 系統已有以下 UserProblem
        | id | topic |
        | 1 | cancel_order |
      And 系統沒有任何 Tutorial
      And 系統已有以下 Ticket
        | id | content | category | customer_ref | user_problem_id | status | deflected_tutorial_id | deflected_tutorial_version |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | open |  |  |
      When 系統自動回覆顧客
      Then Ticket 資料為
        | id | content | category | customer_ref | user_problem_id | status | deflected_tutorial_id | deflected_tutorial_version |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | escalated |  |  |

  Rule: user_problem_id 為空的票單為 escalated
    Example: 無法對應 UserProblem 的票單轉真人
      Given 系統已有以下 Ticket
        | id | content                          | category | customer_ref      | user_problem_id | status | deflected_tutorial_id | deflected_tutorial_version |
        | 1  | Something is wrong with my thing |          | alice@example.com |                 | open   |                       |                            |
      When 系統自動回覆顧客
      Then Ticket 資料為
        | id | content                          | category | customer_ref      | user_problem_id | status    | deflected_tutorial_id | deflected_tutorial_version |
        | 1  | Something is wrong with my thing |          | alice@example.com |                 | escalated |                       |                            |

  Rule: Tutorial 為 retired 時視同沒有 Tutorial
    Example: retired 的 cancel-order Tutorial 使票單 escalated
      Given 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic | feature_id |
        | 1 | cancel_order | 1 |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | user_problem_id | path | status | current_version | is_obsolete | last_action |
        | 1 | 1 | 1 | tutorials/cancel-order.md | retired | v1 | true | RETIRE |
      And 系統已有以下 Ticket
        | id | content | category | customer_ref | user_problem_id | status | deflected_tutorial_id | deflected_tutorial_version |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | open |  |  |
      When 系統自動回覆顧客
      Then Ticket 資料為
        | id | content | category | customer_ref | user_problem_id | status | deflected_tutorial_id | deflected_tutorial_version |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | escalated |  |  |

  Rule: 同一顧客同一 UserProblem 在 deflected 後再開票則新票為 escalated
    Example: alice 對 cancel_order 再開票
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
        | id | content | category | customer_ref | user_problem_id | status | deflected_tutorial_id | deflected_tutorial_version | reopened_from_ticket_id |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | deflected | 1 | v1 |  |
        | 2 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | open |  |  |  |
      When 系統自動回覆顧客
      Then Ticket 資料為
        | id | content | category | customer_ref | user_problem_id | status | deflected_tutorial_id | deflected_tutorial_version | reopened_from_ticket_id |
        | 1 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | deflected | 1 | v1 |  |
        | 2 | I want to cancel order {{Order Number}} | ORDER | alice@example.com | 1 | escalated |  |  | 1 |
