# Discovery 釐清總覽

本輪日期：2026-09-13。階段：clarify。以下 **0 項待釐清**；84 項已歸檔（資料 29、功能 55）。本輪互動釐清已結束。

## 掃描範圍與去重依據

- 主要規格：[erm.dbml](../erm.dbml) 的邏輯實體與 [features](../features) 的 Feature／Rule。D24 新增 TUTORIAL_VIEW。欄位可能另含 `cluster_id`、`source_event_id`（約 70）；Rule 可能微增。以規格檔為準，本檔未重數。
- 交叉核對：[設計文件](../draft/training-kb-design-doc.md)與[原始 ERD](../draft/training-kb-erd.md)；依 [2.discovery.md](../prompts/2.discovery.md) 完成 15 類、50 個檢查點。
- 開始掃描時 `.clarify/` 不存在，作用中的 `resolved/data/` 與 `resolved/features/` 均為 0 項。Git 中既有待刪除紀錄不視為目前答案，不復原、不沿用舊架構結論。
- 輸入 SHA-256 前 12 碼：設計 `dba01a464060`、ERD `fcb5aa0038e8`、ERM `ab7608466791`。來源行號均依本次檔案版本定位。

## 項目統計

| 類型 | High | Medium | Low | 合計 |
|---|---:|---:|---:|---:|
| 資料模型 | 0 | 0 | 0 | 0 |
| 功能模型 | 0 | 0 | 0 | 0 |
| 合計 | 0 | 0 | 0 | 0 |

```text
.clarify/
├── data/               # 0 個待處理資料問題
├── features/           # 0 個功能問題
├── resolved/data/      # 29 個已釐清資料問題
├── resolved/features/  # 55 個已釐清功能問題
└── overview.md         # 本總覽
```

`Dxx`、`Fxx` 是本輪追蹤 ID，分類由檔案所在目錄決定。每個問題保留完整問句、精確定位、互斥選項、影響與優先級；已解決項目另存於 `resolved/`，本表只保留待處理問題。

## 優先處理的阻塞點

- candidate 驗證鏈已釐清：[F26](resolved/features/提出教學規則_提出_candidate_是否必須先滿足弱教學門檻.md)（不必先滿足弱教學門檻）→ [F27](resolved/features/套用教學規則_candidate_規則如何取得驗證用的套用版本.md)（MVP 從明示種子試用版本匯入成效）→ [F30](resolved/features/驗證教學規則_candidate_升為_active_時兩項成效必須如何改善.md)（評分嚴格提高且重開票率嚴格下降）、[F31](resolved/features/驗證教學規則_未套用規則的對照版本如何選取.md)（同篇套用前版本對照）、[F32](resolved/features/驗證教學規則_規則驗證至少累積多少資料才可以改變狀態.md)（僅核定種子批次可改狀態）。已釐清 [F33](resolved/features/驗證教學規則_具備足夠資料後如何判定規則無效而退役.md)（連續兩個核定種子批次未改善才退役）。
- 8 vs 10：已釐清 [F20](resolved/features/定期檢視回饋_八筆回饋的_Demo_如何符合至少十筆的檢視門檻.md)（正式 n>=10，Demo 明示隔離 n>=8）、[F21](resolved/features/定期檢視回饋_recurring_Feedback_Category_的次數門檻是多少.md)（recurring 同類至少 5 筆）、[F25](resolved/features/提出教學規則_候選規則的五筆同類回饋可以跨哪些範圍累積.md)（五筆只在同一 TutorialVersion 累積）。
- 每日檢視：已釐清 [F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md)（只檢視 current_version，累計該版截至本次的全部有效回饋）。已釐清 [F23](resolved/features/定期檢視回饋_同一批回饋是否可以再次觸發_REFINE.md)（須有新有效證據才可再 REFINE）、[F24](resolved/features/定期檢視回饋_診斷找不到有效步驟時如何處理弱教學.md)（無可改步驟則不建新版）。
- 重開票：已釐清 [D23](resolved/data/FEEDBACK_如何識別看過教學後又開票的同一位使用者.md)（共用穩定使用者 ID）/[D24](resolved/data/TUTORIAL_VERSION_重開票率需要的教學瀏覽紀錄從哪裡取得.md)（瀏覽事件當分母）/[D29](resolved/data/TUTORIAL_同題重開票的教學與_cluster_對應以何者為準.md)（首版 `gap:<cluster_id>` 固定對應，落在 `Tutorial.cluster_id`）。來源中的 7→2 是筆數，不可直接當成比例。
- 功能改名與步驟引用的識別：已釐清 D04、D05、D06（PK 不因改名遷移）、[F15](resolved/features/依改版更新教學_向量搜尋取得的最相近_Feature_如何確認可用.md)（最相近 Feature 須 cosine >= 0.85）、[F17](resolved/features/依改版更新教學_反查到歷史版本步驟時是否納入改版.md)（只處理目前已發布版本步驟）。
- Rote 新流程成熟與 Feedback 成功條件：已釐清 [F03](resolved/features/接入來源事件_第二層重放是否沿用至少三次成功的門檻.md)（第二層亦須 active 且 `success_count >= 3`）、[F05](resolved/features/接入來源事件_新流程未達三次成功時如何累積驗證次數.md)（首次成功=1，同簽名完整成功才累加）、[F06](resolved/features/接入來源事件_Feedback_不啟動改版流程時如何認定接入成功.md)（Feedback 不進 PROC，固定保存即成功）。連敗已釐清 D20（連續失敗、成功歸零），重學見 [F53](resolved/features/接入來源事件_已退役簽名重新學到流程時如何保存新序列.md)。
- 版本併發、部分寫入與公開時點：已釐清 [D25](resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md)/[D26](resolved/data/TUTORIAL_VERSION_版本建立失敗後重試是否重用原版本號.md)。已釐清 [F35](resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md)（依接受順序串行）、[F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md)（未完成不可公開）、[F37](resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md)（publish 成功才切換）。

## 建議釐清順序

依賴優先於題號。第一、二階段先確定核心資料與行為；第三階段在可回答的項目中交錯資料與功能。資料題數較少，完成後繼續剩餘功能題，不為交錯而調低核心問題優先級。

### 第 1 階段：核心資料模型（剩餘 0 項）

| 順序 | 問題 | 前置依賴 |
|---:|---|---|
| 11 | [D18](resolved/data/AUTHORING_RULE_derived_from_可以記錄幾個來源版本.md) derived_from 可以記錄幾個來源版本？ | [D03](resolved/data/TUTORIAL_VERSION_關聯欄位使用裸識別碼還是帶前綴的主鍵.md) |
| 12 | [D19](resolved/data/PROVEN_WORKFLOW_same_sender_以哪個來源範圍識別流程.md) same_sender 以哪個來源範圍識別流程？ | 無 |
| 13 | [D20](resolved/data/PROVEN_WORKFLOW_fail_count_代表連續失敗還是累積失敗.md) fail_count 代表連續失敗還是累積失敗？ | 無 |
| 14 | [D21](resolved/data/TUTORIAL_RETIRE_之後的狀態應使用_retired_還是_obsolete.md) RETIRE 之後的狀態應使用 retired 還是 obsolete？ | 無 |
| 15 | [D22](resolved/data/TUTORIAL_後繼_Tutorial_的關係要持久化在哪裡.md) 後繼 Tutorial 的關係要持久化在哪裡？ | [D21](resolved/data/TUTORIAL_RETIRE_之後的狀態應使用_retired_還是_obsolete.md) |
| 16 | [D23](resolved/data/FEEDBACK_如何識別看過教學後又開票的同一位使用者.md) 如何識別看過教學後又開票的同一位使用者？ | 無 |
| 17 | [D24](resolved/data/TUTORIAL_VERSION_重開票率需要的教學瀏覽紀錄從哪裡取得.md) 重開票率需要的教學瀏覽紀錄從哪裡取得？ | [D23](resolved/data/FEEDBACK_如何識別看過教學後又開票的同一位使用者.md) |
| 18 | [D25](resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md) 尚未發布的版本如何與已發布版本區分？ | 無 |
| 19 | [D26](resolved/data/TUTORIAL_VERSION_版本建立失敗後重試是否重用原版本號.md) 版本建立失敗後重試是否重用原版本號？ | [D25](resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md) |
| 20 | [D27](resolved/data/AUTHORING_RULE_跨專案共享規則可以暴露哪些回饋證據.md) 跨專案共享規則可以暴露哪些回饋證據？ | [D18](resolved/data/AUTHORING_RULE_derived_from_可以記錄幾個來源版本.md) |
| 21 | [D29](resolved/data/TUTORIAL_同題重開票的教學與_cluster_對應以何者為準.md) 同題重開票的教學與 cluster 對應以何者為準？ | [D04](resolved/data/TICKET_一張_Ticket_可以對應幾個_Feature.md) |

### 第 2 階段：核心功能規則（剩餘 0 項）

| 順序 | 問題 | 前置依賴 |
|---:|---|---|
| 1 | [F02](resolved/features/接入來源事件_STABLE_KEYS_白名單依哪個範圍定義.md) STABLE_KEYS 白名單依哪個範圍定義？ | 無 |
| 2 | [F03](resolved/features/接入來源事件_第二層重放是否沿用至少三次成功的門檻.md) 第二層重放是否沿用至少三次成功的門檻？ | [D19](resolved/data/PROVEN_WORKFLOW_same_sender_以哪個來源範圍識別流程.md) |
| 3 | [F05](resolved/features/接入來源事件_新流程未達三次成功時如何累積驗證次數.md) 新流程未達三次成功時如何累積驗證次數？ | [F03](resolved/features/接入來源事件_第二層重放是否沿用至少三次成功的門檻.md) |
| 4 | [F06](resolved/features/接入來源事件_Feedback_不啟動改版流程時如何認定接入成功.md) Feedback 不啟動改版流程時如何認定接入成功？ | 無 |
| 5 | [F08](resolved/features/接入來源事件_非_GitHub_事件在_MVP_由哪個可信入口接收.md) 非 GitHub 事件在 MVP 由哪個可信入口接收？ | 無 |
| 6 | [F09](resolved/features/接入來源事件_同一正規化事件重送時是否再次觸發_pipeline.md) 同一正規化事件重送時是否再次觸發 pipeline？ | [D02](resolved/data/TICKET_來源事件的正規化識別碼如何保證唯一.md) |
| 7 | [F13](resolved/features/分析工單_Knowledge_Gap_無法對應既有_Feature_時如何處理.md) Knowledge Gap 無法對應既有 Feature 時如何處理？ | [D04](resolved/data/TICKET_一張_Ticket_可以對應幾個_Feature.md)、[D05](resolved/data/TUTORIAL_STEP_一個教學步驟可以引用幾個_Feature.md) |
| 8 | [F14](resolved/features/依改版更新教學_一則改版包含多個_Feature_變更時如何表示.md) 一則改版包含多個 Feature 變更時如何表示？ | [D02](resolved/data/TICKET_來源事件的正規化識別碼如何保證唯一.md)、[D10](resolved/data/RELEASE_Release_接入必填欄位採哪套契約.md) |
| 9 | [F15](resolved/features/依改版更新教學_向量搜尋取得的最相近_Feature_如何確認可用.md) 向量搜尋取得的最相近 Feature 如何確認可用？ | [D06](resolved/data/FEATURE_功能改名時哪個識別碼必須保持不變.md) |
| 10 | [F17](resolved/features/依改版更新教學_反查到歷史版本步驟時是否納入改版.md) 反查到歷史版本步驟時是否納入改版？ | [D25](resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md) |
| 11 | [F20](resolved/features/定期檢視回饋_八筆回饋的_Demo_如何符合至少十筆的檢視門檻.md) 八筆回饋的 Demo 如何符合至少十筆的檢視門檻？ | 無 |
| 12 | [F21](resolved/features/定期檢視回饋_recurring_Feedback_Category_的次數門檻是多少.md) recurring Feedback Category 的次數門檻是多少？ | [D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md) |
| 13 | [F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md) 每日檢視使用哪些版本與時間範圍的回饋？ | [D25](resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md)、[F20](resolved/features/定期檢視回饋_八筆回饋的_Demo_如何符合至少十筆的檢視門檻.md)、[F21](resolved/features/定期檢視回饋_recurring_Feedback_Category_的次數門檻是多少.md) |
| 14 | [F25](resolved/features/提出教學規則_候選規則的五筆同類回饋可以跨哪些範圍累積.md) 候選規則的五筆同類回饋可以跨哪些範圍累積？ | [D18](resolved/data/AUTHORING_RULE_derived_from_可以記錄幾個來源版本.md)、[D27](resolved/data/AUTHORING_RULE_跨專案共享規則可以暴露哪些回饋證據.md)、[D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md) |
| 15 | [F26](resolved/features/提出教學規則_提出_candidate_是否必須先滿足弱教學門檻.md) 提出 candidate 是否必須先滿足弱教學門檻？ | [F20](resolved/features/定期檢視回饋_八筆回饋的_Demo_如何符合至少十筆的檢視門檻.md)、[F21](resolved/features/定期檢視回饋_recurring_Feedback_Category_的次數門檻是多少.md)、[F25](resolved/features/提出教學規則_候選規則的五筆同類回饋可以跨哪些範圍累積.md) |
| 16 | [F27](resolved/features/套用教學規則_candidate_規則如何取得驗證用的套用版本.md) candidate 規則如何取得驗證用的套用版本？ | [D17](resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md)、[F26](resolved/features/提出教學規則_提出_candidate_是否必須先滿足弱教學門檻.md) |
| 17 | [F30](resolved/features/驗證教學規則_candidate_升為_active_時兩項成效必須如何改善.md) candidate 升為 active 時兩項成效必須如何改善？ | [D23](resolved/data/FEEDBACK_如何識別看過教學後又開票的同一位使用者.md)、[D24](resolved/data/TUTORIAL_VERSION_重開票率需要的教學瀏覽紀錄從哪裡取得.md) |
| 18 | [F31](resolved/features/驗證教學規則_未套用規則的對照版本如何選取.md) 未套用規則的對照版本如何選取？ | [D27](resolved/data/AUTHORING_RULE_跨專案共享規則可以暴露哪些回饋證據.md) |
| 19 | [F32](resolved/features/驗證教學規則_規則驗證至少累積多少資料才可以改變狀態.md) 規則驗證至少累積多少資料才可以改變狀態？ | [F30](resolved/features/驗證教學規則_candidate_升為_active_時兩項成效必須如何改善.md)、[F31](resolved/features/驗證教學規則_未套用規則的對照版本如何選取.md)、[D29](resolved/data/TUTORIAL_同題重開票的教學與_cluster_對應以何者為準.md) |
| 20 | [F35](resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md) 同篇教學的 Release 與 Feedback 改版同時執行時如何排序？ | [D26](resolved/data/TUTORIAL_VERSION_版本建立失敗後重試是否重用原版本號.md) |
| 21 | [F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md) 內容已寫入但版本關聯不完整時如何處理？ | [D17](resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md)、[D25](resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md) |
| 22 | [F37](resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md) current_version 在哪個時點切換到新版？ | [D25](resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md)、[F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md) |
| 23 | [F38](resolved/features/發布教學版本_MVP_的教學發布入口採用哪一種形式.md) MVP 的教學發布入口採用哪一種形式？ | 無 |
| 24 | [F49](resolved/features/執行教學流程_Task_重試耗盡並進入_Catch_後如何結束流程.md) Task 重試耗盡並進入 Catch 後如何結束流程？ | 無 |

### 第 3 階段：邊界條件與跨模型關聯（剩餘 12 項）

| 順序 | 問題 | 前置依賴 |
|---:|---|---|
| 1 | [D07](resolved/data/FEATURE_同一查詢範圍內的_alias_撞名時如何處理.md) 同一查詢範圍內的 alias 撞名時如何處理？ | [D06](resolved/data/FEATURE_功能改名時哪個識別碼必須保持不變.md) |
| 2 | [F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md) 缺少原始 Example 的規則以哪種資料補齊驗收？ | 無 |
| 3 | [D08](resolved/data/TICKET_Ticket_向量以_embedding_還是_embedding_ref_為準.md) Ticket 向量以 embedding 還是 embedding_ref 為準？ | 無 |
| 4 | [F04](resolved/features/接入來源事件_多個同寄件者流程達重疊門檻時選哪一個.md) 多個同寄件者流程達重疊門檻時選哪一個？ | [D19](resolved/data/PROVEN_WORKFLOW_same_sender_以哪個來源範圍識別流程.md)、[F03](resolved/features/接入來源事件_第二層重放是否沿用至少三次成功的門檻.md) |
| 5 | [D11](resolved/data/FEEDBACK_Feedback_是否允許沒有穩定的使用者識別碼.md) Feedback 是否允許沒有穩定的使用者識別碼？ | 無 |
| 6 | [F07](resolved/features/接入來源事件_Agent_最終仍無法產出合法物件時如何處置事件.md) Agent 最終仍無法產出合法物件時如何處置事件？ | [D09](resolved/data/TICKET_Ticket_接入驗證的必填欄位採哪套契約.md)、[D10](resolved/data/RELEASE_Release_接入必填欄位採哪套契約.md) |
| 7 | [D12](resolved/data/FEEDBACK_只有評分而沒有類別與留言的回饋是否有效.md) 只有評分而沒有類別與留言的回饋是否有效？ | 無 |
| 8 | [F10](resolved/features/分析工單_cosine_門檻以哪種群代表判斷_Ticket_歸群.md) cosine 門檻以哪種群代表判斷 Ticket 歸群？ | 無 |
| 9 | [D14](resolved/data/FEEDBACK_同一使用者對同一版本多次回饋計為幾筆.md) 同一使用者對同一版本多次回饋計為幾筆？ | [D02](resolved/data/TICKET_來源事件的正規化識別碼如何保證唯一.md)、[D11](resolved/data/FEEDBACK_Feedback_是否允許沒有穩定的使用者識別碼.md) |
| 10 | [F11](resolved/features/分析工單_recurring_的十四天窗口以哪個時間為基準.md) recurring 的十四天窗口以哪個時間為基準？ | [D09](resolved/data/TICKET_Ticket_接入驗證的必填欄位採哪套契約.md) |
| 11 | [D15](resolved/data/AUTHORING_RULE_規則_evidence_使用識別碼清單還是含類別的物件.md) 規則 evidence 使用識別碼清單還是含類別的物件？ | [D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md) |
| 12 | [F12](resolved/features/分析工單_判定已有教學時哪些_Tutorial_狀態算有效.md) 判定已有教學時哪些 Tutorial 狀態算有效？ | [D21](resolved/data/TUTORIAL_RETIRE_之後的狀態應使用_retired_還是_obsolete.md)、[D25](resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md) |
| 13 | [D16](resolved/data/AUTHORING_RULE_applies_when_的可表達條件範圍為何.md) applies_when 的可表達條件範圍為何？ | 無 |
| 14 | [F16](resolved/features/依改版更新教學_哪種改名算必須執行_safety_net_的重大改名.md) 哪種改名算必須執行 safety_net 的重大改名？ | 無 |
| 15 | [D28](resolved/data/TUTORIAL_VERSION_REFINE_版本的_reason_採用哪種標準格式.md) REFINE 版本的 reason 採用哪種標準格式？ | [D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md) |
| 16 | [F18](resolved/features/依改版更新教學_safety_net_沒有確認任何步驟時如何結束.md) safety_net 沒有確認任何步驟時如何結束？ | [F15](resolved/features/依改版更新教學_向量搜尋取得的最相近_Feature_如何確認可用.md)、[F16](resolved/features/依改版更新教學_哪種改名算必須執行_safety_net_的重大改名.md) |
| 17 | [F19](resolved/features/依改版更新教學_退役時沒有後繼_Tutorial_要呈現什麼結果.md) 退役時沒有後繼 Tutorial 要呈現什麼結果？ | [D21](resolved/data/TUTORIAL_RETIRE_之後的狀態應使用_retired_還是_obsolete.md)、[D22](resolved/data/TUTORIAL_後繼_Tutorial_的關係要持久化在哪裡.md) |
| 18 | [F23](resolved/features/定期檢視回饋_同一批回饋是否可以再次觸發_REFINE.md) 同一批回饋是否可以再次觸發 REFINE？ | [F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md) |
| 19 | [F24](resolved/features/定期檢視回饋_診斷找不到有效步驟時如何處理弱教學.md) 診斷找不到有效步驟時如何處理弱教學？ | [F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md) |
| 20 | [F28](resolved/features/套用教學規則_多條相互衝突的_active_規則同時適用時如何選擇.md) 多條相互衝突的 active 規則同時適用時如何選擇？ | [D16](resolved/data/AUTHORING_RULE_applies_when_的可表達條件範圍為何.md) |
| 21 | [F29](resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md) 未改寫步驟沿用的規則是否算新版的套用紀錄？ | [D17](resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md) |
| 22 | [F33](resolved/features/驗證教學規則_具備足夠資料後如何判定規則無效而退役.md) 具備足夠資料後如何判定規則無效而退役？ | [F30](resolved/features/驗證教學規則_candidate_升為_active_時兩項成效必須如何改善.md)、[F32](resolved/features/驗證教學規則_規則驗證至少累積多少資料才可以改變狀態.md) |
| 23 | [F34](resolved/features/驗證教學規則_合併相近規則時如何保留規則識別與歷史.md) 合併相近規則時如何保留規則識別與歷史？ | [D17](resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md)、[D18](resolved/data/AUTHORING_RULE_derived_from_可以記錄幾個來源版本.md) |
| 24 | [F39](resolved/features/收集教學回饋_已退役教學的既有版本是否仍接受回饋.md) 已退役教學的既有版本是否仍接受回饋？ | [D21](resolved/data/TUTORIAL_RETIRE_之後的狀態應使用_retired_還是_obsolete.md)、[F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md) |
| 25 | [F40](resolved/features/查詢知識圖譜_backfill_發現既有_Feature_引用錯誤時如何更新.md) backfill 發現既有 Feature 引用錯誤時如何更新？ | [D05](resolved/data/TUTORIAL_STEP_一個教學步驟可以引用幾個_Feature.md)、[F17](resolved/features/依改版更新教學_反查到歷史版本步驟時是否納入改版.md) |
| 26 | [F41](resolved/features/檢視學習指標_重開票率是否要求瀏覽發生在再次開票之前.md) 重開票率是否要求瀏覽發生在再次開票之前？ | [D23](resolved/data/FEEDBACK_如何識別看過教學後又開票的同一位使用者.md)、[D24](resolved/data/TUTORIAL_VERSION_重開票率需要的教學瀏覽紀錄從哪裡取得.md)、[D29](resolved/data/TUTORIAL_同題重開票的教學與_cluster_對應以何者為準.md) |
| 27 | [F42](resolved/features/檢視學習指標_沒有可識別瀏覽者時重開票率如何顯示.md) 沒有可識別瀏覽者時重開票率如何顯示？ | [D23](resolved/data/FEEDBACK_如何識別看過教學後又開票的同一位使用者.md)、[D24](resolved/data/TUTORIAL_VERSION_重開票率需要的教學瀏覽紀錄從哪裡取得.md)、[D29](resolved/data/TUTORIAL_同題重開票的教學與_cluster_對應以何者為準.md) |
| 28 | [F43](resolved/features/檢視學習指標_哪些_Feedback_Category_應算入負面回饋.md) 哪些 Feedback Category 應算入負面回饋？ | [D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md) |
| 29 | [F44](resolved/features/檢視學習指標_跨版本比較平均評分時採用哪種加權方式.md) 跨版本比較平均評分時採用哪種加權方式？ | [F31](resolved/features/驗證教學規則_未套用規則的對照版本如何選取.md) |
| 30 | [F45](resolved/features/檢視學習指標_Bedrock_呼叫數是否計入重試與_Map_的每次呼叫.md) Bedrock 呼叫數是否計入重試與 Map 的每次呼叫？ | 無 |
| 31 | [F46](resolved/features/檢視學習指標_seeded_Demo_指標採現算結果還是固定展示值.md) seeded Demo 指標採現算結果還是固定展示值？ | [D24](resolved/data/TUTORIAL_VERSION_重開票率需要的教學瀏覽紀錄從哪裡取得.md) |
| 32 | [F47](resolved/features/檢視學習指標_Tutorial_B_的規則開關對照是否會影響正式上架版本.md) Tutorial B 的規則開關對照是否會影響正式上架版本？ | [F27](resolved/features/套用教學規則_candidate_規則如何取得驗證用的套用版本.md)、[F38](resolved/features/發布教學版本_MVP_的教學發布入口採用哪一種形式.md) |
| 33 | [F48](resolved/features/執行教學流程_LLM_輸出通過_schema_但違反業務規則時如何處理.md) LLM 輸出通過 schema 但違反業務規則時如何處理？ | 無 |
| 34 | [F51](resolved/features/收集教學回饋_不合法回饋要向提交者回傳哪種處理結果.md) 不合法回饋要向提交者回傳哪種處理結果？ | [D11](resolved/data/FEEDBACK_Feedback_是否允許沒有穩定的使用者識別碼.md)、[D12](resolved/data/FEEDBACK_只有評分而沒有類別與留言的回饋是否有效.md)、[D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md) |
| 35 | [F53](resolved/features/接入來源事件_已退役簽名重新學到流程時如何保存新序列.md) 已退役簽名重新學到流程時如何保存新序列？ | [D20](resolved/data/PROVEN_WORKFLOW_fail_count_代表連續失敗還是累積失敗.md)、[F05](resolved/features/接入來源事件_新流程未達三次成功時如何累積驗證次數.md) |
| 36 | [F54](resolved/features/依改版更新教學_退役教學的後繼_Tutorial_由哪個來源指定.md) 退役教學的後繼 Tutorial 由哪個來源指定？ | [D22](resolved/data/TUTORIAL_後繼_Tutorial_的關係要持久化在哪裡.md) |
| 37 | [F55](resolved/features/驗證教學規則_candidate_與既有規則的衝突由誰判定.md) candidate 與既有規則的衝突由誰判定？ | [D16](resolved/data/AUTHORING_RULE_applies_when_的可表達條件範圍為何.md) |

### 第 4 階段：細節與低風險輸出（剩餘 2 項）

| 順序 | 問題 | 前置依賴 |
|---:|---|---|
| 1 | [F50](resolved/features/建立教學版本_第一版沒有前版時_diff_檔案如何表示.md) 第一版沒有前版時 diff 檔案如何表示？ | 無 |
| 2 | [F52](resolved/features/檢視學習指標_版本沒有任何有效評分時平均評分如何呈現.md) 版本沒有任何有效評分時平均評分如何呈現？ | 無 |

### 可連續處理的主題

| 主題 | 建議串接 |
|---|---|
| 識別、隔離與引用 | 已歸檔 5 項。已釐清 F13（對不到 Feature 則保留 gap）。[D06](resolved/data/FEATURE_功能改名時哪個識別碼必須保持不變.md)、[D07](resolved/data/FEATURE_同一查詢範圍內的_alias_撞名時如何處理.md) |
| 回饋輸入與聚合 | 已釐清 [F20](resolved/features/定期檢視回饋_八筆回饋的_Demo_如何符合至少十筆的檢視門檻.md)（正式 n>=10／Demo n>=8）、[F21](resolved/features/定期檢視回饋_recurring_Feedback_Category_的次數門檻是多少.md)（同類 5 筆）、[F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md)（只看 current_version 累計回饋）、[F25](resolved/features/提出教學規則_候選規則的五筆同類回饋可以跨哪些範圍累積.md)（同 TutorialVersion）、[F26](resolved/features/提出教學規則_提出_candidate_是否必須先滿足弱教學門檻.md)（不必先滿足弱教學門檻）。[D11](resolved/data/FEEDBACK_Feedback_是否允許沒有穩定的使用者識別碼.md)、[D12](resolved/data/FEEDBACK_只有評分而沒有類別與留言的回饋是否有效.md)、[D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md)、[D14](resolved/data/FEEDBACK_同一使用者對同一版本多次回饋計為幾筆.md)、[F23](resolved/features/定期檢視回饋_同一批回饋是否可以再次觸發_REFINE.md) |
| 規則試用與效果 | 已釐清 D17、D18、D27、[F27](resolved/features/套用教學規則_candidate_規則如何取得驗證用的套用版本.md)（種子試用版本匯入成效）、[F30](resolved/features/驗證教學規則_candidate_升為_active_時兩項成效必須如何改善.md)（評分嚴格提高且重開票率嚴格下降）、[F31](resolved/features/驗證教學規則_未套用規則的對照版本如何選取.md)（同篇套用前版本對照）、[F32](resolved/features/驗證教學規則_規則驗證至少累積多少資料才可以改變狀態.md)（僅核定種子批次可改狀態）。已釐清 [F29](resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md)（只記本次注入）、[F33](resolved/features/驗證教學規則_具備足夠資料後如何判定規則無效而退役.md)（連續兩批次未改善才退役）、[F34](resolved/features/驗證教學規則_合併相近規則時如何保留規則識別與歷史.md)（MVP 只建相近群組）。[F55](resolved/features/驗證教學規則_candidate_與既有規則的衝突由誰判定.md) |
| Rote 重放與失敗 | 已釐清 D19、D20、F02、F03、F05、F06、F08、F09。[F04](resolved/features/接入來源事件_多個同寄件者流程達重疊門檻時選哪一個.md)、[F07](resolved/features/接入來源事件_Agent_最終仍無法產出合法物件時如何處置事件.md)、[F53](resolved/features/接入來源事件_已退役簽名重新學到流程時如何保存新序列.md) |
| 改版與發布 | 已釐清 D21、D22、D25、D26、F14、F15、[F17](resolved/features/依改版更新教學_反查到歷史版本步驟時是否納入改版.md)。已釐清 [F19](resolved/features/依改版更新教學_退役時沒有後繼_Tutorial_要呈現什麼結果.md)（無後繼仍 RETIRE，不導向）。[F35](resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md)、[F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md)、[F37](resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md)、[F38](resolved/features/發布教學版本_MVP_的教學發布入口採用哪一種形式.md)、[F54](resolved/features/依改版更新教學_退役教學的後繼_Tutorial_由哪個來源指定.md) |
| 指標與示範證據 | 已釐清 D23（共用穩定使用者 ID）、D24（新增瀏覽事件）、D29（首版 `gap:<cluster_id>` 固定對應）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)、[F41](resolved/features/檢視學習指標_重開票率是否要求瀏覽發生在再次開票之前.md)、[F42](resolved/features/檢視學習指標_沒有可識別瀏覽者時重開票率如何顯示.md)、[F43](resolved/features/檢視學習指標_哪些_Feedback_Category_應算入負面回饋.md)、[F44](resolved/features/檢視學習指標_跨版本比較平均評分時採用哪種加權方式.md)、[F45](resolved/features/檢視學習指標_Bedrock_呼叫數是否計入重試與_Map_的每次呼叫.md)、[F46](resolved/features/檢視學習指標_seeded_Demo_指標採現算結果還是固定展示值.md)、[F47](resolved/features/檢視學習指標_Tutorial_B_的規則開關對照是否會影響正式上架版本.md)、[F52](resolved/features/檢視學習指標_版本沒有任何有效評分時平均評分如何呈現.md) |

這些是整理主題，不是要求一次回答整組。D24 已改為新增瀏覽事件，F41、F42、F46 仍須作答，不可默選。選到需要類別表、白名單、門檻或配對條件的選項時，補完該契約才算解決。

## 分類與逐項覆蓋摘要

分類狀態描述輸入規格的完備程度，不表示本輪已補齊實作。題數以問題的主要分類與跨領域標記計算，同一問題可出現在多類，不能將本表加總當成總題數。

| 分類 | 狀態 | 逐項檢查 | 相關問題數 | 判斷依據 |
|---|---|---|---:|---|
| A1 實體完整性 | Partial | 核心概念建模：Partial；實體命名：Clear；隱含實體：Missing | 8 | 十實體與用途已明確；後繼關係已落地為可空 successor。已釐清 D23／D24：共用穩定使用者 ID，並新增 TUTORIAL_VIEW。已釐清 D29：教學以首版 `gap:<cluster_id>` 固定對應，落在 `Tutorial.cluster_id`。已釐清 F13：對不到 Feature 則保留 gap、不建 Tutorial。Knowledge Gap 暫以 cluster_id 表達，沒有據此自行增加實體。 |
| A2 屬性定義 | Partial | 原始型別投影：Clear；note 存在：Clear；屬性語意與命名：Partial | 8 | 欄位可能另含 `cluster_id`、`source_event_id`（約 70）；以規格檔為準，本檔未重數。List、Map、timestamp 用 string 表達是 formulation 投影。已釐清 D15（evidence 只存 Feedback ID 清單）、D16（applies_when 單一 step.type）、D28（REFINE reason 用 `feedback:<n> 則 <category>`）。裸 ID、瀏覽事件 PK 與向量欄位仍需一致。 |
| A3 屬性值邊界 | Partial | 數值範圍：Partial；最小與最大：Partial；臨界值：Partial；空值零值負值：Partial | 18 | rating 1..5、向量 1024 維等已定義；published_at 空＝未發布已釐清。必填集合、空留言與零分母仍需決策。一般字串長度、ID 字元及時間編碼列 P04，沒有自行指定任意上限。 |
| A4 跨屬性不變條件 | Partial | 計算關係：Partial；衍生公式：Partial；多屬性限制：Partial | 32 | 五個識別碼衍生投影及 sk=REFERENCES#+target 已清楚；群歸屬已釐清 D29。已釐清 F30／F31 的啟用比較方式。跨版加權仍待 F44。 |
| A5 關係與唯一性 | Partial | 關聯基數：Partial；主鍵唯一性：Partial；邏輯參照：Partial | 22 | 11 個 Ref 可解析且指向存在欄位；Ticket 的 asks_about 因原始基數衝突刻意未補 Ref。後繼關係與瀏覽事件對版本的 Ref 已落地。改名與來源版本的剩餘影響見待釐清題。 |
| A6 生命週期與狀態 | Partial | 全部狀態：Partial；合法轉換：Partial；初始與終止：Partial | 23 | Tutorial 與 PROC 的 active/retired 已統一；obsolete 只是 retired 的顯示文字。published_at 空／非空區分未發布與已上架；失敗重試重用原版號。已釐清 F03／F05：第二層亦須 active 且 `success_count >= 3`；首次成功=1，同簽名完整成功才累加。已釐清 F26／F27／F30／F31／F32：不必先達弱教學門檻；MVP 從明示種子試用版本匯入成效；評分嚴格提高且重開票率嚴格下降才啟用；對照取同篇套用前版本；僅核定種子批次可改狀態。已釐清 F33：連續兩個核定種子批次未達 F30 改善判準才退役。 |
| B1 功能識別 | Partial | 交互點完整：Partial；交互時機存在：Clear；功能命名：Clear；功能界線：Partial | 19 | 13 個 Feature 都有事件、排程或操作觸發。已新增瀏覽事件契約。已釐清 F06／F08：Feedback 固定保存即成功且不進 PROC；MVP 僅一個 GitHub webhook，其餘手動上傳。已釐清 F38：MVP 只提供 S3 靜態 docs 站。已釐清 F26：提出 candidate 不必先滿足弱教學門檻。 |
| B2 規則完整性 | Partial | 每功能至少一條 Rule：Clear；單一規則原子性：Clear；前置條件個別列示：Clear；後置條件個別列示：Clear；必要前置條件完整：Partial；狀態變更完整：Partial；可驗證描述：Partial | 37 | 現有 Rule 以單一行為或資料契約切分；以規格檔為準，本檔未重數。缺口集中在 schema、失敗支線、併發、發布與規則退役判準。已釐清 F30／F31／F32／F33 的啟用與退役條件。 |
| B3 Example 覆蓋度 | Partial | 每條至少一例：Missing；現有 Given-When-Then 語法：Clear；缺例保留 TODO：Clear | 3 | 22 條 Rule 各有一例，115 條沒有 Example 且保留 @Missing 與 #TODO。10 條 @Partial 有例但仍缺資料或輸出。F01 決定資料來源，不能代替實際補例。 |
| B4 邊界覆蓋 | Partial | 數值：Partial；組合：Partial；類別：Partial；時間：Partial；狀態：Partial | 46 | 現有示範集中於 R-007 與 A 的改名。已釐清 F09（同一事件只處理一次）、F14（多變更拆子 Release）、F15（cosine >= 0.85）、F17（只改已發布 current_version）、F20（正式 n>=10／Demo n>=8）、F21（同類 5 筆）、F22（只看 current_version 累計回饋）。等於門檻、差一筆、平手、未發布與退役等案例仍不足。 |
| B5 錯誤與異常 | Partial | 前置失敗行為：Partial；異常規則與例子：Partial；錯誤回饋：Missing | 21 | GitHub 無簽名拒絕、Rote 回退與三次連敗退役已明確。已釐清 F13：對不到 Feature 則保留 gap、不建 Tutorial。已釐清 F24（無可改步驟不建新版）、F36（未完成不可公開）、F49（Catch 後整次失敗不發布）。最終正規化失敗與 widget 錯誤回饋仍需決策。 |
| C1 詞彙表 | Clear | 標準詞彙表：Clear；核心概念命名：Clear | 0 | 設計 §4、§4.1、§4.2 與附錄 D 已區分 TutorialStep、Step Functions state、Rote step 及三種記憶；沿用既有詞彙，不另建同義名詞。Category 合法值屬 A3，另由 D13 處理。 |
| C2 術語衝突 | Partial | 同義詞混用：Partial；同名異義：Partial；棄用或統一名稱：Partial | 9 | obsolete/retired 已統一。已釐清 F06：Feedback 成功＝固定保存，不進 PROC。裸 ID/PK 與「呼叫數」仍需統一。已釐清 F27：正式寫作不自動試用 candidate。舊架構文檔不作本輪規格的替代答案，見 P08。 |
| D1 待決事項 | Partial | TODO 與未決項盤點：Partial；影響評估：Clear | 3 | TODO 保持未解，全部納入逐 Rule 對照或 P01–P08 延後理由。每個問題均具定位、影響、優先級與必要前置依賴。 |
| D2 模糊描述 | Partial | 未量化用語：Partial；應該或可能的決策：Partial | 6 | 已釐清 F15（最相近須 cosine >= 0.85）、F21（recurring 同類至少 5 筆）與 F30（評分嚴格提高且重開票率嚴格下降）。已釐清 F16（alias 失敗才算重大改名）與 F33（連續兩批次未改善才退役）。已釐清 F34（MVP curation 只建相近群組供人工檢視）。路線與預算的選配細節留給規劃。 |

## 資料欄位覆蓋

以下列出掃描時的欄位；本批決策可能另增 `Tutorial.cluster_id`、`Release.source_event_id`（約 70）。以規格檔為準，本檔未重數。題目依主實體列示，跨實體影響可沿各問題的定位追蹤。已確定的 PK 投影、向量維度、rating 範圍、各 pipeline 寫入責任與 REFERENCES 結構不再重問。

| 實體 | 已掃描欄位 | 主要資料問題 |
|---|---|---|
| TUTORIAL | `pk`、`slug`、`current_version`、`topic`、`feature_ids`、`status`、`successor`、`cluster_id` | 已釐清 D21、D22、D29（首版 `gap:<cluster_id>` 固定對應） |
| TUTORIAL_VERSION | `pk`、`version_id`、`slug`、`supersedes`、`reason`、`rules_applied`、`s3_key`、`published_at` | 已釐清 D24、D25、D26、D28（REFINE reason 用 `feedback:<n> 則 <category>`） |
| TUTORIAL_VIEW | `pk`、`tutorial_version`、`user`、`ts` | 已釐清 D23、D24。PK 格式未指定。 |
| TUTORIAL_STEP | `pk`、`tutorial_version`、`sk`、`target`、`type`、`text` | 已釐清 D05：每步恰好一個 Feature |
| FEATURE | `pk`、`name`、`aliases`、`first_seen` | 已釐清 D06。[D07](resolved/data/FEATURE_同一查詢範圍內的_alias_撞名時如何處理.md) |
| TICKET | `pk`、`id`、`source`、`text`、`author`、`ts`、`project_id`、`embedding_ref`、`cluster_id`、`feature_ids`、`embedding` | 已釐清 D09；D23 覆寫 author 為接入必填。[D08](resolved/data/TICKET_Ticket_向量以_embedding_還是_embedding_ref_為準.md) |
| RELEASE | `pk`、`id`、`source`、`feature`、`kind`、`old_name`、`new_name`、`evidence`、`ts`、`source_event_id` | 已釐清 D10、F14（子 Release 共用父來源事件 ID） |
| FEEDBACK | `pk`、`id`、`tutorial_version`、`rating`、`category`、`comment`、`user`、`ts` | 已釐清 D13、D23（user 接入必填，與 Ticket.author、TUTORIAL_VIEW.user 同一 ID）。[D11](resolved/data/FEEDBACK_Feedback_是否允許沒有穩定的使用者識別碼.md)、[D12](resolved/data/FEEDBACK_只有評分而沒有類別與留言的回饋是否有效.md)、[D14](resolved/data/FEEDBACK_同一使用者對同一版本多次回饋計為幾筆.md) |
| AUTHORING_RULE | `pk`、`rule_id`、`rule`、`applies_when`、`evidence`、`status`、`applied_to`、`derived_from` | 已釐清 D17、D18、D27、D15（evidence 只存 Feedback ID 清單）、D16（applies_when 單一 step.type） |
| PROVEN_WORKFLOW | `pk`、`steps`、`keys`、`success_count`、`fail_count`、`status`、`last_used` | 已釐清 D19、D20 |

## Example 缺口與補例策略

現有 22 個 Example、77 個 Step；來源標記為 12 條 `@Specified`、10 條 `@Partial`、115 條 `@Missing`。每個 Missing Rule 皆保留 `#TODO`。`@Missing` 通常表示缺少可引用例子，不能直接解讀為該條業務規則沒有定義。

[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md) 只決定驗收資料來源；下列資料仍須實際提供或核准後補成 Given-When-Then。既有 22 個例子也仍需檢查輸出完整性與邊界。此次 discovery 不產生假的原始 payload、不改標記、不宣稱 Example 覆蓋完成。

| 功能 | 需要補齊的驗收資料與邊界 |
|---|---|
| 接入來源事件 | 三種原始事件到正規化物件的完整 fixture；正確、缺少與錯誤 GitHub 簽名；只改 ID、時間與標題時簽名不變；增加選填 key；Jaccard 0.7999/0.8/0.8001 與平手；success_count 0/1/2/3；失敗與成功交錯；JSONPath 缺值或無唯一對應；validate、保存或啟動失敗；同事件重送。 |
| 分析工單 | 1024 維向量及不合法維度；F10 選定算法的臨界相似矩陣；4/5/6 筆與十四天端點；同 Feature 有、無、待發布或退役教學；無 Feature 對應；新教學五段完整內容與每步 0/1/多引用；20 則 seeded Ticket 的原始內容。 |
| 依改版更新教學 | PR #42 原文、A 修改前後完整步驟與完整 diff；B、C 未變斷言；renamed/changed/removed；alias 撞名；歷史與目前版本同時有引用時只改已發布 current_version；多功能改版；反查零筆、疑似全否定、重大改名；無後繼、無效後繼及導向循環。 |
| 收集教學回饋 | rating 0/1/2/5/6 與非整數；不存在、未發布與退役版本；使用者類別和模型判定不同；空類別、空留言、匿名與重複提交；正確綁定版本；單筆低分只保存而不改版。 |
| 定期檢視回饋 | 正式 n=9/10/11 及平均 3.49/3.5/3.51；Demo 隔離 n=7/8/9；recurring 4/5/6；只計 current_version 累計回饋；無新回饋重跑；診斷不存在或空步驟；完整 REFINE 輸入輸出與 reason。 |
| 提出教學規則 | 同類 4/5/6 筆，分散不同版本或專案的 3+2 筆；R-007 的 8 個 Feedback ID 對應真實 fixture 列；candidate 初態、evidence、derived_from 與 applies_when；共享範圍內外的可讀資料。 |
| 套用教學規則 | candidate/active/retired 與 click_ui/input/read 組合；無適用規則；互斥規則；candidate 試用；A v2 到 B v1 轉移；只改部分步驟時直接與沿用套用紀錄；兩份清單與 APPLIED_TO 邊一致且不重複。 |
| 驗證教學規則 | 套用與對照組原始指標；持平、只改善一項與一項惡化；不足樣本、成熟與未成熟窗口；R-007 啟用及 R-012 的明確前態與無效證據；不同適用範圍不誤判衝突；合併後的 ID 與歷史。 |
| 建立教學版本 | v1/v2/v3、同 Tutorial 的 supersedes；跨 pipeline 同時寫入；事件重送與失敗重試；S3 全文、s3_key、diff 與邊的實際斷言；v1 無前版；部分寫入失敗時保留或補償策略。 |
| 發布教學版本 | 實際入口可讀、widget 綁定指定版本；待發布不可誤示為已上架；publish 與讀取失敗；current_version 切換及 published_at；舊網址與退役頁的可見行為。 |
| 查詢知識圖譜 | 正查與反查的 0/1/多筆結果；跨版本引用；回饋與規則套用反查；純關係查詢的 AI 次數為 0；漏邊與錯邊 backfill；P05 定案後補分頁與投影可見性的驗收。 |
| 檢視學習指標 | 完整 rating、類別、瀏覽與 Ticket 資料重算指標；零樣本與零分母；同人多次瀏覽、先開票後瀏覽及十四天端點；同 Feature 不同 cluster；跨版加權；負面 OR 去重；重試與 Map 呼叫；固定示意值和計算值分開；B 的對照變體隔離。 |
| 執行教學流程 | 固定節點輸入輸出與最後結果；P02/P03 選定值的 max_tokens、timeout、Retry/Catch 案例；schema 合法但語意錯誤；原文未要求 Agent 自由選擇 pipeline；ASL 快照與 TutorialVersion 分別版本化。 |

### 逐 Rule 對照（以規格檔為準，本檔未重數）

`F01` 是所有缺例或部分例子的共同前置。每行另列會影響該 Rule 的決策；沒有決策題的明確規則仍須補例。`Pxx` 表示下節具理由的規劃延後，並非已完成驗收。

#### 依改版更新教學

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 從 PR diff 或 changelog 抽出 feature、kind、old_name 與 new_name](../features/依改版更新教學.feature)：7 | 0／@Missing | 已釐清 D10、F14（子 Release 共用 `source_event_id`）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R02 改名前後的 alias 對應同一個 Feature 節點](../features/依改版更新教學.feature)：12 | 1／@Partial | [D06](resolved/data/FEATURE_功能改名時哪個識別碼必須保持不變.md)、[D07](resolved/data/FEATURE_同一查詢範圍內的_alias_撞名時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出 |
| [R03 alias 比對未命中時以向量搜尋最相近的 Feature](../features/依改版更新教學.feature)：27 | 0／@Missing | 已釐清 F15（cosine >= 0.85，否則不改版）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R04 by_target 反查只選出引用改版 Feature 的步驟](../features/依改版更新教學.feature)：32 | 1／@Partial | [D05](resolved/data/TUTORIAL_STEP_一個教學步驟可以引用幾個_Feature.md)、已釐清 [F17](resolved/features/依改版更新教學_反查到歷史版本步驟時是否納入改版.md)（只處理目前已發布版本）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出 |
| [R05 反查為零或重大改名時使用 step 文字向量搜尋補漏](../features/依改版更新教學.feature)：49 | 0／@Missing | [F16](resolved/features/依改版更新教學_哪種改名算必須執行_safety_net_的重大改名.md)、[F18](resolved/features/依改版更新教學_safety_net_沒有確認任何步驟時如何結束.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R06 safety_net 的疑似命中交給 Claude 確認](../features/依改版更新教學.feature)：54 | 0／@Missing | [F18](resolved/features/依改版更新教學_safety_net_沒有確認任何步驟時如何結束.md)、[F48](resolved/features/執行教學流程_LLM_輸出通過_schema_但違反業務規則時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R07 renamed 或 changed 的改版動作為 UPDATE](../features/依改版更新教學.feature)：59 | 1／@Partial | 已釐清 D10、F14。[F35](resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出 |
| [R08 kind 為 removed 的改版動作為 RETIRE](../features/依改版更新教學.feature)：70 | 0／@Missing | [D21](resolved/data/TUTORIAL_RETIRE_之後的狀態應使用_retired_還是_obsolete.md)、[F19](resolved/features/依改版更新教學_退役時沒有後繼_Tutorial_要呈現什麼結果.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R09 UPDATE 只重寫受影響的步驟](../features/依改版更新教學.feature)：75 | 1／@Partial | [F35](resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md)、[F48](resolved/features/執行教學流程_LLM_輸出通過_schema_但違反業務規則時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出 |
| [R10 UPDATE 將未命中步驟的原文複製到下一版](../features/依改版更新教學.feature)：88 | 1／@Specified | [F29](resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md)；保留現有例並依上表補邊界 |
| [R11 未引用改版 Feature 的教學維持 KEEP](../features/依改版更新教學.feature)：101 | 1／@Specified | [F18](resolved/features/依改版更新教學_safety_net_沒有確認任何步驟時如何結束.md)；保留現有例並依上表補邊界 |
| [R12 UPDATE 為受影響教學產生與前版的 diff](../features/依改版更新教學.feature)：113 | 1／@Partial | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出；P07 |
| [R13 UPDATE 下一版的 reason 使用 release 加上改版事件 id](../features/依改版更新教學.feature)：126 | 0／@Missing | 已釐清 D02、F09（同一事件只處理一次）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R14 UPDATE 完成時更新 Feature 的 aliases](../features/依改版更新教學.feature)：132 | 0／@Missing | [D06](resolved/data/FEATURE_功能改名時哪個識別碼必須保持不變.md)、[D07](resolved/data/FEATURE_同一查詢範圍內的_alias_撞名時如何處理.md)、[F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R15 RETIRE 將受影響教學標記為過期](../features/依改版更新教學.feature)：144 | 0／@Missing | 已釐清 D21（status=retired）。[F37](resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R16 RETIRE 的教學導向後繼 Tutorial](../features/依改版更新教學.feature)：150 | 0／@Missing | 已釐清 D22（Tutorial.successor）。[F19](resolved/features/依改版更新教學_退役時沒有後繼_Tutorial_要呈現什麼結果.md)、[F54](resolved/features/依改版更新教學_退役教學的後繼_Tutorial_由哪個來源指定.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

#### 分析工單

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding](../features/分析工單.feature)：8 | 0／@Missing | 已釐清 D09、F09。[D08](resolved/data/TICKET_Ticket_向量以_embedding_還是_embedding_ref_為準.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P04 |
| [R02 demo 分群以 cosine 至少 0.85 為同群門檻](../features/分析工單.feature)：13 | 0／@Missing | [F10](resolved/features/分析工單_cosine_門檻以哪種群代表判斷_Ticket_歸群.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R03 同群在 14 天內至少有 5 筆 Ticket 才算 recurring](../features/分析工單.feature)：18 | 0／@Missing | 已釐清 F09。[F11](resolved/features/分析工單_recurring_的十四天窗口以哪個時間為基準.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R04 只有達 recurring 門檻的群才交給模型命名 Knowledge Gap](../features/分析工單.feature)：23 | 0／@Missing | [F10](resolved/features/分析工單_cosine_門檻以哪種群代表判斷_Ticket_歸群.md)、[F11](resolved/features/分析工單_recurring_的十四天窗口以哪個時間為基準.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R05 Knowledge Gap 的命名結果包含對應 Feature](../features/分析工單.feature)：28 | 0／@Missing | 已釐清 D04、F13（對不到 Feature 則保留 gap、不建 Tutorial）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R05a 一張 Ticket 對應零或一個 Feature](../features/分析工單.feature) | 0／@Missing | 已釐清 D04；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R06 對應 Feature 已有教學時動作為 KEEP](../features/分析工單.feature)：33 | 0／@Missing | [F12](resolved/features/分析工單_判定已有教學時哪些_Tutorial_狀態算有效.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R07 KEEP 只記錄 log 而不寫入教學內容](../features/分析工單.feature)：38 | 0／@Missing | [F12](resolved/features/分析工單_判定已有教學時哪些_Tutorial_狀態算有效.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P03 |
| [R08 已識別且尚無現成教學的 Knowledge Gap 建立新的 Tutorial](../features/分析工單.feature)：43 | 0／@Missing | 已釐清 D04、F13、F09。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R09 Ticket Analysis 是唯一建立新 Tutorial 身分的 pipeline](../features/分析工單.feature)：49 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R10 新教學的完整內容包含 Title、Problem、Prerequisites、Steps 與 Expected Outcome](../features/分析工單.feature)：54 | 0／@Missing | [F48](resolved/features/執行教學流程_LLM_輸出通過_schema_但違反業務規則時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R11 產生新教學時同時輸出每步提到的 Feature](../features/分析工單.feature)：59 | 0／@Missing | 已釐清 D05；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R11a 新教學的每個步驟恰好引用一個 Feature](../features/分析工單.feature) | 0／@Missing | 已釐清 D05；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R12 新教學第一版的 reason 使用 gap 加上來源 cluster_id](../features/分析工單.feature)：64 | 0／@Missing | 已釐清 D29（`Tutorial.cluster_id`）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

#### 執行教學流程

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 教學 pipeline 依 Step Functions 預定義節點執行](../features/執行教學流程.feature)：8 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P01 |
| [R02 Agent 的工具選擇自由度只用於接入層](../features/執行教學流程.feature)：13 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P01 |
| [R03 每個 Bedrock 呼叫設定 max_tokens](../features/執行教學流程.feature)：18 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P02 |
| [R04 每個 Bedrock 呼叫設定逾時](../features/執行教學流程.feature)：23 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P02 |
| [R05 每個 Step Functions Task 設定 Retry](../features/執行教學流程.feature)：28 | 0／@Missing | [F49](resolved/features/執行教學流程_Task_重試耗盡並進入_Catch_後如何結束流程.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P03 |
| [R06 每個 Step Functions Task 設定 Catch](../features/執行教學流程.feature)：34 | 0／@Missing | [F49](resolved/features/執行教學流程_Task_重試耗盡並進入_Catch_後如何結束流程.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P03 |
| [R07 LLM 輸出遵循指定 JSON schema](../features/執行教學流程.feature)：39 | 0／@Missing | [D09](resolved/data/TICKET_Ticket_接入驗證的必填欄位採哪套契約.md)、[D10](resolved/data/RELEASE_Release_接入必填欄位採哪套契約.md)、[F48](resolved/features/執行教學流程_LLM_輸出通過_schema_但違反業務規則時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P04 |
| [R08 判斷節點使用低 temperature](../features/執行教學流程.feature)：44 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P02 |
| [R09 Step Functions 的 ASL 版本快照存於 stepfunctions/<pipeline>/v<n>.json](../features/執行教學流程.feature)：49 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P01 |

#### 套用教學規則

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 CREATE、UPDATE 與 REFINE 在寫作前讀取教學規則](../features/套用教學規則.feature)：7 | 0／@Missing | [D16](resolved/data/AUTHORING_RULE_applies_when_的可表達條件範圍為何.md)、已釐清 [F27](resolved/features/套用教學規則_candidate_規則如何取得驗證用的套用版本.md)（正式寫作不自動試用 candidate）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R02 一般寫作路徑只取得 status 為 active 的規則](../features/套用教學規則.feature)：12 | 0／@Missing | 已釐清 [F27](resolved/features/套用教學規則_candidate_規則如何取得驗證用的套用版本.md)（正式寫作不自動試用 candidate）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R03 依 step 型態與 applies_when 篩選規則](../features/套用教學規則.feature)：18 | 1／@Partial | [D16](resolved/data/AUTHORING_RULE_applies_when_的可表達條件範圍為何.md)、[F28](resolved/features/套用教學規則_多條相互衝突的_active_規則同時適用時如何選擇.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出 |
| [R04 適用規則的內容注入教學寫作 prompt](../features/套用教學規則.feature)：32 | 0／@Missing | [F28](resolved/features/套用教學規則_多條相互衝突的_active_規則同時適用時如何選擇.md)、[F48](resolved/features/執行教學流程_LLM_輸出通過_schema_但違反業務規則時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R05 既有教學衍生的適用規則可用於不同主題新教學的第一版](../features/套用教學規則.feature)：37 | 0／@Missing | 已釐清 D27（共享只接受合成種子證據）、[F27](resolved/features/套用教學規則_candidate_規則如何取得驗證用的套用版本.md)（正式寫作不自動試用 candidate）。[F47](resolved/features/檢視學習指標_Tutorial_B_的規則開關對照是否會影響正式上架版本.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R06 套用規則的版本記錄於規則的 applied_to](../features/套用教學規則.feature)：43 | 0／@Missing | [D17](resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md)、[F29](resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R07 版本的 rules_applied 記錄本次套用的規則](../features/套用教學規則.feature)：49 | 0／@Missing | [D17](resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md)、[F29](resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R08 後續 Release 重寫仍注入適用的教學規則](../features/套用教學規則.feature)：54 | 0／@Missing | [F28](resolved/features/套用教學規則_多條相互衝突的_active_規則同時適用時如何選擇.md)、[F29](resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

#### 定期檢視回饋

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 Periodic Feedback Review 每日執行](../features/定期檢視回饋.feature)：7 | 0／@Missing | 已釐清 [F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md)（只看 current_version 累計回饋）、[F23](resolved/features/定期檢視回饋_同一批回饋是否可以再次觸發_REFINE.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P02 |
| [R02 弱教學的版本平均評分必須小於 3.5](../features/定期檢視回饋.feature)：12 | 0／@Missing | 已釐清 [F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md)（只看 current_version 累計回饋）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R03 弱教學的版本回饋樣本數必須至少為 10](../features/定期檢視回饋.feature)：18 | 0／@Missing | [D14](resolved/data/FEEDBACK_同一使用者對同一版本多次回饋計為幾筆.md)、已釐清 [F20](resolved/features/定期檢視回饋_八筆回饋的_Demo_如何符合至少十筆的檢視門檻.md)（正式 n>=10，Demo n>=8）、[F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R04 弱教學必須具有 recurring Feedback Category](../features/定期檢視回饋.feature)：24 | 0／@Missing | 已釐清 [F21](resolved/features/定期檢視回饋_recurring_Feedback_Category_的次數門檻是多少.md)（同類至少 5 筆）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R05 診斷結果包含需要改寫的步驟編號與原因](../features/定期檢視回饋.feature)：29 | 0／@Missing | [F24](resolved/features/定期檢視回饋_診斷找不到有效步驟時如何處理弱教學.md)、[F48](resolved/features/執行教學流程_LLM_輸出通過_schema_但違反業務規則時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R06 REFINE 只重寫診斷命中的步驟](../features/定期檢視回饋.feature)：34 | 0／@Missing | [F23](resolved/features/定期檢視回饋_同一批回饋是否可以再次觸發_REFINE.md)、[F24](resolved/features/定期檢視回饋_診斷找不到有效步驟時如何處理弱教學.md)、[F35](resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R07 REFINE 的下一版 reason 記錄回饋數與類別](../features/定期檢視回饋.feature)：39 | 0／@Missing | [D28](resolved/data/TUTORIAL_VERSION_REFINE_版本的_reason_採用哪種標準格式.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R08 Feedback Review 是唯一提出 Authoring Rule 的 pipeline](../features/定期檢視回饋.feature)：44 | 0／@Missing | [F23](resolved/features/定期檢視回饋_同一批回饋是否可以再次觸發_REFINE.md)、已釐清 [F26](resolved/features/提出教學規則_提出_candidate_是否必須先滿足弱教學門檻.md)（不必先滿足弱教學門檻）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

#### 建立教學版本

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 新 Tutorial 的版本從 v1 起算](../features/建立教學版本.feature)：9 | 0／@Missing | 已釐清 D26（失敗重試重用原版號）。[F50](resolved/features/建立教學版本_第一版沒有前版時_diff_檔案如何表示.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R02 任一 pipeline 修改既有教學時使用該篇的下一個版本號](../features/建立教學版本.feature)：14 | 1／@Specified | 已釐清 D26（失敗重試重用原版號）、F09（同一事件只處理一次）。[F35](resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md)；保留現有例並依上表補邊界 |
| [R03 新版以 supersedes 關聯同一篇教學的前一版](../features/建立教學版本.feature)：23 | 1／@Specified | 已釐清 D26（失敗重試重用原版號）。[F35](resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md)；保留現有例並依上表補邊界 |
| [R04 每次建立版本都記錄引起變更的 reason](../features/建立教學版本.feature)：33 | 0／@Missing | [D02](resolved/data/TICKET_來源事件的正規化識別碼如何保證唯一.md)、[D28](resolved/data/TUTORIAL_VERSION_REFINE_版本的_reason_採用哪種標準格式.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R05 每個版本的完整內容儲存在 tutorials/<slug>/v<n>.md](../features/建立教學版本.feature)：39 | 0／@Missing | [F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P04 |
| [R06 TutorialVersion 的 s3_key 指向該版本完整內容](../features/建立教學版本.feature)：44 | 0／@Missing | [F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R07 與前版的 diff 儲存在 tutorials/<slug>/v<n>.diff](../features/建立教學版本.feature)：49 | 0／@Missing | [F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md)、[F50](resolved/features/建立教學版本_第一版沒有前版時_diff_檔案如何表示.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P07 |
| [R08 建立 TutorialStep 時保存 references Feature 邊](../features/建立教學版本.feature)：54 | 1／@Specified | 已釐清 D05。[D06](resolved/data/FEATURE_功能改名時哪個識別碼必須保持不變.md)、[F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md)；保留現有例並依上表補邊界；P01 |
| [R08a 沒有 Feature 或引用多個 Feature 的步驟不可保存](../features/建立教學版本.feature) | 0／@Missing | 已釐清 D05；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R09 references 邊的 target 等於 SK 中的關係終點](../features/建立教學版本.feature)：67 | 1／@Specified | 已釐清 D05；保留現有例並依上表補邊界 |

#### 接入來源事件

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 GitHub webhook 必須以 X-Hub-Signature-256 驗簽](../features/接入來源事件.feature)：11 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P05 |
| [R02 沒有簽名的 GitHub webhook 請求被拒絕](../features/接入來源事件.feature)：16 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R03 來源簽名使用來源網域、有意義的 header 名稱與穩定 payload key 計算](../features/接入來源事件.feature)：21 | 0／@Missing | 已釐清 D19、F02（每來源／事件類型固定 STABLE_KEYS；MVP GitHub = action, issue, repository, sender）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P06 |
| [R04 ID、時間戳與標題等事件值不參與來源簽名](../features/接入來源事件.feature)：29 | 0／@Missing | 已釐清 F02。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P06 |
| [R05 第一層以 PROC 主鍵精確比對來源簽名](../features/接入來源事件.feature)：34 | 0／@Missing | 已釐清 F02、F05。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R06 第一層只允許 status 為 active 的流程重放](../features/接入來源事件.feature)：39 | 0／@Missing | 已釐清 F05。[F53](resolved/features/接入來源事件_已退役簽名重新學到流程時如何保存新序列.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R07 第一層流程的 success_count 必須至少為 3](../features/接入來源事件.feature)：44 | 0／@Missing | 已釐清 F05（首次成功=1，同簽名完整成功才累加）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R08 第一層未命中才在同寄件者的流程中以 Jaccard 至少 0.8 比對欄位](../features/接入來源事件.feature)：49 | 0／@Missing | 已釐清 D19、F02、F03（第二層亦須 active 且 `success_count >= 3`）。[F04](resolved/features/接入來源事件_多個同寄件者流程達重疊門檻時選哪一個.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R09 前兩層皆未命中時才由 Agent 選擇 adapter tool](../features/接入來源事件.feature)：55 | 0／@Missing | 已釐清 F05、F08。[F07](resolved/features/接入來源事件_Agent_最終仍無法產出合法物件時如何處置事件.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R10 接入層命中已驗證流程的重放路徑不呼叫 LLM](../features/接入來源事件.feature)：60 | 0／@Missing | [F45](resolved/features/檢視學習指標_Bedrock_呼叫數是否計入重試與_Map_的每次呼叫.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R11 記錄的 tool 參數以 JSONPath 指向事件欄位或前一步輸出](../features/接入來源事件.feature)：65 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P06 |
| [R12 寫回新流程前最後一個 tool 必須是通過的 validate](../features/接入來源事件.feature)：71 | 0／@Missing | 已釐清 F05、F06（Feedback 不進 PROC）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R13 寫回新流程前 Step Functions 必須成功啟動](../features/接入來源事件.feature)：76 | 0／@Missing | 已釐清 F06、F09。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R14 每次重放失敗時 fail_count 增加 1](../features/接入來源事件.feature)：83 | 0／@Missing | 已釐清 D20；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R14a 重放成功時 fail_count 歸零](../features/接入來源事件.feature)：89 | 0／@Missing | 已釐清 D20；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R15 重放或正規化驗證失敗時當次回退到 Agent](../features/接入來源事件.feature)：94 | 0／@Missing | [F07](resolved/features/接入來源事件_Agent_最終仍無法產出合法物件時如何處置事件.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R16 同一流程連續三次重放失敗後 status 變為 retired](../features/接入來源事件.feature)：99 | 0／@Missing | 已釐清 D20。[F53](resolved/features/接入來源事件_已退役簽名重新學到流程時如何保存新序列.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R17 已退役流程在下次接入時視同未命中](../features/接入來源事件.feature)：97 | 0／@Missing | 已釐清 F03。[F53](resolved/features/接入來源事件_已退役簽名重新學到流程時如何保存新序列.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R18 正規化物件必須具有 schema 的必填欄位](../features/接入來源事件.feature)：102 | 0／@Missing | [D09](resolved/data/TICKET_Ticket_接入驗證的必填欄位採哪套契約.md)、[D10](resolved/data/RELEASE_Release_接入必填欄位採哪套契約.md)、[D11](resolved/data/FEEDBACK_Feedback_是否允許沒有穩定的使用者識別碼.md)、[D12](resolved/data/FEEDBACK_只有評分而沒有類別與留言的回饋是否有效.md)、[F51](resolved/features/收集教學回饋_不合法回饋要向提交者回傳哪種處理結果.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R18a 正規化物件的 id 直接使用已全域唯一的上游識別碼](../features/接入來源事件.feature) | 0／@Missing | 已釐清 D02；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R19 正規化物件的枚舉欄位必須使用合法值](../features/接入來源事件.feature)：107 | 0／@Missing | [D10](resolved/data/RELEASE_Release_接入必填欄位採哪套契約.md)、[D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R20 正規化成功的 Ticket 觸發 Ticket Analysis](../features/接入來源事件.feature)：113 | 0／@Missing | 已釐清 F08、F09。[F07](resolved/features/接入來源事件_Agent_最終仍無法產出合法物件時如何處置事件.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R21 正規化成功的 Release 觸發 Release Note Update](../features/接入來源事件.feature)：118 | 0／@Missing | 已釐清 F08、F09、F14。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R22 正規化成功的 Feedback 寫入 FEEDBACK item](../features/接入來源事件.feature)：123 | 0／@Missing | 已釐清 F06、F09。[F51](resolved/features/收集教學回饋_不合法回饋要向提交者回傳哪種處理結果.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R23 單筆 Feedback 接入不立即觸發教學改版](../features/接入來源事件.feature)：128 | 0／@Missing | 已釐清 F06（固定保存即成功，不進 PROC）。[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R24 只有 Rote 接入層讀寫 PROVEN_WORKFLOW](../features/接入來源事件.feature)：164 | 0／@Missing | [D19](resolved/data/PROVEN_WORKFLOW_same_sender_以哪個來源範圍識別流程.md)、[F53](resolved/features/接入來源事件_已退役簽名重新學到流程時如何保存新序列.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P01 |
| [R25 瀏覽事件接入時 tutorial_version、user 與 ts 必填](../features/接入來源事件.feature)：169 | 0／@Missing | 已釐清 D23、D24；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

#### 提出教學規則

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 同類 Feedback 至少 5 筆才可提出 candidate 規則](../features/提出教學規則.feature)：8 | 1／@Partial | 已釐清 [F25](resolved/features/提出教學規則_候選規則的五筆同類回饋可以跨哪些範圍累積.md)（僅同一 TutorialVersion）、[F26](resolved/features/提出教學規則_提出_candidate_是否必須先滿足弱教學門檻.md)（不必先滿足弱教學門檻）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出 |
| [R02 Authoring Rule 保留可追溯的 Feedback 證據](../features/提出教學規則.feature)：20 | 1／@Partial | [D15](resolved/data/AUTHORING_RULE_規則_evidence_使用識別碼清單還是含類別的物件.md)、已釐清 D27（共享只接受合成種子證據）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出 |
| [R03 Authoring Rule 記錄 applies_when 適用範圍](../features/提出教學規則.feature)：41 | 1／@Specified | [D16](resolved/data/AUTHORING_RULE_applies_when_的可表達條件範圍為何.md)；保留現有例並依上表補邊界 |
| [R04 Authoring Rule 記錄 derived_from 來源版本](../features/提出教學規則.feature)：49 | 1／@Specified | 已釐清 D18（恰好一個來源版本）；保留現有例並依上表補邊界 |
| [R05 Authoring Rule 記錄歸納出的寫作要求](../features/提出教學規則.feature)：57 | 1／@Specified | 主要規則已明確；保留現有例並依上表補邊界 |
| [R06 MVP 的教學與產品功能識別碼在單一專案範圍內唯一](../features/提出教學規則.feature)：68 | 0／@Missing | 單一專案範圍已定案。已釐清 D27（共享只接受合成種子證據）、[F25](resolved/features/提出教學規則_候選規則的五筆同類回饋可以跨哪些範圍累積.md)（僅同一 TutorialVersion）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

#### 收集教學回饋

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 Feedback 的 tutorial_version 必須存在於圖譜](../features/收集教學回饋.feature)：8 | 0／@Missing | 已釐清 D25（published_at 空＝未發布）。[F39](resolved/features/收集教學回饋_已退役教學的既有版本是否仍接受回饋.md)、[F51](resolved/features/收集教學回饋_不合法回饋要向提交者回傳哪種處理結果.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R02 Feedback 的 rating 只能為 1 到 5 的整數](../features/收集教學回饋.feature)：14 | 0／@Missing | [F51](resolved/features/收集教學回饋_不合法回饋要向提交者回傳哪種處理結果.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R03 使用者勾選的 Feedback Category 優先於模型分類](../features/收集教學回饋.feature)：19 | 0／@Missing | [D12](resolved/data/FEEDBACK_只有評分而沒有類別與留言的回饋是否有效.md)、[D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R04 需要分類的自由留言在接入時計算一次 Feedback Category](../features/收集教學回饋.feature)：24 | 0／@Missing | [D12](resolved/data/FEEDBACK_只有評分而沒有類別與留言的回饋是否有效.md)、[D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md)、[F07](resolved/features/接入來源事件_Agent_最終仍無法產出合法物件時如何處置事件.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R05 回饋關聯到提交時指定的 TutorialVersion](../features/收集教學回饋.feature)：36 | 0／@Missing | 已釐清 D23（共用穩定使用者 ID）。[F39](resolved/features/收集教學回饋_已退役教學的既有版本是否仍接受回饋.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R06 收到單筆低分 Feedback 時不立即修改 Tutorial](../features/收集教學回饋.feature)：42 | 0／@Missing | 已釐清 F06（固定保存即成功，不進 PROC）、[F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md)（只看 current_version 累計回饋）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R07 Feedback 接入時必須提供穩定使用者 ID](../features/收集教學回饋.feature)：47 | 0／@Missing | 已釐清 D23。[D11](resolved/data/FEEDBACK_Feedback_是否允許沒有穩定的使用者識別碼.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

#### 查詢知識圖譜

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 查詢某起點的關係使用該起點的 PK](../features/查詢知識圖譜.feature)：8 | 0／@Missing | [D03](resolved/data/TUTORIAL_VERSION_關聯欄位使用裸識別碼還是帶前綴的主鍵.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P01、P05 |
| [R02 查詢誰引用 Feature 時使用 by_target 的 target](../features/查詢知識圖譜.feature)：13 | 1／@Partial | [D05](resolved/data/TUTORIAL_STEP_一個教學步驟可以引用幾個_Feature.md)、[D06](resolved/data/FEATURE_功能改名時哪個識別碼必須保持不變.md)、已釐清 [F17](resolved/features/依改版更新教學_反查到歷史版本步驟時是否納入改版.md)（只處理目前已發布版本）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出；P05 |
| [R03 沿 Feature 關係邊反查不呼叫 AI](../features/查詢知識圖譜.feature)：27 | 0／@Missing | 主要規則已明確；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R04 可查詢某篇 Tutorial 所屬的版本](../features/查詢知識圖譜.feature)：32 | 0／@Missing | 已釐清 D25（published_at 空＝未發布）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P05 |
| [R05 可查詢某條 Authoring Rule 套用的版本](../features/查詢知識圖譜.feature)：37 | 1／@Specified | [D17](resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md)、[F29](resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md)；保留現有例並依上表補邊界；P05 |
| [R06 Feedback Review 以 refers_to 關係反查指定版本的回饋](../features/查詢知識圖譜.feature)：53 | 0／@Missing | [D14](resolved/data/FEEDBACK_同一使用者對同一版本多次回饋計為幾筆.md)、已釐清 [F22](resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md)（只看 current_version 累計回饋）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P05 |
| [R07 定期 backfill 漏抽的 Feature 引用邊](../features/查詢知識圖譜.feature)：58 | 0／@Missing | [F40](resolved/features/查詢知識圖譜_backfill_發現既有_Feature_引用錯誤時如何更新.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P02、P05 |

#### 檢視學習指標

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 平均評分以每個 TutorialVersion 的 rating 計算](../features/檢視學習指標.feature)：8 | 0／@Missing | [D14](resolved/data/FEEDBACK_同一使用者對同一版本多次回饋計為幾筆.md)、[F44](resolved/features/檢視學習指標_跨版本比較平均評分時採用哪種加權方式.md)、[F52](resolved/features/檢視學習指標_版本沒有任何有效評分時平均評分如何呈現.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R02 負面 Feedback 數計入 rating 不超過 2 或 category 屬負面的回饋](../features/檢視學習指標.feature)：13 | 0／@Missing | [D13](resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md)、[F43](resolved/features/檢視學習指標_哪些_Feedback_Category_應算入負面回饋.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R03 同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例](../features/檢視學習指標.feature)：18 | 0／@Missing | 已釐清 D23（共用穩定使用者 ID）、D24（瀏覽事件當分母）、D29（`Tutorial.cluster_id`）。[F41](resolved/features/檢視學習指標_重開票率是否要求瀏覽發生在再次開票之前.md)、[F42](resolved/features/檢視學習指標_沒有可識別瀏覽者時重開票率如何顯示.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R04 規則效果比較套用與未套用版本的評分及同題重開票率差](../features/檢視學習指標.feature)：24 | 0／@Missing | 已釐清 [F30](resolved/features/驗證教學規則_candidate_升為_active_時兩項成效必須如何改善.md)（評分嚴格提高且重開票率嚴格下降）、[F31](resolved/features/驗證教學規則_未套用規則的對照版本如何選取.md)（同篇套用前版本對照）。[F44](resolved/features/檢視學習指標_跨版本比較平均評分時採用哪種加權方式.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R05 已學規則數依 RULE item 的 status 分別計數](../features/檢視學習指標.feature)：29 | 0／@Missing | [F34](resolved/features/驗證教學規則_合併相近規則時如何保留規則識別與歷史.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P07 |
| [R06 規則套用次數等於 applied_to 清單長度](../features/檢視學習指標.feature)：34 | 1／@Specified | [D17](resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md)、[F29](resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md)、[F34](resolved/features/驗證教學規則_合併相近規則時如何保留規則識別與歷史.md)；保留現有例並依上表補邊界 |
| [R07 每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫](../features/檢視學習指標.feature)：46 | 0／@Missing | [F45](resolved/features/檢視學習指標_Bedrock_呼叫數是否計入重試與_Map_的每次呼叫.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R08 Demo 指標以 seeded data 展示](../features/檢視學習指標.feature)：51 | 1／@Specified | [F46](resolved/features/檢視學習指標_seeded_Demo_指標採現算結果還是固定展示值.md)；保留現有例並依上表補邊界 |
| [R09 Demo 對同題重開票率標明 proxy 與精確定義](../features/檢視學習指標.feature)：72 | 0／@Missing | 已釐清 D24（瀏覽事件當分母；Demo 的 7 與 2 仍是筆數）。[F41](resolved/features/檢視學習指標_重開票率是否要求瀏覽發生在再次開票之前.md)、[F42](resolved/features/檢視學習指標_沒有可識別瀏覽者時重開票率如何顯示.md)、[F46](resolved/features/檢視學習指標_seeded_Demo_指標採現算結果還是固定展示值.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R10 Demo 以同一批 Ticket 並排展示規則關閉與開啟產生的 Tutorial B](../features/檢視學習指標.feature)：78 | 0／@Missing | [F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)、[F47](resolved/features/檢視學習指標_Tutorial_B_的規則開關對照是否會影響正式上架版本.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R11 同題重開票率的分母取自瀏覽事件的版本、使用者與瀏覽時間](../features/檢視學習指標.feature)：83 | 0／@Missing | 已釐清 D24；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R12 看過教學又開票的同一人比對穩定使用者 ID](../features/檢視學習指標.feature)：88 | 0／@Missing | 已釐清 D23；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

#### 發布教學版本

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 publish 上架指定的 TutorialVersion](../features/發布教學版本.feature)：8 | 0／@Missing | 已釐清 D25（published_at 空＝未發布）。[F36](resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md)、[F37](resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R02 發布的教學透過 S3 靜態 docs 站或 in-app 提供](../features/發布教學版本.feature)：13 | 0／@Missing | [F38](resolved/features/發布教學版本_MVP_的教學發布入口採用哪一種形式.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R03 發布的教學提供 feedback widget](../features/發布教學版本.feature)：18 | 0／@Missing | [D11](resolved/data/FEEDBACK_Feedback_是否允許沒有穩定的使用者識別碼.md)、[D12](resolved/data/FEEDBACK_只有評分而沒有類別與留言的回饋是否有效.md)、[F39](resolved/features/收集教學回饋_已退役教學的既有版本是否仍接受回饋.md)、[F51](resolved/features/收集教學回饋_不合法回饋要向提交者回傳哪種處理結果.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例；P07 |
| [R04 Tutorial 的 current_version 指向目前教學版本](../features/發布教學版本.feature)：23 | 0／@Missing | [F37](resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R05 已上架的版本具有 published_at](../features/發布教學版本.feature)：28 | 0／@Missing | 已釐清 D25（published_at 空＝未發布）。[F37](resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

#### 驗證教學規則

| Rule 與來源行 | 現有 Example／標記 | 決策與處理 |
|---|---|---|
| [R01 規則成效比較 applied_to 中的版本與未套用版本](../features/驗證教學規則.feature)：8 | 0／@Missing | 已釐清 [F31](resolved/features/驗證教學規則_未套用規則的對照版本如何選取.md)（同篇套用前版本對照）、[F32](resolved/features/驗證教學規則_規則驗證至少累積多少資料才可以改變狀態.md)（僅核定種子批次可改狀態）。[F44](resolved/features/檢視學習指標_跨版本比較平均評分時採用哪種加權方式.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R02 candidate 在套用版本成效優於未套用版本後變為 active](../features/驗證教學規則.feature)：13 | 0／@Missing | 已釐清 [F27](resolved/features/套用教學規則_candidate_規則如何取得驗證用的套用版本.md)（種子試用版本匯入成效）、[F30](resolved/features/驗證教學規則_candidate_升為_active_時兩項成效必須如何改善.md)（評分嚴格提高且重開票率嚴格下降）、[F32](resolved/features/驗證教學規則_規則驗證至少累積多少資料才可以改變狀態.md)（僅核定種子批次可改狀態）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R03 無效的 candidate 規則變為 retired](../features/驗證教學規則.feature)：19 | 0／@Missing | 已釐清 [F32](resolved/features/驗證教學規則_規則驗證至少累積多少資料才可以改變狀態.md)（僅核定種子批次可改狀態）。[F33](resolved/features/驗證教學規則_具備足夠資料後如何判定規則無效而退役.md)（連續兩批次未改善才退役）；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R04 與既有規則衝突的 candidate 規則變為 retired](../features/驗證教學規則.feature)：24 | 0／@Missing | [F55](resolved/features/驗證教學規則_candidate_與既有規則的衝突由誰判定.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R05 後來失效的 active 規則變為 retired](../features/驗證教學規則.feature)：29 | 0／@Missing | [F33](resolved/features/驗證教學規則_具備足夠資料後如何判定規則無效而退役.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R06 驗證無效的規則從可使用規則中退役](../features/驗證教學規則.feature)：34 | 1／@Partial | [F33](resolved/features/驗證教學規則_具備足夠資料後如何判定規則無效而退役.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補完整資料或輸出 |
| [R07 curation 合併相近教學規則](../features/驗證教學規則.feature)：47 | 0／@Missing | [F34](resolved/features/驗證教學規則_合併相近規則時如何保留規則識別與歷史.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |
| [R08 Analytics 寫入教學規則的驗證後 status](../features/驗證教學規則.feature)：52 | 0／@Missing | [F33](resolved/features/驗證教學規則_具備足夠資料後如何判定規則無效而退役.md)、[F55](resolved/features/驗證教學規則_candidate_與既有規則的衝突由誰判定.md)；[F01](resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md)：待補例 |

## 延後到設計與規劃的項目

以下為篩選後未另立問答檔的事項。延後是保留責任與驗證需求，不是刪除來源 TODO 或假設已有答案。

| 編號 | 項目 | 範圍 | 延後理由 |
|---|---|---|---|
| P01 | 物理佈局與執行拆分 | 九邏輯實體對單表的 metadata SK、List/Map 原生型別、索引配置、固定流程採一個或多個 state machine、ASL 版本命名。 | D03/D05/D17/D22/D25 已釐清；待 F35/F36 的語意契約定案後由設計選擇；不把 DBML string 投影誤讀成實體字串儲存。 |
| P02 | 可設定的執行參數 | 每日 Review 的確切時刻、backfill 頻率、max_tokens、timeout 秒數、低 temperature 具體值與可調 demo 參數。 | 存在性要求已確定，具體值需配合模型、資料與執行預算。F20/F21 已定案（正式 n>=10、Demo n>=8、recurring 同類 5 筆）。日期窗口仍由 F11 釐清，規則驗證樣本仍由 F32 釐清，不能以本項略過。 |
| P03 | 失敗機制的工程設定 | Retry 次數、backoff、錯誤代碼、log 欄位、執行追蹤與重新處理介面實作。 | 已釐清 F09（同一事件只處理一次）。先由 F07/F36/F49/F51 確立可見結果與冪等性，再填工程配置；Catch 不得只有名稱而沒有目的地。 |
| P04 | 序列化與欄位限制 | 時間採可比較的統一編碼、字串長度、ID 合法字元、slug 轉換、JSON schema 完整欄位表、向量與產出大小限制。 | 不是現階段重新發明業務門檻；依 D02/D03/D09/D10/D11/D12/D13 與 F48 的決策補規範。已知 rating、維度、狀態枚舉照來源保留。 |
| P05 | 查詢與 adapter 實作 | SDK 呼叫、分頁、投影可見性處理、查詢空結果格式、簽章比較機制及 backfill 執行方式。 | 目前沒有 runtime。已釐清 F17（只處理目前已發布版本）。必須以固定的來源驗證要求和 F18/F40 的可見行為設計；不得把讀到不完整結果默認為完整掃描。 |
| P06 | Rote 參數化的技術細節 | 雜湊序列化測試、header 正規化、JSONPath 支援範圍、從 tool 輸入抽取參數的演算法。 | 固定不含事件值與最後 validate 的要求已明確。已釐清 F02／F03；最終失敗由 F07 決定。無法可靠泛化不能假裝流程已驗證。 |
| P07 | 展示與文件細節 | 一般 diff 格式、指標小數位、規則卡片排序、非決策性的錯誤文案與已有術語的交叉連結。 | 不實質改變模型或驗收策略，留到介面設計；首版 diff、空評分與零分母仍分別有 F50/F52/F42，不能省略可見結果。 |
| P08 | 舊架構與非目標 | 舊 HydraDB、hotdata、RocketRide、Bitext 相關文件與已刪除釐清紀錄；未來的完整 LMS、多 Agent、微調與企業功能。 | 本輪以目前 AWS draft、ERM 與 features 為準。舊文件整併或 4.design_prompt.md 的架構更新是下一階段準備工作，不在 discovery 擅改。 |

## 驗證方式與階段界線

本輪驗證結果：14 個待處理問題（資料 0、功能 14）、70 個已解決問題（資料 29、功能 41）與 1 個總覽。欄位可能另含 `cluster_id`、`source_event_id`（約 70）；Rule 可能微增。以規格檔為準，本檔未重數。未重跑 `@dbml/core`，未宣稱 parser 通過。

比對期間觀察到 `docs/spec/.DS_Store` 更新；這是 macOS 目錄 Metadata，已保留原狀並與規格內容的雜湊檢查分開記錄。

- 逐檔檢查五個必要標題、完整問句、選項數（含 Short 至多 5）、優先級及來源行號。
- 以問題 ID 驗證總覽連結與欄位／Rule 對照，並檢查前置依賴無循環且先於相依題。以規格檔為準，本檔未重數。
- 依 Git 狀態確認回寫範圍為相關 ERM、Feature 與 `.clarify/` 檔案；既有刪除不復原。
- 本儲存庫沒有應用程式或測試 runner。本輪檢查屬 Markdown、DBML/Gherkin 結構及來源一致性，不代表已執行應用程式、AWS 流程或端到端測試。

## 下一階段

使用現有 [3.clarify.md](../prompts/3.clarify.md) 依本表互動釐清並回寫已確定規格。`2.discovery.md` 的部分敘述仍稱後續為 formulation；本儲存庫實際的互動釐清檔名是 `3.clarify.md`。本輪到問題建檔與驗證為止。
