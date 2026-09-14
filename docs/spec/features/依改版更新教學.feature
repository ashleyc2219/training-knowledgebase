# 來源：../draft/training-kb-design-doc.md §9.2、§10、§11.1、§12.1、§16、§20.C。
Feature: 依改版更新教學
  新的正規化 Release 觸發 Release Note Update，定位受影響的教學步驟。

  # 來源：設計 §9.2；釐清 F14、D10。
  @Missing
  Rule: 從 PR diff 或 changelog 抽出 feature、kind、old_name 與 new_name
    #TODO 原文有 Meeting Summary → Prepare 的變更摘要，沒有原始 diff 與抽取結果的完整配對。
    # 一則來源含多個 Feature 變更時拆成多個子 Release，各遵守一則一個 feature 加 kind，並保留相同 source_event_id。
    # 子 Release 的 id 仍須全域唯一，不可多筆共用同一 r_ 識別碼。

  # 來源：設計 §4、§9.2、§10.1；釐清 D06。
  @Partial
  Rule: 改名前後的 alias 對應同一個 Feature 節點
    #TODO alias 完全未命中的案例仍待釐清。改名不遷移第一次建立的 Feature 主鍵。

    Example: Meeting Summary 對應到 Prepare 功能節點
      Given 圖譜具有下列功能
        | pk              | aliases         |
        | FEATURE#Prepare | Meeting Summary |
      And PR #42 的改版名稱如下
        | old_name        | new_name |
        | Meeting Summary | Prepare  |
      When 系統處理 PR #42 的 Release
      Then 改版對應的 Feature 主鍵為 "FEATURE#Prepare"

  # 來源：釐清 D06；設計 §9.2。
  @Missing
  Rule: 改名不變更第一次建立的 Feature 主鍵
    #TODO 原文沒有連續改名後 PK 保持不變的完整前後對照。
    # 改名只更新 name 與 aliases。

  # 來源：設計 §9.2；釐清 F15。
  @Missing
  Rule: alias 比對未命中時以向量搜尋最相近的 Feature
    #TODO 原文未提供候選 Feature、相似度或無合適候選時的結果。
    # 最相近 Feature 必須達 cosine 至少 0.85 才可用；門檻沿用分析工單的 demo 分群值。
    # 未達標不改版、不新建 Feature。

  # 來源：設計 §9.2、§10.1；釐清 F17。
  @Partial
  Rule: by_target 反查只選出引用改版 Feature 的步驟
    #TODO 多步或多篇命中的具體資料未提供；反查同時命中其他關係型別時的篩選方式待釐清。
    # 改寫只針對每篇目前已發布版本：published_at 非空且為該篇 current_version。
    # 歷史版與未發布版的命中只供追溯，不觸發改寫。

    Example: PR #42 只命中準備會議教學的第三步
      Given PR #42 將 "Meeting Summary" 改名為 "Prepare"
      And 三篇教學與該功能的引用資料如下
        | tutorial | topic    | referenced_feature | step |
        | A        | 準備會議 | FEATURE#Prepare    | 3    |
        | B        | 分享摘要 |                    |      |
        | C        | 設定通知 |                    |      |
      When 系統處理 PR #42 的 Release
      Then 命中的教學步驟集合為
        | tutorial | step |
        | A        | 3    |

  # 來源：設計 §9.2、§18。
  @Missing
  Rule: 反查為零或重大改名時使用 step 文字向量搜尋補漏
    #TODO 原文沒有零命中與重大改名的具體案例。
    # 只有 alias 比對失敗的 renamed 才算重大改名；此情況下即使已有 references 命中仍跑 safety_net。
    # alias 已命中的 renamed 不算重大改名。
    # 反查為零仍獨立觸發 safety_net，與是否重大改名無關。

  # 來源：設計 §9.2。
  @Missing
  Rule: safety_net 的疑似命中交給 Claude 確認
    #TODO 原文沒有候選步驟與確認或否決的結果。
    # 全數未確認、無候選或無法確認時，記錄此次未命中並以 KEEP 結束，不建立新版本。

  # 來源：設計 §9.2、§10、§10.1。
  @Partial
  Rule: renamed 或 changed 的改版動作為 UPDATE
    #TODO 原文未提供 kind = changed 的具體案例。

    Example: PR #42 的按鈕改名執行 UPDATE
      Given PR #42 將 "Meeting Summary" 改名為 "Prepare"
      And 改版命中教學 A 的第 3 步
      When 系統處理 PR #42 的 Release
      Then 教學 A 的改版動作為 "UPDATE"

  # 來源：設計 §9.2、§10、§20.C。
  @Missing
  Rule: kind 為 removed 的改版動作為 RETIRE
    #TODO 原文只有分支規則，沒有被移除 Feature 與受影響 Tutorial 的實例。

  # 來源：設計 §9.2、§10.1。
  @Partial
  Rule: UPDATE 只重寫受影響的步驟
    #TODO 原文沒有多步命中的案例。

    Example: PR #42 的重寫集合只有第三步
      Given PR #42 將 "Meeting Summary" 改名為 "Prepare"
      And 改版只命中教學 A 的第 3 步
      When 系統處理 PR #42 的 Release
      Then 教學 A 的重寫步驟集合為
        | step |
        | 3    |

  # 來源：設計 §9.2、§10.2。
  @Specified
  Rule: UPDATE 將未命中步驟的原文複製到下一版
    Example: 第三步改名時保留第一、二、四步文字
      Given PR #42 將 "Meeting Summary" 改名為 "Prepare"
      And 教學 A 的 v2 只有第 3 步引用該功能
      When 系統處理 PR #42 的 Release
      Then 教學 A 的 v3 與 v2 步驟文字比較結果為
        | step | text_equal |
        | 1    | true       |
        | 2    | true       |
        | 4    | true       |

  # 來源：設計 §10.1。
  @Specified
  Rule: 未引用改版 Feature 的教學維持 KEEP
    Example: PR #42 不改動分享摘要與設定通知教學
      Given PR #42 將 "Meeting Summary" 改名為 "Prepare"
      And 教學 B 與教學 C 沒有引用 "FEATURE#Prepare" 的邊
      When 系統處理 PR #42 的 Release
      Then 教學動作資料如下
        | tutorial | topic    | action |
        | B        | 分享摘要 | KEEP   |
        | C        | 設定通知 | KEEP   |

  # 來源：設計 §9.2、§10.1。
  @Partial
  Rule: UPDATE 為受影響教學產生與前版的 diff
    #TODO 原文未提供完整 diff 文字，僅有變更範圍與行數。

    Example: PR #42 的 diff 只包含第三步
      Given PR #42 將 "Meeting Summary" 改名為 "Prepare"
      And 教學 A 的 v2 只有第 3 步引用該功能
      When 系統處理 PR #42 的 Release
      Then 教學 A 的 v3 diff 範圍為
        | step |
        | 3    |

  # 來源：設計 §9.2。
  @Missing
  Rule: UPDATE 下一版的 reason 使用 release 加上改版事件 id
    #TODO PR #42、r42 與 r_... 在來源中沒有統一 ID 對應；不把 PR 號直接當 Release.id。
    # 格式：release:<id>。

  # 來源：設計 §9.2；釐清 D06。
  @Missing
  Rule: UPDATE 完成時更新 Feature 的 aliases
    #TODO 原文有改名後的 aliases，缺少更新前後完整清單。
    # 主鍵保持第一次建立的值，不因改名遷移。
    # 新 alias 若與其他 Feature 的 name 或 alias 衝突，拒絕該次 alias 更新。

  # 來源：設計 §9.2；ERD §2；釐清 D21。
  @Missing
  Rule: RETIRE 將受影響教學標記為過期
    #TODO 原文沒有 RETIRE 前後的 status 對照。
    # 資料狀態寫入 retired；obsolete 只作為同一狀態的顯示文字。

  # 來源：設計 §9.2、§20.B；釐清 D22、F19。
  @Missing
  Rule: RETIRE 的教學導向後繼 Tutorial
    #TODO 原文沒有 successor 範例。
    # 沒有後繼仍完成 RETIRE；顯示過期說明與原文，不產生導向。
    # successor 保持空。不卡住等待後繼。
    # 後繼由維護者選定既有 Tutorial，寫入 Tutorial.successor，值為裸 slug。
    # 未選定時依無後繼分支處理。來源事件不直接指定後繼。
