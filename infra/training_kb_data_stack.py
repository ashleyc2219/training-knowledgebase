"""唯一的資料 stack：DynamoDB 單表、唯一的 by_target 索引、私有內容 bucket 與最小資料角色。"""

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

TABLE_NAME = "training_kb"
TARGET_INDEX = "by_target"


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
        CfnOutput(self, "TrainingKbTableName", value=self.table.table_name)
