Feature: 依 Release Note 更新 Tutorial
  Release 列由「輪詢 Release Note」定期寫入資料庫；本功能不負責入庫。
  當系統處理 Release Note 時，處理所有 processed_at 為空的 Release。
  系統擷取產品變更、依 Tutorial.feature_id 找出受影響的 Tutorial，並決定 UPDATE 或 RETIRE。
  CREATE 只由「分析 Ticket」決定，Release Note 只產生 UPDATE / RETIRE。
  Then 中的 processed_at 等於 Given 的系統目前時間。

  Rule: 從 Release Note 擷取產品變更並寫入 ReleaseFeatureChange
    Example: 擷取 Cancel Order 更名為 Cancel Purchase
      Given 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Order | active |
      And 系統已有以下 Release
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:00:00Z |  |
      When 系統處理 Release Note
      Then ReleaseFeatureChange 資料為
        | release_id | feature_id | change_type | from_name | to_name |
        | 1 | 1 | renamed | Cancel Order | Cancel Purchase |

  Rule: 只依 Tutorial.feature_id 找出受影響 Tutorial
    Example: feature_id 命中 tutorials/cancel-order.md
      Given 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Order | active |
        | 2 | Track Refund | active |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | path |
        | 1 | 1 | tutorials/cancel-order.md |
        | 2 | 2 | tutorials/track-refund.md |
      And 系統已有以下 Release
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:00:00Z |  |
      When 系統處理 Release Note
      Then 系統找出以下受影響 Tutorial
        | tutorial_id | path |
        | 1 | tutorials/cancel-order.md |

  Rule: renamed 或 changed 時對受影響 Tutorial 執行 UPDATE
    同一次處理內先將 is_possibly_outdated 設為 true，產出新版後設回 false；Then 寫最終狀態。
    Example: 僅有 v1 時更新後版本為 v2
      Given 系統目前時間為 "2026-09-11T12:00:00Z"
      And 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Order | active |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | 1 | tutorials/cancel-order.md | published | v1 | false | false | CREATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | steps | reason | supersedes_version |
        | 1 | v1 | Step 3: Click "Cancel Order" |  |  |
      And 系統已有以下 Release
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:00:00Z |  |
      When 系統處理 Release Note
      Then TutorialVersion 資料為
        | tutorial_id | tutorial_version | steps | reason | supersedes_version |
        | 1 | v1 | Step 3: Click "Cancel Order" |  |  |
        | 1 | v2 | Step 3: Click "Cancel Purchase" | Cancel Order has been renamed to Cancel Purchase. | v1 |
      And Tutorial 資料為
        | tutorial_id | feature_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | 1 | tutorials/cancel-order.md | published | v2 | false | false | UPDATE |
      And Feature 資料為
        | id | name | status |
        | 1 | Cancel Purchase | active |
      And Release 資料為
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:00:00Z | 2026-09-11T12:00:00Z |
      And 系統決定的動作為
        | tutorial_id | action |
        | 1 | UPDATE |

  Rule: deprecated 或 removed 時對受影響 Tutorial 執行 RETIRE
    Example: Feature 被 deprecated 後 Tutorial 為 retired
      Given 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Order | active |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | 1 | tutorials/cancel-order.md | published | v1 | false | false | CREATE |
      And 系統已有以下 Release
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been deprecated. | 2026-09-11T09:00:00Z |  |
      When 系統處理 Release Note
      Then Tutorial 資料為
        | tutorial_id | feature_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | 1 | tutorials/cancel-order.md | retired | v1 | false | true | RETIRE |
      And Feature 資料為
        | id | name | status |
        | 1 | Cancel Order | deprecated |
      And 系統決定的動作為
        | tutorial_id | action |
        | 1 | RETIRE |

    Example: Feature 被 removed 後 Tutorial 為 retired
      Given 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Order | active |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | 1 | tutorials/cancel-order.md | published | v1 | false | false | CREATE |
      And 系統已有以下 Release
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been removed. | 2026-09-11T09:00:00Z |  |
      When 系統處理 Release Note
      Then Tutorial 資料為
        | tutorial_id | feature_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | 1 | tutorials/cancel-order.md | retired | v1 | false | true | RETIRE |
      And Feature 資料為
        | id | name | status |
        | 1 | Cancel Order | removed |
      And 系統決定的動作為
        | tutorial_id | action |
        | 1 | RETIRE |

  Rule: 出現 new feature 且無對應 Tutorial 時不決定動作
    Example: 新功能無 Tutorial 時動作為空
      Given 系統目前時間為 "2026-09-11T12:00:00Z"
      And 系統已有以下 Feature
        | id | name | status |
        | 2 | Track Refund | active |
      And 系統沒有任何 Tutorial
      And 系統已有以下 Release
        | id | content | created_at | processed_at |
        | 2 | Track Refund is a new feature. | 2026-09-11T09:00:00Z |  |
      When 系統處理 Release Note
      Then Release 資料為
        | id | content | created_at | processed_at |
        | 2 | Track Refund is a new feature. | 2026-09-11T09:00:00Z | 2026-09-11T12:00:00Z |
      And 系統決定的動作為
        | tutorial_id | action |

  Rule: 找不到受影響 Tutorial 時只記錄 processed_at
    Example: renamed 的 Feature 沒有 Tutorial
      Given 系統目前時間為 "2026-09-11T12:00:00Z"
      And 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Order | active |
      And 系統沒有任何 Tutorial
      And 系統已有以下 Release
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:00:00Z |  |
      When 系統處理 Release Note
      Then Release 資料為
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:00:00Z | 2026-09-11T12:00:00Z |

  Rule: 已有 processed_at 的 Release 不再處理
    Example: 已處理的 Release 不改變 Tutorial
      Given 系統已有以下 Feature
        | id | name | status |
        | 1 | Cancel Purchase | active |
      And 系統已有以下 Tutorial
        | tutorial_id | feature_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | 1 | tutorials/cancel-order.md | published | v2 | false | false | UPDATE |
      And 系統已有以下 TutorialVersion
        | tutorial_id | tutorial_version | steps | reason | supersedes_version |
        | 1 | v1 | Step 3: Click "Cancel Order" |  |  |
        | 1 | v2 | Step 3: Click "Cancel Purchase" | Cancel Order has been renamed to Cancel Purchase. | v1 |
      And 系統已有以下 Release
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:00:00Z | 2026-09-11T09:30:00Z |
      When 系統處理 Release Note
      Then Tutorial 資料為
        | tutorial_id | feature_id | path | status | current_version | is_possibly_outdated | is_obsolete | last_action |
        | 1 | 1 | tutorials/cancel-order.md | published | v2 | false | false | UPDATE |
