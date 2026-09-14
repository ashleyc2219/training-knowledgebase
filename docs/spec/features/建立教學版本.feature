# 來源：../draft/training-kb-design-doc.md §8.2–§8.4、§9、§10、§11.1、§20.B。
# 來源：../draft/training-kb-erd.md §1–§4。
Feature: 建立教學版本
  Ticket Analysis、Release Note Update 或 Periodic Feedback Review 呼叫 create_version，
  保存教學內容、步驟、來源原因與版本關係。

  # 來源：設計 §9、§16 T0；釐清 D26。
  @Missing
  Rule: 新 Tutorial 的版本從 v1 起算
    # 同一邏輯變更重試重用原版號；永久失敗可留缺口；不要覆蓋已發布版本。
    #TODO 原文有 Tutorial A v1，但沒有 create_version 的完整 steps 輸入。

  # 來源：設計 §4、§9、§10.1、§12.1；釐清 D26。
  @Specified
  Rule: 任一 pipeline 修改既有教學時使用該篇的下一個版本號
    # 同一邏輯變更重試重用原版號；永久失敗可留缺口；不要覆蓋已發布版本。
    # 同篇 Release 與 Feedback 改版依接受順序串行；每次讀取最新可用基底再產生下一版。
    Example: Feedback 產生 v2 後 Release 產生 v3
      Given 教學 "prepare-meeting" 的目前版本為 "prepare-meeting@v2"
      And 該版本來自 Feedback Review
      When Release Note Update 為教學 "prepare-meeting" 建立下一版
      Then 新版本的識別碼為 "prepare-meeting@v3"

  # 來源：設計 §4、§9；ERD §4。
  @Specified
  Rule: 新版以 supersedes 關聯同一篇教學的前一版
    Example: prepare-meeting v3 取代 v2
      Given 教學 "prepare-meeting" 的目前版本為 "prepare-meeting@v2"
      When Release Note Update 為教學 "prepare-meeting" 建立下一版
      Then 新版本的取代關係資料如下
        | PK                         | SK                                    | target                     |
        | VERSION#prepare-meeting@v3 | SUPERSEDES#VERSION#prepare-meeting@v2   | VERSION#prepare-meeting@v2 |

  # 來源：設計 §9。
  @Missing
  Rule: 每次建立版本都記錄引起變更的 reason
    #TODO 原文有 gap、release、feedback 的格式範例，沒有同一版本完整寫入的 reason 資料。
    # REFINE 格式：feedback:<n> 則 <category>。gap:<cluster_id> 與 release:<id> 不變。

  # 來源：設計 §8.4、§9.1；ERD §1。
  @Missing
  Rule: 每個版本的完整內容儲存在 tutorials/<slug>/v<n>.md
    #TODO 原文沒有完整 Markdown 內容與 S3 物件配對。
    # S3 已寫入但版本或關聯不完整時，保留不可公開的未完成未發布版本。
    # 待 S3、版本 item 與關聯全部就緒後才允許 publish。

  # 來源：設計 §8.2、§8.4；ERD §1。
  @Missing
  Rule: TutorialVersion 的 s3_key 指向該版本完整內容
    #TODO 原文只有路徑模板，沒有含 s3_key 的具體版本 item。

  # 來源：設計 §8.4；ERD §1。
  @Missing
  Rule: 與前版的 diff 儲存在 tutorials/<slug>/v<n>.diff
    #TODO 原文未提供 diff 檔案內容。
    # v1 建立空的 v1.diff；介面以版本號識別它沒有前版。

  # 來源：設計 §8.3、§9.1；ERD §4。
  @Specified
  Rule: 建立 TutorialStep 時保存 references Feature 邊
    Example: prepare-meeting v2 的第三步引用 Prepare
      Given 教學 "prepare-meeting" 的新版本為 "prepare-meeting@v2"
      And 新版本的步驟資料如下
        | step | feature         | text                                                               |
        | 3    | FEATURE#Prepare | Open Copilot and select Prepare in the upper-right corner            |
      When 系統保存 "prepare-meeting@v2" 的教學步驟
      Then references 邊的資料如下
        | PK                       | SK                           | target          |
        | STEP#prepare-meeting@v2#3 | REFERENCES#FEATURE#Prepare   | FEATURE#Prepare |

  # 來源：釐清 D05；ERD §2。
  @Missing
  Rule: 沒有 Feature 或引用多個 Feature 的步驟不可保存
    #TODO 原文沒有零個或多個 Feature 的步驟輸入；錯誤案例補齊時使用 Then 操作失敗。

  # 來源：ERD §4；設計 §8.3。
  @Specified
  Rule: references 邊的 target 等於 SK 中的關係終點
    Example: Prepare 終點寫入 by_target 索引欄位
      Given 步驟資料的 PK 為 "STEP#prepare-meeting@v2#3"
      And 其引用邊的 SK 為 "REFERENCES#FEATURE#Prepare"
      When 系統保存 "prepare-meeting@v2" 的教學步驟
      Then 該引用邊的 target 為 "FEATURE#Prepare"
