"""整合測試共用器材：moto 的本機 DynamoDB 表與建在它上面的 `Repository`。

`table` 用 `mock_aws` 攔截 boto3，不會碰到真實帳號；moto 的 PASS 只證明資料形狀，
不是實表行為的證據（實表證據走 `@pytest.mark.aws` 的 smoke）。
`by_target` GSI 由 Phase 08 補、bucket 由 Phase 07 補；metadata 讀寫不經 GSI，本 Phase 先不建。
"""

from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from training_kb.repository import Repository

TABLE_NAME = "training_kb"
MOTO_REGION = "us-west-2"


@pytest.fixture
def table() -> Iterator[object]:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=MOTO_REGION)
        created = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        created.wait_until_exists()
        yield created


@pytest.fixture
def repository(table: object) -> Repository:
    return Repository(table)
