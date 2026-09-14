# Phase 09：AWS 資料資源與最小 IAM 實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 用 AWS CDK Python v2 建立唯一的 `training_kb` 表、唯一的 `by_target` GSI、一個完全私有的內容 bucket，以及一個只能碰這兩者的資料角色。

**架構：** `TrainingKbDataStack` 只宣告資料資源；Lambda、Step Functions 與排程留給後面 Phase 的另一個 stack。程式從環境變數讀實際名稱，不把 bucket 名稱寫死在程式裡。`aws_cdk.assertions.Template` 在本機把「不能多出東西」變成可執行的測試。

**技術：** Python 3.12、`aws-cdk-lib` v2、`constructs`、`aws_cdk.assertions`、pytest、Node.js 版 CDK CLI、AWS CLI。

## 全域限制

- 唯一主來源是 [Training KB 設計 §9.1、§9.3、§13、§17](../../design/training-kb.md)；前置為 [Phase 08：分頁查詢與一致讀取基礎](./08-Phase08-分頁查詢與一致讀取基礎.md)，Phase 08 未通過時停止。
- 下一階段是 [Phase 10：O2 操作紀錄與永久去重契約](./10-Phase10-O2操作紀錄與永久去重契約.md)。
- 本階段不做：不建立 Lambda、Step Functions、EventBridge、CloudFront 或任何公開讀取 API；不開放 bucket 公開讀取（`site/` 的公開設定屬於 Phase 57）；不寫入任何業務資料；不建立第二張表或第二個索引。
- 與本 Phase 有關的 gate：O1 必須已核定（`docs/decisions/O1-metadata-sort-key.md` 明寫 `Status: accepted` 或 `rejected` 與替代值），因為 `PK`／`SK` 與 metadata 鍵直接決定表結構。部署成功只代表資源存在，**不代表** O2、O3、O5 任何一個通過，也不代表 Repository 行為已在真實 AWS 驗證。停止點：計畫一旦出現第二個資料庫、第二個 GSI、公開的私有內容或帶 `*` 的 IAM 動作／資源，立刻停止並回到設計 §9.1 與 §17.2。
- 帳號、Region、配額與費用都要部署前確認；沒有帳號或權限時把 Task 3 標記 `BLOCKED`，不要填猜測值，也不要宣稱免費。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 05-08 的程式契約（鍵、item、查詢）
                |
                v
+---------------+---------------------------+
| [你在這裡] Phase 09 TrainingKbDataStack    |
|  DynamoDB training_kb（PK/SK）+ by_target  |
|  S3 私有 bucket + 最小資料角色              |
+-------+---------------------------+-------+
        v                           v
 Phase 06-08 的實表 smoke    Phase 41/48/52 的流程 stack
                            （另一個 stack，本 Phase 不建）
```

## 2. 完成後看得到什麼

`cdk synth` 產生的 template 只有兩個資料資源與一個角色；`cdk deploy` 之後，實際帳號可以查到：

```text
aws dynamodb describe-table --table-name training_kb
  -> KeySchema: PK(HASH), SK(RANGE)
  -> GlobalSecondaryIndexes: [by_target] <- 只有一個；target(HASH)，KEYS_ONLY

aws s3api get-public-access-block --bucket <輸出的 bucket 名稱>
  -> BlockPublicAcls / IgnorePublicAcls / BlockPublicPolicy / RestrictPublicBuckets 皆為 true

CfnOutput -> TrainingKbTableName / TrainingKbBucketName / TrainingKbDataRoleArn
```

這三個輸出就是 `.env` 裡 `TKB_TABLE_NAME`、`TKB_CONTENT_BUCKET` 的來源（變數名以 [00A 第 3.5 節](00A-共用契約與名詞.md) 為準），程式不再猜名稱。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| CDK | 用 Python 寫基礎設施；`cdk synth` 只在本機把它轉成 CloudFormation template，不動雲端資源。 |
| bootstrap | 在某個帳號＋Region 準備 CDK 部署用的暫存 bucket 與角色，一個環境只要做一次。 |
| GSI | 第二個查法的索引；本案只有 `by_target`，分割鍵 `target`，而 `KEYS_ONLY` 代表索引只存鍵，查到候選要回基表拿完整資料。 |
| 最小 IAM | 只給「這個角色真的會用到」的動作與資源，不用 `dynamodb:*` 或 `Resource: "*"`。 |
| `s3:ListBucket` 與 `s3:prefix` | `ListBucket` 是「列出 bucket 裡有哪些 key」的權限，屬於 bucket 層級，所以資源要寫 bucket ARN 而不是 `bucket/*`。`s3:prefix` 是加在這個動作上的條件，限制只能列出哪些開頭的 key。 |
| `enforce_ssl` | CDK 的 bucket 參數；打開時會自動加一段 bucket policy，對「沒走 TLS」的請求 `Deny`。它是額外限制，不是授權。 |
| `RemovalPolicy.RETAIN` | 刪 stack 時保留這個資源；`cdk destroy` 不會順手刪掉表與教學內容，要刪得由維護者另外動手。 |
| `CfnOutput` | 部署完成後印在終端與 CloudFormation Outputs 的值；本 Phase 用它把實際名稱交給 `.env`。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `infra/training_kb_data_stack.py` | `TrainingKbDataStack`：表、索引、bucket、資料角色與輸出。 |
| 建立 | `infra/app.py` | CDK app 進入點；本 Phase 只實例化 `TrainingKbDataStack(app, "TrainingKbData")`，[Phase 41](41-Phase41-Ticket-Analysis雲端流程驗收.md) 才加上 `TrainingKbStack(app, "TrainingKbApp")`。 |
| 建立 | `cdk.json`（專案根目錄） | 指定 `app` 指令，讓 CLI 用專案環境執行。 |
| 建立 | `infra/__init__.py` | 套件標記（只有 docstring）。沒有它，`mypy src infra` 會把 `infra/training_kb_data_stack.py` 同時當成 `training_kb_data_stack` 與 `infra.training_kb_data_stack` 而報 `Source file found twice under different module names`。 |
| 測試 | `tests/unit/test_data_stack.py` | `Template` 斷言：只能有這些資源、不能有萬用字元。 |
| ~~修改~~ 已存在 | `pyproject.toml` | `aws-cdk-lib`、`constructs` 早已在 `[dependency-groups] dev`（[00A §3.2](00A-共用契約與名詞.md) 規定後續相依一律放 dev group，不另開 infra extra），本 Phase **不修改** `pyproject.toml`／`uv.lock`。 |

## 5. 固定介面

### Consumes

```text
設計 §9.1：表名 training_kb、主鍵 (PK, SK)、唯一 GSI by_target 以 target 為分割鍵
設計 §9.3：私有前綴 tutorials/、operations/、stepfunctions/、demo/previews/；site/ 只由發布流程寫
Phase 02 Settings：TKB_TABLE_NAME、TKB_CONTENT_BUCKET、TKB_AWS_REGION 由部署輸出填入
```

環境變數名以 [00A 第 3.5 節](00A-共用契約與名詞.md) 為準：bucket 的變數名逐字是 `TKB_CONTENT_BUCKET`，不要自創短名。

### Produces

```python
TABLE_NAME = "training_kb"
TARGET_INDEX = "by_target"
PRIVATE_PREFIXES = ("tutorials/", "operations/", "stepfunctions/", "demo/previews/")


class TrainingKbDataStack(Stack):
    """唯一的資料 stack；屬性 table、bucket、data_role 供後續 stack 引用。"""

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None: ...
```

`**kwargs` 的標註是 `Any` 而不是 `object`：`object` 在 mypy strict 下會因為 `**kwargs: object`
轉送給 `Stack.__init__` 的每個具名參數（`env`、`description`、`tags`…）而各報一次
`incompatible type "**dict[str, object]"`，共 8 個錯誤。`Any` 是 CDK Python 範本本身的寫法，
也不需要 `# type: ignore` 消音。

後續 Phase 的流程 stack 以 `stack.table`、`stack.bucket`、`stack.data_role` 引用同一份資源，不重新建立第二張表。`PRIVATE_PREFIXES` 是**測試與 IAM 的核對清單**，不是公開判準：哪些 key 對外可讀由 bucket policy 的 `site/*` 決定（[Phase 57](57-Phase57-S3靜態教學站與回饋下載.md) 才寫）。四個前綴依序對應教學全文與 diff（Phase 22）、操作紀錄（[Phase 10](10-Phase10-O2操作紀錄與永久去重契約.md)）、ASL 快照（Phase 29）與 Demo 規則開關對照（[Phase 58](58-Phase58-Demo控制台與規則開關預覽.md)）。

## 6. 設計細節

資源清單刻意很短，因為每多一個資源就多一個要驗收的失敗切點：

```text
TrainingKbDataStack
   +-- AWS::DynamoDB::Table training_kb
   |     PK(S) HASH + SK(S) RANGE，PAY_PER_REQUEST
   |     GSI by_target：target(S) HASH，無排序鍵，KEYS_ONLY
   +-- AWS::S3::Bucket（名稱由 CDK 產生，確保全域唯一）
   |     BlockPublicAccess=BLOCK_ALL、S3_MANAGED 加密、enforce_ssl
   +-- AWS::IAM::Role + AWS::IAM::Policy（資料角色）
         dynamodb：只在表 ARN 與 index ARN 上
         s3 物件動作：只在四個私有前綴的物件 ARN 上
         s3:ListBucket：在 bucket ARN 上，用 s3:prefix 條件限定同四個前綴
```

`by_target` 用 `KEYS_ONLY` 是設計 §9.1 的「先投影查詢需要的鍵，完整資料回基表取得」；這也是 Phase 08 `query_by_target` 只當候選的原因。

IAM 動作清單固定為 `GetItem`、`BatchGetItem`、`Query`、`Scan`、`PutItem`、`UpdateItem`、`ConditionCheckItem`，刻意不含 `DeleteItem`：本案沒有刪除業務資料的流程。之後的交易寫入（Phase 24 publish）是由 `PutItem`／`UpdateItem`／`ConditionCheckItem` 這些 item 層級動作授權；若實際部署後仍被拒絕，記錄真實錯誤訊息再補上最小動作，**不得**改成 `dynamodb:*`。

S3 這邊除了 `GetObject`／`PutObject`，還要一個 `s3:ListBucket`。原因是 [Phase 07](./07-Phase07-S3物件與關係邊讀寫.md) 的 `get_object` 對不存在的 key 要回 `None`：真實 S3 對**沒有列出權限**的呼叫者，一律把「不存在」回成 `403 AccessDenied` 而不是 `404 NoSuchKey`，那條「讀不到就回 None」的分支在雲端就會變成錯誤。`ListBucket` 是**bucket 層級**動作，所以資源必須是 bucket ARN（不是 `bucket-arn/*`），再用 `s3:prefix` 條件把可列出的範圍限定在同樣那四個私有前綴，避免一次放行整個 bucket（00A §3.8、§6.11）。

`enforce_ssl=True` 會自動產生一段 `AWS::S3::BucketPolicy`，形狀固定如下；它是**額外限制**而不是授權，所以「不能有萬用字元」的測試只掃 `AWS::IAM::Policy`，不掃 bucket policy：

```text
AWS::IAM::Policy（資料角色）  <- 測試掃這一塊     AWS::S3::BucketPolicy  <- 測試跳過
  Effect  : Allow                                  Effect   : Deny
  Action  : 7 個 dynamodb 動作                     Action   : "s3:*"（方向相反）
            + s3:GetObject / s3:PutObject          Condition: aws:SecureTransport = false
            + s3:ListBucket（帶 s3:prefix 條件）   Resource : bucket ARN 與 bucket ARN/*
  Resource: 表 ARN / index ARN / 四個私有前綴
            / bucket ARN（ListBucket 專用）
```

把 Deny 的 `s3:*` 當成違規會逼人關掉 `enforce_ssl`，反而放寬安全性，所以測試挑資源型別、不挑字串，並在註解寫明原因。

**與 [Phase 57](57-Phase57-S3靜態教學站與回饋下載.md) 的銜接（不得在本 Phase 自行動手）：** S3 website endpoint 只有 HTTP（設計 §13、§17.1），`enforce_ssl=True` 卻會 `Deny` 所有非 TLS 請求。設計 §9.3 只有一個 bucket，所以 Phase 57 會把 website hosting 與 `site/*` 公開 policy 加在**同一個** bucket 上，屆時由它以「修改本 Phase 的 CDK」把 `enforce_ssl` 改成 `False` 並寫明理由（私有前綴仍靠 IAM 與 block public access 保護，SDK 存取本身走 HTTPS）。**本 Phase 一律維持 `enforce_ssl=True` 與全私有，不得為了讓頁面看得到就先關掉它或開放公開讀取。**

`removal_policy` 用 `RETAIN`，`cdk destroy` 不會順手刪掉教學內容；Demo 結束的清理由維護者另外執行。表名固定為 `training_kb`，同一帳號同一 Region 只能有一份，要跑第二套環境請換 Region 或帳號。

## 7. TDD Tasks

### Task 1：用 Template 鎖定單表與唯一 GSI

- [x] **Step 1：建立失敗測試**

`infra/` 不是 `src/` 底下的安裝套件，pytest 也不會把專案根目錄放進 `sys.path`，
所以測試檔開頭要先把專案根目錄插進路徑（同 `tests/unit/test_check_models.py` 的既有作法），
才 import `infra.*`；`# noqa: E402` 也沿用同一份慣例。

```python
import sys
from pathlib import Path

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infra.training_kb_data_stack import TrainingKbDataStack  # noqa: E402


def synth() -> Template:
    return Template.from_stack(TrainingKbDataStack(cdk.App(), "TrainingKbData"))


def test_exactly_one_table_with_one_index() -> None:
    template = synth()
    template.resource_count_is("AWS::DynamoDB::Table", 1)
    template.has_resource_properties("AWS::DynamoDB::Table", Match.object_like({
        "TableName": "training_kb",
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"},
                      {"AttributeName": "SK", "KeyType": "RANGE"}],
        "GlobalSecondaryIndexes": [Match.object_like({
            "IndexName": "by_target",
            "KeySchema": [{"AttributeName": "target", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "KEYS_ONLY"},
        })],
    }))
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_data_stack.py -q
```

預期：FAIL，訊號包含 `No module named 'infra.training_kb_data_stack'`。

- [x] **Step 3：建立最小實作**

```python
from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

TABLE_NAME = "training_kb"
TARGET_INDEX = "by_target"


class TrainingKbDataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)
        text = dynamodb.AttributeType.STRING
        self.table = dynamodb.Table(
            self, "TrainingKbTable",
            table_name=TABLE_NAME,
            partition_key=dynamodb.Attribute(name="PK", type=text),
            sort_key=dynamodb.Attribute(name="SK", type=text),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.table.add_global_secondary_index(
            index_name=TARGET_INDEX,
            partition_key=dynamodb.Attribute(name="target", type=text),
            projection_type=dynamodb.ProjectionType.KEYS_ONLY,
        )
        CfnOutput(self, "TrainingKbTableName", value=self.table.table_name)
```

- [x] **Step 4：補「不能多出東西」的測試並跑綠燈**

```python
import pytest

FORBIDDEN = ["AWS::RDS::DBInstance", "AWS::OpenSearchService::Domain",
             "AWS::Neptune::DBCluster", "AWS::Lambda::Function",
             "AWS::StepFunctions::StateMachine", "AWS::CloudFront::Distribution"]


@pytest.mark.parametrize("resource_type", FORBIDDEN)
def test_no_extra_datastore_or_pipeline_is_declared(resource_type: str) -> None:
    synth().resource_count_is(resource_type, 0)
```

這六個型別對應設計 §2、§3 明確排除的服務與「本 Phase 只建資料資源」的上限；Lambda 與 state machine 屬於 [Phase 41](41-Phase41-Ticket-Analysis雲端流程驗收.md) 的另一個 stack。

```bash
uv run pytest tests/unit/test_data_stack.py -q
```

預期：全部 PASS。

- [x] **Step 5：提交**

```bash
git add infra/training_kb_data_stack.py tests/unit/test_data_stack.py
git commit -m "feat(infra): 建立單表與 by_target 索引"
```

（`pyproject.toml` 不在這一批：相依早已存在，本 Phase 不改它，也不改 `uv.lock`。）

### Task 2：私有 bucket 與最小資料角色

- [x] **Step 1：建立失敗測試並確認紅燈**

```python
import json


def test_bucket_blocks_all_public_access() -> None:
    template = synth()
    template.resource_count_is("AWS::S3::Bucket", 1)
    template.has_resource_properties("AWS::S3::Bucket", Match.object_like({
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        },
    }))


def test_data_role_has_no_wildcard_action_or_resource() -> None:
    # 只檢查 IAM Policy；enforce_ssl 產生的 bucket policy 是 Deny s3:*，屬於額外限制。
    for policy in synth().find_resources("AWS::IAM::Policy").values():
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            actions = statement["Action"]
            for action in actions if isinstance(actions, list) else [actions]:
                assert action != "*" and not action.endswith(":*")
            assert '"*"' not in json.dumps(statement["Resource"])
```

```bash
uv run pytest tests/unit/test_data_stack.py -q -k "bucket or wildcard"
```

- [x] **Step 2：在同一個 `__init__` 續寫最小實作**

```python
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3

PRIVATE_PREFIXES = ("tutorials/", "operations/", "stepfunctions/", "demo/previews/")

self.bucket = s3.Bucket(
    self, "TrainingKbContent",
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
    encryption=s3.BucketEncryption.S3_MANAGED,
    enforce_ssl=True,
    removal_policy=RemovalPolicy.RETAIN,
)
role = iam.Role(self, "TrainingKbDataRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
role.add_to_policy(iam.PolicyStatement(
    actions=[
        "dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:Scan",
        "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem",
    ],
    resources=[self.table.table_arn, f"{self.table.table_arn}/index/{TARGET_INDEX}"],
))
role.add_to_policy(iam.PolicyStatement(
    actions=["s3:GetObject", "s3:PutObject"],
    resources=[f"{self.bucket.bucket_arn}/{prefix}*" for prefix in PRIVATE_PREFIXES],
))
role.add_to_policy(iam.PolicyStatement(
    # ListBucket 是 bucket 層級動作，資源必須是 bucket ARN；沒有它，真實 S3 會把
    # 「key 不存在」回成 403 而不是 404，Phase 07 的 get_object -> None 就不成立。
    actions=["s3:ListBucket"],
    resources=[self.bucket.bucket_arn],
    conditions={"StringLike": {"s3:prefix": [f"{prefix}*" for prefix in PRIVATE_PREFIXES]}},
))
self.data_role = role
```

- [x] **Step 3：補前綴與輸出測試，跑綠燈後提交**

```python
from infra.training_kb_data_stack import PRIVATE_PREFIXES


def test_s3_statement_covers_every_private_prefix_and_never_site() -> None:
    statements = [
        statement
        for policy in synth().find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if "s3:GetObject" in statement["Action"]
    ]
    assert len(statements) == 1
    rendered = json.dumps(statements[0]["Resource"])
    assert len(statements[0]["Resource"]) == len(PRIVATE_PREFIXES) == 4
    for prefix in PRIVATE_PREFIXES:
        assert f"/{prefix}*" in rendered
    assert "site/" not in rendered


def test_list_bucket_is_limited_to_the_private_prefixes() -> None:
    statements = [
        statement
        for policy in synth().find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if "s3:ListBucket" in statement["Action"]
    ]
    assert len(statements) == 1
    prefixes = statements[0]["Condition"]["StringLike"]["s3:prefix"]
    assert prefixes == [f"{prefix}*" for prefix in PRIVATE_PREFIXES]
    assert "site/" not in json.dumps(prefixes)


def test_outputs_expose_the_three_names() -> None:
    assert set(synth().find_outputs("*")) == {
        "TrainingKbTableName", "TrainingKbBucketName", "TrainingKbDataRoleArn"}
```

`"s3:ListBucket" in statement["Action"]` 對兩種形狀都成立：CDK 只有一個動作時會把 `Action` 算成字串，多個動作才是 list，`in` 剛好都涵蓋。`s3:prefix` 條件沒了或多出 `site/`，這條就會紅。

實作端補上另外兩個輸出（`TrainingKbTableName` 已在 Task 1 建立）：

```python
CfnOutput(self, "TrainingKbBucketName", value=self.bucket.bucket_name)
CfnOutput(self, "TrainingKbDataRoleArn", value=role.role_arn)
```

```bash
uv run pytest tests/unit/test_data_stack.py -q
uv run ruff check infra tests/unit/test_data_stack.py
```

預期：全部 PASS，ruff 沒有告警。

- [x] **Step 4：提交**

```bash
git add infra/training_kb_data_stack.py tests/unit/test_data_stack.py
git commit -m "feat(infra): 私有 bucket 與最小資料角色"
```

### Task 3：bootstrap、synth 與實際部署核對

- [x] **Step 1：準備 CLI 與 app 進入點，只在本機 synth**

CDK CLI 是 Node.js 套件，不能用 `uv run` 執行；Python 端只需要 `aws-cdk-lib`。`cdk.json` 放在專案根目錄並寫 `{"app": "uv run python -m infra.app"}`，這樣 CLI 用本專案環境產生 template，`infra` 套件也 import 得到。以下指令都在專案根目錄執行。

```bash
command npx aws-cdk@2 --version
command npx aws-cdk@2 synth TrainingKbData
```

本機 shell 把 `node` 定義成會拒絕的 shell function（見共用規則），所以 CDK CLI 一律走
`command npx aws-cdk@2 <子命令>`；仍然**不加** `uv run`（00A §3.1、D-22）。

預期：終端印出 YAML，`cdk.out/TrainingKbData.template.json` 出現。這一步不碰雲端，失敗代表程式錯誤而不是權限問題。

- [x] **Step 2：bootstrap 與部署**

```bash
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 \
  command npx aws-cdk@2 bootstrap aws://<account-id>/us-east-1
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 \
  command npx aws-cdk@2 deploy TrainingKbData --require-approval never \
  --outputs-file <專案外的暫存路徑>/cdk-outputs.json
```

**Region 裁決：`us-east-1`**（與 Bedrock 同區，全案只用一個 region）。`infra/app.py` 以
`TKB_AWS_REGION` 覆寫、預設 `us-east-1`（00A §3.5 的既有變數，不新增變數名）。

`--require-approval never` 是因為這裡以非互動方式執行：IAM 變更在 `cdk synth` 的 template
與本檔第 6 節已經逐條寫明，且單元測試已鎖住「不得有萬用字元」。`--outputs-file` 產生的
`cdk-outputs.json` **不進版本庫**（寫到專案外的暫存路徑；實際值抄進驗收記錄即可）。

預期：bootstrap 建立 `CDKToolkit` stack 並回報環境已 bootstrapped；deploy 完成後印出三個 `Outputs`。沒有帳號或權限時停在這裡，把結果寫成 `BLOCKED`，保留錯誤訊息與時間。

- [x] **Step 3：用 AWS CLI 核對實際資源**

`TKB_CONTENT_BUCKET` 取自 `TrainingKbBucketName` 輸出；`DATA_ROLE_NAME` 只是本機 shell 變數，取 `TrainingKbDataRoleArn` 最後一段（不新增 `TKB_` 環境變數）。

```bash
aws dynamodb describe-table --table-name training_kb --region us-east-1 \
  --query "Table.{keys:KeySchema,gsi:GlobalSecondaryIndexes[].IndexName}"
aws s3api get-public-access-block --bucket "$TKB_CONTENT_BUCKET" --region us-east-1
aws s3api get-bucket-policy --bucket "$TKB_CONTENT_BUCKET" --region us-east-1
aws iam list-role-policies --role-name "$DATA_ROLE_NAME"
aws iam list-attached-role-policies --role-name "$DATA_ROLE_NAME"
```

預期：索引清單長度為 1；四個 public access block 皆為 `true`；bucket policy 只有 `enforce_ssl`
產生的那一條 `Deny`（沒有任何公開 `Allow`）；角色只有 stack 產生的那一份 inline policy、沒有
attached managed policy。把輸出（去掉帳號 ID）貼進下面的驗收記錄，再
`git commit -m "chore(infra): 記錄資料資源部署步驟"`。

#### 實際驗收記錄（2026-09-14，帳號 123456789012，region us-east-1）

| 項目 | 實際結果 |
|---|---|
| CloudFormation | `CDKToolkit` bootstrap 成功；`TrainingKbData` → `CREATE_COMPLETE`（deploy 60.07s） |
| `TrainingKbTableName` | `training_kb` |
| `TrainingKbBucketName` | `training-kb-content-example` |
| `TrainingKbDataRoleArn` | `arn:aws:iam::123456789012:role/TrainingKbData-TrainingKbDataRoleB75DED38-4EUcpdGUDCov` |
| `describe-table` | `TableStatus=ACTIVE`、`PAY_PER_REQUEST`、`KeySchema=[PK(HASH), SK(RANGE)]`、`GlobalSecondaryIndexes` **長度 1**：`by_target` / `target(HASH)` / `KEYS_ONLY` |
| `get-public-access-block` | `BlockPublicAcls`、`IgnorePublicAcls`、`BlockPublicPolicy`、`RestrictPublicBuckets` 皆 `true` |
| `get-bucket-policy` | 只有一條 `Effect: Deny`、`Action: s3:*`、`Condition: aws:SecureTransport=false`（即 `enforce_ssl`），**沒有任何公開 Allow** |
| `list-role-policies` | 只有 `TrainingKbDataRoleDefaultPolicyF791892E`；`list-attached-role-policies` 為空 |
| inline policy 內容 | 三條 statement：7 個 dynamodb 動作（表 ARN ＋ `index/by_target`，**無 `DeleteItem`**）、`s3:GetObject`／`PutObject` 於四個私有前綴、`s3:ListBucket` 於 **bucket ARN** 並帶 `StringLike: s3:prefix = [tutorials/*, operations/*, stepfunctions/*, demo/previews/*]`；沒有任何 `*` 動作或 `*` 資源 |

`.env` 可據此填：`TKB_TABLE_NAME=training_kb`、
`TKB_CONTENT_BUCKET=training-kb-content-example`、`TKB_AWS_REGION=us-east-1`。

**資源已建立不等於 gate 通過**：O2、O3、O5 與 Repository 在真實 AWS 的行為仍由後續 Phase 驗證；本節只證明資源存在且形狀正確。費用未在此確認，不得宣稱免費。

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | `cdk synth` | template 只有 1 表、1 bucket、1 角色與其 policy。 |
| Happy | `describe-table` | `GlobalSecondaryIndexes` 長度為 1 且名稱是 `by_target`。 |
| Failure | 有人再加一個 GSI | `test_exactly_one_table_with_one_index` FAIL。 |
| Failure | policy 出現 `dynamodb:*` 或 `Resource: "*"` | 萬用字元測試 FAIL，停止部署，不放寬。 |
| Failure | bucket 開放公開讀取 | public access block 測試 FAIL。 |
| Boundary | `enforce_ssl=True` 產生的 bucket policy 帶 `Deny` 的 `s3:*` | 萬用字元測試**不得**因此 FAIL；它只掃 `AWS::IAM::Policy`。 |
| Boundary | 有人把 `demo/previews/` 從 `PRIVATE_PREFIXES` 拿掉 | 前綴測試 FAIL（`len(Resource) == 4`），[Phase 58](58-Phase58-Demo控制台與規則開關預覽.md) 的預覽將無法寫入。 |
| Boundary | `s3:ListBucket` 少了 `s3:prefix` 條件，或條件含 `site/` | `test_list_bucket_is_limited_to_the_private_prefixes` FAIL；不得為了方便改成整個 bucket 可列出。 |
| Boundary | 沒有 AWS 帳號；執行 `cdk destroy` | 單元測試仍可全綠、Task 3 標 `BLOCKED`；表與 bucket 因 `RETAIN` 保留，需維護者明確刪除。 |

人工驗收：在 AWS Console 開啟表與 bucket，確認沒有第二個索引、沒有公開存取；再由另一位維護者讀 template 的 IAM 區塊，逐條說明每個動作為什麼需要。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| `uv run cdk` 找不到指令 | 把 Node CLI 當成 Python 套件 | 用 `npm install -g aws-cdk@2` 或 `npx aws-cdk@2`。 |
| deploy 說需要 bootstrap | 該環境還沒 bootstrap | 先 `cdk bootstrap aws://<account>/<region>`。 |
| 用 `grant_read_write_data` 交差 | 一次授出含刪除的整組權限 | 改回明列動作，或說明為何需要刪除。 |
| 為了 `TransactWriteItems` 加 `dynamodb:*` | 猜測授權模型 | 保留實際錯誤訊息，只補最小動作（交易由 `PutItem`／`UpdateItem`／`ConditionCheckItem` 授權，沒有 `dynamodb:TransactWriteItems` 這個 IAM 動作）。 |
| 萬用字元測試 FAIL，指向 bucket policy 的 `s3:*` | 測試掃到 `enforce_ssl` 產生的 `Deny` | 測試只掃 `AWS::IAM::Policy`；**不要**為了綠燈關掉 `enforce_ssl`。 |
| `get_object` 對不存在的 key 收到 403 而不是 404 | `s3:ListBucket` 那條 statement 被拿掉，或資源誤寫成 `bucket-arn/*` | 它必須在 **bucket ARN**（不是物件 ARN）上，並保留 `s3:prefix` 條件；先保留真實錯誤訊息再修，不改成 `s3:*`、也不拿掉條件。 |
| 直接把 bucket 設公開 | 想先看到頁面 | 停止；公開只限 `site/`，由 Phase 57 決定。 |
| 把 `enforce_ssl` 關掉讓 website endpoint 通 | 提前替 Phase 57 做決定 | 停止；本 Phase 只記錄這個銜接問題，由 Phase 57 選「另開 site bucket」或明確調整設定。 |
| 部署成功就說 O2/O3 通過 | 混淆資源與行為 | 只記「資源已建立」，gate 仍待整合驗證。 |

## 10. 來源與 Rule 對照

- 設計 §9.1：表名 `training_kb`、主鍵 `PK, SK`、唯一 GSI `by_target` 不加排序鍵、只投影需要的鍵；實際 bucket 名稱須符合全域唯一要求。
- 設計 §9.3、§13、§17.2：`tutorials/`、`operations/`、`stepfunctions/`、`demo/previews/` 為私有，只有 `site/` 公開；S3 website 只有 HTTP，本 Phase 不開公開存取；執行角色只授權需要的表、路徑與流程。
- [00A 共用契約與名詞](00A-共用契約與名詞.md) §3.8、§6.11：`s3:ListBucket` 以 `s3:prefix` 限定四個私有前綴；`enforce_ssl` 由 Phase 09 先設 `True`、Phase 57 明確改為 `False` 並說明理由。
- [查詢知識圖譜.feature](../../spec/features/查詢知識圖譜.feature)
  - GPH Rule 2：「查詢誰引用 Feature 時使用 by_target 的 target」→ **相關（primary 在 [Phase 08](08-Phase08-分頁查詢與一致讀取基礎.md)）**；本 Phase 只負責讓這個索引存在且只有一個。
- [發布教學版本.feature](../../spec/features/發布教學版本.feature)
  - PUB Rule 2：「發布的教學透過 S3 靜態 docs 站提供」→ **相關（primary 在 [Phase 57](57-Phase57-S3靜態教學站與回饋下載.md)）**；本 Phase 只建立 bucket 並維持它全私有，不做 website hosting 與公開 policy。
- 本 Phase 沒有 147 Rule 的 primary ownership（見 [00B 需求覆蓋對照](00B-需求覆蓋對照.md)）；它是 VER、GPH、PUB 系列在真實 AWS 上的前置條件。
- [CDK DynamoDB Table（Python）](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_dynamodb/README.html)：`Attribute`、`AttributeType`、`BillingMode`、`add_global_secondary_index`；[CDK S3 Bucket（Python）](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_s3/README.html)：`BlockPublicAccess.BLOCK_ALL`、`BucketEncryption`、`enforce_ssl`。
- [CDK assertions（Python）](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.assertions/README.html)：`Template.from_stack`、`has_resource_properties`、`resource_count_is`、`find_resources`、`Match`。
- [CDK bootstrapping](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html)：每個帳號＋Region 需要一次 bootstrap。

## 11. 完成清單

- [x] O1 已核定（accepted 或 rejected 皆可），表的 `PK`／`SK` 與 metadata 鍵一致。
- [x] template 只有一張表、一個 `by_target`、一個 bucket 與一個資料角色，六個禁用資源型別各為 0。
- [x] bucket 四項 public access block 全為 `true`，沒有公開 policy。
- [x] IAM 沒有任何 `*` 動作或 `*` 資源，S3 物件動作只授權四個私有前綴（含 `demo/previews/`）且不含 `site/`。
- [x] `s3:ListBucket` 在 bucket ARN 上，且 `s3:prefix` 條件只列同樣那四個私有前綴（讓 Phase 07 的 `get_object -> None` 在真實 S3 也成立）。
- [x] 環境變數名為 `TKB_TABLE_NAME`／`TKB_CONTENT_BUCKET`／`TKB_AWS_REGION`，三個 `CfnOutput` 齊全。
- [x] `cdk synth` 可在沒有帳號的機器上執行（指令不加 `uv run`），`tests/unit/test_data_stack.py` 全綠。
- [x] 部署與 CLI 核對輸出已保存，或明確標記 `BLOCKED`。
- [x] `enforce_ssl` 維持 `True`，與 Phase 57 website endpoint 的銜接（由 Phase 57 改成 `False` 並說明理由）已寫進交接說明，未在本 Phase 自行放寬。
- [x] 文件沒有把「資源已建立」寫成 O2、O3、O5 已通過或費用已確定。
