# 客服自助教學生成器 — 架構

- **讀者：** 黑客松評審與開發者
- **用途：** 把 Clarify 定案與 demo 畫面收成一張圖
- **真相來源：** `docs/spec/erm.dbml`、`docs/spec/features/`、`docs/spec/.clarify/resolved/決策總表.md`
- **狀態：** 規格已 Clarify；程式尚未實作。本檔是 demo 畫面草圖，不是已上線系統。完整 design 見 `docs/design/showme.md`。
- **FigJam：** 本機 Figma seat 目前是 View；選完 team / plan 才能生可編輯圖。沒有圖時以本檔 ASCII 為準。

---

## 0. 以上討論定案（Summary）

產品不是 MCP、也不是 platform。是 **單一 Agent 的客服 deflection 教學生成器**。

| 題 | 定案 |
|----|------|
| 產品 | 顧客客服票 → 產 Tutorial → 同類新票自動回教學連結 |
| 使用者 | 顧客。沒有 Champion／教學人員角色、**沒有教學人員清單** |
| Demo UI | **一個 Streamlit 分頁**：左餵票、中看教學、下看曲線 |
| 中間主工作 | Agent **寫／改教學文件**，不是客服總機 |
| 教學誰寫 | 真人只填「這張票怎麼解」（`resolution_steps`）；**LLM 收成五欄，直接發布** |
| 轉真人 | 還沒教學才進真人；湊滿 3 張同類解完才 CREATE v1 |
| Deflect | 已有教學 → 自動回連結，不用真人 |
| 發布 | 建立即 published，無人審核清單 |
| Demo 解法 | Bitext `response` 預填；可做成確認框，不必現場打字 |

三層不要混：

1. **左：** 假裝進資料（餵票 **或** 貼 changelog）  
2. **中：** Agent **寫／改教學文件**  
3. **下：** 曲線證明它有變聰明  

擋票發生在文件寫好**之後**、下一張票進來時，不是寫檔當下。  
Release Note 不另開頁：左欄貼一則 → 入庫 `Release`（`processed_at` 空）→ 同一 Agent UPDATE／RETIRE → 中欄出 diff。不是 RocketRide catalog 的獨立 node。

---

## 1. Demo 畫面（評審只看這一頁）

```
+---------------------------+------------------------------+
| 左：假裝進資料            | 中：Agent 產出                |
| [餵下一張票]              | 這張：deflected / 轉真人      |
| [貼 changelog]            | 轉真人時：解法框（預填 Bitext）|
| 顧客：「我要取消訂單」     | 教學：tutorials/cancel-order.md|
| 或 Release 一列本文       | Release 後：Step 3 diff       |
+---------------------------+------------------------------+
| 下：評審拍照區                                            |
|  deflection rate 上升     |  平均 rating 2.9 --> 4.4     |
+----------------------------------------------------------+
```

Streamlit **只觸發、只展示**，不在 UI 裡決定 CREATE／擋票。

---

## 1.1 一句話架構

```
票單 / 回饋 / Release Note
              |
              v
         hotdata 輪詢、算數字
              |
              v
     +-------- Agent (RocketRide + LLM) --------+
     | 沒教學 → 轉真人 → 確認解法                 |
     |          同類 >= 3 → CREATE .md v1        |
     | 有教學 → 回連結 (deflect)                  |
     |          第一次 Rote 記住，下次重放         |
     | 回饋差 → REFINE     Release → UPDATE      |
     +------------------+-----------------------+
                        |
           Cognee 建圖 --+--> HydraDB 記住
                        |
                        v
              中：教學 / diff     下：兩條曲線
```

中間只有「Agent 產 docs」。擋票是文件寫好之後、下一張票來時才發生。

---

## 2. 完整架構（輸入 → Agent → 教學 → 再用）

```
  Bitext 劇本票          顧客評分／再開票         Release Note
  (左：餵下一張票)       (Feedback)              (changelog 一列)
          \                    |                      /
           \                   |                     /
            v                  v                    v
     +--------------------------------------------------+
     |              hotdata.dev                         |
     |  輪詢新 open 票／未處理 Release；算曲線數字        |
     +------------------------+-------------------------+
                              |
                              v
     +--------------------------------------------------+
     |         單一 Agent（RocketRide + Bedrock LLM）     |
     |                                                  |
     |  問 HydraDB：這題有沒有 published Tutorial？       |
     |                                                  |
     |  [沒有] 轉真人 --> 人確認解法 resolution_steps     |
     |         同類 resolved >= 3 且無教學               |
     |         --> CREATE  tutorials/*.md v1             |
     |             （LLM 把解法收成五欄，直接發布）        |
     |                                                  |
     |  [有]   回教學連結 = deflect                      |
     |         第一次成功 --> Rote 記住攔截流程           |
     |         第二次起   --> Rote 重放，不再重新想       |
     |                                                  |
     |  回饋差（>=3 筆、均分 < 3.5、同類抱怨）            |
     |         --> REFINE  新版（demo 手動按一次）        |
     |                                                  |
     |  Release 改到該 Feature                           |
     |         --> UPDATE 或 RETIRE（先 UPDATE 再 REFINE）|
     +-----------+--------------------------+-----------+
                 |                          |
                 v                          v
          Cognee 建圖                 HydraDB 長期圖譜
          (ECL)                       Tutorial 對應問題類型
                 |                          ^
                 +--------------------------+
                              |
                              v
                    中：打開教學 / diff
                    下：hotdata 曲線
```

Snyk 不在這條資料迴圈裡：開發過程掃程式與依賴，漏洞會扣分。

---

## 3. 中間：Agent 只產文件（你要的那條）

```
   已解決票的解法     教學回饋／再開票      Release Note
           \              |                 /
            \             |                /
             v            v               v
                  單一 Agent
           CREATE / REFINE / UPDATE / RETIRE
                      |
                      v
              tutorials/*.md
              (v1 -> v2 -> v3)
```

CREATE **只來自分析 Ticket**。Release Note **不** CREATE，只 UPDATE／RETIRE。

---

## 4. 轉真人之後怎麼變成 Tutorial

```
沒有 published 教學
        |
        v
Ticket.status = escalated
        |
        v
真人（demo：確認框，解法預填 Bitext response）
寫入 resolution_steps，status = resolved
        |
        v
同類 resolved >= 3？ 且 尚無 published Tutorial？
        |
        +-- 否 --> 先不產文件，等湊滿
        |
        +-- 是 --> Knowledge Gap
                    |
                    v
              Agent + LLM
              讀多張 resolution_steps
              產出五欄：
                Title / Problem / Prerequisites
                Steps / Expected Outcome
                    |
                    v
              tutorials/cancel-order.md
              status = published，version = v1
                    |
                    v
              下一張同類票 --> deflect
```

人填的是 **解法文字**，不是教學五欄。五欄是 Agent 產的。沒有教學人員待辦清單。

---

## 5. 五層誰在做事

| 層 | 工具 | 本專案 |
|----|------|--------|
| 建記憶 | Cognee | 票／教學／回饋／Release → 實體與關係 |
| 存記憶 | HydraDB | 圖譜；問「這類問題有沒有教學」 |
| 即時查 | hotdata.dev | 輪詢新票／Release；deflection rate、均分、重放率 |
| 決策與動作 | RocketRide | 唯一 Agent：CREATE／擋票／UPDATE／REFINE |
| 肌肉記憶 | Rote | 只重放「攔截流程」，鍵是 UserProblem |
| 資安 | Snyk | 掃程式；不參與票流 |

---

## 6. 資料（精簡）

```
Ticket  --asks_about--> Feature
Ticket  --聚成--> UserProblem
Tutorial --explains--> Feature
Tutorial --1:1--> UserProblem
TutorialVersion --supersedes--> 上一版
Feedback --refers_to--> TutorialVersion
Release --changes--> Feature （經 ReleaseFeatureChange）
Workflow --1:1--> UserProblem   （Rote 攔截流程）
```

Deflection rate = `deflected / (deflected + escalated)`，hotdata 算，不落欄。

---

## 7. Demo 現場建議順序

1. 種子已建圖（Cognee → HydraDB）  
2. 餵 3 張 `cancel_order` → 轉真人、確認解法 → CREATE v1  
3. 第 4 張同類 → deflect，Rote 開始可重放  
4. 種子低分 Feedback → 手動 Review → REFINE，2.9 → 4.4  
5. 貼 Release Note「Cancel Order → Cancel Purchase」→ UPDATE，Step 3 diff  

貫穿檔案：`tutorials/cancel-order.md`。
