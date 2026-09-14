# 來源：../draft/training-kb-design-doc.md §8.1、§8.3、§9.2、§10、§20.B。
# 來源：../draft/training-kb-erd.md §4、§6。
Feature: 查詢知識圖譜
  Pipeline 或 Analytics 請求圖譜關聯，取得 Feature 的引用步驟、教學版本或規則套用版本。

  # 來源：設計 §8.3；ERD §4。
  @Missing
  Rule: 查詢某起點的關係使用該起點的 PK
    #TODO 原文列邊的 item 範例，但沒有單一 PK 的完整正向 query 輸入與結果集合。

  # 來源：設計 §8.3、§10.1；ERD §4。
  @Partial
  Rule: 查詢誰引用 Feature 時使用 by_target 的 target
    #TODO 同一 target 可含 TICKET 的 ASKS_ABOUT 邊；原文 query 未示範關係型別篩選與分頁。
    # 改寫範圍見 F17。

    Example: 反查 Prepare 的引用步驟
      Given 圖譜中的 references 邊集合為
        | PK                       | SK                         | target          |
        | STEP#prepare-meeting@v2#3 | REFERENCES#FEATURE#Prepare | FEATURE#Prepare |
      When 系統查詢引用 "FEATURE#Prepare" 的教學步驟
      Then 回傳的步驟主鍵集合為
        | pk                       |
        | STEP#prepare-meeting@v2#3 |

  # 來源：設計 §8.3、§10.1。
  @Missing
  Rule: 沿 Feature 關係邊反查不呼叫 AI
    #TODO 原文只有零 AI 敘述與 query 程式，沒有實際呼叫紀錄範例。

  # 來源：設計 §8.1；ERD §2。
  @Missing
  Rule: 可查詢某篇 Tutorial 所屬的版本
    #TODO 原文沒有完整 Query 的鍵設計與結果集合；不自行新增索引或 HAS_VERSION 邊格式。

  # 來源：設計 §8.1、§11.1；ERD §4；釐清 D17。
  @Specified
  Rule: 可查詢某條 Authoring Rule 套用的版本
    # applied_to 由各版本 rules_applied 重建。
    Example: R-007 套用過三個版本
      Given 規則 "R-007" 的 applied_to 為
        | version_id         |
        | prepare-meeting@v2 |
        | share-summary@v1   |
        | prepare-meeting@v3 |
      When 系統查詢規則 "R-007" 套用的教學版本
      Then 回傳的版本集合為
        | version_id         |
        | prepare-meeting@v2 |
        | share-summary@v1   |
        | prepare-meeting@v3 |

  # 來源：ERD §4、§6。
  @Missing
  Rule: Feedback Review 以 refers_to 關係反查指定版本的回饋
    #TODO 原文有 FEEDBACK#f_12 → prepare-meeting@v1 的邊，沒有某版本的完整回饋結果集合。

  # 來源：設計 §18；釐清 F40。
  @Missing
  Rule: 定期 backfill 漏抽的 Feature 引用邊
    #TODO 原文未定義排程、輸入範圍、漏邊辨識與寫回的範例。
    # backfill 只增加缺少的 Feature 引用邊，不移除或替換既有引用。
    # 錯誤邊另列待處理。不因此建立新 TutorialVersion。
