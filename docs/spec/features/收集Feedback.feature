Feature: 收集 Feedback
  顧客對一篇 Tutorial 提交結構化 Feedback，系統將資料存進 Database。

  Rule: rating 必須為 1 到 5 的整數
    Example: rating 剛好為 1 時提交成功
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v1 | 1 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | rating |
        | 1 | 1 | v1 | 1 |

    Example: rating 剛好為 5 時提交成功
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v1 | 5 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | rating |
        | 1 | 1 | v1 | 5 |

    Example: rating 為 0 時操作失敗
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v1 | 0 | 2026-09-11T10:00:00Z |
      Then 操作失敗

    Example: rating 為 6 時操作失敗
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v1 | 6 | 2026-09-11T10:00:00Z |
      Then 操作失敗

    Example: 未填 rating 時操作失敗
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | timestamp |
        | 1 | v1 | 2026-09-11T10:00:00Z |
      Then 操作失敗

  Rule: feedback_category 允許六類與「其他」，未填存空字串
    Example: feedback_category 為指示不清楚時提交成功
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | feedback_category | timestamp |
        | 1 | v1 | 2 | 指示不清楚 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | feedback_category |
        | 1 | 1 | v1 | 指示不清楚 |

    Example: feedback_category 為其他時提交成功
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | feedback_category | timestamp |
        | 1 | v1 | 3 | 其他 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | feedback_category |
        | 1 | 1 | v1 | 其他 |

    Example: 未填 feedback_category 時存空字串
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v1 | 3 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | feedback_category |
        | 1 | 1 | v1 |  |

  Rule: comment 可空，未填存空字串
    Example: 顧客提交 Step 3 很難懂的 comment
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | comment | timestamp |
        | 1 | v1 | 2 | Step 3 很難懂。 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | comment |
        | 1 | 1 | v1 | Step 3 很難懂。 |

    Example: 顧客提交 Cancel Order 按鈕位置的 comment
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | comment | timestamp |
        | 1 | v1 | 2 | Cancel Order 按鈕在哪？ | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | comment |
        | 1 | 1 | v1 | Cancel Order 按鈕在哪？ |

    Example: 顧客提交 Step 3 需要更多說明的 comment
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | comment | timestamp |
        | 1 | v1 | 2 | 這一步需要更多說明。 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | comment |
        | 1 | 1 | v1 | 這一步需要更多說明。 |

    Example: 未填 comment 時存空字串
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v1 | 3 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | comment |
        | 1 | 1 | v1 |  |

  Rule: Feedback 必須包含 tutorial_id、tutorial_version、rating、timestamp
    Example: 四欄都有值時入庫成功
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v1 | 3 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | 1 | v1 | 3 | 2026-09-11T10:00:00Z |

    Example: 未填 tutorial_id 時操作失敗
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_version | rating | timestamp |
        | v1 | 3 | 2026-09-11T10:00:00Z |
      Then 操作失敗

    Example: 未填 timestamp 時操作失敗
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating |
        | 1 | v1 | 3 |
      Then 操作失敗

  Rule: Feedback 存進 Database
    Example: 提交成功後 Feedback 含 id 與各欄資料
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | v1 | 2 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 2 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-11T10:00:00Z |

  Rule: Feedback 參照 TutorialVersion
    Example: 沒有對應 TutorialVersion 時操作失敗
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v9 | 3 | 2026-09-11T10:00:00Z |
      Then 操作失敗

    Example: 未指定 tutorial_version 時綁定 current_version
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v2 | REFINE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
        | 1 | v2 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. On the order details page, locate the Cancel Order button beside the order status and click "Cancel Order". This starts cancellation for that order. 4. Confirm cancellation. | The order is cancelled. | Repeated feedback indicates Step 3 lacks context. | v1 |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | rating | timestamp |
        | 1 | 4 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | rating |
        | 1 | 1 | v2 | 4 |

    Example: 有指定 tutorial_version 時綁定指定版
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v2 | REFINE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
        | 1 | v2 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. On the order details page, locate the Cancel Order button beside the order status and click "Cancel Order". This starts cancellation for that order. 4. Confirm cancellation. | The order is cancelled. | Repeated feedback indicates Step 3 lacks context. | v1 |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v1 | 2 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | rating |
        | 1 | 1 | v1 | 2 |

  Rule: submitter_id 可空，同一 submitter 重複評分各自成列
    Example: 未填 submitter_id 時提交成功
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統沒有任何 Feedback
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | timestamp |
        | 1 | v1 | 3 | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | rating | submitter_id |
        | 1 | 1 | v1 | 3 |  |

    Example: 同一 submitter 再次評分時新增一列
      Given 系統已有以下 Tutorial
        | tutorial_id | path | status | current_version | last_action |
        | 1 | tutorials/cancel-order.md | published | v1 | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | title | problem | prerequisites | steps | expected_outcome | reason | supersedes_version |
        | 1 | v1 | Cancel Order | The customer wants to cancel an existing order. | The customer has an account and an open order. | 1. Open your orders. 2. Select the order. 3. Click "Cancel Order". 4. Confirm cancellation. | The order is cancelled. |  |  |
      And 系統已有以下 Feedback
        | id | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | 1 | v1 | 2 | 指示不清楚 | Step 3 很難懂。 | alice@example.com | 2026-09-11T09:00:00Z |
      When 顧客提交 Feedback
        | tutorial_id | tutorial_version | rating | feedback_category | comment | submitter_id | timestamp |
        | 1 | v1 | 3 | 缺少資訊 | Cancel Order 按鈕在哪？ | alice@example.com | 2026-09-11T10:00:00Z |
      Then Feedback 資料為
        | id | tutorial_id | tutorial_version | rating | submitter_id | timestamp |
        | 1 | 1 | v1 | 2 | alice@example.com | 2026-09-11T09:00:00Z |
        | 2 | 1 | v1 | 3 | alice@example.com | 2026-09-11T10:00:00Z |
