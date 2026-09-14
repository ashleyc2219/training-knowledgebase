# 來源：../draft/training-kb-design-doc.md §4、§5.2、§6、§9、§20.B。
# 來源：../draft/training-kb-erd.md §1、§2。
Feature: 發布教學版本
  Pipeline 完成教學版本建立後呼叫 publish，將指定 TutorialVersion 上架供使用者閱讀。

  # 來源：設計 §4、§9.1–§9.3、§20.B；釐清 D25。
  @Missing
  Rule: publish 上架指定的 TutorialVersion
    # published_at 空＝未發布；publish 成功才寫入非空 published_at。不加版本狀態機。
    # S3 已寫入但版本或關聯不完整的版本不可 publish。
    #TODO 原文沒有 publish 前後的讀取結果、版本 URL 或失敗範例。

  # 來源：設計 §5.2。
  @Missing
  Rule: 發布的教學透過 S3 靜態 docs 站提供
    # MVP 只提供 S3 靜態 docs 站，頁面包含版本化內容與 feedback widget。
    # 不另做 in-app 教學頁。
    #TODO 原文沒有可驗收的頁面與內容配對。

  # 來源：設計 §5.2。
  @Missing
  Rule: 發布的教學提供 feedback widget
    #TODO 原文只明示 widget，沒有介面、欄位必填性或提交結果的完整範例。

  # 來源：設計 §4；ERD §2。
  @Missing
  Rule: Tutorial 的 current_version 指向目前教學版本
    # publish 成功回傳時才切換 current_version；此時所需內容與關聯已完成寫入。
    # create_version 完成或 publish 失敗時不切換，讀者繼續看到舊的已發布版。
    #TODO 原文沒有切換前後的讀取結果。

  # 來源：ERD §2；釐清 D25。
  @Missing
  Rule: 已上架的版本具有 published_at
    # published_at 空＝未發布；publish 成功才寫入非空 published_at。不加版本狀態機。
    #TODO 原文只定義時間欄位，沒有時間值或失敗時的寫入規則。
