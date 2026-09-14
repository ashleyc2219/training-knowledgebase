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
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
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
            # ListBucket 是 bucket 層級動作，資源必須是 bucket ARN；沒有它，真實 S3 會把
            # 「key 不存在」回成 403 而不是 404，Phase 07 的 get_object -> None 就不成立。
            actions=["s3:ListBucket"],
            resources=[self.bucket.bucket_arn],
            conditions={"StringLike": {"s3:prefix": [f"{prefix}*" for prefix in PRIVATE_PREFIXES]}},
        ))
        self.data_role = role
        CfnOutput(self, "TrainingKbTableName", value=self.table.table_name)
        CfnOutput(self, "TrainingKbBucketName", value=self.bucket.bucket_name)
        CfnOutput(self, "TrainingKbDataRoleArn", value=role.role_arn)
