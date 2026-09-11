Feature: 建構知識圖譜
  系統匯入歷史票單（Bitext 資料集列），建立 Ticket、UserProblem 與 Feature，供後續分析與自動回覆使用。
  匯入列的欄位：content（instruction）、category、intent、response、customer_ref、feature_name、created_at。
  Demo 資料安排不列規則：不納入 Slack QA；三到五類每類兩到三筆與扣住集、欄位不足時用 LLM 補寫皆不是可驗證規則。

  Rule: 匯入歷史票單後 Ticket 的 status 為 resolved 且 resolution_steps 與 created_at 有值
    Example: 匯入一張 cancel_order 歷史票
      When 系統匯入歷史票單
        | content                                 | category | intent       | response                                                | customer_ref      | feature_name | created_at           |
        | I want to cancel order {{Order Number}} | ORDER    | cancel_order | Go to Orders, select the order, and click Cancel Order. | alice@example.com | Cancel Order | 2026-09-01T10:00:00Z |
      Then Ticket 資料為
        | id | content                                 | category | customer_ref      | feature_id | user_problem_id | status   | resolution_steps                                        | created_at           |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | alice@example.com | 1          | 1               | resolved | Go to Orders, select the order, and click Cancel Order. | 2026-09-01T10:00:00Z |

  Rule: 匯入後 UserProblem.topic 等於 intent
    Example: cancel_order 票建立 topic 為 cancel_order 的 UserProblem
      When 系統匯入歷史票單
        | content                                 | category | intent       | response                                                | customer_ref      | feature_name | created_at           |
        | I want to cancel order {{Order Number}} | ORDER    | cancel_order | Go to Orders, select the order, and click Cancel Order. | alice@example.com | Cancel Order | 2026-09-01T10:00:00Z |
      Then UserProblem 資料為
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |

  Rule: 同一 topic 重用同一列 UserProblem
    Example: 兩張 cancel_order 票共用同一列 UserProblem
      When 系統匯入歷史票單
        | content                                 | category | intent       | response                                                | customer_ref      | feature_name | created_at           |
        | I want to cancel order {{Order Number}} | ORDER    | cancel_order | Go to Orders, select the order, and click Cancel Order. | alice@example.com | Cancel Order | 2026-09-01T10:00:00Z |
        | How can I cancel my order?              | ORDER    | cancel_order | Go to Orders, select the order, and click Cancel Order. | bob@example.com   | Cancel Order | 2026-09-01T11:00:00Z |
      Then UserProblem 資料為
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And Ticket 資料為
        | id | user_problem_id | status   |
        | 1  | 1               | resolved |
        | 2  | 1               | resolved |

  Rule: 匯入後 Feature.name 等於 feature_name 且同名重用同一列
    Example: 兩張 cancel_order 票共用同一列 Feature
      When 系統匯入歷史票單
        | content                                 | category | intent       | response                                                | customer_ref      | feature_name | created_at           |
        | I want to cancel order {{Order Number}} | ORDER    | cancel_order | Go to Orders, select the order, and click Cancel Order. | alice@example.com | Cancel Order | 2026-09-01T10:00:00Z |
        | How can I cancel my order?              | ORDER    | cancel_order | Go to Orders, select the order, and click Cancel Order. | bob@example.com   | Cancel Order | 2026-09-01T11:00:00Z |
      Then Feature 資料為
        | id | name         | status |
        | 1  | Cancel Order | active |

  Rule: 不同 intent 建立不同 UserProblem 與 Feature
    Example: cancel_order 與 track_refund 各建一列
      When 系統匯入歷史票單
        | content                                 | category | intent       | response                                                | customer_ref      | feature_name | created_at           |
        | I want to cancel order {{Order Number}} | ORDER    | cancel_order | Go to Orders, select the order, and click Cancel Order. | alice@example.com | Cancel Order | 2026-09-01T10:00:00Z |
        | I want to track my refund               | REFUND   | track_refund | Go to Refunds and open the refund to see its status.    | bob@example.com   | Track Refund | 2026-09-01T11:00:00Z |
      Then UserProblem 資料為
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
        | 2  | track_refund | 2          |
      And Feature 資料為
        | id | name         | status |
        | 1  | Cancel Order | active |
        | 2  | Track Refund | active |
