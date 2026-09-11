Feature: 定期優化 Tutorial
  系統以排程或 demo 手動觸發 Feedback Review，不規定週期。檢視累積 Feedback，對尚未過期但不好用的 Tutorial 決定 REFINE 或 KEEP。

  Rule: 平均 rating 小於 3.5 才進入 REFINE
    Example: 平均 rating 剛好等於 3.5 時動作為 KEEP
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | false | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 3 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-01T10:00:00Z |
        | 2 | 1 | v1 | 3 | 指示不清楚 | Cancel Order 按鈕在哪？ | bob@example.com | 2026-09-02T10:00:00Z |
        | 3 | 1 | v1 | 4 | 指示不清楚 | 這一步需要更多說明。 | alice@example.com | 2026-09-03T10:00:00Z |
        | 4 | 1 | v1 | 4 | 指示不清楚 | Step 3 很難懂。 | bob@example.com | 2026-09-04T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | KEEP |
      And Tutorial 資料為
        | tutorial_id | current_version | last_action |
        | 1 | v1 | KEEP |

  Rule: 平均 rating 只計算 current_version 的 Feedback
    Example: current_version 為 v2 且 v2 平均 rating 高於 3.5 時不計 v1 低分
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | last_action |
        | 1 | tutorials/cancel-order.md | published | v2 | false | REFINE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
        | 1 | v2 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. On the order details page, locate the Cancel Order button beside the order status and click "Cancel Order". This starts cancellation for that order. 4. Confirm cancellation. | The order is cancelled. | Repeated feedback indicates Step 3 lacks context. | v1 |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 1 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-01T10:00:00Z |
        | 2 | 1 | v1 | 1 | 指示不清楚 | Cancel Order 按鈕在哪？ | bob@example.com | 2026-09-02T10:00:00Z |
        | 3 | 1 | v1 | 1 | 指示不清楚 | 這一步需要更多說明。 | alice@example.com | 2026-09-03T10:00:00Z |
        | 4 | 1 | v2 | 5 | 其他 |  | alice@example.com | 2026-09-08T10:00:00Z |
        | 5 | 1 | v2 | 5 | 其他 |  | bob@example.com | 2026-09-09T10:00:00Z |
        | 6 | 1 | v2 | 5 | 其他 |  | alice@example.com | 2026-09-10T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | KEEP |
      And Tutorial 資料為
        | tutorial_id | current_version | last_action |
        | 1 | v2 | KEEP |

  Rule: current_version 的 Feedback 數量必須大於或等於 3 才進入 REFINE
    Example: 平均 rating 小於 3.5 但只有 2 筆時動作為 KEEP
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | false | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 2 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-01T10:00:00Z |
        | 2 | 1 | v1 | 3 | 指示不清楚 | Cancel Order 按鈕在哪？ | bob@example.com | 2026-09-02T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | KEEP |
      And Tutorial 資料為
        | tutorial_id | current_version | last_action |
        | 1 | v1 | KEEP |

  Rule: 同一 feedback_category 至少 2 筆才存在 recurring complaints
    Example: Feedback 有 3 筆且平均 rating 小於 3.5 但各為不同 category 時動作為 KEEP
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | false | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 2 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-01T10:00:00Z |
        | 2 | 1 | v1 | 2 | 缺少資訊 | Cancel Order 按鈕在哪？ | bob@example.com | 2026-09-02T10:00:00Z |
        | 3 | 1 | v1 | 2 | Tutorial 太長 | 這一步需要更多說明。 | alice@example.com | 2026-09-03T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | KEEP |
      And Tutorial 資料為
        | tutorial_id | current_version | last_action |
        | 1 | v1 | KEEP |

  Rule: 不得因單一低分立刻修改 Tutorial
    Example: 只有 1 筆 Feedback 時動作為 KEEP
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | false | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 1 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-01T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | KEEP |
      And Tutorial 資料為
        | tutorial_id | current_version | last_action |
        | 1 | v1 | KEEP |

  Rule: 必須觀察一段時間累積的 pattern 才決定是否優化，不看日曆天數
    Example: 只有 2 筆 Feedback 時動作為 KEEP
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | false | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 2 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-01T10:00:00Z |
        | 2 | 1 | v1 | 3 | 指示不清楚 | Cancel Order 按鈕在哪？ | bob@example.com | 2026-09-02T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | KEEP |
      And Tutorial 資料為
        | tutorial_id | current_version | last_action |
        | 1 | v1 | KEEP |

  Rule: 平均 rating 小於 3.5 且 Feedback 數量足夠且存在 recurring complaints 時進入 REFINE 並發布新版本
    Example: 三條件都成立時產生 Tutorial v2
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | false | false | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 2 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-01T10:00:00Z |
        | 2 | 1 | v1 | 3 | 指示不清楚 | Cancel Order 按鈕在哪？ | bob@example.com | 2026-09-02T10:00:00Z |
        | 3 | 1 | v1 | 3 | 指示不清楚 | 這一步需要更多說明。 | alice@example.com | 2026-09-03T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | REFINE |
      And Tutorial 資料為
        | tutorial_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | tutorials/cancel-order.md | published | v2 | false | false | REFINE |
      And TutorialVersion 資料為
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
        | 1 | v2 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. On the order details page, locate the Cancel Order button beside the order status and click "Cancel Order". This starts cancellation for that order. 4. Confirm cancellation. | The order is cancelled. | Repeated feedback indicates Step 3 lacks context. | v1 |

  Rule: Feedback 表現良好時 KEEP
    Example: 平均 rating 為 4.0 時動作為 KEEP
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | false | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 4 | 其他 |  | alice@example.com | 2026-09-01T10:00:00Z |
        | 2 | 1 | v1 | 4 | 其他 |  | bob@example.com | 2026-09-02T10:00:00Z |
        | 3 | 1 | v1 | 4 | 其他 |  | alice@example.com | 2026-09-03T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | KEEP |
      And Tutorial 資料為
        | tutorial_id | current_version | last_action |
        | 1 | v1 | KEEP |

  Rule: 過去結果會改變系統下一次的行為
    Example: Tutorial v1 評分 2.9 優化後 v2 評分為 4.4
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | last_action |
        | 1 | tutorials/cancel-order.md | published | v2 | false | REFINE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
        | 1 | v2 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. On the order details page, locate the Cancel Order button beside the order status and click "Cancel Order". This starts cancellation for that order. 4. Confirm cancellation. | The order is cancelled. | Repeated feedback indicates Step 3 lacks context. | v1 |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 2 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-01T10:00:00Z |
        | 2 | 1 | v1 | 2 | 指示不清楚 | Cancel Order 按鈕在哪？ | bob@example.com | 2026-09-01T11:00:00Z |
        | 3 | 1 | v1 | 3 | 指示不清楚 | 這一步需要更多說明。 | alice@example.com | 2026-09-02T10:00:00Z |
        | 4 | 1 | v1 | 3 | 指示不清楚 | Step 3 很難懂。 | bob@example.com | 2026-09-02T11:00:00Z |
        | 5 | 1 | v1 | 3 | 指示不清楚 | Cancel Order 按鈕在哪？ | alice@example.com | 2026-09-03T10:00:00Z |
        | 6 | 1 | v1 | 3 | 指示不清楚 | 這一步需要更多說明。 | bob@example.com | 2026-09-03T11:00:00Z |
        | 7 | 1 | v1 | 3 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-04T10:00:00Z |
        | 8 | 1 | v1 | 3 | 指示不清楚 | Cancel Order 按鈕在哪？ | bob@example.com | 2026-09-04T11:00:00Z |
        | 9 | 1 | v1 | 3 | 指示不清楚 | 這一步需要更多說明。 | alice@example.com | 2026-09-05T10:00:00Z |
        | 10 | 1 | v1 | 4 | 指示不清楚 | Step 3 很難懂。 | bob@example.com | 2026-09-05T11:00:00Z |
        | 11 | 1 | v2 | 4 | 其他 |  | alice@example.com | 2026-09-08T10:00:00Z |
        | 12 | 1 | v2 | 4 | 其他 |  | bob@example.com | 2026-09-08T11:00:00Z |
        | 13 | 1 | v2 | 4 | 其他 |  | alice@example.com | 2026-09-09T10:00:00Z |
        | 14 | 1 | v2 | 5 | 其他 |  | bob@example.com | 2026-09-09T11:00:00Z |
        | 15 | 1 | v2 | 5 | 其他 |  | alice@example.com | 2026-09-10T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | KEEP |
      And Tutorial 資料為
        | tutorial_id | current_version | last_action |
        | 1 | v2 | KEEP |
      And 學習指標為
        | tutorial_id | tutorial_version | avg_rating | feedback_count |
        | 1 | v1 | 2.9 | 10 |
        | 1 | v2 | 4.4 | 5 |

  Rule: is_possibly_outdated 為 true 的 Tutorial 本輪 Review 動作為 KEEP
    Example: 三條件都成立但 Tutorial 已標記可能過期時動作為 KEEP
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | is_possibly_outdated | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | true | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 2 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-01T10:00:00Z |
        | 2 | 1 | v1 | 3 | 指示不清楚 | Cancel Order 按鈕在哪？ | bob@example.com | 2026-09-02T10:00:00Z |
        | 3 | 1 | v1 | 3 | 指示不清楚 | 這一步需要更多說明。 | alice@example.com | 2026-09-03T10:00:00Z |
      When 系統執行定期 Feedback Review
      Then 系統決定的動作為
        | tutorial_id | action |
        | 1 | KEEP |
      And Tutorial 資料為
        | tutorial_id | current_version | is_possibly_outdated | last_action |
        | 1 | v1 | true | KEEP |
