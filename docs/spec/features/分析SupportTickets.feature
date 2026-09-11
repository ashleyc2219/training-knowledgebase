Feature: 分析 Ticket
  系統分析顧客 Ticket，依 user_problem_id（Bitext intent）聚集 recurring topic，並在沒有 published Tutorial 時識別 Knowledge Gap、決定 CREATE 或 KEEP。
  分析只納入 status 為 escalated 或 resolved 的 Ticket。
  分析不檢查 Ticket 總張數；二十到三十張僅為 Demo 建議量。

  Rule: 同一 user_problem_id 且至少 3 張 Ticket 才識別為 recurring topic
    Example: 剛好 3 張 cancel_order 票識別為 recurring topic
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統已有以下 Ticket
        | id | content                                    | category | feature_id | user_problem_id | status   |
        | 1  | I want to cancel order {{Order Number}}    | ORDER    | 1          | 1               | resolved |
        | 2  | How can I cancel my order?                 | ORDER    | 1          | 1               | resolved |
        | 3  | Please cancel order {{Order Number}}       | ORDER    | 1          | 1               | resolved |
      When 系統分析 Ticket
      Then 系統識別出以下 recurring topic
        | user_problem_id | topic        |
        | 1               | cancel_order |

    Example: 只有 2 張 cancel_order 票時 recurring topic 為空
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統已有以下 Ticket
        | id | content                                 | category | feature_id | user_problem_id | status   |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | 1          | 1               | resolved |
        | 2  | How can I cancel my order?              | ORDER    | 1          | 1               | resolved |
      When 系統分析 Ticket
      Then 系統識別出以下 recurring topic
        | user_problem_id | topic |

  Rule: 沒有任何 Ticket 時分析結果為空
    Example: 沒有 Ticket 時 recurring topic 與動作皆為空
      Given 系統沒有任何 Ticket
      When 系統分析 Ticket
      Then 系統識別出以下 recurring topic
        | user_problem_id | topic |
      And 系統決定的動作為
        | user_problem_id | action |

  Rule: Tickets 無法聚成同一主題時分析結果為空
    Example: 三張票各屬不同 user_problem_id 時 recurring topic 與動作皆為空
      Given 系統已有以下 Feature
        | id | name                     | status |
        | 1  | Cancel Order             | active |
        | 2  | Track Refund             | active |
        | 3  | Change Shipping Address  | active |
      And 系統已有以下 UserProblem
        | id | topic                    | feature_id |
        | 1  | cancel_order             | 1          |
        | 2  | track_refund             | 2          |
        | 3  | change_shipping_address  | 3          |
      And 系統已有以下 Ticket
        | id | content                                      | category         | feature_id | user_problem_id | status   |
        | 1  | I want to cancel order {{Order Number}}      | ORDER            | 1          | 1               | resolved |
        | 2  | I want to track my refund                    | REFUND           | 2          | 2               | resolved |
        | 3  | I want to change my shipping address         | SHIPPING_ADDRESS | 3          | 3               | resolved |
      When 系統分析 Ticket
      Then 系統識別出以下 recurring topic
        | user_problem_id | topic |
      And 系統決定的動作為
        | user_problem_id | action |

  Rule: 分析只納入 status 為 escalated 或 resolved 的 Ticket
    Example: 3 張同 topic 但 status 為 open、deflected 時 recurring topic 為空
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統已有以下 Ticket
        | id | content                                 | category | feature_id | user_problem_id | status    |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | 1          | 1               | open      |
        | 2  | How can I cancel my order?              | ORDER    | 1          | 1               | open      |
        | 3  | Please cancel order {{Order Number}}    | ORDER    | 1          | 1               | deflected |
      When 系統分析 Ticket
      Then 系統識別出以下 recurring topic
        | user_problem_id | topic |

    Example: 2 張 resolved 加 1 張 escalated 識別為 recurring topic
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統已有以下 Ticket
        | id | content                                 | category | feature_id | user_problem_id | status    |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | 1          | 1               | resolved  |
        | 2  | How can I cancel my order?              | ORDER    | 1          | 1               | resolved  |
        | 3  | Please cancel order {{Order Number}}    | ORDER    | 1          | 1               | escalated |
      When 系統分析 Ticket
      Then 系統識別出以下 recurring topic
        | user_problem_id | topic        |
        | 1               | cancel_order |

  Rule: 沒有 published Tutorial 的 recurring topic 才識別為 Knowledge Gap
    Example: 3 張 cancel_order 且沒有 Tutorial 時識別為 Knowledge Gap
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統已有以下 Ticket
        | id | content                                 | category | feature_id | user_problem_id | status   |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | 1          | 1               | resolved |
        | 2  | How can I cancel my order?              | ORDER    | 1          | 1               | resolved |
        | 3  | Please cancel order {{Order Number}}    | ORDER    | 1          | 1               | resolved |
      And 系統沒有任何 Tutorial
      When 系統分析 Ticket
      Then 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |

    Example: 已有 published Tutorial 時 Knowledge Gap 為空
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統已有以下 Ticket
        | id | content                                 | category | feature_id | user_problem_id | status   |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | 1          | 1               | resolved |
        | 2  | How can I cancel my order?              | ORDER    | 1          | 1               | resolved |
        | 3  | Please cancel order {{Order Number}}    | ORDER    | 1          | 1               | resolved |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | user_problem_id | path                      | status    | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1           | 1          | 1               | tutorials/cancel-order.md | published | v1              | false                | false       | CREATE      |
      When 系統分析 Ticket
      Then 系統識別出以下 Knowledge Gap
        | user_problem_id | topic |

  Rule: Knowledge Gap 的動作為 CREATE
    Example: cancel_order 沒有 published Tutorial 時動作為 CREATE
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統已有以下 Ticket
        | id | content                                 | category | feature_id | user_problem_id | status   |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | 1          | 1               | resolved |
        | 2  | How can I cancel my order?              | ORDER    | 1          | 1               | resolved |
        | 3  | Please cancel order {{Order Number}}    | ORDER    | 1          | 1               | resolved |
      And 系統沒有任何 Tutorial
      When 系統分析 Ticket
      Then 系統決定的動作為
        | user_problem_id | action |
        | 1               | CREATE |

  Rule: 已有 published Tutorial 的動作為 KEEP
    Example: cancel_order 已有 published Tutorial 時動作為 KEEP
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統已有以下 Ticket
        | id | content                                 | category | feature_id | user_problem_id | status   |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | 1          | 1               | resolved |
        | 2  | How can I cancel my order?              | ORDER    | 1          | 1               | resolved |
        | 3  | Please cancel order {{Order Number}}    | ORDER    | 1          | 1               | resolved |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | user_problem_id | path                      | status    | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1           | 1          | 1               | tutorials/cancel-order.md | published | v1              | false                | false       | CREATE      |
      When 系統分析 Ticket
      Then 系統決定的動作為
        | user_problem_id | action |
        | 1               | KEEP   |

  Rule: 一次分析識別出多個 Knowledge Gap 時每個都 CREATE
    Example: cancel_order 與 track_refund 兩個 gap 皆 CREATE
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
        | 2  | Track Refund | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
        | 2  | track_refund | 2          |
      And 系統已有以下 Ticket
        | id | content                                 | category | feature_id | user_problem_id | status   |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | 1          | 1               | resolved |
        | 2  | How can I cancel my order?              | ORDER    | 1          | 1               | resolved |
        | 3  | Please cancel order {{Order Number}}    | ORDER    | 1          | 1               | resolved |
        | 4  | I want to track my refund               | REFUND   | 2          | 2               | resolved |
        | 5  | Where is my refund {{Refund Order Number}} | REFUND | 2          | 2               | resolved |
        | 6  | How can I check the status of my refund | REFUND   | 2          | 2               | resolved |
      And 系統沒有任何 Tutorial
      When 系統分析 Ticket
      Then 系統決定的動作為
        | user_problem_id | action |
        | 1               | CREATE |
        | 2               | CREATE |

  Rule: 新問題的先備知識已有現成教學時動作仍為 CREATE
    Example: track_refund 已有 Tutorial 時 cancel_order 仍 CREATE
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
        | 2  | Track Refund | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
        | 2  | track_refund | 2          |
      And 系統已有以下 Ticket
        | id | content                                 | category | feature_id | user_problem_id | status   |
        | 1  | I want to cancel order {{Order Number}} | ORDER    | 1          | 1               | resolved |
        | 2  | How can I cancel my order?              | ORDER    | 1          | 1               | resolved |
        | 3  | Please cancel order {{Order Number}}    | ORDER    | 1          | 1               | resolved |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | user_problem_id | path                      | status    | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1           | 2          | 2               | tutorials/track-refund.md | published | v1              | false                | false       | CREATE      |
      When 系統分析 Ticket
      Then 系統決定的動作為
        | user_problem_id | action |
        | 1               | CREATE |
