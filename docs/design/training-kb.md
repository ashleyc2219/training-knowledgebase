# Training Knowledge Base 設計文件

> 2026-09-13｜設計階段｜尚未實作或部署
>
> 目的：把重複工單變成教學，從使用者回饋改善教學，並在產品改版時只更新受影響的步驟。

<a id="s1"></a>

## 1. 文件目的與閱讀方式

本文件整合目前規格、84 份已解決的釐清紀錄，以及根目錄的 Ticket-to-Knowledge 設計。產品定位是協助 indie builder 維護使用者教學。這裡的「學習」是過去的結果改變下一次寫作或接入方式，不涉及模型微調。

先讀 [架構](#s5)、[完整流程](#s6)與[Demo](#s11)，即可理解要做什麼；實作時再查[資料儲存](#s9)、[錯誤處理](#s14)與[逐條 Rule 對照](#rules)。

全文使用四種標示，避免把建議當成已定案規格：

| 標示 | 意義 |
|---|---|
| **產品／黑客松約束** | 本次 MVP 的範圍與平台限制。 |
| **已釐清決策** | 已由 resolved 紀錄或現行規格確定，不重新提問。 |
| **本文件設計選擇** | 為了落實規格而選的模組、資料讀寫方式或展示做法。 |
| **待確認事項** | 規格明留未定義、或必須先驗證的平台整合問題，集中於[第 18 節](#s18)。 |

以下架構、目錄、函式與測試均為目標設計。這次只新增本文件；不代表程式、種子資料或 AWS 資源已存在。

幾個容易混淆的名稱：

| 名稱 | 本文件的意思 |
|---|---|
| Tutorial／TutorialVersion | 一篇教學，以及它某一次修改後的完整版本。 |
| Feature | 產品功能，例如「準備會議」；不是 Gherkin 檔案的 Feature 關鍵字。 |
| Release／publish | Release 是產品改版事件；publish 是把某個教學版本上架。 |
| Step／Task | Step 是教學中的操作步驟；Task 是 Step Functions 執行的工作節點。 |
| Rote／PROC | Rote 是三層接入處理；PROC 保存已驗證的接入工具順序。 |
| candidate／active／retired | 尚待驗證的規則／可供寫作採用的規則／已停止使用的規則。 |

<a id="s2"></a>

## 2. 來源優先順序與衝突裁決

**已釐清決策：** 依序採用個別 resolved 檔案的最新「解決記錄」、現行 ERM／Gherkin、design prompt 的產品約束，再參考草稿。總覽內過期的題數、待答文字與舊行號，不覆蓋個別答案。完整清單見[來源盤點](#s19)。

**本文件設計選擇：** 根目錄 [Ticket-to-Knowledge](../../ticket-to-knowledge-design-doc.md) 是整合參考。保留相容的設計理由；與已定案規格不同的部分依下表處理。

| 差異 | 本文件裁決與原因 | 依據 |
|---|---|---|
| 根目錄文件以 FAQ、Issue、RootCause、Resolution 為核心 | 使用 Tutorial、版本、步驟與 Feature；不增加另一套實體。 | ERM、design prompt §4.1 |
| 根目錄 §8 採 Neptune、OpenSearch 與 DynamoDB 快取 | 使用 DynamoDB 單表與 S3。固定查詢由程式走關係邊，少量語意搜尋在 Lambda 計算，減少服務與同步工作。 | ERM、design prompt §4.1 |
| 根目錄 §7.2 不做 Rote | 保留 Rote 三層，但只學 Ticket／Release 的接入程序。 | F03、F05、F06 |
| 草稿以 Strands SDK 擷取工具紀錄 | 改採 AWS SDK 與小型工具迴圈。MVP 只有少數固定 adapter，由程式直接保存呼叫順序即可；不依賴特定 Agent SDK 的紀錄格式。 | 本文件設計選擇，第 5、7.2 節 |
| 根目錄 §3 將寫作規則延後 | Authoring Rule 的提出、驗證、轉移與退役是本次核心。 | F25–F34、F55 |
| 根目錄含人工審核發布流程 | 驗證通過後自動發布；不做人工審核佇列。PROC 退役後重置仍依 F53 由人核定，兩者不同。 | D25、F37、F53 |
| 根目錄以 CATEGORY 快取命中後跳過整條分析 | PROC 命中只省掉接入層的模型呼叫；核心分析照常執行。 | 接入來源事件、F45 |
| 草稿與 AGENTS 舊說明仍稱九實體 | 使用十實體，包含 TUTORIAL_VIEW；D23、D24 的最新答案均為 A。 | D23、D24、現行 ERM |
| D09 舊答案允許 Ticket.author 空值 | author 必填，與回饋、瀏覽共用穩定使用者 ID。 | D23 覆寫 D09 |
| 草稿範例混用 candidate 與一般寫作 | 一般寫作只用 active；candidate 成效來自明示的種子試用版本。 | F27 |
| 草稿先讓 B 與 Release 套用 R-007，之後才啟用 | Demo 先匯入試用成效、完成 Analytics 驗證，再展示 active 規則供一般寫作使用。 | F27、F30–F32 |
| Demo 八筆回饋直接套用正式門檻 | 正式至少十筆；Demo 明示隔離使用八筆，其他條件相同。 | F20、F21 |
| 根目錄示意平均 2.8／4.3，或把 7／2 當成率 | 本案重現 2.9／4.4；7／2 是筆數。率另由瀏覽者分母計算。 | D24、F41、F46 |
| ERM 的 RULE note 仍說試用與驗證未定義 | 採已解決的 F27、F30–F33；這段 TODO 已過期。 | 個別 resolved 紀錄 |
| overview 仍有「剩餘問題」及 embedding_ref | 目前兩個待處理目錄皆空；向量只存 Ticket.embedding。 | 磁碟盤點、D08 |
| prompt 說 .env 已忽略 | 本次 `git check-ignore .env` 未命中，不能宣稱已受保護；本次不讀取或修改秘密檔。 | 實際 repo 檢查 |

根目錄文件仍提供五個實用原則，本案具體採用如下：

- §7.3：工單、Release、回饋共用產品功能清單，避免各自描述不同產品。
- §10.4：識別碼不從重新呼叫模型得到的文字決定；同一次變更重試使用已保存的輸出。
- §10.5：明確區分原始資料與可重建的查詢資料；本案以 `rules_applied` 為規則套用的唯一判準。
- §11、§12：固定程式先比對，只有需要理解文字時才呼叫模型。
- §14、§15：展示完整 diff、標明預先準備的資料，並在部署前檢查帳號與費用；不沿用未驗證的低成本保證。

<a id="s3"></a>

## 3. 產品範圍

**產品／黑客松約束：** MVP 只服務一個專案，完成兩條循環：

```text
重複工單 -> 教學缺口 -> 新教學 -> 回饋與瀏覽 -> 改善教學
                                      |
                                      +-> 寫作規則 -> 後續教學採用

產品改版 -> 找到引用該功能的目前步驟 -> 只改命中步驟
                                      |
                                      +-> 功能移除時退役教學
```

驗收重點是四個可見結果：缺口產生教學、低分教學獲得改善、改版不改無關文字、已驗證規則能用在另一篇教學。

不納入完整 LMS、教學影片、企業認證、Teams／Microsoft Graph、多租戶、複雜 dashboard、multi-agent、MCP server、瀏覽器自動操作或 fine-tuning。Neptune、OpenSearch、Athena 與 FAQ 快取不屬於本案 MVP。

<a id="s4"></a>

## 4. Repo 現況

**已確認的檔案狀態：** 目前有規格、草稿與舊設計；沒有應用程式入口、依賴清單或可執行測試。

| 路徑／項目 | 本次觀察 | 對實作的意義 |
|---|---|---|
| `docs/spec/erm.dbml` | 十個邏輯實體、73 個欄位投影、11 個 Ref | 描述資料關係，不是十張 SQL 表。 |
| `docs/spec/features/` | 十三份功能規格、147 條 Rule、22 個 Example | Rule 是契約；Example 仍不足以涵蓋全部行為。 |
| `docs/spec/.clarify/resolved/` | 29 份資料決策、55 份功能決策 | 全部納入本文件，見第 19 節。 |
| `docs/spec/.clarify/data/`、`features/` | 均為零個待處理問題 | 不重啟產品釐清。 |
| `tests/unit/`、`tests/integration/`、`scripts/` | 無檔案 | 尚無測試與執行腳本。 |
| `pyproject.toml`、`package.json` | 不存在 | 不能宣稱可執行 `uv run`、`npm start` 或測試指令。 |
| `docs/design/ITAgent.md`、舊 `docs/plan/` | 歷史文件 | 不作本案執行入口或實作依據。 |

本次驗證屬文件與來源一致性檢查，不是 AWS、應用程式或端到端測試。

<a id="s5"></a>

## 5. 目標架構與模組責任

**產品／黑客松約束：** 核心是三條預先定義的 Step Functions。Agent 只在接入層選 adapter，不能自行增加流程或決定發布政策。

```text
GitHub -> Signature check --+
                           +-> Rote -> Ticket Analysis -----+
Manual Ticket / Release ---+         |                      |
                                     +-> Release Update ----+
                                                            |
EventBridge -> Feedback Review -----------------------------+
                                                            v
                                                   Content + Publish
                                                            |
                                                            v
Manual Feedback / View -> Fixed import ------------> DynamoDB + S3
                                                            |
                                         +------------------+------+
                                         v                         v
                                     Analytics                  S3 docs
                                         |
                                         +-> active rules -> Writing

Rote / Writing -> Bedrock
Development checks -> Snyk
```

圖中 Signature check 是 Lambda 驗簽入口，Manual 是 IAM 驗證的手動匯入。Feedback／View 走固定保存路徑，不通過 Rote。Content + Publish 負責建立完整版本與上架；Writing 負責文字工作，各流程需要理解或撰寫文字時才透過它呼叫 Bedrock。

**本文件設計選擇：** 使用 Python、AWS SDK 與 CDK，維持單一程式專案；Lambda 可有不同 handler 與權限，但共用同一套模組。Rote 採小型工具呼叫迴圈，不另外引入 Agent framework 或常駐 controller。

| 規劃模組 | 責任 | 不能負責的事 |
|---|---|---|
| `ingress` | 驗簽、手動匯入、欄位檢查、事件去重、啟動流程 | 不產生教學、不能把匯入成功當發布成功。 |
| `rote` | 結構簽名、候選流程比較、adapter 執行、PROC 計數 | 不學 Feedback，不重放使用者解題步驟。 |
| `pipelines` | 三條固定流程、分支、呼叫次序 | 不讓模型任選下一個流程。 |
| `content` | 版本編號、步驟驗證、全文、diff、發布與退役 | 不修改已發布版本的教學文字。 |
| `repository` | DynamoDB 鍵轉換、關係邊、分頁、S3 存取 | 不代替業務規則作決策。 |
| `writing` | Bedrock 呼叫、JSON 驗證、規則注入 | 不直接操作資料庫或接受任意工具。 |
| `analytics` | 指標、規則驗證、狀態更新、可重建投影 | 不提出新 Authoring Rule。 |
| `demo` | 準備合成資料、觸發操作、展示結果 | 不自行改計數或決定 CREATE／UPDATE。 |

預計目錄如下；本次不建立這些實作檔案：

```text
src/training_kb/
  ingress.py       rote.py          content.py
  repository.py    writing.py       analytics.py
  pipelines/
    ticket.py      release.py       feedback.py
infra/             CDK 與三條流程定義
demo/              合成資料、展示頁與規則開關對照
tests/
  unit/            純規則與計算
  integration/     接入、儲存、發布與失敗復原
```

相依方向是「入口呼叫流程，流程呼叫領域模組，領域模組透過 repository／writing 存取 AWS」。展示頁不直接寫 DynamoDB。Snyk 在開發與部署檢查階段掃描依賴與 secrets，不在使用者請求中執行。

<a id="s6"></a>

## 6. 端到端流程

以下是**已釐清決策**對應的正常路徑；示範資料的準備方式見[第 11 節](#s11)。

1. 維護者提供同一產品的 Feature 清單，並匯入工單。Ticket Analysis 計算向量、分群，確認重複問題與功能對應。
2. 該功能沒有 active 教學時，建立 Tutorial 與 v1，檢查全文、步驟與引用後發布。已有 active 教學就 KEEP。
3. 使用者閱讀指定版本，留下瀏覽紀錄與回饋。單筆回饋只保存，不立刻改版。
4. 每日 Review 分別做兩件事：挑出弱教學並 REFINE；從同版同類的至少五筆回饋提出 candidate。
5. 黑客松使用明示的種子試用版本補足 candidate 成效。Analytics 確認評分提高且重開票率下降後，將規則改為 active。
6. 下一篇教學或下一次改寫，在寫作前取用適用的 active 規則。
7. PR #42 改名後，Release 流程沿 Feature 關係找出目前版本的第 3 步，產生新版；第 1、2、4 步保持原文。
8. Analytics 從回饋、瀏覽、工單與執行紀錄重算結果，呈現原始筆數、比例與資料來源。

<a id="s7"></a>

## 7. 接入路徑與三條流程契約

### 7.1 接入：先驗證，再承認處理成功

**已釐清決策：** 一個 GitHub webhook 接收 Issue 與 PR；Discord、email、changelog、Feedback 由維護者手動上傳。瀏覽紀錄也採同一受控匯入路徑，這是**本文件設計選擇**。

| 輸入 | 必要資料／合法值 | 讀取 | 成功後的寫入與結果 |
|---|---|---|---|
| Ticket | `id, source, text, author, ts, project_id`；source 為 github_issue／discord／email | 來源規則、PROC、既有事件紀錄 | 保存 Ticket，啟動 Ticket Analysis；embedding／cluster_id 由分析補入。 |
| Release | `id, source, feature, kind, evidence, ts`；source 為 github_pr／changelog；kind 為 renamed／changed／removed | 來源規則、PROC、既有事件紀錄 | 保存 Release，啟動 Release Note Update；renamed 另須 old_name／new_name。 |
| Feedback | `id, tutorial_version, rating, user`；rating 是 1..5 整數；category／comment 可空 | 指定版本、所屬 Tutorial、既有提交 ID | 保存 FEEDBACK 與 REFERS_TO 關係；不啟動 Step Functions、不更新 PROC。 |
| Tutorial View | `tutorial_version, user, ts` | 指定版本、既有瀏覽鍵 | 固定保存 TUTORIAL_VIEW；不呼叫模型、不更新 PROC。 |

Feedback 的 `ts` 在 ERM 未標必填；本文件選擇由匯入工具在缺值時記錄匯入時間，若來源有時間則保留來源時間。不可假稱這是使用者實際提交的時間。瀏覽的 `ts` 則必填，不能以匯入時間補成先瀏覽的證據。

Ticket／Feedback／View 的使用者 ID 必須相同才算同一人，不比對顯示名稱，也不建立 User 或身分對照表。現行規格要求上游已提供全域唯一的 t_／r_／f_ 識別碼；PR 編號不能直接當 Release.id。原始 GitHub payload 如何對應此契約見[待確認事項](#s18)。

**本文件設計選擇：** Function URL 對 GitHub 使用 `NONE`，由程式以原始 request body 計算 HMAC-SHA256，先比對 `X-Hub-Signature-256` 才解析 JSON；採固定時間比較。此設定不是免驗證接入。手動上傳由已登入 AWS 的維護者透過 SDK 呼叫匯入 handler，不建立第二個公開 URL。[Lambda URL 權限](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html)、[GitHub 驗簽](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)。

沒有或錯誤簽名、必填缺值、非法枚舉及最終正規化失敗，由入口回傳「操作失敗」與不合法欄位；不保存成合法業務物件。這裡不新增 HTTP 錯誤碼契約。

### 7.2 Rote：只記住可重複使用的接入程序

**已釐清決策：** 三層依序嘗試；前兩層重放都要求 `status=active` 且 `success_count >= 3`。

```text
Ticket / Release 原始事件
          |
          v
(1) 結構簽名相同？ ------ 是 -----> 重放 adapter 程序
          | 否                              |
          v                                 v
(2) 同網域與 adapter 類型             正規化 + validate
    Jaccard >= 0.8？ ------ 是 ------------->|
          | 否                              |
          v                                 | 失敗
(3) Agent 選 adapter <-----------------------+
          |
       validate 通過
          |
  保存物件 + 成功啟動 Step Functions
          |
   才記成功、更新 PROC
```

簽名沿用規格公式：將 `domain`、小寫排序的有意義 header 名稱、排序後的 STABLE_KEYS 組成 `shape`，用 `sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]` 取得識別碼。header 名稱限規格列出的 x-github／x-discord／x-zendesk 前綴；不放事件的 ID、標題、時間或其他值。此 SHA-1 只是結構索引，不能代替 webhook 驗簽。

已提供的 GitHub **Issue** key 清單是 `action, issue, repository, sender`。PR 與其他來源不能直接套用 Issue 清單；各事件類型的白名單仍需補足。

Jaccard 為兩組 key 的交集數除以聯集數。多個合格候選依「分數最高、last_used 最新、PROC 識別碼升序」選定。空集合不當成命中。來源網域及 adapter 範圍取自可信入口設定與流程脈絡，不能從雜湊反推；保存這份脈絡的做法列於第 18 節。

PROC 的 steps 只包含已註冊工具與 JSONPath 參數，不含真實事件值。**本文件設計選擇：** 先支援明確欄位與陣列索引的 JSONPath，不執行任意運算式。無法把工具參數可靠轉成欄位參照時，不保存成可重放程序。

工具範圍沿用草稿並縮到本案來源：`parse_github_issue`、`parse_discord_message`、`parse_support_email`、`parse_pr_diff`、`parse_changelog`，接著轉成 Ticket／Release，最後 `validate`。不包含 shell、瀏覽器、發布或任意 AWS 操作；這些工具目前均尚未實作。

保存新程序前，最後一個工具必須是已通過的 `validate`，且 Step Functions 已成功啟動；只完成欄位轉換不算一次成功。

第一次完整成功記 1；同簽名事件由 Agent 再完成相同程序才累加，第三次之後可重放。同一事件的重送不提供新的成功樣本。重放成功將 fail_count 歸零並更新 last_used；每次重放失敗加 1，連續三次後 retired。退役流程不自動覆寫，人工核定新序列後才明確重置。

### 7.3 Ticket Analysis：CREATE 或 KEEP

**已釐清決策：** 只有這條流程能建立新的 Tutorial 身分。

| 項目 | 契約 |
|---|---|
| 觸發 | 新的、合法且未重複處理的 Ticket。 |
| 讀取 | Ticket.embedding／cluster_id、同專案工單、Feature.name／aliases、Tutorial.status、active 規則。 |
| 計算 | 缺少 embedding 才呼叫 Titan；群中心比對 cosine >= 0.85，選最高者，無合格群則建立新 cluster_id。 |
| recurring | 依 Ticket.ts 的 UTC 日期，計算當日及前十三個日期；同群至少五筆才交模型命名 gap。 |
| CREATE | gap 能對應既有 Feature，且該 Feature 無 active Tutorial；寫入 Tutorial.cluster_id、v1、步驟、引用、全文與空 diff。 |
| KEEP／不建立 | 有 active Tutorial，即使尚待首次發布也 KEEP；retired 不阻擋 CREATE。無有效 Feature 時保留 Ticket 群與 gap 診斷紀錄，不建立 Feature 或 Tutorial。 |
| 成功 | KEEP 有原因紀錄；CREATE 經第 8 節發布後，讀者可讀新教學。 |
| 失敗 | 向量、寫作、引用或發布驗證失敗，有限重試後「操作失敗」；不切 current_version。 |

**本文件設計選擇：** 群中心由已保存向量計算；同分依 cluster_id 升序。新群 ID 由程式配置並保留，不重新從模型命名推導。MVP 不做合群或重編號，以保留 Tutorial.cluster_id 的追溯。

新教學必須有 Title、Problem、Prerequisites、Steps、Expected Outcome。每一步輸出 type、text 與一個既有 Feature；零個或多個引用須先拆步或驗證失敗。首版 reason 為 `gap:<cluster_id>`；KEEP 不改教學文字。

### 7.4 Release Note Update：UPDATE 或 RETIRE

**已釐清決策：** 接入已完成 change 解析。流程中的 extract_change 使用並檢查這份結果，不再呼叫模型重新決定另一個 Release 身分。

| 項目 | 契約 |
|---|---|
| 觸發 | 新的正規化 Release；多功能變更拆成不同子 Release.id，共用 source_event_id。 |
| 讀取 | Release、Feature 名稱與 aliases、REFERENCES 邊、Tutorial.current_version、已發布步驟、全文與 active 規則。 |
| 定位 | 先比 name／alias；失敗才用 Feature 語意搜尋，最高 cosine 至少 0.85 才採用。無合格 Feature 不改版、不建立功能。 |
| 補漏 | 反查為零，或 renamed 且 alias 比對失敗時，使用步驟文字搜尋，再由 Claude 確認候選。 |
| UPDATE | renamed／changed 只重寫命中步驟，其他原文複製；寫下一版、diff、reason=`release:<id>`，完成後更新 aliases。 |
| RETIRE | removed 將受影響 Tutorial.status 設為 retired；維護者可選既有 successor，未選仍完成退役。 |
| 成功／KEEP | 更新後發布；未受影響教學 KEEP。補漏無任何可確認命中時，記錄未命中並 KEEP。 |
| 失敗 | alias 撞名、模型輸出違規或寫入失敗，依第 14 節結束；不把技術故障當 KEEP。 |

若已有明確 REFERENCES 命中，補漏未增加候選也不抹掉原本命中。所有候選均再次限制為目前已發布版本。Feature PK 始終保留第一次建立時的值；改名只調整 name／aliases。

### 7.5 Periodic Feedback Review：兩個判斷分開做

**已釐清決策：** 每日只看各篇已發布的 current_version，累計該版本截至本次執行的全部有效回饋；不混入舊版，也不只計上次之後的新回饋。

```text
取得目前已發布版本的全部有效回饋
                    |
          +---------+----------+
          v                    v
      是否為弱教學？        同版同類 >= 5？
          | 是                 | 是
          v                    v
      診斷步驟與原因       提出 candidate 規則
          |                    |
      有有效命中？         保存 evidence、
          | 是             derived_from、
          v                applies_when
       REFINE
          |
   驗證完整版本並發布
```

| 項目 | 契約 |
|---|---|
| 觸發 | EventBridge 每日排程；Demo 可由受控入口手動執行同一流程。 |
| 讀取 | active Tutorial 的已發布 current_version、REFERS_TO 回饋、原步驟／全文、active 規則、已處理證據紀錄。 |
| 弱教學 | 平均 < 3.5、正式 n >= 10、同一核定問題類別 >= 5，三者同時成立。Demo 隔離門檻僅將 n 改為 >= 8。 |
| REFINE | 診斷回傳有效步驟編號與原因；只改命中步驟。reason=`feedback:<n> 則 <category>`，n 為本次該類有效證據數。 |
| 不改版 | 無有效步驟時記錄「無可改步驟」、保留回饋；沒有新有效證據時，不用同一批證據再產生新版。 |
| 提出規則 | 不必先達弱教學門檻；同一版本同類至少五筆即可提出 candidate，evidence 只存 Feedback ID，derived_from 恰好一版。 |
| 成功 | 完成符合條件的寫入；無需修改時留下判斷結果。 |
| 失敗 | Task 重試耗盡即失敗；不發布不完整新版本。已保存的合法 candidate 不因此變成 active。 |

**本文件設計選擇：** 候選規則的證據檢查先完成，再準備 REFINE，publish 放在所有必要驗證之後。同一次證據集合排序後比對，避免重複提出相同內容的 candidate；這不是把新回饋從平均分母排除。證據處理紀錄的實體儲存尚待第 18 節決定。

### 7.6 共用寫作與 Analytics 的內部介面

**本文件設計選擇：** 下表是函式間傳遞的資料，不新增公開 API 或業務實體。模型輸出須通過 JSON schema 與程式的業務驗證，才可進入儲存。

| 責任 | 輸入與輸出 | 必須由程式驗證 |
|---|---|---|
| 命名 gap | 同群文字 + Feature 清單 → gap 說明、既有 Feature 或無對應 | Feature 存在、Ticket 最多一個 Feature。 |
| 撰寫教學 | 問題 + 功能證據 + active 規則 → 五段內容與步驟 | 每步一個 Feature；型態合法；必備區塊齊全。 |
| 改寫步驟 | 原步驟 + Release／Feedback 證據 + 規則 → 指定步驟新文字 | 編號存在、僅改命中集合；其餘文字逐字相同。 |
| 分類留言 | 未勾選類別的非空留言 → 核定類別或待分類 | 不自動擴充類別表；已勾選時不覆蓋。 |
| 提出規則 | 同版同類證據 → rule、applies_when、evidence、derived_from | 至少五筆；ID 可追溯；僅 step.type 的單一等值條件。 |
| 衝突判定 | candidate + 相同適用範圍的既有規則 → 結構化判斷與證據 | 參照存在、範圍一致、不是只因文字相似就退役。 |

CREATE／UPDATE／REFINE 都在寫作前取 active 規則；applies_when 只支援 click_ui、input、read。衝突的 active 規則採最近驗證通過者，不新增 priority，也不讓寫作模型自行取捨。實際注入的 ID 寫入版本 rules_applied；複製原文不算本次套用。

Analytics 是獨立 Lambda 職責，不是第四條教學 pipeline。它依核定種子批次比較同篇套用前後已發布版本，寫入規則 status；candidate 的提出仍只屬於 Feedback Review。具體狀態條件見[第 12 節](#s12)。

<a id="s8"></a>

## 8. 教學生命週期與發布

### 8.1 五種動作與版本鏈

**已釐清決策：**

| 動作 | 發起者 | 結果 |
|---|---|---|
| CREATE | Ticket Analysis | 建立新 Tutorial，版本從 v1 開始。 |
| UPDATE | Release Note Update | 既有教學因產品改版產生下一版。 |
| REFINE | Feedback Review | 既有教學因回饋產生下一版。 |
| KEEP | Ticket／Release 的判斷結果 | 只記原因，不改教學內容、不增加版本。 |
| RETIRE | Release Note Update | Tutorial.status 改為 retired，保留歷史原文與版本。 |

```text
Tutorial: prepare-meeting
  |
  +-- v1   reason = gap:c12
  |     ^
  |     | supersedes
  +-- v2   reason = feedback:8 則 找不到按鈕
  |     ^
  |     | supersedes
  +-- v3   reason = release:r_42
        ^
        |
  current_version（僅在 v3 publish 成功後指向這裡）
```

版本號屬於 Tutorial，三條流程不能各自計數。同一邏輯變更失敗重試時重用原 version_id；永久失敗可留下號碼缺口。下一次成功版本仍以最近的已發布版本為基底，不把不完整文字帶入新版。已發布內容不可覆寫。

**本文件設計選擇：** `content` 模組集中負責版本分配及發布；不讓各 handler 自行拼出「current + 1」。新版本須保存與原操作的對應，才能在重送時找回相同版號。

### 8.2 create_version 的完成條件

**已釐清決策：** 建立版本與發布是兩個步驟。

```text
分配本次版號
     |
驗證五段內容、命中範圍、每步一個 Feature
     |
寫 S3 全文與 diff
     |
寫 VERSION、STEP 與必要關係
     |
核對全部內容與關係
     |
未發布版本：published_at = null
     |
publish 成功
     |
published_at 有值 + current_version 切換
```

S3 成功但版本或關係未完成時，保留不可公開的產物，不刪掉後偽稱成功。v1 仍有空的 `v1.diff`；畫面顯示「第一版，沒有前一版可比較」。一般 diff 使用 unified diff，是**本文件設計選擇**。

套用關係以 VERSION.rules_applied 為準。RULE.applied_to 與 APPLIED_TO 邊由它重建並去重；發布前檢查所需關係已就緒，不把三份表示都當獨立權威。

### 8.3 發布與併發必須守住的界線

**已釐清決策：** 同篇變更依接受順序串行，輪到該次操作時才讀最新基底。先前版本尚未完成時，後來的 Release／Feedback 不得同時從舊版寫出另一條版本鏈。

**本文件設計選擇：** 黑客松先採單一專案的序列化寫入，縮小需要協調的範圍；接受順序、原操作對應版號、已處理證據由共用操作紀錄支援。這些是執行資訊，不新增第十一個業務實體。實際儲存位置與取得寫入順序的機制仍是[O2](#s18)，不能把「共用模組」或條件更新本身當成順序保證。

publish 必須在全文、diff、步驟與關係齊全後才成功；失敗保持舊 current_version。**本文件設計選擇：** DynamoDB 內的 published_at 與 current_version 使用同一交易更新，並檢查基底未改變。S3 產物先保存在私有區，公開站僅使用完成發布的版本。

**待確認事項 O3：** DynamoDB 交易不能同時提交 S3 網站的公開切換。公開 HTML、發布時間與目前版指標之間的失敗復原仍需一個整合驗證；只列出寫入先後不足以保證完全同步。在解決之前，不可宣稱 publish 的故障驗收已通過，也不能用「只是沒有連結」代替未發布內容不可公開。

同一 Release 或每日 Review 若命中多篇教學，也受 F49「整次失敗不發布新版」限制。不能在逐篇 Map 中先發布 A，再因 B 失敗而聲稱整次沒有發布。建議先完成所有待發布產物的驗證，再集中提交；多篇提交途中失敗如何保持此契約，一併納入 O3，不能默默改成允許部分成功。

S3 可使用條件寫入防止已存在物件被覆蓋；同 key 已存在時，應核對它是否為本次相同產物，而非盲目重寫。[S3 條件寫入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)。DynamoDB 交易僅涵蓋其中的資料庫操作，仍需遵守其交易限制。[DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)。

### 8.4 退役後的畫面與資料

**已釐清決策：** 資料只使用 `retired`；obsolete 是顯示用語。沒有 successor 時仍完成退役，顯示過期原因與原文，不導向別篇。維護者選了既有 successor 才顯示後繼教學連結，來源事件不能直接指定。

退役版本拒絕新回饋，原回饋仍可查閱。**本文件設計選擇：** 後繼連結優先採明確可點的提示，不做連續自動跳轉；設定時檢查存在、可公開、非自身且不形成循環。找不到合法後繼時保持空值，不能阻擋退役。

<a id="s9"></a>

## 9. 十個邏輯實體如何存入一張表

### 9.1 鍵與原生型別

**產品／黑客松約束：** DynamoDB 表名為 `training_kb`，複合主鍵為 `PK, SK`；唯一 GSI `by_target` 以 `target` 為分割鍵。S3 的邏輯名稱為 `training-kb-content`。部署時實際 bucket 名稱須符合 AWS 的唯一性要求，不假設此名稱可直接取得。

**本文件設計選擇：** GSI 不另加排序鍵，先投影查詢需要的鍵；完整資料回基表取得。沒有 target 的 metadata item 不放入反向關係索引。

下表的 `META` 是**待確認事項 O1 的建議值**，不是 ERM 已定案欄位；Step 已有明確的 REFERENCES 排序鍵。View 的鍵則由本文件明確選定。

| 邏輯實體 | PK | SK | 保存內容 |
|---|---|---|---|
| TUTORIAL | `TUTORIAL#<slug>` | 建議 META | current_version、topic、feature_ids、status、successor、固定的 cluster_id。 |
| TUTORIAL_VERSION | `VERSION#<slug>@v<n>` | 建議 META | supersedes、reason、rules_applied、s3_key、published_at。 |
| TUTORIAL_STEP | `STEP#<slug>@v<n>#<i>` | `REFERENCES#<Feature PK>` | target、type、text；同一 item 同時表達步驟與引用。 |
| FEATURE | `FEATURE#<建立時名稱>` | 建議 META | name、aliases、first_seen；PK 不因改名遷移。 |
| TICKET | `TICKET#<id>` | 建議 META | source、text、author、ts、project_id、cluster_id、feature_ids、embedding。 |
| RELEASE | `RELEASE#<id>` | 建議 META | source_event_id、source、feature、kind、old_name、new_name、evidence、ts。 |
| FEEDBACK | `FEEDBACK#<id>` | 建議 META | tutorial_version、rating、category、comment、user、ts。 |
| TUTORIAL_VIEW | `VIEW#<事件摘要>` | META，設計選擇 | tutorial_version、user、ts。 |
| AUTHORING_RULE | `RULE#<rule_id>` | 建議 META | rule、applies_when、evidence、status、applied_to、derived_from。 |
| PROVEN_WORKFLOW | `PROC#<signature>` | 建議 META | steps、keys、success_count、fail_count、status、last_used；沒有圖譜邊。 |

**本文件設計選擇：** View 的事件摘要為正規化後 `[tutorial_version, user, ts]` 的固定 JSON 編碼 SHA-256。相同三元組重送得到相同 PK；不同瀏覽時間建立不同紀錄。它只用於瀏覽去重，不是使用者 ID。此選擇會合併完全同一時間的重複紀錄；不影響每版每人最多一次的指標分母。View 不要求新增 `view_id` 輸入欄位。

邏輯關聯保存裸 ID，例如 `prepare-meeting@v2`、`R-007`；PK、SK、target 才加類型前綴。Feature 的裸識別採固定 PK 後綴，不使用會變動的顯示名稱重新產生 ID。DBML 用來表達 Ref 的 slug／version_id／tutorial_version 等「衍生投影」，由既有鍵解析，不額外增加一份持久化欄位。

List、Map 使用 DynamoDB 原生型別；embedding 是含 1024 個有限數值的清單。DBML 的 string 投影不表示把所有資料 JSON 字串化。全文只存 S3，DynamoDB 保留各步文字供定位；不得另存 embedding_ref。

### 9.2 關係邊

**已釐清決策：** 邊的通用格式為 `PK=起點`、`SK=關係#終點`、`target=終點`。

| 起點 PK | SK 範例 | target | 用途 |
|---|---|---|---|
| `STEP#prepare-meeting@v2#3` | `REFERENCES#FEATURE#Prepare` | `FEATURE#Prepare` | 功能反查引用步驟。 |
| `VERSION#prepare-meeting@v3` | `SUPERSEDES#VERSION#prepare-meeting@v2` | `VERSION#prepare-meeting@v2` | 版本往前追溯。 |
| `RULE#R-007` | `APPLIED_TO#VERSION#prepare-meeting@v2` | `VERSION#prepare-meeting@v2` | 規則套用版本，可重建。 |
| `TICKET#t_881` | `ASKS_ABOUT#FEATURE#Prepare` | `FEATURE#Prepare` | 工單至功能，最多一條。 |
| `FEEDBACK#f_12` | `REFERS_TO#VERSION#prepare-meeting@v1` | `VERSION#prepare-meeting@v1` | 版本反查回饋。 |

沒有另外發明 HAS_VERSION、User 或 Project 邊。View 先依既有欄位掃描篩選，不新增規格未列的 VIEWED 關係。Tutorial.successor 保存在 metadata，不另造 SUCCESSOR 邊。

### 9.3 S3 與執行資訊

| 路徑 | 地位 | 內容 |
|---|---|---|
| `tutorials/<slug>/v<n>.md` | 已釐清決策 | 該版完整教學，未發布時不可公開。 |
| `tutorials/<slug>/v<n>.diff` | 已釐清決策 | 與前版的差異；v1 是空檔。 |
| `stepfunctions/<pipeline>/v<n>.json` | 已釐清決策 | ASL 定義快照，版本號與教學無關。 |
| `site/` | 本文件設計選擇 | 公開教學 HTML 與靜態資產；僅發布流程可寫。 |
| `demo/previews/` | 本文件設計選擇 | B 規則開關對照產物，不進正式教學與統計。 |
| `operations/` | O2 建議，尚待確認 | 重試所需輸出、已處理證據、規則驗證批次等執行紀錄；私有。 |

**本文件設計選擇：** ASL 在受控部署流程中先保存快照再更新 state machine；使用 ticket-analysis、release-update、feedback-review 三個名稱。這次不產生 ASL 檔或部署資源。

<a id="s10"></a>

## 10. 圖譜查詢與多跳定位

「圖譜」在這裡是資料之間可追溯的關係，不需要另一個圖資料庫。

```text
Feature: FEATURE#Prepare
   |
   | by_target(target = FEATURE#Prepare)
   v
所有指向它的邊
   |
   | 只取 STEP# 起點 + REFERENCES# 關係
   v
候選步驟：A v1 #3、A v2 #3
   |
   | 查 Tutorial.current_version 與 VERSION.published_at
   v
目前已發布步驟：A v2 #3
   |
   | 讀 S3 v2 全文；只重寫第 3 步
   v
A v3；A 的其他步驟、B、C 原文不變
```

**本文件設計選擇：** `repository` 提供下列固定讀取，不讓 LLM 拼查詢。

| 問題 | 查法 |
|---|---|
| 起點有哪些關係？ | 以完整 PK Query，按 SK 的關係前綴篩選。 |
| 誰引用 Feature？ | Query by_target，再篩選 STEP／REFERENCES；排除 ASKS_ABOUT 等其他邊。 |
| 某篇教學有哪些版本？ | MVP 對基表分頁 Scan，依 VERSION PK 解析的 slug 篩選；不能用 PK 前綴冒稱是有效的 DynamoDB Query。 |
| 規則套用哪些版本？ | RULE 起點的 APPLIED_TO 邊；以各版本 rules_applied 核對或重建。 |
| 某版有哪些回饋？ | Query by_target，保留 FEEDBACK／REFERS_TO，再讀回饋本體。 |
| 某版有哪些瀏覽者？ | Scan TUTORIAL_VIEW，篩選 tutorial_version 與時間，再依 user 去重。 |

所有 Query／Scan 都必須讀完分頁；空的一頁不等於全部沒有資料。Query 以 LastEvaluatedKey 接續，直到沒有下一頁。[DynamoDB 分頁](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html)。

GSI 只有最終一致讀取，可能尚未反映剛寫入的邊。**本文件設計選擇：** 在本案的小量資料與序列化教學寫入範圍內，改版前以基表一致讀取核對目前版的完整引用集合，避免 GSI 暫時少資料就錯判 KEEP。不能只多等固定秒數便宣稱結果完整；基表 Scan 也不當成跨併發寫入的快照。此核對與第 8 節的寫入協調一併驗收。[DynamoDB 一致性](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html)。

正常關係遍歷不呼叫 AI。alias 未命中或需要補漏才做語意搜尋。**本文件設計選擇：** 先在 Lambda 對少量 Feature／步驟文字計算向量並比較；Feature／Step 向量可在單次執行內重用，不往 ERM 增加 embedding 欄位，也不假設 DynamoDB 原生提供本案的向量查詢。

backfill 比對已發布版本的 S3 Steps 與基表 STEP／REFERENCES，找出缺少的引用。優先沿用已保存的版本建立輸出；若需從原文重新抽取 Feature，可呼叫文字分析，但必須確認恰好一個既有 Feature 才補邊，不能確定就列為待處理。這與一般關係查詢不呼叫 AI 的路徑分開計數。

每步若已有另一個引用，不再追加第二個，而是記錄錯誤供處理。不替換舊邊、不改歷史文字、不因此產生新版本。執行頻率見第 14.3 節。

<a id="s11"></a>

## 11. Demo 資料與展示順序

### 11.1 共用一份產品資料清單

**本文件設計選擇：** 同一批 Demo 的工單、Feature、Release、教學、Feedback、View 都引用同一份清單。核心為 A「準備會議」、B「分享摘要」、C「設定通知」；PR #42 描述 Meeting Summary 改名為 Prepare。Feature PK 一開始即固定，不能在展示中把改名說成搬移主鍵。

種子套件需包含以下資料。這些是**待實作並核定的合成資料配方**，不是已存在的原始觀測或已核准批次。

| 資料 | 配方與檢查 |
|---|---|
| 產品功能清單 | 每個 Feature 的固定 PK、目前 name、aliases；包含 FEATURE#Prepare，名稱不可與其他功能撞名。 |
| 建立教學用工單 | 20 筆不同 t_ ID，具備 source／text／author／ts／project_id；時間落在執行當日及前十三個 UTC 日期。 |
| 版本全文 | A v1／v2 的完整四步與五個區塊；每步有一個 Feature。B、C 不引用 Prepare。 |
| Release | `r_42` 是本配方的合成上游 ID，與人看的 PR #42 分開；提供 renamed、old_name、new_name、evidence、ts。 |
| 回饋與瀏覽 | 使用下兩節可展開的資料；ID、版本與穩定使用者相互對得上。 |
| 規則試用 | 明示 A v2 是 R-007 candidate 的合成試用版本；提供實際注入紀錄、rules_applied 與核定批次清單。 |
| 執行紀錄 | 真實呼叫次數另留逐次 trace；預先準備的 trace 需明示為歷史展示。 |

工單文字使用相同功能的不同問法，例如「會前摘要在哪裡開啟？」、「如何看到開會前整理的重點？」。實作時展開為二十筆完整資料並驗證實際 embedding 分群；不能只把所有 cluster_id 寫成 c12 就聲稱已測過分群。

**已釐清決策：** 缺少原始 Example 可使用明示合成且經確認的驗收資料。文件中的配方不自動解除 Gherkin 的 @Missing。

### 11.2 可重算的評分與負面回饋

以下屬**本文件設計選擇**。八筆基底證據對應既有 R-007 的 Feedback ID；兩組使用相同的 u_01 等穩定 ID。表內「空」表示 category／comment 不提供。

| 版本 | Feedback ID | user | rating | category |
|---|---|---|---:|---|
| A v1 | f_12 | u_01 | 2 | 找不到按鈕 |
| A v1 | f_15 | u_02 | 2 | 找不到按鈕 |
| A v1 | f_19 | u_03 | 3 | 找不到按鈕 |
| A v1 | f_23 | u_04 | 3 | 找不到按鈕 |
| A v1 | f_27 | u_05 | 3 | 找不到按鈕 |
| A v1 | f_31 | u_06 | 3 | 找不到按鈕 |
| A v1 | f_34 | u_07 | 3 | 找不到按鈕 |
| A v1 | f_40 | u_08 | 4 | 找不到按鈕 |
| A v2 | f_101 | u_01 | 2 | 缺少資訊 |
| A v2 | f_102 | u_02 | 2 | 缺少資訊 |
| A v2 | f_103～f_110，各一筆 | u_03～u_10，一對一 | 每筆 5 | 空 |

A v1 每筆 comment 使用合成文字「第三步沒有指出按鈕在哪一頁與位置」；A v2 的 f_101／f_102 使用「資訊仍不夠完整」，其餘 comment 空。版本分別展開為 prepare-meeting@v1／@v2；時間分別為各版模擬發布後第二日。

計算結果：

- A v1：總分 23／8 = 2.875，顯示一位小數為 **2.9**；八筆皆有核定問題類別，所以負面回饋 **8**。
- A v2：總分 44／10 = **4.4**；只有兩筆低分或問題類別，所以負面回饋 **2**。
- Demo 的 A v1 滿足 n >= 8、平均 < 3.5、同類 >= 5；在正式 n >= 10 模式下，這八筆不觸發 REFINE。

指標判斷使用未四捨五入的數值；顯示位數不影響門檻。

### 11.3 可重算的瀏覽、重開票筆數與比例

以下同為**合成歷史配方**，不把模擬發布時間套在本次真實發布上。

| 項目 | A v1 | A v2 |
|---|---|---|
| 模擬 published_at | 2026-08-01T00:00:00Z | 2026-08-20T00:00:00Z |
| 瀏覽紀錄 | u_01～u_10，各在 08-02T09:00:00Z 一筆 | 同十人，各在 08-21T09:00:00Z 一筆 |
| 先瀏覽後同題開票 | u_01～u_07，各在 08-03T10:00:00Z 一筆 | u_01～u_02，各在 08-22T10:00:00Z 一筆 |
| Ticket ID | t_2001～t_2007，一對一 | t_2101～t_2102，一對一 |
| 固定同題對應 | Tutorial.cluster_id = c12；上述 Ticket.cluster_id = c12 | 同左 |
| 重開票筆數 | **7** | **2** |
| 符合條件的不同使用者／瀏覽者 | 7／10 | 2／10 |
| 依此配方計算的重開票率 | **70%** | **20%** |

上述九筆 Ticket 的 source 為 email，project_id 為本 Demo 的固定專案 ID，author 依表中使用者，text 為「看過準備會議教學後，仍找不到第三步的按鈕」。View 使用相應的完整 tutorial_version、user、ts；其 PK 依第 9 節計算。所有時間皆為 2026 年 UTC。

70% 與 20% 是這份配方新增分母後的計算結果，並非來源文件已量測的百分比。另加驗收資料時，先開票後瀏覽、同人重複瀏覽、同人多次開票、不同 cluster、窗外時間均需分開測；不得混入本表以維持目標數字。

### 11.4 讓規則轉移的順序正確

**已釐清決策 + 本文件設計選擇：**

```text
A v1 的八筆同類回饋
          |
          v
R-007 candidate
          |
匯入明示的 A v2 試用版本與完整核定種子批次
          |
Analytics：2.875 -> 4.4，70% -> 20%
          |
          v
R-007 active
          |
    +-----+----------------------+
    v                            v
後續正式 B v1 可採用規則      PR #42 更新 A 的第 3 步
                                 |
                                 v
                           A v3 仍採用規則
```

B 的「規則關閉／開啟」並排比較是兩份隔離預覽，使用同一批 Ticket，兩份都不寫正式 Tutorial、rules_applied、Feedback 或效果統計。若另展示正常 Ticket Analysis 建立 B v1，使用獨立正常流程，並在畫面與預覽明確區分。

因此既有 Example 中 R-007 的三次套用，可以由 A v2 的明示試用、正常 B v1、後續 A v3 構成；不能把 B 的兩份預覽都算進去。沒有套用前版本的 B v1，不用來當 R-007 啟用所需的前後對照。

退役 R-012 的展示需兩個完整、不重疊的核定種子批次，各自含同篇前後對照、原始回饋／瀏覽／工單與前態。兩批都未改善才退役；只有「缺少資訊增加」一句話不足以證明完整轉換。此資料屬後續驗收工作，不在本文件假造已完成結果。

### 11.5 Demo 的資料與即時執行分開標示

畫面固定標示「合成資料示範」及資料批次。即時運作使用真實執行時間；模擬歷史資料使用明示的模擬時間。兩者不得合併成真實使用者成效。

初次建教學與歷史成效回放可分成兩個受控 Demo 場次，各自使用單一專案資料；不在同一場混入重複版本。預先跑好的教學可供備援展示，但必須寫「預先執行結果」，不能將它當成本次 AWS 呼叫成功。

<a id="s12"></a>

## 12. 學習指標與規則狀態

### 12.1 指標公式

**已釐清決策：**

| 指標 | 計算方式 | 空資料／注意事項 |
|---|---|---|
| 每版平均評分 | 該版有效 Feedback.rating 總和／有效 Feedback 筆數 | 無評分為 null，顯示「尚無評分」；不當成 0 分。 |
| 跨版平均評分 | 先算每版平均，再對版本等權平均 | 不把所有回饋混成一個加權平均。 |
| 負面回饋數 | rating <= 2 **或** category 為核定問題類別的 Feedback ID 集合大小 | 同筆同時命中只算一次；待分類不因類別計負面。 |
| 同題重開票筆數 | 符合瀏覽先後、版本窗口與 cluster 的不同 Ticket ID 數 | 可多於重開票使用者數，不能直接當比例。 |
| 同題重開票率 | 符合條件的不同開票使用者數／該版窗口內不同瀏覽者數 | 每版每人分子、分母各最多一次；分母 0 顯示 N/A／樣本不足。 |
| 已學規則數 | 分別計算 candidate、active、retired 的 RULE item | 不把 candidate 全部寫成已有效。 |
| 規則套用次數 | 去重且核對過的 applied_to 長度 | 以 VERSION.rules_applied 重建，不計原文沿用或隔離預覽。 |
| Bedrock 呼叫數 | 每次實際送出的請求嘗試總數 | 包含 embedding、Rote、Map 每一項、失敗與重試；記憶體重用不算新呼叫。 |

對版本 v，發布時間為 p，窗口為發布後十四天。分母為該窗口內 TUTORIAL_VIEW 的不同 user；分子使用同一 user，要求存在 `view.ts < ticket.ts`，且 Ticket 位於相同窗口並符合 Tutorial.cluster_id。Feedback.user 共用身分，但回饋本身不是「看過教學」的替代證據。

**待確認事項 O4：** ERM 明留窗口端點與時間編碼未定義。本文件建議 UTC、窗口 `[p, p + 14 天)`；這是本文件配方的計算假設，須在時間邊界驗收前確認。不得拿工單 recurring 的「UTC 當日加前十三日」替代這個窗口。

**本文件設計選擇：** MVP 規則驗證先使用一組同篇前後配對。多組版本的評分依既定等權公式；多組重開票率的彙總權重尚未定義，先逐組顯示，不自行用總 Ticket／總 View 判斷規則狀態。

### 12.2 規則驗證

**已釐清決策：** 一般寫作只讀 active；只有 Analytics 能寫驗證後狀態。

```text
Feedback Review
      |
      v
  candidate --完整核定批次且兩項嚴格改善--> active
      |                                      |
      | 驗證成立的衝突                        |
      | 或連續兩個核定批次未改善              | 連續兩個核定批次未改善
      v                                      v
   retired <---------------------------------+

資料不足：保持原狀態
```

啟用必須同時滿足「套用組平均評分嚴格提高」和「同題重開票率嚴格下降」。對照來自同篇套用前的已發布版本，不使用未發布版本或跨教學湊對照。零分母、缺平均、未完整載入批次時，不作有效／無效判定。

持平或僅一項改善都不符合啟用條件。candidate／active 連續兩個不重疊的核定種子批次未改善才退役；線上樣本不足不算失敗批次。MVP 的狀態變更只在完整核定種子批次中執行，包括依驗證過的衝突判斷退役 candidate；不覆蓋既有 active 規則。

模型負責回傳衝突判斷與證據，Analytics 驗證適用範圍及引用後才寫狀態。相近規則的 curation 在 MVP 只產生供人工檢視的群組，不合併 ID、不搬移 evidence、不自動修改文字或 status。

規則共享只使用明示合成種子證據，不把真實專案的回饋或來源版本帶到其他專案。MVP 本身仍只有一個專案，不因此增加多租戶架構。

### 12.3 指標不能替代的證據

評分前後差異與重開票率都是觀察結果，不宣稱已證明因果。根目錄設計中的「省時」與「降低支援成本」可作產品目標，本次沒有真實工時測量，不能填入投影片當實測。

來源表的 Bedrock 8 → 2、過期步驟 1 → 0 仍是展示目標。呼叫數須由逐次 trace 核對；過期步驟須由已知 Release 與目前文字核對。若實際是三次呼叫就顯示三次，不為配合表格而刪掉 embedding 或 retry。

<a id="s13"></a>

## 13. Demo UI 與 S3 教學頁

**已釐清決策：** S3 靜態 docs 站是教學發布入口；不再做 in-app 教學頁。Demo UI 只觸發與展示，所有門檻由後端流程判定。

**本文件設計選擇：** 靜態教學頁提供教學內容、版本選擇、diff 與 feedback widget。Demo 操作區由維護者本機開啟，使用既有 AWS 登入；瀏覽器不嵌入 AWS 或 GitHub 金鑰。

```text
[合成資料示範]  準備會議                     版本：v3
原因：PR #42 將 Meeting Summary 改名為 Prepare

1. ...
2. ...
3. 開啟會議頁面，在右上角選擇 Prepare，查看會前摘要。
4. ...

[查看與 v2 的差異]    [查看版本紀錄]

這篇有幫助嗎？  [1] [2] [3] [4] [5]
問題類別： [找不到按鈕] [缺少資訊] [未選擇]
留言： _____________________________
[下載回饋檔案，交由維護者匯入]
```

為符合「Feedback 手動上傳」，widget 先產生回饋檔，維護者再匯入；下載後顯示「檔案已產生，尚未送出」，只有匯入成功才顯示已保存。瀏覽紀錄同樣匯出後匯入，不宣稱即時自動收集。

Demo 使用事先提供的穩定 user ID；缺少 ID 時要求補入，不能用瀏覽器隨機 ID 或使用者姓名假裝能與 GitHub 作者對上。若匯入時版本不存在、教學已退役或欄位非法，指出問題欄位並保留供修正，不顯示成功。

Dashboard 只需四個區塊：最新教學與版本差異、每版評分與回饋數、重開票筆數及分子／分母、規則狀態與來源證據。另提供 B 的隔離開關對照，以及當次執行的實際模型呼叫數。少量離散版本使用表格或折線即可，不建立報表平台。

**平台限制：** S3 website endpoint 只有 HTTP；本文件不把它描述為 HTTPS。若要公開提供可靠的 HTTPS 網站，需另確認 CloudFront 等託管方式與範圍；本次不默默加進 MVP。只有可公開的示範教學可以進 site 區，回饋原文、身份、執行紀錄與未發布產物保持私有。[S3 website endpoints](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteEndpoints.html)。

<a id="s14"></a>

## 14. 錯誤、重送與執行限制

### 14.1 各層如何結束

下列是**已釐清決策**的失敗語意；「操作失敗」對應規格的 `Then 操作失敗`，不新增業務錯誤碼表。

| 情況 | 負責層與結果 |
|---|---|
| webhook 無簽名、簽名不符 | Ingress 拒絕，不能先進 Rote 或寫合法 Ticket／Release。 |
| Rote 重放失敗 | Rote 記連敗並當次回退 Agent；Agent 最終也失敗則 Ingress 回傳失敗。 |
| Feedback 欄位非法或版本不存在 | Ingress 指出欄位，允許修正；不建立 FEEDBACK 或成功回執。 |
| schema 通過但步驟、引用或未改文字不符 | writing／content 的業務驗證拒絕，有限重試後失敗，不發布。 |
| 分析找不到有效 Feature | Ticket 流程保留 gap；Release 不改版。這是明確的業務結果，不是模型服務故障。 |
| 補漏沒有確認步驟 | Release 記錄未命中，無其他有效命中時 KEEP。 |
| 診斷沒有有效步驟 | Review 不建立版本，保留回饋；不改成整篇重寫。 |
| S3／DynamoDB 部分寫入 | 保留不可公開的未完成版本；重送沿用原版號，補齊後才發布。 |
| Task 重試耗盡 | Catch 導向失敗終點，不發布新版；不新增待審狀態或另一個待處理入口。 |
| 已 retired 的 PROC／Tutorial | PROC 不重放；Tutorial 不接受新回饋；歷史保留。 |
| 同一事件／Feedback 重送 | 取得既有結果或沿用未完成邏輯操作；不新增版本、回饋樣本或 PROC 成功樣本。 |

### 14.2 重試不是重新抽一次文字

**本文件設計選擇：** 一次邏輯操作的 ID、正規化結果、模型輸出與分配版號一旦保存，儲存階段重試就重用它們。若外部寫入結果不明，先核對既有物件；不要直接再分配 ID 或重新呼叫模型。

三條 state machine 採 Standard，便於查執行紀錄。StartExecution 對「同名、同 input、仍在執行」有冪等行為；已結束的同名執行會回傳 ExecutionAlreadyExists，不能把此例外直接當成功，也不能改名就無條件重跑。需檢查原結果與操作紀錄；其保留與重試關聯是 O2。[StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)。

每個 Task 都設 Retry 與 Catch；Catch 到失敗終點。區分暫時服務故障與確定非法資料，不無限重試。States.ALL 並非涵蓋所有終止錯誤；ASL 資料路徑與 payload 大小需另外驗證。[Step Functions 錯誤處理](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)。

### 14.3 執行參數的建議起點

以下是**本文件設計選擇**的初始設定，不是已釐清的產品門檻；先用這些有限值實作，再以模型與執行時間驗證。O5 保留帳號可用模型及參數支援的確認。

| 項目 | 黑客松建議 |
|---|---|
| 一般判斷模型 | max_tokens 512、temperature 0.1；適用於支援這些參數的 Claude 模型。 |
| 教學寫作模型 | max_tokens 2048、temperature 0.1；截斷則驗證失敗，不發布缺段落的文字。 |
| 呼叫與 Task 時限 | Bedrock 連線最多 2 秒、等待回應最多 30 秒；一般 Lambda 最多 90 秒，Task 最多 120 秒。公開 webhook 的整體 8 秒期限優先。 |
| Pipeline 暫時錯誤 | 最多重試兩次，等待 1 秒、2 秒；模型輸出業務不合法最多修正一次後失敗。只讓一層管理重試，避免 SDK 與 Task 次數相乘。 |
| 每日 Review | UTC 00:30；Demo 手動觸發相同邏輯，不修改正式門檻。 |
| backfill | 與每日維護同批執行，保持獨立紀錄，不新增第四條教學 pipeline。 |
| 工作流資料 | state 間傳 ID、必要的小型判斷結果或 S3 key，不攜帶全文與向量陣列。 |

Titan V2 是 embedding API，不使用文字生成的 max_tokens／temperature；程式的共用呼叫設定須區分兩類。Titan 設定輸入上限、1024 維輸出與 timeout，生成模型才傳輸出 token 上限。不能為滿足文字規格而向 embedding API 塞不支援的參數。[Titan Embeddings](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)。

Claude 的取樣參數依選定模型檢查；本案只設定 temperature，不同時調整 top_p。若模型不支援表列設定，先確認可用替代模型，不能默默忽略判斷節點的低 temperature 契約。[Claude 請求參數](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages-request-response.html)。

GitHub 要求及時回應，超過十秒可能記為失敗，而且不自動重送。**本文件設計選擇：** 公開入口在八秒內完成或明確回傳失敗；不能先回成功、再讓不合法正規化留待背景處理。首次 Rote 探索可能超時，展示前先以受控事件累積成功流程；需重新送達時由維護者使用 GitHub 原有重送功能。[GitHub 失敗處理](https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries)。

每次實際 Bedrock 請求記錄所屬操作、節點、模型、嘗試序號與結果；以嘗試為單位計數。不要把原始 request body、secret 或使用者全文直接寫進公開 log。

<a id="s15"></a>

## 15. 測試與驗收設計

**已釐清決策：** Gherkin 的 Rule 是驗收依據；`@Missing` 表示還缺案例，不能直接刪掉規則或宣稱已測過。後續可補明示合成且經確認的資料，但本階段不改 Gherkin。

**本文件設計選擇：** Python 純邏輯以 pytest 驗證，AWS 整合使用隔離的 Demo 環境；目前未安裝或設定測試工具，不提供尚不存在的執行指令。

| 驗收範圍 | 必須看見的結果 |
|---|---|
| 來源與 Rote | 有效／無效／缺少簽名；事件值改變不改結構簽名；Jaccard 0.7999／0.8；成功數 2／3；成功穿插失敗不誤退役。 |
| 接入去重 | 同事件重送只對應一次邏輯處理；保存後但啟動前失敗可辨識，不遺失也不重複建版。 |
| Ticket 分析 | cosine 0.8499／0.85；UTC 日期窗口；四筆／五筆 recurring；active 未發布仍 KEEP；無 Feature 不 CREATE。 |
| 全文與步驟 | 五段齊全；每步零／一／多 Feature；非法步驟型態；schema 合法但引用不存在時拒絕。 |
| 版本與發布 | 同篇 Release／Feedback 按接受順序；重試同版號；v1 空 diff；S3 或邊寫入失敗時 current_version 不變。 |
| Release 精準更新 | A 只改第 3 步，第 1、2、4 步逐字相同；B、C 無新版；歷史或未發布步驟不觸發更新。 |
| 退役 | 有／無後繼都能完成；保留原文；拒絕新回饋；無效後繼不建立循環導向。 |
| 回饋輸入 | rating 0／1／5／6／非整數；僅評分有效；勾選優先；未知類別待分類；同 ID 重送不增加樣本。 |
| Review | 正式 n=9／10、Demo n=7／8；平均 3.49／3.5；同類 4／5；無新證據不重做；無有效步驟不整篇改寫。 |
| 規則 | 同版五筆可提案、跨版 3+2 不可；candidate 不進一般 prompt；實際注入才計套用；同範圍衝突採最近驗證者。 |
| Analytics | 零評分／零瀏覽；先開票後瀏覽不計分子；重複瀏覽與多次開票分別去重；2.9／4.4 與 7／2 可由配方重算。 |
| 規則驗證 | 兩項都改善才啟用；持平、單項改善不啟用；不完整批次保持原狀；連續兩個不重疊未改善批次才退役。 |
| 圖譜與索引 | 多頁與空頁後仍有下一頁；GSI 延遲不誤判無影響；backfill 只補漏、不替換錯邊。 |
| UI 與公開界線 | 未發布資產不可公開；回饋下載不顯示已送出；退役頁不能送新回饋；B 預覽不污染正式統計。 |
| 呼叫與失敗 | 每個 Task 有 Retry／Catch；終止不發布不合規內容；重試、Map、Rote、embedding 都計入實際請求數。 |

測試證據依責任保留：純計算的輸入輸出、儲存前後資料、Step Functions 執行紀錄、實際教學頁與 diff。不能只看模型說「已完成」，也不能用 JSON parser 成功替代業務驗收。

文件層可先檢查來源連結、Rule 對照與 Markdown 格式；DBML／Gherkin parser 僅驗證語法，不證明上述流程已完成。本次沒有執行應用程式測試。

<a id="s16"></a>

## 16. 交付切片與依賴順序

**本文件設計選擇：** 依可展示的結果分切片。這是設計中的相依圖，不是另產生一份 implementation plan 或建立實作檔案。

```text
S0 -> S1 -> S2 -> S3 -> S4 -> S6 -> S7 --+
                   |                   +-> S8
                   +-------> S5 -------+
```

| 切片 | 完成後的手動檢查 | 前置 |
|---|---|---|
| S0 | O2／O3 的最小整合驗證有可追溯結果；來源 ID、白名單與模型可用性已確認。 | 第 18 節 |
| S1 | 一則有效 GitHub 事件正規化；缺簽名失敗；手動上傳走受控入口。 | S0 |
| S2 | 工單達門檻後建立未發布 v1；active 已存在時 KEEP。 | S1 |
| S3 | 發布後讀到正確全文；中途失敗仍讀舊版；版本與引用齊全。 | S2 |
| S4 | View 與 Feedback 可匯入；穩定 user 能對上工單；重送不重複。 | S3 |
| S5 | PR #42 只改 A 第 3 步；removed 呈現退役；B、C 不變。 | S3 |
| S6 | Demo 八筆走隔離門檻；REFINE 只改有效步驟；candidate 不自動進一般寫作。 | S4 |
| S7 | 原始資料重算成效，R-007 由 Analytics 啟用，再供後續寫作使用。 | S6 |
| S8 | 展示兩條循環、B 隔離對照、真實呼叫數及一次儲存失敗復原。 | S5、S7 |

先完成這九個結果，再考慮更大量資料或額外介面；不為 stretch 功能提前增加服務。

<a id="s17"></a>

## 17. 平台查證、安全與 Demo 當日準備

### 17.1 已查證的平台用法

查證日期為 2026-09-13。以下是平台事實；帳號權限、區域及實際配置仍須部署前確認。

| 平台 | 查證結果與設計影響 | 官方來源 |
|---|---|---|
| Bedrock | Titan V2 模型 ID 為 `amazon.titan-embed-text-v2:0`，支援 1024 維；本案固定此維度。 | [Titan Embeddings](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html) |
| 生成模型 | safety_net 依規格使用 Claude；具體 Claude model ID／inference profile 由可用區域及帳號確認後固定，不填猜測值。 | [Bedrock 模型與區域資訊](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html) |
| Step Functions | 採 Standard；同名 input 的啟動冪等有執行狀態與保留期限限制，不能取代永久事件去重。 | [StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html) |
| EventBridge | Scheduler 可透過執行角色啟動 Step Functions，需明確授權目標。 | [Scheduler 與 Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/using-eventbridge-scheduler.html) |
| DynamoDB | 基表可一致讀取，GSI 不行；單 item 上限 400 KB，序列化後仍需檢查大小。 | [一致性](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html)、[交易與大小限制](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html) |
| S3 | website endpoint 不提供 HTTPS；條件寫入可避免同 key 覆蓋。 | [網站端點](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteEndpoints.html)、[條件寫入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html) |
| Lambda URL | NONE 仍需 resource policy；GitHub 驗簽由 handler 執行。不可只設 NONE 就視為可信來源。 | [Function URL 權限](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html) |
| Snyk | Open Source 掃描依賴；Snyk Secrets 有獨立能力與組織啟用前提，不能只跑依賴掃描就聲稱查過金鑰。 | [依賴掃描](https://docs.snyk.io/developer-tools/snyk-cli/scan-and-maintain-projects-using-the-cli/snyk-cli-for-open-source)、[Snyk Secrets](https://docs.snyk.io/scan-fix-and-prevent/scan-with-snyk/snyk-secrets) |

### 17.2 最小必要的安全處理

**產品／黑客松約束 + 本文件設計選擇：**

- webhook secret 只由執行環境提供；頁面、種子檔、Git 與公開 log 不含真實金鑰。
- AWS 執行角色只授權需要的模型、表、S3 路徑與流程；前端不取得寫入資料庫的憑證。
- Ticket、PR diff、回饋與模型輸出都是資料，不是可覆蓋系統指示的內容。模型只有白名單工具，輸出先驗證再寫入。
- Markdown 轉 HTML 時跳脫不可信內容並限制可執行 HTML，避免回饋或模型文字變成頁面 script。
- 公開區只放可公開教學與合成展示資料。原始回饋、穩定使用者 ID、未發布內容及操作紀錄不公開。
- 目前 .env 尚未被忽略的事實需在實作階段修正；這次只記錄限制，不修改輸出範圍以外的檔案。

Snyk 檢查需保留工具版本、掃描範圍與結果；尚未取得 Secrets 權限不能寫成「secrets scan 通過」。本次沒有送出程式碼至 Snyk，也沒有執行掃描。

### 17.3 帳號、費用與現場備援

**待確認事項：** 選定 AWS Region、Claude 可呼叫性、Titan 權限、實際配額、S3 公開存取政策與 Snyk 組織功能。Free Tier／credits 取決於帳號方案、建立時間及服務條款，本案不保證全免費或固定美元成本。[AWS Free Tier FAQ](https://aws.amazon.com/free/free-tier-faqs/)。

**本文件設計選擇：** Demo 前完成三次不同事件的同程序成功驗證，確認 PROC 可重放；檢查公開 webhook 驗簽、模型小量試呼叫與事件重送。主要展示採少量資料，記錄每次呼叫，避免模型重試失控。

現場可使用預先執行的標示版結果作備援，並同時呈現本次失敗原因。不能把快取影片或歷史 trace 說成本次現場成功。展示結束後由維護者停用不再需要的排程與 webhook，依實際部署清單處理資源；本文件不執行關閉或刪除。

<a id="s18"></a>

## 18. 待確認事項與已知限制

產品釐清已結束。下表只列現行規格明留未定義、或實作必須驗證的契約；**本文件不要求再跑 84 題，也不修改規格來假裝這些已解決**。

| 項目 | 影響與來源 | 黑客松最省的建議 | 完成前不能宣稱什麼 |
|---|---|---|---|
| **O1：metadata SK** | ERM Project note 明留未定義，影響所有 metadata 的讀寫。View 已由本文件選鍵。 | 各 metadata 統一 META；Step 保持既定 REFERENCES 鍵。 | 物理鍵契約已全部定案。 |
| **O2：操作紀錄與接受順序** | F09／F23／F28／F33／F35 要求去重、證據進度、最近驗證及連續批次；儲存形狀未指定。PROC 同來源脈絡也缺持久化位置。 | 共用一套私有 S3 操作紀錄，保留原輸出與版號；單專案串行處理。先驗證接受順序、程序重啟與重送，再決定具體協調方式；不新增業務實體或 controller。 | 只靠 SDK 重試或共享 content 函式，就保證沒有重複與版本分叉。 |
| **O3：S3 公開與發布提交** | F36／F37／F49 要求未完成不可公開、發布成功才切指標，且整次失敗不發布；跨 S3、DynamoDB 與多篇教學的提交尚無完整契約。 | 以共用 publisher 集中操作，全部私有產物驗證完成後才提交，針對公開、指標與多篇提交切點注入失敗；不得用未連結的 URL 充當私有。 | 所有中途失敗都符合完整 publish 契約。 |
| **O4：時間與比較邊界** | ERM 明留時間編碼、View 窗口端點；多版本重開票率彙總權重未指定。 | UTC、十四天窗口左含右不含；規則驗證先固定一組同篇前後配對。 | 窗口端點或多組 rate 彙總已有規格答案。 |
| **O5：模型與參數驗證** | Claude model ID／inference profile、帳號配額及參數支援尚未驗證。 | 初始時限、Retry 與排程已選在第 14.3 節；以可用 Claude 與 Titan 做小量驗證，生成與 embedding 分開配置。 | 帳號一定可用、首次探索一定能在 webhook 時限內完成。 |
| **O6：來源完整契約** | F02 僅提供 Issue STABLE_KEYS；D02 要求上游唯一且有前綴 ID，D23 要求共享穩定 user。原始 GitHub 與手動檔之間的完整配對未提供。 | 先完成一個 Issue、一個 PR 的實際 fixture；對已有來源穩定 ID 做確定性編碼，維護者匯入檔採同一 user 命名方式。此編碼須確認符合 D02，不能拿模型臨時產 ID。 | 公開 PR 接入及跨來源重開票已能端到端運作。 |
| **O7：核定種子與外部設定** | F27／F32／F46 需要完整核定批次，repo 目前只有故事與目標數字；AWS／Snyk 帳號設定未驗證。 | 將第 11 節配方展開、確認後再載入；另準備 R-012 兩批退役證據。 | 已有實測改善、已核准種子或完整雲端驗收。 |

O1、O4 的建議不影響已寫明的主要流程；O2、O3、O6 是實作最先處理的整合邊界。O7 的核定是確認合成驗收資料來源，不是新增日常教學發布審核佇列。

單表 Scan、Lambda 內 cosine 與手動匯入是**本文件設計選擇**的規模取捨，適合少量 Demo 資料，不宣稱適用大型站點。從更多真人資料自動驗證規則、正式 HTTPS 站及更大量事件處理，都需另行評估；本次不替未來產品增加基礎設施。

<a id="s19"></a>

## 19. 來源盤點與決策索引

已完整讀取以下來源。統計以本次磁碟內容為準，不沿用 overview 的舊數字。

| 來源 | 使用方式 |
|---|---|
| [design prompt](../spec/prompts/4.design_prompt.md) | 本次範圍、輸出限制、架構與驗收要求。 |
| [formulation rules](../spec/prompts/formulation-rules.md) | 保留規格與設計的界線，不捏造原始 Example。 |
| [Training KB 草稿](../spec/draft/training-kb-design-doc.md) | 956 行；產品、三條流程、Rote、示範與工具責任。 |
| [ERD 草稿](../spec/draft/training-kb-erd.md) | 173 行；單表、S3、關係邊；被 clarify 更新處依新決策。 |
| [ERM](../spec/erm.dbml) | 275 行；十實體、73 欄位投影與 11 個 Ref。 |
| [釐清總覽](../spec/.clarify/overview.md) | 447 行；追蹤來源與遺留工程議題；舊題數與待答摘要不作權威。 |
| [Ticket-to-Knowledge](../../ticket-to-knowledge-design-doc.md) | 674 行；採用與否的理由見第 2 節。 |
| [功能規格目錄](../spec/features/) | 十三份、147 條 Rule、22 個 Example；逐條責任見第 20 節。 |
| [資料決策](../spec/.clarify/resolved/data/)／[功能決策](../spec/.clarify/resolved/features/) | 29 + 55 = 84 份，以下逐份列出最新答案。 |

根目錄文件提到的 `aws-architecture-decisions.md` 與 `from-demo-to-production.md` 在本次檔案盤點中不存在，沒有假設讀過或引用其內容。`docs/design/ITAgent.md` 與舊實作提示不作本案架構來源。

### 19.1 資料決策

以下簡述最新解決記錄；D09 必須與 D23 的覆寫一起讀。

| 決策 | 最新答案摘要 |
|---|---|
| [D01](../spec/.clarify/resolved/data/TUTORIAL_教學與產品功能的識別範圍是否包含專案.md) | A - MVP 固定單一專案，所有 Tutorial 與 Feature 識別碼在此範圍唯一；平台規則使用明示的外部 seeded data 示範。 |
| [D02](../spec/.clarify/resolved/data/TICKET_來源事件的正規化識別碼如何保證唯一.md) | A - 上游 ID 已全域唯一，正規化 id 直接使用上游 ID。接入層產出 t_、r_、f_ 前綴且不撞號。 |
| [D03](../spec/.clarify/resolved/data/TUTORIAL_VERSION_關聯欄位使用裸識別碼還是帶前綴的主鍵.md) | A - 所有邏輯關聯欄位使用裸 ID，僅在 DynamoDB 邊與查詢時加上型別前綴。 |
| [D04](../spec/.clarify/resolved/data/TICKET_一張_Ticket_可以對應幾個_Feature.md) | A - 零或一個；feature_ids 的長度限制為 0..1，維持 ERD 的基數。 |
| [D05](../spec/.clarify/resolved/data/TUTORIAL_STEP_一個教學步驟可以引用幾個_Feature.md) | A - 恰好一個；無 Feature 或多 Feature 的內容須先拆解或驗證失敗。 |
| [D06](../spec/.clarify/resolved/data/FEATURE_功能改名時哪個識別碼必須保持不變.md) | A - 保留第一次建立的 FEATURE PK，改名只更新顯示名稱與 aliases。 |
| [D07](../spec/.clarify/resolved/data/FEATURE_同一查詢範圍內的_alias_撞名時如何處理.md) | A - alias 必須唯一；新增或改名造成衝突時拒絕該次 alias 更新。 |
| [D08](../spec/.clarify/resolved/data/TICKET_Ticket_向量以_embedding_還是_embedding_ref_為準.md) | A - 以 Ticket.embedding 保存 1024 維向量，移除 embedding_ref 的持久化要求。 |
| [D09](../spec/.clarify/resolved/data/TICKET_Ticket_接入驗證的必填欄位採哪套契約.md) | A（原答）允許 author 空值；此點已由 D23 覆寫，最新契約為 author 必填，其餘分析欄位由流程補入。 |
| [D10](../spec/.clarify/resolved/data/RELEASE_Release_接入必填欄位採哪套契約.md) | A - 接入即完成解析：id、source、feature、kind、evidence、ts 必填；renamed 另要求 old_name 與 new_name，其他 kind 允許名稱欄位為空。 |
| [D11](../spec/.clarify/resolved/data/FEEDBACK_Feedback_是否允許沒有穩定的使用者識別碼.md) | A - 不允許；每次提交都必須提供可重用的使用者識別碼。 |
| [D12](../spec/.clarify/resolved/data/FEEDBACK_只有評分而沒有類別與留言的回饋是否有效.md) | A - 有效；category 為空、comment 為空，只參與評分計算，不送模型分類。 |
| [D13](../spec/.clarify/resolved/data/FEEDBACK_Feedback_Category_的合法值採用哪種管理方式.md) | B - 使用可擴充的核定類別表；初始清單為找不到按鈕、缺少資訊；未知值進入待分類。 |
| [D14](../spec/.clarify/resolved/data/FEEDBACK_同一使用者對同一版本多次回饋計為幾筆.md) | A - 每次新的提交 ID 都算一筆，只排除同一提交的重送。 |
| [D15](../spec/.clarify/resolved/data/AUTHORING_RULE_規則_evidence_使用識別碼清單還是含類別的物件.md) | A - 只存 Feedback ID 清單，category 由被引用的回饋取得。 |
| [D16](../spec/.clarify/resolved/data/AUTHORING_RULE_applies_when_的可表達條件範圍為何.md) | A - MVP 僅支援 step.type 等於 click_ui、input 或 read 的單一條件。 |
| [D17](../spec/.clarify/resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md) | A - 以版本的 rules_applied 為權威，規則清單與 APPLIED_TO 邊可由它重建。 |
| [D18](../spec/.clarify/resolved/data/AUTHORING_RULE_derived_from_可以記錄幾個來源版本.md) | A - 恰好一個；單條規則的證據只能來自同一版本，跨專案共享的是完成後的規則。 |
| [D19](../spec/.clarify/resolved/data/PROVEN_WORKFLOW_same_sender_以哪個來源範圍識別流程.md) | B - 來源網域與 adapter 類型共同構成範圍，同類來源可跨專案共用不含事件值的流程。 |
| [D20](../spec/.clarify/resolved/data/PROVEN_WORKFLOW_fail_count_代表連續失敗還是累積失敗.md) | A - 代表連續失敗；成功重放後歸零，達到 3 才退役。 |
| [D21](../spec/.clarify/resolved/data/TUTORIAL_RETIRE_之後的狀態應使用_retired_還是_obsolete.md) | A - retired 是唯一資料狀態，obsolete 只是同一狀態的顯示文字。 |
| [D22](../spec/.clarify/resolved/data/TUTORIAL_後繼_Tutorial_的關係要持久化在哪裡.md) | A - 在 Tutorial metadata 保存可空的 successor Tutorial ID。 |
| [D23](../spec/.clarify/resolved/data/FEEDBACK_如何識別看過教學後又開票的同一位使用者.md) | A - 瀏覽、回饋與 Ticket 共用同一個穩定使用者 ID，由來源接入時直接提供。 |
| [D24](../spec/.clarify/resolved/data/TUTORIAL_VERSION_重開票率需要的教學瀏覽紀錄從哪裡取得.md) | A - 在 MVP 新增瀏覽事件，至少記錄版本、使用者與瀏覽時間，作為指標來源。 |
| [D25](../spec/.clarify/resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md) | A - 版本可以先建立，published_at 為 null 代表未發布；只有非空值才表示已上架。 |
| [D26](../spec/.clarify/resolved/data/TUTORIAL_VERSION_版本建立失敗後重試是否重用原版本號.md) | A - 同一邏輯變更重試時重用原版本號；若永久失敗，後續版本可保留號碼缺口。 |
| [D27](../spec/.clarify/resolved/data/AUTHORING_RULE_跨專案共享規則可以暴露哪些回饋證據.md) | C - MVP 跨專案共享只接受明示的合成種子證據，真實專案證據暫不進共享庫。 |
| [D28](../spec/.clarify/resolved/data/TUTORIAL_VERSION_REFINE_版本的_reason_採用哪種標準格式.md) | A - 使用設計格式 feedback:&lt;n&gt; 則 &lt;category&gt;，同時保存數量與類別。 |
| [D29](../spec/.clarify/resolved/data/TUTORIAL_同題重開票的教學與_cluster_對應以何者為準.md) | A - 以該教學首版的 gap:&lt;cluster_id&gt; 作為固定對應，後續分群需保留此 cluster 的可追溯身分。 |

### 19.2 功能決策

| 決策 | 最新答案摘要 |
|---|---|
| [F01](../spec/.clarify/resolved/features/執行教學流程_缺少原始_Example_的規則以哪種資料補齊驗收.md) | B - 允許新增明示為合成且經確認的驗收資料；不得把合成資料描述為原始觀測或實測結果。 |
| [F02](../spec/.clarify/resolved/features/接入來源事件_STABLE_KEYS_白名單依哪個範圍定義.md) | A - 每一種來源與事件類型有自己的固定必備 top-level key 清單。 |
| [F03](../spec/.clarify/resolved/features/接入來源事件_第二層重放是否沿用至少三次成功的門檻.md) | A - 沿用；第二層也必須 active 且 success_count &gt;= 3 才可重放。 |
| [F04](../spec/.clarify/resolved/features/接入來源事件_多個同寄件者流程達重疊門檻時選哪一個.md) | A - 選 Jaccard 最高者，同分時選最近成功使用者；須固定最後的識別碼排序以消除平手。 |
| [F05](../spec/.clarify/resolved/features/接入來源事件_新流程未達三次成功時如何累積驗證次數.md) | A - 首次成功記為 1；同簽名事件再由 Agent 完成相同可泛化序列，每次完整成功才累加。 |
| [F06](../spec/.clarify/resolved/features/接入來源事件_Feedback_不啟動改版流程時如何認定接入成功.md) | C - Feedback 不納入 PROVEN_WORKFLOW 學習，只使用固定接入保存流程。 |
| [F07](../spec/.clarify/resolved/features/接入來源事件_Agent_最終仍無法產出合法物件時如何處置事件.md) | A - 回傳失敗，由來源依既定重送方式重試；不得寫入合法業務物件或成功 PROC。 |
| [F08](../spec/.clarify/resolved/features/接入來源事件_非_GitHub_事件在_MVP_由哪個可信入口接收.md) | A - Discord、email、changelog 與 Feedback 僅由本機或受控種子匯入提供，不開放未驗證的公開接入。 |
| [F09](../spec/.clarify/resolved/features/接入來源事件_同一正規化事件重送時是否再次觸發_pipeline.md) | A - 同一事件只接受一次邏輯處理；重送回傳既有結果或沿用未完成執行。 |
| [F10](../spec/.clarify/resolved/features/分析工單_cosine_門檻以哪種群代表判斷_Ticket_歸群.md) | A - 比較 Ticket 與每個群的中心向量，達 0.85 的群中選相似度最高者。 |
| [F11](../spec/.clarify/resolved/features/分析工單_recurring_的十四天窗口以哪個時間為基準.md) | C - 以每日 UTC 日界線計算當日及前 13 個日期，該日內的所有事件歸同一窗口。 |
| [F12](../spec/.clarify/resolved/features/分析工單_判定已有教學時哪些_Tutorial_狀態算有效.md) | B - active 的 Tutorial 即使仍待首次發布也算已有教學，避免重複建立。 |
| [F13](../spec/.clarify/resolved/features/分析工單_Knowledge_Gap_無法對應既有_Feature_時如何處理.md) | A - 保留待釐清的 gap，取得有效 Feature 對應前不建立 Tutorial。 |
| [F14](../spec/.clarify/resolved/features/依改版更新教學_一則改版包含多個_Feature_變更時如何表示.md) | B - 依變更拆成多個子 Release，保留相同的父來源事件識別碼。 |
| [F15](../spec/.clarify/resolved/features/依改版更新教學_向量搜尋取得的最相近_Feature_如何確認可用.md) | B - 必須達明確的相似度門檻才可採用；門檻與未達標輸出需列入規格。 |
| [F16](../spec/.clarify/resolved/features/依改版更新教學_哪種改名算必須執行_safety_net_的重大改名.md) | B - 只有 alias 比對失敗的 renamed 才算重大改名；反查為零仍獨立觸發。 |
| [F17](../spec/.clarify/resolved/features/依改版更新教學_反查到歷史版本步驟時是否納入改版.md) | A - 只處理每篇目前已發布版本的步驟，歷史與待發布版本的命中不觸發改寫。 |
| [F18](../spec/.clarify/resolved/features/依改版更新教學_safety_net_沒有確認任何步驟時如何結束.md) | A - 記錄此次未命中並以 KEEP 結束，不建立新版本。 |
| [F19](../spec/.clarify/resolved/features/依改版更新教學_退役時沒有後繼_Tutorial_要呈現什麼結果.md) | A - 仍完成退役，顯示過期說明與原文，但不產生導向。 |
| [F20](../spec/.clarify/resolved/features/定期檢視回饋_八筆回饋的_Demo_如何符合至少十筆的檢視門檻.md) | B - 正式規則維持 n&gt;=10，Demo 使用明示且隔離的 n&gt;=8 門檻。 |
| [F21](../spec/.clarify/resolved/features/定期檢視回饋_recurring_Feedback_Category_的次數門檻是多少.md) | A - 同一類別至少 5 筆，與候選規則提出門檻一致。 |
| [F22](../spec/.clarify/resolved/features/定期檢視回饋_每日檢視使用哪些版本與時間範圍的回饋.md) | A - 只檢視 current_version，使用該版本截至本次執行的全部有效回饋。 |
| [F23](../spec/.clarify/resolved/features/定期檢視回饋_同一批回饋是否可以再次觸發_REFINE.md) | A - 不可；完成後記錄已處理證據集合，必須有新的有效證據才可再次觸發。 |
| [F24](../spec/.clarify/resolved/features/定期檢視回饋_診斷找不到有效步驟時如何處理弱教學.md) | A - 記錄無可修改步驟，本次不建立版本，保留回饋供後續分析。 |
| [F25](../spec/.clarify/resolved/features/提出教學規則_候選規則的五筆同類回饋可以跨哪些範圍累積.md) | A - 僅同一 TutorialVersion；規則完成後才跨教學或專案套用。 |
| [F26](../spec/.clarify/resolved/features/提出教學規則_提出_candidate_是否必須先滿足弱教學門檻.md) | B - 不必；Feedback Review 另外掃描同類至少 5 筆的證據，即使平均分或總樣本未達改版門檻。 |
| [F27](../spec/.clarify/resolved/features/套用教學規則_candidate_規則如何取得驗證用的套用版本.md) | B - MVP 從明示的種子試用版本匯入 candidate 成效，正式寫作不自動試用 candidate。 |
| [F28](../spec/.clarify/resolved/features/套用教學規則_多條相互衝突的_active_規則同時適用時如何選擇.md) | B - 同一適用範圍內只採用最近驗證通過的規則，舊規則保留歷史但本次不套用。 |
| [F29](../spec/.clarify/resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md) | B - 只記錄本次寫作 prompt 實際注入的規則，原文複製帶來的效果不計本次套用。 |
| [F30](../spec/.clarify/resolved/features/驗證教學規則_candidate_升為_active_時兩項成效必須如何改善.md) | A - 平均評分嚴格提高且重開票率嚴格下降，兩者都成立才啟用。 |
| [F31](../spec/.clarify/resolved/features/驗證教學規則_未套用規則的對照版本如何選取.md) | A - 使用同一篇 Tutorial 在套用前的版本，作為前後比較對照。 |
| [F32](../spec/.clarify/resolved/features/驗證教學規則_規則驗證至少累積多少資料才可以改變狀態.md) | C - MVP 僅在完整的核定種子驗證批次載入後判定；線上資料不足時保持原狀態。 |
| [F33](../spec/.clarify/resolved/features/驗證教學規則_具備足夠資料後如何判定規則無效而退役.md) | B - 連續兩個不重疊的成熟評估窗口未改善才退役。 |
| [F34](../spec/.clarify/resolved/features/驗證教學規則_合併相近規則時如何保留規則識別與歷史.md) | C - MVP 只建立相近群組供人工檢視，不自動改寫規則或移轉歷史。 |
| [F35](../spec/.clarify/resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md) | A - 同篇變更依接受順序串行處理，每次讀取最新可用基底再產生下一版。 |
| [F36](../spec/.clarify/resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md) | A - 保留不可公開的待完成版本，待 S3、版本與關聯全部就緒後才允許發布。 |
| [F37](../spec/.clarify/resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md) | A - publish 成功回傳時切換；此時所需內容與關聯已完成寫入。 |
| [F38](../spec/.clarify/resolved/features/發布教學版本_MVP_的教學發布入口採用哪一種形式.md) | A - 只提供 S3 靜態 docs 站，頁面包含版本化內容與 feedback widget。 |
| [F39](../spec/.clarify/resolved/features/收集教學回饋_已退役教學的既有版本是否仍接受回饋.md) | C - 拒絕新回饋，保留既有回饋供歷史查詢。 |
| [F40](../spec/.clarify/resolved/features/查詢知識圖譜_backfill_發現既有_Feature_引用錯誤時如何更新.md) | A - 只增加缺少的邊，不移除或替換既有引用；錯誤邊另列待處理。 |
| [F41](../spec/.clarify/resolved/features/檢視學習指標_重開票率是否要求瀏覽發生在再次開票之前.md) | A - 要求；分子只計在瀏覽之後且窗口結束前同群開票的使用者。 |
| [F42](../spec/.clarify/resolved/features/檢視學習指標_沒有可識別瀏覽者時重開票率如何顯示.md) | A - 顯示 N/A 與樣本不足，不把零分母當成改善或惡化。 |
| [F43](../spec/.clarify/resolved/features/檢視學習指標_哪些_Feedback_Category_應算入負面回饋.md) | A - 所有已核定的問題類別都屬負面，未分類不因 category 計入；rating&lt;=2 仍獨立計入。 |
| [F44](../spec/.clarify/resolved/features/檢視學習指標_跨版本比較平均評分時採用哪種加權方式.md) | A - 先算每版平均再等權平均，每個 TutorialVersion 權重相同。 |
| [F45](../spec/.clarify/resolved/features/檢視學習指標_Bedrock_呼叫數是否計入重試與_Map_的每次呼叫.md) | A - 計算每次實際送出的呼叫嘗試，包含重試、每個 Map item 與 Rote 呼叫。 |
| [F46](../spec/.clarify/resolved/features/檢視學習指標_seeded_Demo_指標採現算結果還是固定展示值.md) | A - 由完整 seeded 回饋、瀏覽與 Ticket 資料實時計算；2.9、4.4、7、2 是資料必須能重現的目標。 |
| [F47](../spec/.clarify/resolved/features/檢視學習指標_Tutorial_B_的規則開關對照是否會影響正式上架版本.md) | C - 兩份都只是隔離的 Demo 產物，不寫入正式教學、回饋與規則效果統計。 |
| [F48](../spec/.clarify/resolved/features/執行教學流程_LLM_輸出通過_schema_但違反業務規則時如何處理.md) | A - 以明確的業務驗證拒絕結果，進入有限重試與最終失敗路徑，不發布不合規內容。 |
| [F49](../spec/.clarify/resolved/features/執行教學流程_Task_重試耗盡並進入_Catch_後如何結束流程.md) | A - 整次執行以失敗結束，不發布新版本；來源可依既定重試契約重新執行。 |
| [F50](../spec/.clarify/resolved/features/建立教學版本_第一版沒有前版時_diff_檔案如何表示.md) | C - 建立空的 v1.diff，介面另外以版本號識別它沒有前版。 |
| [F51](../spec/.clarify/resolved/features/收集教學回饋_不合法回饋要向提交者回傳哪種處理結果.md) | A - 立即拒絕並指出不合法欄位，允許提交者修正；不建立 FEEDBACK 或成功回執。 |
| [F52](../spec/.clarify/resolved/features/檢視學習指標_版本沒有任何有效評分時平均評分如何呈現.md) | A - 顯示尚無評分，內部值為 null，規則驗證不使用此版本平均。 |
| [F53](../spec/.clarify/resolved/features/接入來源事件_已退役簽名重新學到流程時如何保存新序列.md) | C - 退役簽名保持停用，由人工核定新的序列後再明確重置流程。 |
| [F54](../spec/.clarify/resolved/features/依改版更新教學_退役教學的後繼_Tutorial_由哪個來源指定.md) | B - 由維護者選定既有 Tutorial，未選定時依無後繼分支處理。 |
| [F55](../spec/.clarify/resolved/features/驗證教學規則_candidate_與既有規則的衝突由誰判定.md) | B - 由模型輸出結構化衝突判定與證據，Analytics 依通過驗證的判定自動退役。 |

<a id="rules"></a>

## 20. 逐條 Rule 與負責模組

以下保留十三份 `.feature` 的 **147 條 Rule 原文**，每條都指定責任與設計位置。對照表表示設計有涵蓋該契約，不表示對應程式或測試已完成。若 Rule 概述較早，仍須一起遵守同檔補充文字與第 19 節的最新答案。

### 20.1 依改版更新教學

來源：[依改版更新教學.feature](../spec/features/依改版更新教學.feature)；共 17 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | 從 PR diff 或 changelog 抽出 feature、kind、old_name 與 new_name | ingress／Rote | [7.1](#s7) |
| 2 | 改名前後的 alias 對應同一個 Feature 節點 | repository | [7.4、9.1](#s7) |
| 3 | 改名不變更第一次建立的 Feature 主鍵 | repository | [9.1](#s9) |
| 4 | alias 比對未命中時以向量搜尋最相近的 Feature | pipelines／writing | [7.4、10](#s7) |
| 5 | by_target 反查只選出引用改版 Feature 的步驟 | repository | [10](#s10) |
| 6 | 反查為零或重大改名時使用 step 文字向量搜尋補漏 | pipelines／writing | [7.4、10](#s7) |
| 7 | safety_net 的疑似命中交給 Claude 確認 | writing | [7.4](#s7) |
| 8 | renamed 或 changed 的改版動作為 UPDATE | pipelines／content | [7.4、8](#s7) |
| 9 | kind 為 removed 的改版動作為 RETIRE | pipelines／content | [7.4、8.4](#s7) |
| 10 | UPDATE 只重寫受影響的步驟 | content／writing | [7.4](#s7) |
| 11 | UPDATE 將未命中步驟的原文複製到下一版 | content | [7.4](#s7) |
| 12 | 未引用改版 Feature 的教學維持 KEEP | pipelines | [7.4](#s7) |
| 13 | UPDATE 為受影響教學產生與前版的 diff | content | [8.2、9.3](#s8) |
| 14 | UPDATE 下一版的 reason 使用 release 加上改版事件 id | content | [7.4、8.1](#s8) |
| 15 | UPDATE 完成時更新 Feature 的 aliases | repository | [7.4、9.1](#s7) |
| 16 | RETIRE 將受影響教學標記為過期 | content | [8.4](#s8) |
| 17 | RETIRE 的教學導向後繼 Tutorial | content／demo | [8.4](#s8) |

### 20.2 分析工單

來源：[分析工單.feature](../spec/features/分析工單.feature)；共 14 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | 每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding | pipelines／writing／repository | [7.3、14.3](#s7) |
| 2 | demo 分群以 cosine 至少 0.85 為同群門檻 | pipelines | [7.3](#s7) |
| 3 | 同群在 14 天內至少有 5 筆 Ticket 才算 recurring | pipelines | [7.3](#s7) |
| 4 | 只有達 recurring 門檻的群才交給模型命名 Knowledge Gap | pipelines／writing | [7.3](#s7) |
| 5 | Knowledge Gap 的命名結果包含對應 Feature | writing | [7.3、7.6](#s7) |
| 6 | 一張 Ticket 對應零或一個 Feature | repository | [7.3、9.2](#s7) |
| 7 | 對應 Feature 已有教學時動作為 KEEP | pipelines | [7.3](#s7) |
| 8 | KEEP 只記錄 log 而不寫入教學內容 | pipelines | [7.3](#s7) |
| 9 | 已識別且尚無現成教學的 Knowledge Gap 建立新的 Tutorial | pipelines／content | [7.3、8](#s7) |
| 10 | Ticket Analysis 是唯一建立新 Tutorial 身分的 pipeline | pipelines | [7.3](#s7) |
| 11 | 新教學的完整內容包含 Title、Problem、Prerequisites、Steps 與 Expected Outcome | writing／content | [7.3、7.6](#s7) |
| 12 | 產生新教學時同時輸出每步提到的 Feature | writing／content | [7.3、7.6](#s7) |
| 13 | 新教學的每個步驟恰好引用一個 Feature | content | [7.3、9.2](#s7) |
| 14 | 新教學第一版的 reason 使用 gap 加上來源 cluster_id | content | [8.1](#s8) |

### 20.3 執行教學流程

來源：[執行教學流程.feature](../spec/features/執行教學流程.feature)；共 10 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | 缺少原始 Example 時可用明示合成且經確認的驗收資料 | demo／驗收維護者 | [11、15](#s15) |
| 2 | 教學 pipeline 依 Step Functions 預定義節點執行 | pipelines | [5、7](#s5) |
| 3 | Agent 的工具選擇自由度只用於接入層 | rote | [7.2](#s7) |
| 4 | 每個 Bedrock 呼叫設定 max_tokens | writing | [14.3（embedding 差異另列）](#s14) |
| 5 | 每個 Bedrock 呼叫設定逾時 | writing | [14.3](#s14) |
| 6 | 每個 Step Functions Task 設定 Retry | pipelines | [14.2](#s14) |
| 7 | 每個 Step Functions Task 設定 Catch | pipelines | [14.1、14.2](#s14) |
| 8 | LLM 輸出遵循指定 JSON schema | writing／content | [7.6、14.1](#s7) |
| 9 | 判斷節點使用低 temperature | writing | [14.3](#s14) |
| 10 | Step Functions 的 ASL 版本快照存於 stepfunctions/&lt;pipeline&gt;/v&lt;n&gt;.json | 部署流程／repository | [9.3](#s9) |

### 20.4 套用教學規則

來源：[套用教學規則.feature](../spec/features/套用教學規則.feature)；共 8 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | CREATE、UPDATE 與 REFINE 在寫作前讀取教學規則 | writing | [7.6](#s7) |
| 2 | 一般寫作路徑只取得 status 為 active 的規則 | writing | [7.6、12.2](#s7) |
| 3 | 依 step 型態與 applies_when 篩選規則 | writing | [7.6](#s7) |
| 4 | 適用規則的內容注入教學寫作 prompt | writing | [7.6](#s7) |
| 5 | 既有教學衍生的適用規則可用於不同主題新教學的第一版 | writing／demo | [7.6、11.4](#s11) |
| 6 | 套用規則的版本記錄於規則的 applied_to | repository／analytics | [8.2、9.2](#s9) |
| 7 | 版本的 rules_applied 記錄本次套用的規則 | content | [7.6、8.2](#s8) |
| 8 | 後續 Release 重寫仍注入適用的教學規則 | writing | [7.4、7.6](#s7) |

### 20.5 定期檢視回饋

來源：[定期檢視回饋.feature](../spec/features/定期檢視回饋.feature)；共 9 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | Periodic Feedback Review 每日執行 | pipelines／排程 | [7.5、14.3](#s7) |
| 2 | 弱教學的版本平均評分必須小於 3.5 | pipelines／analytics | [7.5](#s7) |
| 3 | 弱教學的版本回饋樣本數必須至少為 10 | pipelines／analytics | [7.5、11.2](#s7) |
| 4 | 弱教學必須具有 recurring Feedback Category | pipelines／analytics | [7.5](#s7) |
| 5 | 診斷結果包含需要改寫的步驟編號與原因 | writing／content | [7.5、7.6](#s7) |
| 6 | 診斷找不到有效步驟時不建立新版 | pipelines | [7.5](#s7) |
| 7 | REFINE 只重寫診斷命中的步驟 | writing／content | [7.5](#s7) |
| 8 | REFINE 的下一版 reason 記錄回饋數與類別 | content | [7.5、8.1](#s7) |
| 9 | Feedback Review 是唯一提出 Authoring Rule 的 pipeline | pipelines／writing | [7.5](#s7) |

### 20.6 建立教學版本

來源：[建立教學版本.feature](../spec/features/建立教學版本.feature)；共 10 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | 新 Tutorial 的版本從 v1 起算 | content | [8.1](#s8) |
| 2 | 任一 pipeline 修改既有教學時使用該篇的下一個版本號 | content | [8.1、8.3](#s8) |
| 3 | 新版以 supersedes 關聯同一篇教學的前一版 | content／repository | [8.1、9.2](#s8) |
| 4 | 每次建立版本都記錄引起變更的 reason | content | [8.1](#s8) |
| 5 | 每個版本的完整內容儲存在 tutorials/&lt;slug&gt;/v&lt;n&gt;.md | content／repository | [8.2、9.3](#s9) |
| 6 | TutorialVersion 的 s3_key 指向該版本完整內容 | repository | [9.1、9.3](#s9) |
| 7 | 與前版的 diff 儲存在 tutorials/&lt;slug&gt;/v&lt;n&gt;.diff | content／repository | [8.2、9.3](#s9) |
| 8 | 建立 TutorialStep 時保存 references Feature 邊 | repository | [9.2](#s9) |
| 9 | 沒有 Feature 或引用多個 Feature 的步驟不可保存 | content／repository | [7.6、9.2](#s9) |
| 10 | references 邊的 target 等於 SK 中的關係終點 | repository | [9.2](#s9) |

### 20.7 接入來源事件

來源：[接入來源事件.feature](../spec/features/接入來源事件.feature)；共 31 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | GitHub webhook 必須以 X-Hub-Signature-256 驗簽 | ingress | [7.1](#s7) |
| 2 | 沒有簽名的 GitHub webhook 請求被拒絕 | ingress | [7.1](#s7) |
| 3 | 來源簽名使用來源網域、有意義的 header 名稱與穩定 payload key 計算 | rote | [7.2](#s7) |
| 4 | ID、時間戳與標題等事件值不參與來源簽名 | rote | [7.2](#s7) |
| 5 | 第一層以 PROC 主鍵精確比對來源簽名 | rote／repository | [7.2、9.1](#s7) |
| 6 | 第一層只允許 status 為 active 的流程重放 | rote | [7.2](#s7) |
| 7 | 第一層流程的 success_count 必須至少為 3 | rote | [7.2](#s7) |
| 8 | 新流程每次完整成功才將 success_count 加 1 | rote | [7.2](#s7) |
| 9 | 第一層未命中才在同寄件者的流程中以 Jaccard 至少 0.8 比對欄位 | rote | [7.2](#s7) |
| 10 | 前兩層皆未命中時才由 Agent 選擇 adapter tool | rote | [7.2](#s7) |
| 11 | 接入層命中已驗證流程的重放路徑不呼叫 LLM | rote | [7.2、12.1](#s7) |
| 12 | 記錄的 tool 參數以 JSONPath 指向事件欄位或前一步輸出 | rote | [7.2](#s7) |
| 13 | 寫回新流程前最後一個 tool 必須是通過的 validate | rote | [7.2](#s7) |
| 14 | 寫回新流程前 Step Functions 必須成功啟動 | rote／ingress | [7.2](#s7) |
| 15 | 每次重放失敗時 fail_count 增加 1 | rote | [7.2](#s7) |
| 16 | 重放成功時 fail_count 歸零 | rote | [7.2](#s7) |
| 17 | 重放或正規化驗證失敗時當次回退到 Agent | rote | [7.2、14.1](#s7) |
| 18 | Agent 最終仍無法產出合法物件時回傳失敗 | ingress／rote | [7.1、14.1](#s14) |
| 19 | 同一流程連續三次重放失敗後 status 變為 retired | rote | [7.2](#s7) |
| 20 | 已退役流程在下次接入時視同未命中 | rote | [7.2](#s7) |
| 21 | 正規化物件必須具有 schema 的必填欄位 | ingress | [7.1](#s7) |
| 22 | Ticket 接入時 id、source、text、author、ts 與 project_id 必填 | ingress | [7.1](#s7) |
| 23 | Release 接入時即完成功能與種類解析 | ingress／rote | [7.1、7.4](#s7) |
| 24 | 正規化物件的 id 直接使用已全域唯一的上游識別碼 | ingress | [7.1、18（O6）](#s7) |
| 25 | 正規化物件的枚舉欄位必須使用合法值 | ingress | [7.1、7.6](#s7) |
| 26 | 正規化成功的 Ticket 觸發 Ticket Analysis | ingress／pipelines | [7.1、7.3](#s7) |
| 27 | 正規化成功的 Release 觸發 Release Note Update | ingress／pipelines | [7.1、7.4](#s7) |
| 28 | 正規化成功的 Feedback 寫入 FEEDBACK item | ingress／repository | [7.1](#s7) |
| 29 | 單筆 Feedback 接入不立即觸發教學改版 | ingress | [7.1](#s7) |
| 30 | 同一正規化事件重送時只處理一次 | ingress／content | [14.1、18（O2）](#s14) |
| 31 | 只有 Rote 接入層讀寫 PROVEN_WORKFLOW | rote | [5、7.2](#s7) |

### 20.8 提出教學規則

來源：[提出教學規則.feature](../spec/features/提出教學規則.feature)；共 6 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | 同類 Feedback 至少 5 筆才可提出 candidate 規則 | pipelines／writing | [7.5、12.2](#s7) |
| 2 | Authoring Rule 保留可追溯的 Feedback 證據 | writing／repository | [7.5、9.1](#s7) |
| 3 | Authoring Rule 記錄 applies_when 適用範圍 | writing | [7.6](#s7) |
| 4 | Authoring Rule 記錄 derived_from 來源版本 | repository | [7.5、9.1](#s9) |
| 5 | Authoring Rule 記錄歸納出的寫作要求 | writing | [7.6](#s7) |
| 6 | MVP 的教學與產品功能識別碼在單一專案範圍內唯一 | repository／demo | [3、9.1、11](#s9) |

### 20.9 收集教學回饋

來源：[收集教學回饋.feature](../spec/features/收集教學回饋.feature)；共 10 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | Feedback 的 tutorial_version 必須存在於圖譜 | ingress／repository | [7.1](#s7) |
| 2 | 已退役教學的既有版本拒絕新回饋 | ingress／content | [8.4](#s8) |
| 3 | Feedback 的 rating 只能為 1 到 5 的整數 | ingress | [7.1](#s7) |
| 4 | 使用者勾選的 Feedback Category 優先於模型分類 | ingress／writing | [7.6、13](#s13) |
| 5 | Feedback Category 必須屬於核定類別表或待分類 | ingress／writing | [7.6、12.1](#s12) |
| 6 | 需要分類的自由留言在接入時計算一次 Feedback Category | writing | [7.6、13](#s13) |
| 7 | 回饋關聯到提交時指定的 TutorialVersion | ingress／repository | [7.1、13](#s13) |
| 8 | 收到單筆低分 Feedback 時不立即修改 Tutorial | ingress | [7.1、7.5](#s7) |
| 9 | Feedback 接入時必須提供穩定使用者 ID | ingress | [7.1](#s7) |
| 10 | 同一使用者對同一版本的每次新提交都計一筆 | ingress／analytics | [7.1、12.1](#s12) |

### 20.10 查詢知識圖譜

來源：[查詢知識圖譜.feature](../spec/features/查詢知識圖譜.feature)；共 7 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | 查詢某起點的關係使用該起點的 PK | repository | [10](#s10) |
| 2 | 查詢誰引用 Feature 時使用 by_target 的 target | repository | [10](#s10) |
| 3 | 沿 Feature 關係邊反查不呼叫 AI | repository | [10](#s10) |
| 4 | 可查詢某篇 Tutorial 所屬的版本 | repository | [10](#s10) |
| 5 | 可查詢某條 Authoring Rule 套用的版本 | repository | [10](#s10) |
| 6 | Feedback Review 以 refers_to 關係反查指定版本的回饋 | repository | [10](#s10) |
| 7 | 定期 backfill 漏抽的 Feature 引用邊 | repository | [10](#s10) |

### 20.11 檢視學習指標

來源：[檢視學習指標.feature](../spec/features/檢視學習指標.feature)；共 12 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | 平均評分以每個 TutorialVersion 的 rating 計算 | analytics | [12.1](#s12) |
| 2 | 負面 Feedback 數計入 rating 不超過 2 或 category 屬負面的回饋 | analytics | [12.1](#s12) |
| 3 | 同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例 | analytics | [11.3、12.1](#s12) |
| 4 | 同題重開票率的分母取自教學瀏覽事件 | analytics | [11.3、12.1](#s12) |
| 5 | 看過教學又開票的同一人比對穩定使用者 ID | analytics | [7.1、12.1](#s12) |
| 6 | 規則效果比較套用與未套用版本的評分及同題重開票率差 | analytics | [12.2](#s12) |
| 7 | 已學規則數依 RULE item 的 status 分別計數 | analytics | [12.1](#s12) |
| 8 | 規則套用次數等於 applied_to 清單長度 | analytics／repository | [9.2、12.1](#s12) |
| 9 | 每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫 | writing／rote／analytics | [12.1、14.3](#s12) |
| 10 | Demo 指標以 seeded data 展示 | demo／analytics | [11.2、11.3](#s11) |
| 11 | Demo 對同題重開票率標明 proxy 與精確定義 | demo | [11.3、13](#s11) |
| 12 | Demo 以同一批 Ticket 並排展示規則關閉與開啟產生的 Tutorial B | demo／writing | [11.4、13](#s11) |

### 20.12 發布教學版本

來源：[發布教學版本.feature](../spec/features/發布教學版本.feature)；共 5 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | publish 上架指定的 TutorialVersion | content | [8.2、8.3](#s8) |
| 2 | 發布的教學透過 S3 靜態 docs 站提供 | content／demo | [13](#s13) |
| 3 | 發布的教學提供 feedback widget | demo／ingress | [13](#s13) |
| 4 | Tutorial 的 current_version 指向目前教學版本 | content／repository | [8.3](#s8) |
| 5 | 已上架的版本具有 published_at | content／repository | [8.2、8.3](#s8) |

### 20.13 驗證教學規則

來源：[驗證教學規則.feature](../spec/features/驗證教學規則.feature)；共 8 條。

| # | Rule 原文 | 負責模組 | 設計段落 |
|---:|---|---|---|
| 1 | 規則成效比較套用組與同一篇教學套用前的已發布版本 | analytics | [12.2](#s12) |
| 2 | candidate 僅在平均評分嚴格提高且重開票率嚴格下降時升為 active | analytics | [12.2](#s12) |
| 3 | 未載入完整核定種子驗證批次時不改變規則狀態 | analytics | [12.2](#s12) |
| 4 | 與既有規則衝突的 candidate 規則變為 retired | writing／analytics | [7.6、12.2](#s12) |
| 5 | 後來失效的 active 規則變為 retired | analytics | [12.2](#s12) |
| 6 | 驗證無效的規則從可使用規則中退役 | analytics | [12.2](#s12) |
| 7 | curation 合併相近教學規則 | analytics／維護者 | [12.2](#s12) |
| 8 | Analytics 寫入教學規則的驗證後 status | analytics | [7.6、12.2](#s12) |
