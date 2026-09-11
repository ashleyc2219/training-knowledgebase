Feature: 建立 Tutorial
  當系統識別出 Knowledge Gap 時，建立 Tutorial v1。建立成功即 status = published、current_version = v1、last_action = CREATE。
  教學內容來自已解決票的 resolution_steps，不需先實際操作產品驗證。

  Rule: 存在 Knowledge Gap 時建立 Tutorial，status 為 published、current_version 為 v1、last_action 為 CREATE
    Example: 為 cancel_order 建立 Tutorial
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |
      And 系統沒有任何 Tutorial
      When 系統建立 Tutorial
        | feature_id | user_problem_id | path                      | title        | problem                                      | prerequisites                                      | steps                                                                  | expected_outcome         |
        | 1          | 1               | tutorials/cancel-order.md | Cancel Order | Customer wants to cancel an existing order. | Customer is logged in and has an order number.     | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order".          | The order is cancelled.  |
      Then Tutorial 資料為
        | tutorial_id | feature_id | user_problem_id | path                      | status    | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1           | 1          | 1               | tutorials/cancel-order.md | published | v1              | false                | false       | CREATE      |

  Rule: 建立的 TutorialVersion v1 五個內容欄必填且 supersedes_version 為空
    Example: cancel_order 的 v1 五欄有值且 supersedes_version 為空
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |
      And 系統沒有任何 Tutorial
      When 系統建立 Tutorial
        | feature_id | user_problem_id | path                      | title        | problem                                      | prerequisites                                  | steps                                                         | expected_outcome        |
        | 1          | 1               | tutorials/cancel-order.md | Cancel Order | Customer wants to cancel an existing order. | Customer is logged in and has an order number. | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order". | The order is cancelled. |
      Then TutorialVersion 資料為
        | tutorial_id | tutorial_version | title        | problem                                     | prerequisites                                  | steps                                                         | expected_outcome        | reason | supersedes_version |
        | 1           | v1               | Cancel Order | Customer wants to cancel an existing order. | Customer is logged in and has an order number. | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order". | The order is cancelled. |        |                    |

  Rule: 建立 Tutorial 時缺少 Title、Problem、Prerequisites、Steps、Expected Outcome 任一欄則操作失敗
    Example: 缺少 title 時操作失敗
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |
      When 系統建立 Tutorial
        | feature_id | user_problem_id | path                      | problem                                     | prerequisites                                  | steps                                                         | expected_outcome        |
        | 1          | 1               | tutorials/cancel-order.md | Customer wants to cancel an existing order. | Customer is logged in and has an order number. | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order". | The order is cancelled. |
      Then 操作失敗

    Example: 缺少 problem 時操作失敗
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |
      When 系統建立 Tutorial
        | feature_id | user_problem_id | path                      | title        | prerequisites                                  | steps                                                         | expected_outcome        |
        | 1          | 1               | tutorials/cancel-order.md | Cancel Order | Customer is logged in and has an order number. | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order". | The order is cancelled. |
      Then 操作失敗

    Example: 缺少 prerequisites 時操作失敗
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |
      When 系統建立 Tutorial
        | feature_id | user_problem_id | path                      | title        | problem                                     | steps                                                         | expected_outcome        |
        | 1          | 1               | tutorials/cancel-order.md | Cancel Order | Customer wants to cancel an existing order. | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order". | The order is cancelled. |
      Then 操作失敗

    Example: 缺少 steps 時操作失敗
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |
      When 系統建立 Tutorial
        | feature_id | user_problem_id | path                      | title        | problem                                     | prerequisites                                  | expected_outcome        |
        | 1          | 1               | tutorials/cancel-order.md | Cancel Order | Customer wants to cancel an existing order. | Customer is logged in and has an order number. | The order is cancelled. |
      Then 操作失敗

    Example: 缺少 expected_outcome 時操作失敗
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |
      When 系統建立 Tutorial
        | feature_id | user_problem_id | path                      | title        | problem                                     | prerequisites                                  | steps                                                         |
        | 1          | 1               | tutorials/cancel-order.md | Cancel Order | Customer wants to cancel an existing order. | Customer is logged in and has an order number. | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order". |
      Then 操作失敗

  Rule: 未識別出 Knowledge Gap 時建立 Tutorial 操作失敗
    Example: Knowledge Gap 為空時操作失敗
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic |
      When 系統建立 Tutorial
        | feature_id | user_problem_id | path                      | title        | problem                                     | prerequisites                                  | steps                                                         | expected_outcome        |
        | 1          | 1               | tutorials/cancel-order.md | Cancel Order | Customer wants to cancel an existing order. | Customer is logged in and has an order number. | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order". | The order is cancelled. |
      Then 操作失敗

  Rule: 建立 Tutorial 時必須有對應的 Feature
    Example: When 未給 feature_id 時操作失敗
      Given 系統已有以下 Feature
        | id | name         | status |
        | 1  | Cancel Order | active |
      And 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |
      When 系統建立 Tutorial
        | user_problem_id | path                      | title        | problem                                     | prerequisites                                  | steps                                                         | expected_outcome        |
        | 1               | tutorials/cancel-order.md | Cancel Order | Customer wants to cancel an existing order. | Customer is logged in and has an order number. | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order". | The order is cancelled. |
      Then 操作失敗

    Example: 對應的 Feature 不存在時操作失敗
      Given 系統已有以下 UserProblem
        | id | topic        | feature_id |
        | 1  | cancel_order | 1          |
      And 系統識別出以下 Knowledge Gap
        | user_problem_id | topic        |
        | 1               | cancel_order |
      When 系統建立 Tutorial
        | feature_id | user_problem_id | path                      | title        | problem                                     | prerequisites                                  | steps                                                         | expected_outcome        |
        | 1          | 1               | tutorials/cancel-order.md | Cancel Order | Customer wants to cancel an existing order. | Customer is logged in and has an order number. | 1. Open Orders. 2. Select the order. 3. Click "Cancel Order". | The order is cancelled. |
      Then 操作失敗
