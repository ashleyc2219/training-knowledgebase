"""TrainingKbDataStack 的 Template 斷言：鎖定單表、唯一索引、私有 bucket 與最小 IAM。"""

import json
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

from infra.training_kb_data_stack import (  # noqa: E402
    PRIVATE_PREFIXES,
    PUBLISH_PREFIX,
    TrainingKbDataStack,
)


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


def test_bucket_blocks_public_acls_and_serves_the_static_site() -> None:
    # Phase 57 起 bucket 兼作靜態教學站：policy 那兩道 BPA 必須放寬公開讀才生效，
    # ACL 那兩道維持 True（本案永遠不用 ACL 公開物件）。公開範圍只有 site/*，
    # 由 tests/unit/test_infra_site_hosting.py 逐條斷言。
    template = synth()
    template.resource_count_is("AWS::S3::Bucket", 1)
    template.has_resource_properties("AWS::S3::Bucket", Match.object_like({
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": False,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": False,
        },
        "WebsiteConfiguration": {"IndexDocument": "index.html",
                                 "ErrorDocument": "index.html"},
    }))


def test_data_role_has_no_wildcard_action_or_resource() -> None:
    # 只檢查 IAM Policy；Phase 57 之後唯一的 bucket policy 是「site/* 可公開讀」那條
    # Allow（AWS::S3::BucketPolicy，不是 AWS::IAM::Policy），不在本條的掃描範圍。
    for policy in synth().find_resources("AWS::IAM::Policy").values():
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            actions = statement["Action"]
            for action in actions if isinstance(actions, list) else [actions]:
                assert action != "*" and not action.endswith(":*")
            assert '"*"' not in json.dumps(statement["Resource"])


def object_statements() -> list[dict[str, object]]:
    return [
        statement
        for policy in synth().find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if "s3:GetObject" in statement["Action"]
    ]


def test_s3_statement_covers_every_private_prefix_and_never_site() -> None:
    # Phase 57 把「私有前綴」與「公開前綴 site/」拆成兩條 statement，所以這裡先挑出
    # 不含 site/ 的那一條再斷言；site/ 那條由 test_site_prefix_has_its_own_statement 守。
    private = [statement for statement in object_statements()
               if PUBLISH_PREFIX not in json.dumps(statement["Resource"])]
    assert len(private) == 1
    resources = private[0]["Resource"]
    assert isinstance(resources, list)
    rendered = json.dumps(resources)
    assert len(resources) == len(PRIVATE_PREFIXES) == 4
    for prefix in PRIVATE_PREFIXES:
        assert f"/{prefix}*" in rendered
    assert "site/" not in rendered


def test_site_prefix_has_its_own_statement() -> None:
    # Phase 57：資料角色要寫得進 site/（promote_site_objects），但只有這一條、只有兩個動作。
    public = [statement for statement in object_statements()
              if PUBLISH_PREFIX in json.dumps(statement["Resource"])]
    assert len(public) == 1
    assert sorted(public[0]["Action"]) == ["s3:GetObject", "s3:PutObject"]
    assert json.dumps(public[0]["Resource"]).count(f"/{PUBLISH_PREFIX}*") == 1


def test_list_bucket_is_limited_to_the_declared_prefixes() -> None:
    # Phase 57 起 site/ 也要能 List（條件寫入要分得出 404 與 403），但仍然不得整桶 List。
    statements = [
        statement
        for policy in synth().find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if "s3:ListBucket" in statement["Action"]
    ]
    assert len(statements) == 1
    prefixes = statements[0]["Condition"]["StringLike"]["s3:prefix"]
    assert prefixes == [f"{prefix}*" for prefix in (*PRIVATE_PREFIXES, PUBLISH_PREFIX)]
    assert "*" not in prefixes


def test_outputs_expose_the_four_names() -> None:
    # 第四個是 Phase 57 的 website endpoint（只有 HTTP），人工驗收要用它。
    assert set(synth().find_outputs("*")) == {
        "TrainingKbTableName", "TrainingKbBucketName", "TrainingKbDataRoleArn",
        "TrainingKbSiteUrl"}
