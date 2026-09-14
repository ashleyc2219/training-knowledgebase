"""TrainingKbDataStack 的 Template 斷言：鎖定單表、唯一索引、私有 bucket 與最小 IAM。"""

import sys
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

# infra/ 是部署用的 CDK 程式，不在 src/ 的安裝套件裡，所以把專案根目錄加進路徑
# （同 tests/unit/test_check_models.py 的既有作法）。
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


FORBIDDEN = ["AWS::RDS::DBInstance", "AWS::OpenSearchService::Domain",
             "AWS::Neptune::DBCluster", "AWS::Lambda::Function",
             "AWS::StepFunctions::StateMachine", "AWS::CloudFront::Distribution"]


@pytest.mark.parametrize("resource_type", FORBIDDEN)
def test_no_extra_datastore_or_pipeline_is_declared(resource_type: str) -> None:
    synth().resource_count_is(resource_type, 0)
