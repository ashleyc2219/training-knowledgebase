# Phase 04：AWS 基礎建設與模型可用性確認

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 03：Repository — 本機儲存層（`03-Phase03-Repository-本機儲存層.md`） |
| 下一階段 | Phase 05：Writing — Bedrock 呼叫與輸出驗證（`05-Phase05-Writing-Bedrock呼叫與輸出驗證.md`） |
| 對應設計文件章節 | §9.1（表名、鍵、GSI、bucket）、§13（S3 website 的平台限制）、§17.1（已查證的平台用法）、§17.2（最小必要的安全處理）、§17.3（帳號、費用與現場備援）、待確認事項 O5（`docs/design/training-kb.md`） |
| 對應交付切片 | S0（設計文件第 16 節） |
| 預估時間 | 約 4 小時（其中 `cdk bootstrap` 第一次跑可能要等 3–5 分鐘） |
| 做完會得到 | 真正存在於你 AWS 帳號裡的一張 DynamoDB 表、一個 S3 bucket，以及一份確認過「這個 Region、這個帳號真的叫得動」的 Titan 與 Claude 模型 ID，寫進 `.env`。 |

---

## 1. 這階段做完會得到什麼

前三個階段完全在你自己的電腦上跑。這一階段第一次真的連上 AWS。

做完之後你會有：

1. **`infra/` 目錄**：用 AWS CDK（Python）描述基礎建設的程式碼。CDK 是「用程式碼寫雲端資源」的工具——你寫 Python，它產生 CloudFormation 範本，AWS 照著建。
2. **`TrainingKbDataStack`**：一個「堆疊」（stack，一組會一起建立、一起刪除的 AWS 資源），裡面有：
   - DynamoDB 表 `training_kb`：主鍵 `PK`／`SK`，一個 GSI `by_target`，隨用隨付（on-demand）。
   - S3 bucket：完全封鎖公開存取、強制用 HTTPS 存取、由 AWS 管理加密。
3. **四個 CDK 單元測試**：用 `aws_cdk.assertions.Template` 檢查「產生出來的範本真的長成我要的樣子」，不用部署就能跑。
4. **實際部署過的資源**，並有一組標了 `@pytest.mark.aws` 的驗收測試可以證明它們存在。
5. **`infra/scripts/check_models.py`**：列出你這個 Region 可用的基礎模型與 inference profile，實際呼叫一次 Titan（確認回 1024 維）、實際呼叫一次 Claude（確認 `converse` 通得過），把成功的 ID 印出來。
6. **填好的 `.env`**：`TKB_AWS_REGION`、`TKB_TABLE_NAME`、`TKB_BUCKET_NAME`、`TKB_EMBED_MODEL_ID`、`TKB_GEN_MODEL_ID` 等。這對應設計文件的 **O5**：「Claude model ID／inference profile、帳號配額及參數支援尚未驗證」，本階段就是去驗證它。

> **費用警告（設計文件 §17.3）：** 這一階段會在你的 AWS 帳號建立資源、呼叫付費 API。DynamoDB on-demand、S3 儲存、Bedrock 推論都可能產生費用。AWS 的免費額度取決於你的帳號方案與建立時間，**本文件不保證任何操作免費**。做完 Demo 之後請依 Phase 25 的清單刪除資源。

---

## 2. 它在整張地圖的位置

```text
基礎層          01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> [04 AWS 基礎建設]
                                                                 ^^^^^^^^^^^^^^^^^
                                                                     你在這裡
                                                                      |
AI 與內容層     05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                                        |
接入層          10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                        |
流程層          13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

Phase 04 建立的是「資料的家」。Phase 14 會在同一個 `infra/` 目錄加上第二個 stack `TrainingKbAppStack`（Lambda、Function URL、Step Functions），Phase 22 才會決定 `site/` 前綴要不要公開。

---

## 3. 開始前檢查

### 3.1 你需要先準備的東西

| 條件 | 怎麼確認 |
|---|---|
| 一個 AWS 帳號，而且你有權限建立 CloudFormation 堆疊 | 下面 3.2 的 `aws sts get-caller-identity` |
| 已安裝 AWS CLI v2 | `aws --version` |
| 已安裝 Node.js 18 以上（CDK 的命令列工具是 Node 寫的，即使我們用 Python 寫堆疊） | `node --version` |
| Phase 03 的 `uv run pytest -q` 全綠 | `uv run pytest -q` |
| 已在 Bedrock 主控台開啟你要用的模型存取權 | 下面 3.3 |

### 3.2 確認 AWS 認證

如果還沒設定過，先執行：

```bash
aws configure
```

它會依序問你四個問題：`AWS Access Key ID`、`AWS Secret Access Key`、`Default region name`（填 `us-east-1`）、`Default output format`（填 `json`）。金鑰要在 AWS 主控台的 IAM 建立。

**金鑰絕對不可以寫進任何 repo 裡的檔案**（設計文件 §17.2）。`aws configure` 會把它存在 `~/.aws/credentials`，那個目錄不在 repo 裡，沒問題。

驗證：

```bash
aws sts get-caller-identity
```

預期輸出（三個欄位都有值）：

```json
{
    "UserId": "AIDA...",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/your-name"
}
```

把 `Account` 的值記下來，等一下要用它組成全球唯一的 bucket 名稱。

### 3.3 確認 Bedrock 模型存取權

Bedrock 的模型預設是關閉的，要先在主控台申請開啟：

1. 打開 AWS 主控台，右上角把 Region 切到 `us-east-1`（或你決定要用的 Region）。
2. 搜尋並進入 **Amazon Bedrock**。
3. 左側選單找 **Model access**（模型存取）。
4. 勾選 **Amazon Titan Text Embeddings V2** 與至少一個 **Anthropic Claude** 模型，送出申請。
5. 等狀態變成 **Access granted**。

如果沒有這一步，Task 7 會拿到 `AccessDeniedException`。

### 3.4 選 Region（本計劃選擇）

設計文件 §17.3 把「選定 AWS Region」列為待確認事項。本計劃的建議順序：

| 選項 | 說明 |
|---|---|
| `us-east-1`（維吉尼亞北部） | Bedrock 模型種類最齊、新模型最早上；本文件所有範例都用它。缺點是離台灣遠，延遲高一點。 |
| `us-west-2`（奧勒岡） | 模型也很齊，常見的第二選擇。 |
| `ap-northeast-1`（東京） | 離台灣近，但 Bedrock 可用模型較少，Claude 的可用性要用 Task 6 的腳本實際確認。 |

**同一個 Region 要從頭用到尾**：DynamoDB、S3、Bedrock、Step Functions 都要在同一個 Region，否則後面會出現「表找不到」「模型找不到」的怪錯誤。決定之後寫進 `.env` 的 `TKB_AWS_REGION`，不要再換。

### 3.5 IAM 最少需要什麼權限（設計文件 §17.2）

這一階段其實有兩種身分，權限需求差很多：

```text
身分 A：部署者（你本人，跑 cdk bootstrap / cdk deploy）
  需要：cloudformation:*（限本帳號）
        s3:*           （CDK 的 bootstrap 資產 bucket + 我們自己的 bucket）
        iam:*          （建立／傳遞 CDK 的部署角色）
        ssm:GetParameter（讀 /cdk-bootstrap/* 的版本參數）
        dynamodb:CreateTable / DescribeTable / UpdateTable / DeleteTable
  說明：CDK bootstrap 本質上會建立 IAM 角色，所以它需要 iam 權限。
        黑客松最省事的做法是用一個附了 AdministratorAccess 的 IAM 使用者，
        但那不是最小權限。折衷做法：建立一個「只在部署時使用」的管理員身分，
        Demo 結束後依 Phase 25 的清單停用它。

身分 B：執行者（Lambda 的角色，以及你跑 check_models.py 時用的身分）
  需要（本階段只會用到 Bedrock 這幾項）：
        bedrock:ListFoundationModels
        bedrock:ListInferenceProfiles
        bedrock:InvokeModel          （資源限定在你要用的模型 ARN）
  Phase 14 以後才會加上 dynamodb / s3 / states 的執行權限。
```

身分 B 的最小政策 JSON（給 Task 6、7 用；你可以先用身分 A 跑，之後再收斂）：

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ListBedrockModels",
            "Effect": "Allow",
            "Action": [
                "bedrock:ListFoundationModels",
                "bedrock:ListInferenceProfiles"
            ],
            "Resource": "*"
        },
        {
            "Sid": "InvokeSelectedModels",
            "Effect": "Allow",
            "Action": "bedrock:InvokeModel",
            "Resource": [
                "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0",
                "arn:aws:bedrock:us-east-1::foundation-model/anthropic.*",
                "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.*"
            ]
        }
    ]
}
```

把 `123456789012` 換成你自己的帳號 ID。注意 foundation model 的 ARN 中間是**兩個冒號**（`bedrock:us-east-1::foundation-model/...`），因為基礎模型不屬於任何帳號；inference profile 則屬於你的帳號，所以有帳號 ID。

### 3.6 驗證指令與預期輸出

```bash
aws --version
```

預期：`aws-cli/2.x.x ...`。

```bash
node --version
```

預期：`v18.x.x` 以上。若沒有安裝，到 <https://nodejs.org/> 下載 LTS 版。

```bash
npx aws-cdk@2 --version
```

預期：`2.x.x (build ...)`。第一次跑會先下載，要等一下。如果你比較喜歡全域安裝，改用 `npm install -g aws-cdk` 之後就可以直接打 `cdk`。**本文件後面一律寫 `npx aws-cdk@2`**，你若已全域安裝，把它換成 `cdk` 即可。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| IaC（Infrastructure as Code） | 用程式碼描述要建立哪些雲端資源，而不是用滑鼠在主控台點。好處是可以版控、可以重建、不會忘記做了什麼。 | 整個 `infra/` |
| CloudFormation | AWS 內建的 IaC 服務。你給它一份 JSON/YAML 範本（template），它照著建立資源並記錄成一個「堆疊」。 | CDK 最終產生的東西 |
| CDK（Cloud Development Kit） | 讓你用 Python／TypeScript 寫程式，再由它產生 CloudFormation 範本的工具。省掉手寫幾百行 YAML。 | `infra/app.py`、`infra/stacks/data_stack.py` |
| stack（堆疊） | 一組會一起建立、一起更新、一起刪除的 AWS 資源。本專案有兩個：`TrainingKbDataStack`（本階段）與 `TrainingKbAppStack`（Phase 14）。 | `TrainingKbDataStack` |
| construct（構件） | CDK 裡的一個「零件」。`dynamodb.Table`、`s3.Bucket` 都是構件。 | `data_stack.py` |
| `cdk bootstrap` | 第一次在某個帳號＋Region 使用 CDK 時要跑一次。它會建立 CDK 自己需要的 S3 bucket（放部署用的檔案）與 IAM 角色。 | Task 5 |
| `cdk synth` | 「合成」：把你的 Python 程式跑一遍，產生 CloudFormation 範本印出來。**不會動到 AWS**，可以放心跑。 | Task 2–4 |
| `cdk deploy` | 把範本送去 CloudFormation，真的建立／更新資源。**會動到 AWS、會花錢。** | Task 5 |
| `cdk.out/` | `cdk synth` 產生的範本放在這個資料夾。要加進 `.gitignore`。 | Task 1 |
| on-demand / PAY_PER_REQUEST | DynamoDB 的計費方式：按實際讀寫次數收費，不用預先買容量。流量很小的 Demo 適合這個。 | Task 2 |
| RemovalPolicy | 「刪掉這個堆疊時，這個資源怎麼辦」。`DESTROY` 是一起刪掉；`RETAIN` 是留著（避免誤刪正式資料）。 | Task 4 |
| Block Public Access | S3 的「完全封鎖公開存取」開關。打開之後，就算有人不小心設了公開權限也不會生效。 | Task 3 |
| foundation model（基礎模型） | Bedrock 上可以直接呼叫的預訓練模型，例如 `amazon.titan-embed-text-v2:0`。 | Task 6、7 |
| inference profile（推論設定檔） | 一個「代表多個 Region 的模型別名」，ID 通常以 `us.`／`eu.` 開頭。某些新的 Claude 模型只能透過它呼叫，不能用裸的 model ID。 | Task 6、7 |
| `converse` | Bedrock 的統一對話 API。不管底下是哪家模型，請求格式都一樣。 | Task 6 |
| `invoke_model` | Bedrock 的原始呼叫 API，request body 格式各模型自己定。Titan embedding 只能用這個。 | Task 6 |
| `aws_cdk.assertions.Template` | CDK 提供的測試工具：把堆疊合成出範本，然後斷言「裡面有一個 XXX 資源、屬性是 YYY」。 | Task 2–4 |
| O5 | 設計文件第 18 節待確認事項的第五項：「模型與參數驗證」。本階段負責把它從「待確認」變成「已確認並寫進 `.env`」。 | Task 6、7 |

---

## 5. 設計說明

### 5.1 從 Python 程式到真正的 AWS 資源

```text
  你寫的 Python
  infra/stacks/data_stack.py
  (dynamodb.Table / s3.Bucket)
          |
          |  infra/app.py 建立 App 並實例化 Stack
          v
   npx aws-cdk@2 synth
          |
          |  CDK 執行 cdk.json 裡指定的指令（跑你的 Python）
          v
  cdk.out/TrainingKbDataStack.template.json     <- CloudFormation 範本（純 JSON）
          |                                        這一步完全不碰 AWS
          |
          +--> tests/unit/test_data_stack.py 用 assertions.Template 檢查它
          |
          |  npx aws-cdk@2 deploy
          v
  AWS CloudFormation 服務
          |
          +--> DynamoDB 表 training_kb（含 by_target GSI）
          +--> S3 bucket training-kb-content-<帳號ID>
          +--> 一個 BucketPolicy（因為我們開了 enforce_ssl）
          |
          v
  CfnOutput 把表名與 bucket 名印回終端機 -> 你抄進 .env
```

重點：`synth` 是安全的、可以一直跑；`deploy` 才會花錢。所以我們的測試全部建立在 `synth` 的結果上（`assertions.Template`），真正部署只做一次。

### 5.2 為什麼是這些資源、這些設定

| 設定 | 為什麼 | 依據 |
|---|---|---|
| 表名固定 `training_kb` | 設計文件 §9.1 明定 | §9.1 |
| 主鍵 `PK`（HASH）+ `SK`（RANGE） | 單表設計，十種實體共用；Phase 03 的 `Repository` 已經照這個寫 | §9.1 |
| 唯一 GSI `by_target`，分割鍵 `target`，沒有排序鍵 | 設計文件 §9.1：「GSI 不另加排序鍵」 | §9.1 |
| GSI 投影 `KEYS_ONLY` | 設計文件 §9.1：「先投影查詢需要的鍵；完整資料回基表取得」。與 Phase 03 的 conftest fixture 一致 | §9.1（本計劃選擇） |
| `BillingMode = PAY_PER_REQUEST` | Demo 流量極小，不預買容量；也省掉自動擴縮設定 | 本計劃選擇 |
| bucket 全開 Block Public Access | 設計文件 §17.2：「公開區只放可公開教學」。現在還沒有任何東西該公開，所以先全封 | §17.2 |
| `enforce_ssl = True` | 加一條 bucket policy，拒絕非 HTTPS 的存取。CloudFormation 範本會多出一個 `AWS::S3::BucketPolicy` 資源 | 本計劃選擇 |
| `encryption = S3_MANAGED` | 由 S3 自己管理加密金鑰（SSE-S3），不用額外設定 KMS | 本計劃選擇 |
| `site/` 前綴**現在不公開** | 設計文件 §13 說靜態站只有 HTTP、只有 `site/` 可公開，但那是 Phase 22 的決定。本階段先全封，避免未發布內容外洩（F36） | §13、§8.3 |
| `RemovalPolicy` 依環境 | 預設 `dev` → `DESTROY`（方便重來）；`-c env=prod` → `RETAIN`（避免誤刪） | 本計劃選擇 |
| 不用 `auto_delete_objects` | 它會偷偷多建一個 Lambda 與 IAM 角色，對新手來說多出很多看不懂的資源。改成在 `cdk destroy` 前手動清空 bucket | 本計劃選擇 |
| 用 `Table` 構件而不是 `TableV2` | `Table` 產生的 CloudFormation 資源型別就是 `AWS::DynamoDB::Table`，測試斷言最直覺。`TableV2` 是給多 Region 全域表用的，本專案用不到 | 本計劃選擇 |

### 5.3 `infra/` 的目錄結構

```text
AWS-Hackathon/
  pyproject.toml            <- 本階段修改：加 aws-cdk-lib、constructs，設定 pythonpath
  .env                      <- 本階段填值（已被 .gitignore 忽略，不會進版控）
  .env.example              <- 本階段補上 Bedrock 相關的鍵
  .gitignore                <- 本階段加入 cdk.out/
  infra/
    cdk.json                <- 告訴 CDK「怎麼執行我的 Python app」
    app.py                  <- CDK 的進入點：建立 App、實例化 Stack
    stacks/
      __init__.py
      data_stack.py         <- TrainingKbDataStack：table + GSI + bucket
    scripts/
      __init__.py
      check_models.py       <- 列模型、試呼叫 Titan 與 Claude、印出 .env 內容
    asl/                    <- 空的，Phase 14 才會放 ASL 檔
  tests/
    unit/
      test_data_stack.py    <- 用 assertions.Template 檢查合成結果（不碰 AWS）
      test_check_models.py  <- 檢查 check_models.py 的純函式（不碰 AWS）
    integration/
      test_aws_resources.py <- 標 @pytest.mark.aws，確認資源真的存在
      test_bedrock_live.py  <- 標 @pytest.mark.aws，真的呼叫一次模型
```

`cdk.json` 裡的 `app` 欄位告訴 CDK 要怎麼執行你的程式。因為我們用 `uv` 管理虛擬環境，最穩的寫法是直接指到 venv 裡的 python：

```json
{ "app": "../.venv/bin/python app.py" }
```

這樣你在 `infra/` 目錄下打 `npx aws-cdk@2 synth` 就會用到正確的 Python 與套件，不需要先 `activate`。

### 5.4 `check_models.py` 做什麼（對應 O5）

```text
  bedrock（控制面 client）
        |
        +-- list_foundation_models()
        |        |
        |        +--> 篩 outputModalities 含 "EMBEDDING" -> 印出可用的 embedding 模型
        |        +--> 篩 providerName == "Anthropic"     -> 印出可用的 Claude 基礎模型
        |
        +-- list_inference_profiles(typeEquals="SYSTEM_DEFINED")
                 |
                 +--> 篩 inferenceProfileId 含 "anthropic" -> 印出可用的 Claude profile

  bedrock-runtime（資料面 client）
        |
        +-- invoke_model(amazon.titan-embed-text-v2:0,
        |                body={"inputText": "...", "dimensions": 1024, "normalize": true})
        |        |
        |        +--> 讀 response["body"] -> json -> ["embedding"]
        |        +--> 確認 len(embedding) == 1024    <- O5 要確認的第一件事
        |
        +-- converse(候選 Claude ID 逐一試,
                     messages=[{"role":"user","content":[{"text":"回答 OK"}]}],
                     inferenceConfig={"maxTokens": 16, "temperature": 0.1})
                 |
                 +--> 第一個成功的 ID 就是答案      <- O5 要確認的第二件事
                 +--> 全部失敗 -> 印出每個的錯誤碼，不猜一個填進去

  最後印出可以直接貼進 .env 的幾行：
        TKB_AWS_REGION=us-east-1
        TKB_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0
        TKB_EMBED_DIMENSIONS=1024
        TKB_GEN_MODEL_ID=<實際成功的那一個>
```

設計文件 §17.1 已經查證 Titan V2 的 model ID 是 `amazon.titan-embed-text-v2:0`、輸出 1024 維；但 **Claude 的 model ID 沒有查證**，因為它依 Region 與帳號而異。設計文件明說「具體 Claude model ID／inference profile 由可用區域及帳號確認後固定，**不填猜測值**」。所以 `Settings.gen_model_id` 沒有預設值，一定要由本階段填。

候選清單順序（本計劃選擇）：先試 inference profile（`us.anthropic.*`），再試裸的 foundation model ID。原因是近年新的 Claude 模型在多數 Region 只開放 inference profile 呼叫，直接用裸 ID 會拿到 `ValidationException`。

---

## 6. 工作項目

### Task 1：建立 `infra/` 骨架與第一個 CDK 測試

**目的**：讓 `npx aws-cdk@2 synth` 跑得起來，並且讓 pytest 能夠 import 到 `infra/` 底下的模組。

**檔案**：
- 新增：`infra/cdk.json`、`infra/app.py`、`infra/stacks/__init__.py`、`infra/stacks/data_stack.py`
- 新增：`tests/unit/test_data_stack.py`
- 修改：`pyproject.toml`、`.gitignore`

**介面**：
- 消費：無
- 產出：`stacks.data_stack.TrainingKbDataStack(scope, construct_id, *, table_name: str, bucket_name: str, retain: bool, **kwargs)`

先安裝 CDK 的 Python 套件：

```bash
cd ~/AWS-Hackathon
uv add --dev aws-cdk-lib constructs
```

預期輸出：`+ aws-cdk-lib==2.x.x`、`+ constructs==10.x.x`。

在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 區塊加上 `pythonpath` 這一行（這個區塊 Phase 01 就建立了，Phase 03 核對過，現在只是多加一行）：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["infra"]
markers = [
    "aws: 需要真實 AWS 資源的測試；只有設定環境變數 TKB_RUN_AWS_TESTS=1 才會執行",
]
```

在 `.gitignore` 末端加上：

```gitignore
cdk.out/
infra/cdk.out/
```

- [ ] **步驟 1：寫測試**

`tests/unit/test_data_stack.py`：

```python
"""用 CDK 的 assertions 檢查合成出來的 CloudFormation 範本。

這些測試完全不碰 AWS：它們只是把 Python 程式跑一遍產生 JSON，然後檢查 JSON。
"""

from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from stacks.data_stack import TrainingKbDataStack


@pytest.fixture()
def dev_template() -> Template:
    app = cdk.App()
    stack = TrainingKbDataStack(
        app,
        "TrainingKbDataStack",
        table_name="training_kb",
        bucket_name="training-kb-content-test-account",
        retain=False,
    )
    return Template.from_stack(stack)


def test_stack_synthesizes(dev_template: Template) -> None:
    """最基本的檢查：範本合成得出來，而且是一個字典。"""
    rendered = dev_template.to_json()
    assert isinstance(rendered, dict)
    assert "Resources" in rendered


def test_stack_has_exactly_one_table_and_one_bucket(dev_template: Template) -> None:
    dev_template.resource_count_is("AWS::DynamoDB::Table", 1)
    dev_template.resource_count_is("AWS::S3::Bucket", 1)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_data_stack.py -v
```

預期：FAIL，`ModuleNotFoundError: No module named 'stacks'`。原因是 `infra/stacks/data_stack.py` 還不存在，而且 `pythonpath` 設定要等檔案存在才有意義。

- [ ] **步驟 3：寫最少的程式讓測試通過**

`infra/stacks/__init__.py`（空檔案）：

```python
"""CDK 堆疊定義。"""
```

`infra/stacks/data_stack.py`：

```python
"""TrainingKbDataStack：DynamoDB 單表與 S3 bucket。

對應設計文件 §9.1（表名、鍵、GSI、bucket 邏輯名）與 §17.2（公開存取先全封）。
"""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from constructs import Construct


class TrainingKbDataStack(Stack):
    """本專案的資料層：一張表、一個 bucket。

    參數：
        table_name:  DynamoDB 表名，設計文件 §9.1 固定為 training_kb。
        bucket_name: S3 bucket 名稱。S3 的名稱是「全球唯一」的，
                     所以要自己加上帳號 ID 之類的字尾。
        retain:      True 時刪堆疊會保留資源（正式環境）；
                     False 時一起刪掉（開發環境）。
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table_name: str,
        bucket_name: str,
        retain: bool,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        removal_policy = RemovalPolicy.RETAIN if retain else RemovalPolicy.DESTROY

        self.table = dynamodb.Table(
            self,
            "TrainingKbTable",
            table_name=table_name,
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
        )

        self.bucket = s3.Bucket(
            self,
            "TrainingKbContent",
            bucket_name=bucket_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=removal_policy,
        )

        CfnOutput(self, "TableName", value=self.table.table_name)
        CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
```

`infra/app.py`：

```python
#!/usr/bin/env python3
"""CDK 的進入點。

用法（在 infra/ 目錄下執行）：
    npx aws-cdk@2 synth  -c bucketName=training-kb-content-123456789012
    npx aws-cdk@2 deploy -c bucketName=training-kb-content-123456789012
    npx aws-cdk@2 deploy -c bucketName=... -c env=prod   # 資源改成刪堆疊時保留
"""

from __future__ import annotations

import os

import aws_cdk as cdk

from stacks.data_stack import TrainingKbDataStack

app = cdk.App()

env_name = app.node.try_get_context("env") or "dev"
table_name = app.node.try_get_context("tableName") or "training_kb"
bucket_name = app.node.try_get_context("bucketName")
if not bucket_name:
    raise SystemExit(
        "缺少 bucket 名稱。請加上 -c bucketName=<全球唯一的名稱>，"
        "例如 -c bucketName=training-kb-content-123456789012"
    )

region = (
    os.environ.get("TKB_AWS_REGION")
    or os.environ.get("CDK_DEFAULT_REGION")
    or "us-east-1"
)

TrainingKbDataStack(
    app,
    "TrainingKbDataStack",
    table_name=table_name,
    bucket_name=bucket_name,
    retain=(env_name == "prod"),
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=region,
    ),
)

app.synth()
```

`infra/cdk.json`：

```json
{
  "app": "../.venv/bin/python app.py",
  "watch": {
    "include": ["**"],
    "exclude": ["README.md", "cdk*.json", "**/__pycache__", "tests"]
  },
  "context": {
    "@aws-cdk/aws-lambda:recognizeLayerVersion": true,
    "@aws-cdk/core:checkSecretUsage": true,
    "@aws-cdk/core:target-partitions": ["aws"]
  }
}
```

> Windows 使用者：把 `app` 改成 `"..\\.venv\\Scripts\\python.exe app.py"`。

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/unit/test_data_stack.py -v
```

預期：`2 passed`。

再確認 CDK 命令列也認得這個專案（這一步不會動到 AWS）：

```bash
cd infra && npx aws-cdk@2 synth -c bucketName=training-kb-content-demo > /dev/null && echo SYNTH_OK; cd ..
```

預期：先出現 CDK 的一些提示訊息，最後印出 `SYNTH_OK`。如果看到 `Unable to resolve AWS account`，先確認 3.2 的 `aws sts get-caller-identity` 有成功。

- [ ] **步驟 5：commit**

```bash
git add pyproject.toml uv.lock .gitignore infra/ tests/unit/test_data_stack.py
git commit -m "feat(infra): 建立 CDK 骨架與 TrainingKbDataStack"
```

---

### Task 2：DynamoDB 表與 `by_target` 索引

**目的**：讓合成出來的範本裡的表，鍵、索引、計費方式都與 Phase 03 的測試 fixture 一模一樣。

**檔案**：
- 修改：`infra/stacks/data_stack.py`
- 修改：`tests/unit/test_data_stack.py`

**介面**：
- 消費：`aws_cdk.aws_dynamodb.Table`
- 產出：`TrainingKbDataStack.table`（`aws_cdk.aws_dynamodb.Table`）

- [ ] **步驟 1：寫測試**

把下面的測試加在 `tests/unit/test_data_stack.py` 最後：

```python
def test_table_uses_pk_sk_composite_key(dev_template: Template) -> None:
    dev_template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "TableName": "training_kb",
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
    )


def test_table_declares_all_three_key_attributes(dev_template: Template) -> None:
    tables = dev_template.find_resources("AWS::DynamoDB::Table")
    assert len(tables) == 1
    properties = next(iter(tables.values()))["Properties"]
    declared = {
        (a["AttributeName"], a["AttributeType"])
        for a in properties["AttributeDefinitions"]
    }
    assert declared == {("PK", "S"), ("SK", "S"), ("target", "S")}


def test_table_has_by_target_gsi_with_keys_only_projection(dev_template: Template) -> None:
    """設計文件 §9.1：唯一 GSI by_target，以 target 為分割鍵、不另加排序鍵。"""
    dev_template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "by_target",
                    "KeySchema": [{"AttributeName": "target", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                }
            ]
        },
    )
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_data_stack.py -v
```

預期：`test_stack_synthesizes` 與 `test_stack_has_exactly_one_table_and_one_bucket` 仍然 PASS；新的三個 FAIL。`test_table_declares_all_three_key_attributes` 會報 `AssertionError`，因為現在只宣告了 `PK`、`SK` 兩個屬性——DynamoDB 只要求把「當成鍵用」的屬性列出來，而 `target` 還沒被任何索引使用。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `infra/stacks/data_stack.py` 的 `self.table = dynamodb.Table(...)` 之後、`self.bucket = ...` 之前，插入：

```python
        # 唯一的 GSI：反查「誰指向這個終點」（設計文件 §9.1、§9.2）。
        # 只投影鍵，需要內容時由 Repository 回基表一致讀取。
        self.table.add_global_secondary_index(
            index_name="by_target",
            partition_key=dynamodb.Attribute(
                name="target", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.KEYS_ONLY,
        )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/unit/test_data_stack.py -v
```

預期：`5 passed`。

想親眼看看產生的 JSON，可以跑：

```bash
cd infra && npx aws-cdk@2 synth -c bucketName=training-kb-content-demo TrainingKbDataStack 2>/dev/null | head -40; cd ..
```

預期：印出 YAML 格式的資源定義，看得到 `Type: AWS::DynamoDB::Table` 與 `IndexName: by_target`。

- [ ] **步驟 5：commit**

```bash
git add infra/stacks/data_stack.py tests/unit/test_data_stack.py
git commit -m "feat(infra): 加入 by_target 全域次要索引"
```

---

### Task 3：S3 bucket 與公開存取封鎖

**目的**：確保 bucket 建出來時完全不可公開存取，而且只能用 HTTPS 存取。

**檔案**：
- 修改：`tests/unit/test_data_stack.py`

**介面**：
- 消費：`aws_cdk.aws_s3.Bucket`
- 產出：`TrainingKbDataStack.bucket`（`aws_cdk.aws_s3.Bucket`）

> Task 1 已經把 `s3.Bucket` 寫好了，這個 Task 補上測試來把「為什麼要這些設定」釘住。如果測試一次就過，那是正確的——TDD 的目的是讓契約被寫下來，不是每次都要先看到紅燈。但還是要先跑一次確認它現在會失敗，因為斷言的細節（例如 `BlockPublicAcls` 這些欄位名）很容易寫錯。

- [ ] **步驟 1：寫測試**

把下面的測試加在 `tests/unit/test_data_stack.py` 最後：

```python
def test_bucket_blocks_all_public_access(dev_template: Template) -> None:
    """設計文件 §17.2：公開區只放可公開教學。現在什麼都還不能公開，先全封。"""
    dev_template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "BucketName": "training-kb-content-test-account",
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
        },
    )


def test_bucket_is_encrypted(dev_template: Template) -> None:
    buckets = dev_template.find_resources("AWS::S3::Bucket")
    properties = next(iter(buckets.values()))["Properties"]
    rules = properties["BucketEncryption"]["ServerSideEncryptionConfiguration"]
    assert rules[0]["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"


def test_bucket_policy_denies_plain_http(dev_template: Template) -> None:
    """enforce_ssl 會產生一條拒絕非 HTTPS 存取的 bucket policy。"""
    policies = dev_template.find_resources("AWS::S3::BucketPolicy")
    assert len(policies) == 1
    statements = next(iter(policies.values()))["Properties"]["PolicyDocument"]["Statement"]
    denies = [
        s
        for s in statements
        if s.get("Effect") == "Deny"
        and s.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false"
    ]
    assert len(denies) == 1


def test_no_public_website_configuration_yet(dev_template: Template) -> None:
    """site/ 前綴是否公開留到 Phase 22 決定；本階段不得出現網站設定。"""
    buckets = dev_template.find_resources("AWS::S3::Bucket")
    properties = next(iter(buckets.values()))["Properties"]
    assert "WebsiteConfiguration" not in properties
```

- [ ] **步驟 2：跑測試，確認它失敗**

先故意把 `infra/stacks/data_stack.py` 裡的這兩行註解掉：

```python
            # block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            # enforce_ssl=True,
```

執行：

```bash
uv run pytest tests/unit/test_data_stack.py -v
```

預期：`test_bucket_blocks_all_public_access` FAIL（範本裡沒有 `PublicAccessBlockConfiguration`），`test_bucket_policy_denies_plain_http` FAIL（`assert len(policies) == 1` 收到 0）。這證明測試真的在檢查東西，不是空轉。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把剛才註解掉的兩行還原，`s3.Bucket(...)` 的完整內容應該是：

```python
        self.bucket = s3.Bucket(
            self,
            "TrainingKbContent",
            bucket_name=bucket_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=removal_policy,
        )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/unit/test_data_stack.py -v
```

預期：`9 passed`。

- [ ] **步驟 5：commit**

```bash
git add infra/stacks/data_stack.py tests/unit/test_data_stack.py
git commit -m "test(infra): 釘住 bucket 的公開存取與加密設定"
```

---

### Task 4：RemovalPolicy 依環境切換

**目的**：開發環境刪堆疊時資源一起刪掉（方便重來）；正式環境刪堆疊時資源保留（避免把資料刪光）。

**檔案**：
- 修改：`tests/unit/test_data_stack.py`

**介面**：
- 消費：`aws_cdk.RemovalPolicy`
- 產出：`TrainingKbDataStack(..., retain: bool)` 的行為契約

- [ ] **步驟 1：寫測試**

把下面的測試加在 `tests/unit/test_data_stack.py` 最後：

```python
def _template_for(retain: bool) -> Template:
    app = cdk.App()
    stack = TrainingKbDataStack(
        app,
        "TrainingKbDataStack",
        table_name="training_kb",
        bucket_name="training-kb-content-test-account",
        retain=retain,
    )
    return Template.from_stack(stack)


def test_dev_resources_are_destroyed_with_the_stack() -> None:
    template = _template_for(retain=False)
    template.has_resource("AWS::DynamoDB::Table", {"DeletionPolicy": "Delete"})
    template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Delete"})


def test_prod_resources_are_retained() -> None:
    template = _template_for(retain=True)
    template.has_resource("AWS::DynamoDB::Table", {"DeletionPolicy": "Retain"})
    template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Retain"})


def test_outputs_expose_table_and_bucket_names(dev_template: Template) -> None:
    outputs = dev_template.to_json().get("Outputs", {})
    names = set(outputs.keys())
    assert "TableName" in names
    assert "BucketName" in names
```

- [ ] **步驟 2：跑測試，確認它失敗**

先把 `data_stack.py` 裡的 `removal_policy` 那一行改成固定值：

```python
        removal_policy = RemovalPolicy.DESTROY
```

執行：

```bash
uv run pytest tests/unit/test_data_stack.py -v
```

預期：`test_prod_resources_are_retained` FAIL，訊息顯示 `DeletionPolicy` 是 `Delete` 而不是 `Retain`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把那一行改回：

```python
        removal_policy = RemovalPolicy.RETAIN if retain else RemovalPolicy.DESTROY
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/unit/test_data_stack.py -v
uv run ruff check .
```

預期：`12 passed`、`All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add infra/stacks/data_stack.py tests/unit/test_data_stack.py
git commit -m "feat(infra): RemovalPolicy 依環境切換並輸出資源名稱"
```

---

### Task 5：`cdk bootstrap`、`cdk deploy`，以及真的存在的驗收測試

**目的**：把範本真的送上 AWS，並用一個 `@pytest.mark.aws` 測試證明資源存在且設定正確。

**檔案**：
- 新增：`tests/integration/test_aws_resources.py`
- 修改：`.env`（新增，不進版控）、`.env.example`

**介面**：
- 消費：`training_kb.config.load_settings`
- 產出：真實存在的 DynamoDB 表與 S3 bucket

> **這個 Task 會花錢。** 執行 `cdk bootstrap` 與 `cdk deploy` 之前，請確認你知道自己在哪個帳號。設計文件 §17.3 明說 Free Tier 取決於帳號方案，**本文件不保證免費**。

- [ ] **步驟 1：寫測試**

`tests/integration/test_aws_resources.py`：

```python
"""確認 TrainingKbDataStack 部署出來的資源真的存在、設定正確。

這些測試會連上真正的 AWS，所以標了 @pytest.mark.aws。
只有設定 TKB_RUN_AWS_TESTS=1 時才會執行（規則寫在 tests/conftest.py）。
"""

from __future__ import annotations

import boto3
import pytest
from botocore.exceptions import ClientError
from training_kb.config import load_settings

pytestmark = pytest.mark.aws


@pytest.fixture(scope="module")
def settings():
    return load_settings()


def test_table_exists_with_expected_keys(settings) -> None:
    client = boto3.client("dynamodb", region_name=settings.aws_region)
    description = client.describe_table(TableName=settings.table_name)["Table"]
    key_schema = {k["AttributeName"]: k["KeyType"] for k in description["KeySchema"]}
    assert key_schema == {"PK": "HASH", "SK": "RANGE"}
    assert description["TableStatus"] == "ACTIVE"


def test_table_has_by_target_index(settings) -> None:
    client = boto3.client("dynamodb", region_name=settings.aws_region)
    description = client.describe_table(TableName=settings.table_name)["Table"]
    indexes = {g["IndexName"]: g for g in description.get("GlobalSecondaryIndexes", [])}
    assert "by_target" in indexes
    assert indexes["by_target"]["KeySchema"][0]["AttributeName"] == "target"
    assert indexes["by_target"]["Projection"]["ProjectionType"] == "KEYS_ONLY"


def test_bucket_exists(settings) -> None:
    client = boto3.client("s3", region_name=settings.aws_region)
    client.head_bucket(Bucket=settings.bucket_name)


def test_bucket_blocks_public_access(settings) -> None:
    client = boto3.client("s3", region_name=settings.aws_region)
    config = client.get_public_access_block(Bucket=settings.bucket_name)[
        "PublicAccessBlockConfiguration"
    ]
    assert config["BlockPublicAcls"] is True
    assert config["BlockPublicPolicy"] is True
    assert config["IgnorePublicAcls"] is True
    assert config["RestrictPublicBuckets"] is True


def test_repository_can_write_and_read_against_real_aws(settings) -> None:
    """最小的端到端煙霧測試：寫一筆、讀回來、刪掉。"""
    from training_kb.repository import build_repository

    repo = build_repository(settings)
    repo.put_meta("CONFIG#smoke_test", {"entity": "CONFIG", "values": ["ok"]})
    assert repo.get_config_list("smoke_test", ["fallback"]) == ["ok"]

    repo.put_object("operations/smoke_test.json", '{"ok": true}',
                    content_type="application/json; charset=utf-8")
    assert repo.get_object("operations/smoke_test.json") == b'{"ok": true}'

    repo.table.delete_item(Key={"PK": "CONFIG#smoke_test", "SK": "META"})
    repo.s3.delete_object(Bucket=settings.bucket_name, Key="operations/smoke_test.json")


def test_table_name_is_not_a_leftover_from_another_region(settings) -> None:
    """常見錯誤：.env 的 Region 和實際部署的 Region 不同。"""
    client = boto3.client("dynamodb", region_name=settings.aws_region)
    try:
        client.describe_table(TableName=settings.table_name)
    except ClientError as exc:
        pytest.fail(
            f"在 {settings.aws_region} 找不到表 {settings.table_name}："
            f"{exc.response['Error']['Code']}。"
            "請確認 .env 的 TKB_AWS_REGION 與你 cdk deploy 的 Region 一致。"
        )
```

- [ ] **步驟 2：跑測試，確認它失敗**

先建立 `.env`（如果 Phase 01 已經有這個檔案，就把下面的鍵加進去）。把 `123456789012` 換成你自己的帳號 ID：

```bash
cd ~/AWS-Hackathon
cat >> .env <<'EOF'
TKB_AWS_REGION=us-east-1
TKB_TABLE_NAME=training_kb
TKB_BUCKET_NAME=training-kb-content-123456789012
TKB_PROJECT_ID=demo-project
TKB_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0
TKB_EMBED_DIMENSIONS=1024
TKB_GEN_MODEL_ID=PENDING-PHASE04-TASK7
TKB_GITHUB_WEBHOOK_SECRET=change-me-before-phase-10
EOF
```

確認 `.env` 沒有被 Git 追蹤（設計文件 §17.2 特別提醒過這一點）：

```bash
git check-ignore -v .env
```

預期輸出類似 `.gitignore:5:.env	.env`。**如果這個指令沒有輸出，代表 `.env` 還沒被忽略，立刻回 Phase 01 把 `.env` 加進 `.gitignore`，不要繼續。**

執行測試：

```bash
TKB_RUN_AWS_TESTS=1 uv run --env-file .env pytest tests/integration/test_aws_resources.py -v
```

預期：FAIL。錯誤訊息是 `ResourceNotFoundException: Requested resource not found: Table: training_kb not found`，因為資源還沒部署。

> 如果你的 `uv` 版本不支援 `--env-file`，改用：
> `set -a && source .env && set +a && TKB_RUN_AWS_TESTS=1 uv run pytest tests/integration/test_aws_resources.py -v`

- [ ] **步驟 3：部署**

第一次在這個帳號＋Region 使用 CDK 時，要先 bootstrap：

```bash
cd ~/AWS-Hackathon/infra
npx aws-cdk@2 bootstrap aws://123456789012/us-east-1
```

預期輸出（要等 2–5 分鐘）：

```text
 ⏳  Bootstrapping environment aws://123456789012/us-east-1...
 ✅  Environment aws://123456789012/us-east-1 bootstrapped.
```

它會在你的帳號建立一個叫 `CDKToolkit` 的 CloudFormation 堆疊，裡面有 CDK 部署用的 S3 bucket 與 IAM 角色。這個動作每個帳號＋Region 只要做一次。

接著先看一次「將要建立什麼」：

```bash
npx aws-cdk@2 diff -c bucketName=training-kb-content-123456789012
```

預期：印出 `Resources` 清單，每一行前面是 `[+]`，代表全部都是新增。確認只有 `AWS::DynamoDB::Table`、`AWS::S3::Bucket`、`AWS::S3::BucketPolicy` 三個資源，沒有你不認得的東西。

真的部署：

```bash
npx aws-cdk@2 deploy -c bucketName=training-kb-content-123456789012
```

預期：CDK 會先列出「IAM 政策變更」要你確認（因為 `enforce_ssl` 會建一條 bucket policy），輸入 `y` 後開始部署。完成後印出：

```text
 ✅  TrainingKbDataStack

Outputs:
TrainingKbDataStack.BucketName = training-kb-content-123456789012
TrainingKbDataStack.TableName = training_kb

Stack ARN:
arn:aws:cloudformation:us-east-1:123456789012:stack/TrainingKbDataStack/...
```

把 `Outputs` 的兩個值和你 `.env` 裡的 `TKB_TABLE_NAME`、`TKB_BUCKET_NAME` 核對一次。

```bash
cd ~/AWS-Hackathon
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
TKB_RUN_AWS_TESTS=1 uv run --env-file .env pytest tests/integration/test_aws_resources.py -v
```

預期：`6 passed`。

再確認「沒設環境變數時會自動跳過」：

```bash
uv run pytest tests/integration/test_aws_resources.py -v
```

預期：`6 skipped`，理由是 `需要真實 AWS 資源；設定環境變數 TKB_RUN_AWS_TESTS=1 才會執行`。這代表其他人 clone 你的 repo、沒有 AWS 帳號時也能跑 `uv run pytest`。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_aws_resources.py .env.example
git commit -m "test(infra): 加入真實 AWS 資源的驗收測試"
```

注意 `git status --short` 應該**看不到** `.env`。如果看得到，立刻停下來處理 `.gitignore`。

---

### Task 6：`check_models.py` 的純函式

**目的**：先把「怎麼從 AWS 回應裡挑出候選模型」這段邏輯寫成純函式並測試，之後才拿去打真的 API。

**檔案**：
- 新增：`infra/scripts/__init__.py`、`infra/scripts/check_models.py`
- 新增：`tests/unit/test_check_models.py`

**介面**：
- 消費：無
- 產出（本階段新增的介面，簡報第 6 節未列）：
  - `scripts.check_models.embedding_model_ids(summaries: list[dict]) -> list[str]`
  - `scripts.check_models.claude_model_ids(summaries: list[dict]) -> list[str]`
  - `scripts.check_models.claude_profile_ids(profiles: list[dict]) -> list[str]`
  - `scripts.check_models.generation_candidates(summaries: list[dict], profiles: list[dict]) -> list[str]`
  - `scripts.check_models.env_lines(region: str, embed_model_id: str, dimensions: int, gen_model_id: str) -> list[str]`

- [ ] **步驟 1：寫測試**

`tests/unit/test_check_models.py`：

```python
"""check_models.py 的純函式：從 Bedrock 回應挑出候選模型。"""

from __future__ import annotations

from scripts.check_models import (
    claude_model_ids,
    claude_profile_ids,
    embedding_model_ids,
    env_lines,
    generation_candidates,
)

SUMMARIES = [
    {
        "modelId": "amazon.titan-embed-text-v2:0",
        "providerName": "Amazon",
        "outputModalities": ["EMBEDDING"],
        "inferenceTypesSupported": ["ON_DEMAND"],
        "modelLifecycle": {"status": "ACTIVE"},
    },
    {
        "modelId": "amazon.titan-embed-text-v1",
        "providerName": "Amazon",
        "outputModalities": ["EMBEDDING"],
        "inferenceTypesSupported": ["ON_DEMAND"],
        "modelLifecycle": {"status": "LEGACY"},
    },
    {
        "modelId": "anthropic.claude-3-5-haiku-20241022-v1:0",
        "providerName": "Anthropic",
        "outputModalities": ["TEXT"],
        "inferenceTypesSupported": ["INFERENCE_PROFILE"],
        "modelLifecycle": {"status": "ACTIVE"},
    },
    {
        "modelId": "anthropic.claude-3-haiku-20240307-v1:0",
        "providerName": "Anthropic",
        "outputModalities": ["TEXT"],
        "inferenceTypesSupported": ["ON_DEMAND"],
        "modelLifecycle": {"status": "ACTIVE"},
    },
    {
        "modelId": "meta.llama3-8b-instruct-v1:0",
        "providerName": "Meta",
        "outputModalities": ["TEXT"],
        "inferenceTypesSupported": ["ON_DEMAND"],
        "modelLifecycle": {"status": "ACTIVE"},
    },
]

PROFILES = [
    {
        "inferenceProfileId": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
        "inferenceProfileName": "US Claude 3.5 Haiku",
        "status": "ACTIVE",
        "type": "SYSTEM_DEFINED",
    },
    {
        "inferenceProfileId": "us.meta.llama3-2-11b-instruct-v1:0",
        "inferenceProfileName": "US Llama",
        "status": "ACTIVE",
        "type": "SYSTEM_DEFINED",
    },
]


def test_embedding_model_ids_keeps_only_active_embedding_models() -> None:
    assert embedding_model_ids(SUMMARIES) == ["amazon.titan-embed-text-v2:0"]


def test_claude_model_ids_filters_by_provider() -> None:
    assert claude_model_ids(SUMMARIES) == [
        "anthropic.claude-3-5-haiku-20241022-v1:0",
        "anthropic.claude-3-haiku-20240307-v1:0",
    ]


def test_claude_profile_ids_filters_by_id_prefix() -> None:
    assert claude_profile_ids(PROFILES) == [
        "us.anthropic.claude-3-5-haiku-20241022-v1:0"
    ]


def test_generation_candidates_puts_profiles_first() -> None:
    """profile 先試：新的 Claude 在多數 Region 只能用 inference profile 呼叫。"""
    candidates = generation_candidates(SUMMARIES, PROFILES)
    assert candidates[0] == "us.anthropic.claude-3-5-haiku-20241022-v1:0"
    assert "anthropic.claude-3-haiku-20240307-v1:0" in candidates
    assert len(candidates) == len(set(candidates))


def test_generation_candidates_skips_models_that_need_a_profile_without_one() -> None:
    """只支援 INFERENCE_PROFILE 的裸 model ID 直接呼叫一定失敗，不放進候選。"""
    candidates = generation_candidates(SUMMARIES, [])
    assert "anthropic.claude-3-5-haiku-20241022-v1:0" not in candidates
    assert candidates == ["anthropic.claude-3-haiku-20240307-v1:0"]


def test_env_lines_are_ready_to_paste() -> None:
    lines = env_lines(
        region="us-east-1",
        embed_model_id="amazon.titan-embed-text-v2:0",
        dimensions=1024,
        gen_model_id="us.anthropic.claude-3-5-haiku-20241022-v1:0",
    )
    assert lines == [
        "TKB_AWS_REGION=us-east-1",
        "TKB_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0",
        "TKB_EMBED_DIMENSIONS=1024",
        "TKB_GEN_MODEL_ID=us.anthropic.claude-3-5-haiku-20241022-v1:0",
    ]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_check_models.py -v
```

預期：FAIL，`ModuleNotFoundError: No module named 'scripts'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

`infra/scripts/__init__.py`（空檔案）：

```python
"""部署與確認用的一次性腳本。"""
```

`infra/scripts/check_models.py`：

```python
#!/usr/bin/env python3
"""列出這個 Region 可用的 Bedrock 模型，並實際小量呼叫一次做確認。

對應設計文件待確認事項 O5：
「Claude model ID／inference profile、帳號配額及參數支援尚未驗證。」
本腳本的輸出就是把 O5 變成已確認的依據；沒有跑過它，不可以在 .env 裡
填一個猜測的 gen_model_id。

用法：
    uv run --env-file .env python infra/scripts/check_models.py
    uv run python infra/scripts/check_models.py --region us-west-2
"""

from __future__ import annotations

import argparse
import json
import os
import sys

TITAN_V2_MODEL_ID = "amazon.titan-embed-text-v2:0"
EXPECTED_DIMENSIONS = 1024


# --------------------------------------------------------------------- 純函式
def embedding_model_ids(summaries: list[dict]) -> list[str]:
    """挑出「還在服役、輸出是向量」的模型 ID。"""
    return [
        summary["modelId"]
        for summary in summaries
        if "EMBEDDING" in summary.get("outputModalities", [])
        and summary.get("modelLifecycle", {}).get("status") == "ACTIVE"
    ]


def claude_model_ids(summaries: list[dict]) -> list[str]:
    """挑出 Anthropic 提供、還在服役、輸出是文字的基礎模型 ID。"""
    return [
        summary["modelId"]
        for summary in summaries
        if summary.get("providerName") == "Anthropic"
        and "TEXT" in summary.get("outputModalities", [])
        and summary.get("modelLifecycle", {}).get("status") == "ACTIVE"
    ]


def claude_profile_ids(profiles: list[dict]) -> list[str]:
    """挑出 Claude 的 inference profile ID（例如 us.anthropic.…）。"""
    return [
        profile["inferenceProfileId"]
        for profile in profiles
        if "anthropic" in profile.get("inferenceProfileId", "")
        and profile.get("status") == "ACTIVE"
    ]


def generation_candidates(summaries: list[dict], profiles: list[dict]) -> list[str]:
    """要依序嘗試的生成模型 ID。

    順序：inference profile 先、裸 model ID 後。
    只支援 INFERENCE_PROFILE 的裸 model ID 會被跳過——直接拿它呼叫一定會收到
    ValidationException，試了只是浪費時間與額度。
    """
    candidates = list(claude_profile_ids(profiles))
    by_id = {summary["modelId"]: summary for summary in summaries}
    for model_id in claude_model_ids(summaries):
        types = by_id[model_id].get("inferenceTypesSupported", [])
        if "ON_DEMAND" not in types:
            continue
        if model_id not in candidates:
            candidates.append(model_id)
    return candidates


def env_lines(
    region: str,
    embed_model_id: str,
    dimensions: int,
    gen_model_id: str,
) -> list[str]:
    """產生可以直接貼進 .env 的幾行。"""
    return [
        f"TKB_AWS_REGION={region}",
        f"TKB_EMBED_MODEL_ID={embed_model_id}",
        f"TKB_EMBED_DIMENSIONS={dimensions}",
        f"TKB_GEN_MODEL_ID={gen_model_id}",
    ]


# ------------------------------------------------------------- 真的呼叫 AWS
def check_embedding(runtime_client, model_id: str, dimensions: int) -> int:
    """對 Titan 做一次小量 embedding，回傳實際拿到的維度。"""
    response = runtime_client.invoke_model(
        modelId=model_id,
        body=json.dumps(
            {
                "inputText": "會前摘要在哪裡開啟？",
                "dimensions": dimensions,
                "normalize": True,
            }
        ),
        accept="application/json",
        contentType="application/json",
    )
    payload = json.loads(response["body"].read())
    vector = payload["embedding"]
    return len(vector)


def check_generation(runtime_client, model_id: str) -> str:
    """對候選生成模型做一次極小的 converse，回傳模型講的話。"""
    response = runtime_client.converse(
        modelId=model_id,
        system=[{"text": "只回答使用者要求的字，不要加任何說明。"}],
        messages=[{"role": "user", "content": [{"text": "請只輸出兩個字元：OK"}]}],
        inferenceConfig={"maxTokens": 16, "temperature": 0.1},
    )
    blocks = response["output"]["message"]["content"]
    return "".join(block.get("text", "") for block in blocks).strip()


def main(argv: list[str] | None = None) -> int:
    import boto3
    from botocore.exceptions import ClientError

    parser = argparse.ArgumentParser(description="確認 Bedrock 模型可用性")
    parser.add_argument(
        "--region",
        default=os.environ.get("TKB_AWS_REGION") or os.environ.get("AWS_REGION") or "us-east-1",
    )
    parser.add_argument("--dimensions", type=int, default=EXPECTED_DIMENSIONS)
    args = parser.parse_args(argv)
    region = args.region

    control = boto3.client("bedrock", region_name=region)
    runtime = boto3.client("bedrock-runtime", region_name=region)

    print(f"== Region：{region} ==\n")

    summaries = control.list_foundation_models().get("modelSummaries", [])
    print(f"這個 Region 共列出 {len(summaries)} 個基礎模型。\n")

    print("-- 可用的 embedding 模型 --")
    for model_id in embedding_model_ids(summaries):
        print(f"  {model_id}")
    print()

    profiles: list[dict] = []
    try:
        profiles = control.list_inference_profiles(typeEquals="SYSTEM_DEFINED").get(
            "inferenceProfileSummaries", []
        )
    except (ClientError, AttributeError) as exc:
        print(f"（無法列出 inference profile：{exc}）")
    print("-- 可用的 Claude inference profile --")
    for profile_id in claude_profile_ids(profiles):
        print(f"  {profile_id}")
    print()

    print("-- 可用的 Claude 基礎模型 --")
    for model_id in claude_model_ids(summaries):
        print(f"  {model_id}")
    print()

    embed_model_id = TITAN_V2_MODEL_ID
    print(f"-- 實際呼叫 {embed_model_id} --")
    try:
        dimensions = check_embedding(runtime, embed_model_id, args.dimensions)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        print(f"  失敗：{code}。請到 Bedrock 主控台的 Model access 開啟這個模型。")
        return 1
    print(f"  成功，回傳 {dimensions} 維")
    if dimensions != args.dimensions:
        print(f"  但維度不是預期的 {args.dimensions}，請停下來檢查。")
        return 1
    print()

    candidates = generation_candidates(summaries, profiles)
    if not candidates:
        print("找不到任何可以嘗試的 Claude 模型，請先到主控台開啟模型存取權。")
        return 1

    print("-- 依序嘗試生成模型 --")
    chosen: str | None = None
    for model_id in candidates:
        try:
            reply = check_generation(runtime, model_id)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            print(f"  {model_id}：失敗（{code}）")
            continue
        print(f"  {model_id}：成功，模型回答 {reply!r}")
        chosen = model_id
        break
    print()

    if chosen is None:
        print("所有候選模型都失敗。請檢查 Model access 與 Region，不要在 .env 填猜測值。")
        return 1

    print("== 把下面幾行寫進 .env ==")
    for line in env_lines(region, embed_model_id, dimensions, chosen):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/unit/test_check_models.py -v
uv run ruff check .
```

預期：`6 passed`、`All checks passed!`。注意這一步**還沒有連上 AWS**，純函式測試不需要帳號。

- [ ] **步驟 5：commit**

```bash
git add infra/scripts/ tests/unit/test_check_models.py
git commit -m "feat(infra): 加入模型候選挑選的純函式"
```

---

### Task 7：實際確認模型可用性並寫進 `.env`

**目的**：把 O5 從「待確認」變成「已確認」：真的呼叫一次 Titan 與 Claude，把成功的 ID 寫進 `.env`。

**檔案**：
- 新增：`tests/integration/test_bedrock_live.py`
- 修改：`.env`、`.env.example`

**介面**：
- 消費：`scripts.check_models.check_embedding`、`scripts.check_models.check_generation`、`training_kb.config.load_settings`
- 產出：`.env` 中確認過的 `TKB_EMBED_MODEL_ID`、`TKB_GEN_MODEL_ID`

- [ ] **步驟 1：寫測試**

`tests/integration/test_bedrock_live.py`：

```python
"""用 .env 裡的 model ID 真的呼叫一次 Bedrock，確認它們可用。

對應設計文件待確認事項 O5。這些測試會產生費用，所以標了 @pytest.mark.aws。
"""

from __future__ import annotations

import boto3
import pytest
from botocore.config import Config
from scripts.check_models import check_embedding, check_generation
from training_kb.config import load_settings

pytestmark = pytest.mark.aws


@pytest.fixture(scope="module")
def settings():
    return load_settings()


@pytest.fixture(scope="module")
def runtime(settings):
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=settings.bedrock_connect_timeout_s,
            read_timeout=settings.bedrock_read_timeout_s,
            retries={"max_attempts": 0},
        ),
    )


def test_gen_model_id_has_been_filled_in(settings) -> None:
    """跑過 check_models.py 之前，.env 裡是佔位字串，這個測試會擋住你。"""
    assert settings.gen_model_id
    assert not settings.gen_model_id.startswith("PENDING")


def test_titan_returns_expected_dimensions(settings, runtime) -> None:
    dimensions = check_embedding(
        runtime, settings.embed_model_id, settings.embed_dimensions
    )
    assert dimensions == settings.embed_dimensions == 1024


def test_claude_converse_returns_text(settings, runtime) -> None:
    reply = check_generation(runtime, settings.gen_model_id)
    assert isinstance(reply, str)
    assert reply.strip() != ""


def test_generation_respects_max_tokens(settings, runtime) -> None:
    """對應執行教學流程.feature Rule 4：每個 Bedrock 呼叫設定 max_tokens。

    把上限設到極小，模型一定會被截斷，stopReason 會是 max_tokens。
    Phase 05 會把這個情況當成驗證失敗。
    """
    response = runtime.converse(
        modelId=settings.gen_model_id,
        system=[{"text": "你是一位助理。"}],
        messages=[
            {"role": "user", "content": [{"text": "請寫一篇一千字的會議準備教學。"}]}
        ],
        inferenceConfig={"maxTokens": 8, "temperature": 0.1},
    )
    assert response["stopReason"] == "max_tokens"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
TKB_RUN_AWS_TESTS=1 uv run --env-file .env pytest tests/integration/test_bedrock_live.py -v
```

預期：`test_gen_model_id_has_been_filled_in` FAIL，因為 `.env` 裡現在是 `TKB_GEN_MODEL_ID=PENDING-PHASE04-TASK7`。其他測試也會 FAIL（`ValidationException`：找不到那個模型）。

- [ ] **步驟 3：執行腳本並填入 `.env`**

```bash
uv run --env-file .env python infra/scripts/check_models.py
```

預期輸出（你的實際模型清單會不一樣）：

```text
== Region：us-east-1 ==

這個 Region 共列出 68 個基礎模型。

-- 可用的 embedding 模型 --
  amazon.titan-embed-text-v2:0
  cohere.embed-english-v3

-- 可用的 Claude inference profile --
  us.anthropic.claude-3-5-haiku-20241022-v1:0
  us.anthropic.claude-sonnet-4-5-20250929-v1:0

-- 可用的 Claude 基礎模型 --
  anthropic.claude-3-haiku-20240307-v1:0
  anthropic.claude-3-5-haiku-20241022-v1:0

-- 實際呼叫 amazon.titan-embed-text-v2:0 --
  成功，回傳 1024 維

-- 依序嘗試生成模型 --
  us.anthropic.claude-3-5-haiku-20241022-v1:0：成功，模型回答 'OK'

== 把下面幾行寫進 .env ==
TKB_AWS_REGION=us-east-1
TKB_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0
TKB_EMBED_DIMENSIONS=1024
TKB_GEN_MODEL_ID=us.anthropic.claude-3-5-haiku-20241022-v1:0
```

把最後那四行複製，取代 `.env` 裡對應的舊值（特別是把 `PENDING-PHASE04-TASK7` 換掉）。

**選模型的建議（本計劃選擇）：** 本專案有兩種呼叫——判斷（`max_tokens` 512）與寫作（`max_tokens` 2048）。設計文件 §14.3 只要求「低 temperature」，沒有指定模型大小。黑客松建議先用腳本挑到的第一個成功模型；如果後面 Phase 07 發現寫出來的教學品質不夠，再換成能力較強的 Claude 並重跑一次本 Task 的測試。**不要因為「聽說某個模型比較好」就填一個腳本沒試成功的 ID。**

同時更新 `.env.example`（這個檔案**會**進版控，所以只放鍵名與說明，不放真值）：

```bash
cat >> .env.example <<'EOF'
# ---- Phase 04 確認後填入（不要填猜測值，先跑 infra/scripts/check_models.py）----
TKB_AWS_REGION=us-east-1
TKB_TABLE_NAME=training_kb
TKB_BUCKET_NAME=training-kb-content-<你的帳號ID>
TKB_PROJECT_ID=demo-project
TKB_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0
TKB_EMBED_DIMENSIONS=1024
TKB_GEN_MODEL_ID=<由 check_models.py 確認的 Claude model ID 或 inference profile>
TKB_GITHUB_WEBHOOK_SECRET=<Phase 10 建立 webhook 時產生的隨機字串>
EOF
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
TKB_RUN_AWS_TESTS=1 uv run --env-file .env pytest tests/integration/test_bedrock_live.py -v
```

預期：`4 passed`。

跑一次完整測試，確認沒有 AWS 帳號的人也能用：

```bash
uv run pytest -q
```

預期：本機測試全綠，`@pytest.mark.aws` 的那些顯示 skipped。

- [ ] **步驟 5：commit**

```bash
git add .env.example tests/integration/test_bedrock_live.py
git commit -m "test(infra): 確認 Titan 與 Claude 可呼叫並記錄設定範本"
```

再次確認 `.env` 沒有被加進去：

```bash
git show --stat HEAD | grep -c '\.env$' || echo "確認：.env 沒有進 commit"
```

預期：印出 `確認：.env 沒有進 commit`。

---

## 7. 完成檢查清單

- [ ] `uv run pytest tests/unit/test_data_stack.py -v` 全綠（12 個測試），完全沒有連 AWS。
- [ ] `uv run pytest tests/unit/test_check_models.py -v` 全綠（6 個測試）。
- [ ] `cd infra && npx aws-cdk@2 synth -c bucketName=<你的 bucket> > /dev/null && echo OK` 印出 `OK`。
- [ ] `aws dynamodb describe-table --table-name training_kb --region <你的 Region> --query 'Table.TableStatus' --output text` 印出 `ACTIVE`。
- [ ] `aws dynamodb describe-table --table-name training_kb --region <你的 Region> --query 'Table.GlobalSecondaryIndexes[0].IndexName' --output text` 印出 `by_target`。
- [ ] `aws s3api get-public-access-block --bucket <你的 bucket>` 四個欄位都是 `true`。
- [ ] `TKB_RUN_AWS_TESTS=1 uv run --env-file .env pytest -m aws -v` 全綠（10 個測試）。
- [ ] `uv run pytest -q` 在沒有 `TKB_RUN_AWS_TESTS` 時全綠，AWS 測試顯示 skipped。
- [ ] `git check-ignore -v .env` 有輸出，且 `git status --short` 看不到 `.env`。
- [ ] `.env` 裡的 `TKB_GEN_MODEL_ID` 是 `check_models.py` **實際呼叫成功**的那一個，不是抄來的。
- [ ] `uv run ruff check .` 通過。

對應設計文件第 16 節切片 S0 的檢查項目：

| S0 要求 | 本階段的狀態 |
|---|---|
| 「模型可用性已確認」 | ✅ Task 6、7 完成 |
| 「來源 ID、白名單已確認」 | ❌ 屬於 Phase 10、12（O6） |
| 「O2／O3 的最小整合驗證有可追溯結果」 | ❌ 機制在 Phase 03、07、08，驗證在 Phase 24 |

所以 **S0 到這裡還沒完成**，不要對外宣稱切片 S0 已交付。

---

## 8. 常見錯誤與排除

**症狀 1：`cdk synth` 出現 `Unable to resolve AWS account to use. It must be either configured when you define your CDK Stack, or through the environment`**

- 原因：`infra/app.py` 用 `CDK_DEFAULT_ACCOUNT` 決定帳號，而 CDK 是靠你的 AWS CLI 設定取得它的。CLI 沒設好時這個變數是空的。
- 解法：先確認 `aws sts get-caller-identity` 有輸出。仍然不行的話，改成在 `cdk` 指令前面明確指定：`CDK_DEFAULT_ACCOUNT=123456789012 CDK_DEFAULT_REGION=us-east-1 npx aws-cdk@2 synth ...`。

**症狀 2：`cdk deploy` 出現 `This stack uses assets, so the toolkit stack must be deployed to the environment (Run "cdk bootstrap aws://ACCOUNT/REGION")`**

- 原因：這個帳號＋Region 還沒 bootstrap 過。
- 解法：執行 Task 5 步驟 3 的 `npx aws-cdk@2 bootstrap aws://<帳號>/<Region>`。每個帳號＋Region 只要做一次。

**症狀 3：`BucketAlreadyExists` 或 `BucketAlreadyOwnedByYou`**

- 原因：S3 的 bucket 名稱是**全世界唯一**的，不只是你的帳號內唯一。`training-kb-content` 這種好記的名字早就被別人用掉了。
- 解法：`-c bucketName=training-kb-content-<你的12位帳號ID>`。名稱只能用小寫英數與連字號，3–63 個字元，不能有底線。

**症狀 4：`AccessDeniedException: You don't have access to the model with the specified model ID`**

- 原因：Bedrock 模型存取權沒開，或是開在別的 Region。
- 解法：回到 3.3，確認主控台右上角的 Region 和你 `.env` 的 `TKB_AWS_REGION` 一致，再確認該模型顯示 `Access granted`。

**症狀 5：`ValidationException: Invocation of model ID anthropic.claude-... with on-demand throughput isn't supported. Retry your request with the ID or ARN of an inference profile that contains this model.`**

- 原因：這個 Claude 模型在你的 Region 只能透過 inference profile 呼叫，不能用裸的 model ID。
- 解法：用 `check_models.py` 印出的 `us.anthropic.…` 形式的 ID。`generation_candidates()` 已經把「只支援 INFERENCE_PROFILE 的裸 ID」過濾掉，所以照著腳本的輸出填就不會踩到。

**症狀 6：`ModuleNotFoundError: No module named 'stacks'`（跑 pytest 時）**

- 原因：`pyproject.toml` 的 `[tool.pytest.ini_options]` 少了 `pythonpath = ["infra"]`，或是 `infra/stacks/__init__.py` 沒建立。
- 解法：兩個都補上。確認方式：`uv run python -c "import sys; sys.path.insert(0, 'infra'); import stacks.data_stack; print('ok')"`。

**症狀 7：`cdk destroy` 失敗，訊息是 `The bucket you tried to delete is not empty`**

- 原因：本計劃刻意不使用 `auto_delete_objects`，所以 CloudFormation 不會幫你清空 bucket。
- 解法：先清空再刪堆疊：`aws s3 rm s3://<你的 bucket> --recursive`，然後 `cd infra && npx aws-cdk@2 destroy -c bucketName=<你的 bucket>`。

**症狀 8：測試說找不到表，但你明明剛部署完**

- 原因：`.env` 的 `TKB_AWS_REGION` 和你部署時用的 Region 不同。DynamoDB 表是 Region 專屬的，`us-east-1` 的表在 `us-west-2` 完全看不到。
- 解法：`aws dynamodb list-tables --region us-east-1` 與 `--region us-west-2` 各跑一次，看表在哪裡，然後統一成同一個 Region。`test_table_name_is_not_a_leftover_from_another_region` 這個測試就是為了提早抓到它。

**症狀 9：`uv run --env-file .env` 說沒有 `--env-file` 這個選項**

- 原因：`uv` 版本太舊。
- 解法：升級 `uv`，或改用 `set -a && source .env && set +a && uv run pytest ...`。

**症狀 10：跑完 `check_models.py` 後看到 AWS 帳單有 Bedrock 費用**

- 原因：這是預期行為。腳本真的呼叫了模型。
- 解法：這不是錯誤。設計文件 §17.3 已經說明本案不保證免費。每次呼叫的量都很小（一句話的 embedding、16 個 token 的生成），但**不要在迴圈裡反覆執行這個腳本**。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| Lambda、Function URL、Layer 打包 | Phase 14（`14-Phase14-StepFunctions與Lambda上線.md`） |
| Step Functions 的 state machine 與 ASL 檔 | Phase 14 |
| EventBridge Scheduler 每日排程 | Phase 18（`18-Phase18-Feedback-Review-候選規則與每日排程.md`） |
| 決定 `site/` 前綴要不要公開、S3 website endpoint 設定 | Phase 22（`22-Phase22-S3靜態教學站.md`）。設計文件 §13 已經指出 website endpoint 只有 HTTP，這個取捨要在那裡做，不是現在 |
| Lambda 執行角色的最小 IAM 政策 | Phase 14；本階段只列出「你本人」與「呼叫模型」需要的權限 |
| 在程式裡呼叫 Bedrock（`BedrockWriter`） | Phase 05（`05-Phase05-Writing-Bedrock呼叫與輸出驗證.md`）。本階段的 `check_models.py` 是一次性確認腳本，不是產品程式 |
| DynamoDB 的 TTL、備份、point-in-time recovery | 不做。Demo 資料可重建，不需要 |
| CloudFront、自訂網域、HTTPS 靜態站 | 不做（設計文件 §13 明確排除） |
| Snyk 依賴掃描 | Phase 25（`25-Phase25-安全檢查與Demo當日準備.md`） |
| 刪除資源、停用 webhook 與排程 | Phase 25 |

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `查詢知識圖譜.feature` | Rule 2：查詢誰引用 Feature 時使用 by_target 的 target | Task 2 建立 `by_target` GSI（查詢邏輯在 Phase 03／09） |
| `建立教學版本.feature` | Rule 5：每個版本的完整內容儲存在 `tutorials/<slug>/v<n>.md` | Task 1、3 建立存放它的 bucket（實際寫入在 Phase 07） |
| `建立教學版本.feature` | Rule 7：與前版的 diff 儲存在 `tutorials/<slug>/v<n>.diff` | Task 1、3（同上） |
| `執行教學流程.feature` | Rule 4：每個 Bedrock 呼叫設定 max_tokens | Task 7 的 `test_generation_respects_max_tokens` 用真實呼叫確認 `maxTokens` 會生效；程式層的強制在 Phase 05 |
| `執行教學流程.feature` | Rule 5：每個 Bedrock 呼叫設定逾時 | Task 7 的 `runtime` fixture 用 `botocore.config.Config` 設了連線 2 秒、讀取 30 秒；程式層在 Phase 05 |
| `執行教學流程.feature` | Rule 9：判斷節點使用低 temperature | Task 6 的 `check_generation` 固定 `temperature=0.1`；程式層在 Phase 05 |
| `執行教學流程.feature` | Rule 10：Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json` | Task 1、3 建立 bucket 並預留 `infra/asl/` 目錄；快照寫入在 Phase 14 |
| `發布教學版本.feature` | Rule 2：發布的教學透過 S3 靜態 docs 站提供 | Task 3 建立 bucket，但**刻意不開公開存取**；是否開放 `site/` 留給 Phase 22 |

設計文件章節對照：

| 設計章節 | 本階段落實處 |
|---|---|
| §9.1 表名 `training_kb`、複合主鍵 `PK`／`SK`、唯一 GSI `by_target`、bucket 邏輯名 `training-kb-content` 與「不假設此名稱可直接取得」 | Task 1–3 |
| §13 S3 website endpoint 只有 HTTP、只有 `site/` 可公開 | Task 3 的 `test_no_public_website_configuration_yet`（本階段先全封） |
| §17.1 Titan V2 model ID 為 `amazon.titan-embed-text-v2:0`、1024 維；Claude model ID 由可用區域及帳號確認後固定，不填猜測值 | Task 6、7 |
| §17.1 DynamoDB 基表可一致讀取、GSI 不行 | Task 2 的 GSI 設定（讀取端在 Phase 03） |
| §17.2 執行角色只授權需要的模型、表、S3 路徑；secrets 只由執行環境提供 | 第 3.5 節的 IAM 政策、Task 5 的 `.env` 檢查 |
| §17.3 選定 Region、Claude 可呼叫性、Titan 權限、實際配額須部署前確認；不保證免費 | 第 3.4 節、Task 7、第 8 節症狀 10 |
| O5 模型與參數驗證 | Task 6、7（腳本輸出即為確認依據） |

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：§9.1 鍵與原生型別、§9.3 S3 與執行資訊、§13 Demo UI 與 S3 教學頁（website endpoint 的平台限制）、§14.3 執行參數的建議起點、§16 交付切片、§17.1 已查證的平台用法、§17.2 最小必要的安全處理、§17.3 帳號費用與現場備援、§18 待確認事項 O5。

規格檔：`docs/spec/features/執行教學流程.feature`、`docs/spec/features/建立教學版本.feature`、`docs/spec/features/查詢知識圖譜.feature`、`docs/spec/features/發布教學版本.feature`。

外部文件（本次以 Context7 MCP 與 AWS 官方文件查證）：

- AWS CDK Python 的 DynamoDB 構件（`Table`、`add_global_secondary_index`、`BillingMode`、`RemovalPolicy`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_dynamodb/README.html>
- AWS CDK Python 的 S3 構件（`Bucket`、`BlockPublicAccess`、`enforce_ssl`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_s3/README.html>
- AWS CDK `assertions`（`Template.from_stack`、`has_resource_properties`、`resource_count_is`、`find_resources`、`has_resource`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.assertions/README.html>
- CDK bootstrap 說明：<https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html>
- Bedrock `ListFoundationModels`（回應欄位 `modelSummaries`、`outputModalities`、`inferenceTypesSupported`、`modelLifecycle.status`）：<https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModels.html>
- Bedrock `ListInferenceProfiles`（參數 `typeEquals`，值 `SYSTEM_DEFINED`／`APPLICATION`；回應 `inferenceProfileSummaries`）：<https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListInferenceProfiles.html>
- Bedrock `Converse`（`modelId`、`system`、`messages`、`inferenceConfig.maxTokens`／`temperature`、回應 `output.message.content[].text`、`stopReason` 合法值含 `max_tokens`）：<https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html>
- Amazon Titan Text Embeddings（model ID `amazon.titan-embed-text-v2:0`、輸出 1024／512／256 維、不支援 `maxTokenCount`／`topP`）：<https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html>
- Titan Embeddings 的 request／response body（`inputText`、`dimensions`、`normalize`、`embeddingTypes`；回應 `embedding`、`inputTextTokenCount`）：<https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html>
- botocore `Config`（`connect_timeout`、`read_timeout`、`retries.max_attempts` 代表「重試次數」，0 表示不重試）：<https://docs.aws.amazon.com/botocore/latest/reference/config.html>
- AWS Free Tier FAQ（費用依帳號方案而定）：<https://aws.amazon.com/free/free-tier-faqs/>
- S3 bucket 命名規則：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html>
