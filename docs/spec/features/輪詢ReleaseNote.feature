Feature: 輪詢 Release Note
  系統定期輪詢 changelog 來源，把 created_at 大於上次檢查時間的新列寫入 Release。
  寫入的 Release processed_at 為空；UPDATE / RETIRE 見依ReleaseNote更新Tutorial。
  Demo 現場餵入模擬 changelog 與 hotdata 輪詢為同一功能，僅資料來源不同。
  排程或 demo 手動觸發，不規定週期。

  Rule: 只把 created_at 大於上次檢查時間的 changelog 列寫入 Release
    Example: 過期列與剛好等於上次檢查時間的列不寫入
      Given 上次檢查時間為 "2026-09-11T10:00:00Z"
      And 系統沒有任何 Release
      And 系統收到以下 changelog
        | content | created_at |
        | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:00:00Z |
        | Track Refund is a new feature. | 2026-09-11T10:00:00Z |
        | Cancel Order has been deprecated. | 2026-09-11T10:30:00Z |
      When 系統輪詢 Release Note
      Then Release 資料為
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been deprecated. | 2026-09-11T10:30:00Z |  |

  Rule: 寫入的 Release processed_at 為空
    Example: 新列入庫後尚未處理
      Given 上次檢查時間為 "2026-09-11T09:00:00Z"
      And 系統沒有任何 Release
      And 系統收到以下 changelog
        | content | created_at |
        | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:30:00Z |
      When 系統輪詢 Release Note
      Then Release 資料為
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:30:00Z |  |

  Rule: 相同 content 與 created_at 已存在時不新增列
    Example: 同一則再輪詢一次 Release 仍只有一列
      Given 上次檢查時間為 "2026-09-11T09:00:00Z"
      And 系統已有以下 Release
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:30:00Z |  |
      And 系統收到以下 changelog
        | content | created_at |
        | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:30:00Z |
      When 系統輪詢 Release Note
      Then Release 資料為
        | id | content | created_at | processed_at |
        | 1 | Cancel Order has been renamed to Cancel Purchase. | 2026-09-11T09:30:00Z |  |
