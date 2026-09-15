"""唯一的資料 stack：DynamoDB 單表、唯一的 by_target 索引、私有內容 bucket 與最小資料角色。"""

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct

TABLE_NAME = "training_kb"
TARGET_INDEX = "by_target"
PRIVATE_PREFIXES = ("tutorials/", "operations/", "stepfunctions/", "demo/previews/")

PUBLISH_PREFIX = "site/"
"""唯一可公開讀的前綴（＝`training_kb.content.PUBLIC_SITE_PREFIX`，Phase 57 加）。

**刻意不塞進 `PRIVATE_PREFIXES`**：那個 tuple 的意思是「不得公開讀」，混進去會讓
`test_s3_statement_covers_every_private_prefix_and_never_site` 這種斷言失去意義。
`infra/` 不 import `src/training_kb`（CDK 程式不在安裝套件裡），所以值在兩邊各寫一次，
由 `tests/unit/test_infra_site_hosting.py` 與 `test_data_stack.py` 守住一致。"""

SITE_INDEX_DOCUMENT = "index.html"
"""website hosting 的索引文件；錯誤文件也用同一份（站台索引就是最合理的落點）。"""


class TrainingKbDataStack(Stack):
    """唯一的資料 stack；屬性 table、bucket、data_role 供後續 stack 引用。"""

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
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
        self.bucket = s3.Bucket(
            self, "TrainingKbContent",
            # Phase 57：只放寬 policy 那兩道保險，ACL 那兩道維持開著——本案永遠不用 ACL
            # 公開物件（`Repository.put_object` 沒有送 `ACL` 參數，00A §3.8），公開與否
            # 一律由下面那條只涵蓋 `site/*` 的 bucket policy 決定。
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=True, ignore_public_acls=True,
                block_public_policy=False, restrict_public_buckets=False,
            ),
            encryption=s3.BucketEncryption.S3_MANAGED,
            # `enforce_ssl=True` 會加一段「非 HTTPS 一律 Deny」的 bucket policy，而 S3
            # website endpoint **只提供 HTTP**（設計 §17.1），兩者並存時公開頁永遠讀不到。
            # 關掉它不會讓私有前綴變公開：`tutorials/`、`operations/`、`stepfunctions/`、
            # `demo/previews/` 沒有任何 Allow 語句，只有 `site/*` 有；程式與 Lambda 透過
            # SDK 存取本來就走 HTTPS。**不得因此宣稱本站提供 HTTPS。**
            enforce_ssl=False,
            website_index_document=SITE_INDEX_DOCUMENT,
            website_error_document=SITE_INDEX_DOCUMENT,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.bucket.add_to_resource_policy(iam.PolicyStatement(
            # 官方 static website 範例的 Resource 是整桶 `<bucket>/*`，本案刻意縮到
            # `site/*`：發布流程以外的一切（含未發布全文與操作紀錄）都不得公開讀
            # （設計 §9.3、§13；COMMON.md R11 的停止條件）。
            effect=iam.Effect.ALLOW,
            principals=[iam.AnyPrincipal()],
            actions=["s3:GetObject"],
            resources=[self.bucket.arn_for_objects(f"{PUBLISH_PREFIX}*")],
        ))
        role = iam.Role(
            self, "TrainingKbDataRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        role.add_to_policy(iam.PolicyStatement(
            # 刻意不含 DeleteItem：本案沒有刪除業務資料的流程。交易寫入由
            # PutItem／UpdateItem／ConditionCheckItem 授權。
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
            # Phase 57：公開前綴的寫入權限。`promote_site_objects` 要 PutObject 才寫得進
            # `site/`，`_put_public_object` 還會先 GetObject 比對既有 bytes；沒有這一條，
            # 真實 AWS 上的發布會在 promote 那一步 403（REP §8 第 6 項）。獨立一條而不是
            # 併進上面那條：上面那條的語意是「私有前綴」，混在一起就看不出公開範圍。
            actions=["s3:GetObject", "s3:PutObject"],
            resources=[self.bucket.arn_for_objects(f"{PUBLISH_PREFIX}*")],
        ))
        role.add_to_policy(iam.PolicyStatement(
            # ListBucket 是 bucket 層級動作，資源必須是 bucket ARN；沒有它，真實 S3 會把
            # 「key 不存在」回成 403 而不是 404，Phase 07 的 get_object -> None 就不成立。
            # Phase 57 把 `site/` 一起納入：公開頁的條件寫入也要分得出 404 與 403。
            actions=["s3:ListBucket"],
            resources=[self.bucket.bucket_arn],
            conditions={"StringLike": {"s3:prefix": [
                f"{prefix}*" for prefix in (*PRIVATE_PREFIXES, PUBLISH_PREFIX)]}},
        ))
        self.data_role = role
        CfnOutput(self, "TrainingKbTableName", value=self.table.table_name)
        CfnOutput(self, "TrainingKbBucketName", value=self.bucket.bucket_name)
        CfnOutput(self, "TrainingKbDataRoleArn", value=role.role_arn)
        CfnOutput(self, "TrainingKbSiteUrl", value=self.bucket.bucket_website_url,
                  description="公開教學站（S3 website endpoint，只有 HTTP，不提供 HTTPS）")
