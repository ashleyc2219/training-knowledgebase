# 自我優化 Training Knowledge Base — 資料庫關係圖

| 項目 | 內容 |
|---|---|
| 版本 | v1.1（與設計文件 §8 同步） |
| 日期 | 2026-09-12 |
| 儲存體 | 1 張 DynamoDB 表 + 1 個 GSI + 1 個 S3 bucket |

## 1. 物理上實際存在的東西

| 儲存體 | 名稱 | 鍵 | 內容 |
|---|---|---|---|
| DynamoDB 表 | `training_kb` | PK（分割鍵）、SK（排序鍵） | 九種 item 全部放這裡，用 PK 前綴區分 |
| DynamoDB GSI | `by_target` | 分割鍵 = `target` | 反向查「誰指向這個節點」：哪些 step 引用某 Feature、哪些版本套用某規則 |
| S3 bucket | `training-kb-content` | 物件路徑 | `tutorials/<slug>/v<n>.md`、`tutorials/<slug>/v<n>.diff`、`stepfunctions/<pipeline>/v<n>.json` |

DynamoDB 只存結構與關係；教學全文與 diff 放 S3，`TUTORIAL_VERSION.s3_key` 指過去。

## 2. 實體關係圖

九個實體 = 同一張表裡的九種 item。`PROVEN_WORKFLOW` 沒有任何邊：它只跟資料來源的形狀有關，不跟教學資料有關。

```mermaid
erDiagram
  TUTORIAL ||--o{ TUTORIAL_VERSION : has
  TUTORIAL_VERSION ||--o{ TUTORIAL_STEP : contains
  TUTORIAL_VERSION |o--o| TUTORIAL_VERSION : supersedes
  TUTORIAL_STEP }o--|| FEATURE : references
  TICKET }o--o| FEATURE : asks_about
  RELEASE }o--|| FEATURE : changes
  FEEDBACK }o--|| TUTORIAL_VERSION : refers_to
  AUTHORING_RULE }o--o{ TUTORIAL_VERSION : applied_to
  TUTORIAL {
    string pk PK "TUTORIAL#slug"
    string current_version
    string topic
    list feature_ids
    string status "active | retired"
  }
  TUTORIAL_VERSION {
    string pk PK "VERSION#slug@vN"
    string supersedes "前一版"
    string reason "gap:c12 | release:r42 | feedback:8"
    list rules_applied
    string s3_key
    timestamp published_at
  }
  TUTORIAL_STEP {
    string pk PK "STEP#slug@vN#i"
    string sk "REFERENCES#FEATURE#x"
    string target "GSI by_target 分割鍵"
    string type "click_ui | input | read"
    string text
  }
  FEATURE {
    string pk PK "FEATURE#name"
    list aliases "改名前後的名稱"
    timestamp first_seen
  }
  TICKET {
    string pk PK "TICKET#id"
    string source "github_issue | discord | email"
    string text
    string cluster_id
    list feature_ids
    list embedding "Titan 1024 維"
  }
  RELEASE {
    string pk PK "RELEASE#id"
    string feature
    string kind "renamed | changed | removed"
    string old_name
    string new_name
    string evidence
  }
  FEEDBACK {
    string pk PK "FEEDBACK#id"
    string tutorial_version
    int rating "1-5"
    string category
    string comment
    string user
    timestamp ts
  }
  AUTHORING_RULE {
    string pk PK "RULE#id"
    string rule
    string applies_when "step.type == click_ui"
    list evidence "feedback ids"
    string status "candidate | active | retired"
    list applied_to "版本清單"
    string derived_from
  }
  PROVEN_WORKFLOW {
    string pk PK "PROC#signature"
    list steps "tool 與 JSONPath 參數"
    list keys "簽名用的欄位"
    int success_count
    int fail_count
    string status "active | retired"
    timestamp last_used
  }
```

## 3. 九種 item 一覽

| PK 前綴 | 代表 | 主要屬性 | 顏色（架構圖） |
|---|---|---|---|
| `TUTORIAL#<slug>` | 教學身分 | current_version、topic、feature_ids、status | 一般 |
| `VERSION#<slug>@v<n>` | 版本 | supersedes、reason、rules_applied[]、s3_key | 一般 |
| `STEP#<slug>@v<n>#<i>` | 版本裡的一步 | SK=`REFERENCES#FEATURE#x`、target、type、text | 一般 |
| `FEATURE#<name>` | 產品功能（圖譜樞紐） | aliases[]、first_seen | 一般 |
| `TICKET#<id>` | 正規化工單 | source、text、cluster_id、feature_ids[]、embedding | 一般 |
| `RELEASE#<id>` | 正規化改版事件 | feature、kind、old_name、new_name、evidence | 一般 |
| `FEEDBACK#<id>` | 回饋 | tutorial_version、rating、category、comment、user、ts | 一般 |
| `RULE#<id>` | Authoring Rule | rule、applies_when、evidence[]、status、applied_to[]、derived_from | 差異化核心 |
| `PROC#<sig>` | Proven workflow | steps[]、keys[]、success_count、fail_count、status、last_used | 可學習 |

## 4. 邊怎麼存（adjacency list）

圖上的每一條線在表裡都是一筆 item：PK 是起點、SK 是「關係#終點」、`target` 是終點的複本給 GSI 用。

| 關係 | PK（起點） | SK | target |
|---|---|---|---|
| step references feature | `STEP#prepare-meeting@v2#3` | `REFERENCES#FEATURE#Prepare` | `FEATURE#Prepare` |
| version supersedes version | `VERSION#prepare-meeting@v3` | `SUPERSEDES#VERSION#prepare-meeting@v2` | `VERSION#prepare-meeting@v2` |
| rule applied_to version | `RULE#R-007` | `APPLIED_TO#VERSION#share-summary@v1` | `VERSION#share-summary@v1` |
| ticket asks_about feature | `TICKET#t_881` | `ASKS_ABOUT#FEATURE#Prepare` | `FEATURE#Prepare` |
| feedback refers_to version | `FEEDBACK#f_12` | `REFERS_TO#VERSION#prepare-meeting@v1` | `VERSION#prepare-meeting@v1` |

- **正向查**（某起點的所有邊）：用 PK query。
- **反向查**（誰指向某終點）：用 GSI `by_target` query。設計文件 §10 的「Release 只命中 A 的 step 3」就是對 `by_target` 下一次 `target = FEATURE#Prepare` 的 query。

```python
# 寫一條邊
table.put_item(Item={
    "PK": "STEP#prepare-meeting@v2#3",
    "SK": "REFERENCES#FEATURE#Prepare",
    "target": "FEATURE#Prepare",
    "text": "Open Copilot and select Prepare in the upper-right corner",
})

# 反查：哪些 step 引用了 Prepare？
resp = table.query(
    IndexName="by_target",
    KeyConditionExpression=Key("target").eq("FEATURE#Prepare"),
)
affected = [it["PK"] for it in resp["Items"]]
```

## 5. 讀寫矩陣

| | 圖譜 | RULE | PROC | FEEDBACK |
|---|---|---|---|---|
| Rote 層（接入） | 寫（正規化物件） | — | 讀、寫 | 寫 |
| Ticket Analysis | 讀、寫（新 Tutorial 節點） | 讀 | — | — |
| Release Note Update | 讀（by_target）、寫（新版本） | 讀 | — | — |
| Periodic Feedback Review | 讀、寫（新版本） | 讀、寫（candidate） | — | 讀 |
| Analytics | 讀 | 讀（applied_to）、寫（status） | — | 讀 |

只有 Rote 層碰 PROC；只有 Feedback Review 產生規則。

## 6. 三個容易問的細節

- **Ticket 的向量存哪裡**：1,024 維浮點數約 4 KB，直接放在 `TICKET` item 的 `embedding` 屬性內（DynamoDB 單筆上限 400 KB）；分群時 Lambda 把近期 Ticket 撈出來算 cosine，demo 規模不需要向量資料庫。
- **Feedback 為什麼能算每版評分**：`refers_to` 邊讓 `by_target` 能反查「某版本的所有 feedback」，Feedback Review 靠這個算平均評分與 category 分布。
- **PROC 為什麼不建邊**：它的查詢鍵是簽名，永遠是精確 get；第二層重疊率比對靠同寄件者的 `keys` 屬性掃描，數量小不需要索引。

## 參考資料

- DynamoDB Query（botocore）— https://botocore.readthedocs.io/reference/services/dynamodb/client/query.html
- Query a DynamoDB Global Secondary Index — https://docs.aws.eu/es_es/amazondynamodb/latest/developerguide/example_dynamodb_Scenarios_QueryWithGlobalSecondaryIndex_section.html
- AWS Free Tier — Serverless always free — https://aws.amazon.com/free/serverless
