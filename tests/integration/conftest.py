"""整合測試共用器材：moto 的本機 DynamoDB 表、本機 S3 bucket 與建在它們上面的 `Repository`。

`table` 用 `mock_aws` 攔截 boto3，不會碰到真實帳號；moto 的 PASS 只證明資料形狀，
不是實表／實 bucket 行為的證據（實體證據走 `@pytest.mark.aws` 的 smoke）。
`bucket` 刻意宣告依賴 `table`：兩者共用**同一個** `mock_aws` 區塊，不另外巢狀開一層攔截器，
所以同一個測試裡的 DynamoDB 與 S3 狀態一起建立、一起丟棄。
`by_target` GSI 由 Phase 08 補；metadata 與關係邊讀寫都不經 GSI，本 Phase 先不建。
"""

from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from training_kb.repository import Repository

TABLE_NAME = "training_kb"
BUCKET_NAME = "training-kb-content"
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
def bucket(table: object) -> object:  # noqa: ARG001 - 只為了共用 table 的 mock_aws 區塊
    """`table` 的 `mock_aws` 內建立的私有 bucket；不是 us-east-1 所以要帶 LocationConstraint。"""
    created = boto3.resource("s3", region_name=MOTO_REGION).Bucket(BUCKET_NAME)
    created.create(CreateBucketConfiguration={"LocationConstraint": MOTO_REGION})
    return created


@pytest.fixture
def repository(table: object, bucket: object) -> Repository:
    return Repository(table, bucket)
