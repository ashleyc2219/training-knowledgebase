"""Phase 57 Task 4：靜態站 hosting 與**只公開 `site/*`** 的 bucket policy（CDK Template）。

公開範圍是本 Phase 的停止條件（設計 §9.3、§13、COMMON.md R11）：

```text
可公開讀     site/*                       <- 唯一一條 Allow，Principal 是 "*"
不可公開讀   tutorials/  operations/       <- 完全沒有 Allow 語句
             stepfunctions/  demo/previews/
```

官方的 S3 static website 範例把 `Resource` 寫成整桶 `<bucket>/*`，本案刻意縮到 `site/*`；
`enforce_ssl` 必須關掉，因為 S3 website endpoint **只提供 HTTP**（設計 §17.1），
`enforce_ssl=True` 會加一段「非 HTTPS 一律 Deny」讓公開頁永遠讀不到。

**`cdk synth` 通過只代表 template 合法，不代表已部署，更不代表 O3 通過**（O3 現況 FAIL）。
真實部署與 website endpoint 的 HTTP 證據在報告 §4。
"""

import json
import sys
from pathlib import Path

import aws_cdk as cdk
from aws_cdk.assertions import Template

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


def test_bucket_policy_only_opens_the_site_prefix() -> None:
    """Given 部署後的 bucket／When 讀 bucket policy／Then 只有一條 `site/*` 的 Allow。"""
    template = synth()
    policies = list(template.find_resources("AWS::S3::BucketPolicy").values())
    assert len(policies) == 1
    statements = policies[0]["Properties"]["PolicyDocument"]["Statement"]
    assert len(statements) == 1
    only = statements[0]
    assert only["Effect"] == "Allow"
    assert only["Principal"] == {"AWS": "*"}
    assert only["Action"] in ("s3:GetObject", ["s3:GetObject"])
    rendered = json.dumps(only["Resource"])
    assert f"/{PUBLISH_PREFIX}*" in rendered
    assert rendered.count("Fn::Join") <= 1


def test_no_private_prefix_is_publicly_readable() -> None:
    """Given bucket policy／When 找私有前綴／Then 一個字都不在裡面（R11 的停止條件）。"""
    policies = json.dumps(list(synth().find_resources("AWS::S3::BucketPolicy").values()))
    for prefix in PRIVATE_PREFIXES:
        assert prefix not in policies
    assert '"/*"' not in policies


def test_enforce_ssl_is_off_because_website_endpoints_are_http_only() -> None:
    """Given website hosting／When 掃整份 template／Then 沒有 `aws:SecureTransport` 的 Deny。

    設計 §17.1：S3 website endpoint 只提供 HTTP。留著那段 Deny 會讓公開頁永遠讀不到。
    關掉它不會讓私有前綴變公開——它們沒有任何 Allow 語句，而程式與 Lambda 走的是
    SDK 的 HTTPS 端點。**不得因此宣稱本站提供 HTTPS。**
    """
    assert "aws:SecureTransport" not in json.dumps(synth().to_json())


def test_website_hosting_is_enabled_without_public_acls() -> None:
    """Given bucket／When 讀屬性／Then 有 website 設定，而且 ACL 那兩道保險仍然開著。

    只放寬 `BlockPublicPolicy`／`RestrictPublicBuckets`（policy 要生效就得放寬這兩項），
    `BlockPublicAcls`／`IgnorePublicAcls` 維持 `True`：本案**永遠不用 ACL** 公開任何物件，
    `Repository.put_object` 也沒有送 `ACL` 參數（00A §3.8）。
    """
    bucket = list(synth().find_resources("AWS::S3::Bucket").values())[0]["Properties"]
    assert bucket["WebsiteConfiguration"] == {"IndexDocument": "index.html",
                                              "ErrorDocument": "index.html"}
    assert bucket["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True, "IgnorePublicAcls": True,
        "BlockPublicPolicy": False, "RestrictPublicBuckets": False}


def test_the_data_role_can_write_the_site_prefix() -> None:
    """Given 資料角色／When 找 `site/` 的語句／Then 有獨立一條、只有兩個動作。

    `promote_site_objects` 要 `PutObject` 才寫得進 `site/`，`_put_public_object` 還會先
    `GetObject` 比對既有 bytes（REP §8 第 6 項；沒有這一條，真實 AWS 上發布會 403）。
    刻意**不**把 `site/` 塞進 `PRIVATE_PREFIXES`：那個名字就叫 private，混進去會讓
    `test_s3_statement_covers_every_private_prefix_and_never_site` 的語意壞掉。
    """
    statements = [
        statement
        for policy in synth().find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if f"/{PUBLISH_PREFIX}*" in json.dumps(statement.get("Resource"))
    ]
    assert len(statements) == 1
    assert sorted(statements[0]["Action"]) == ["s3:GetObject", "s3:PutObject"]
    assert len(statements[0]["Resource"]) == 1


def test_list_bucket_covers_the_publish_prefix_but_never_the_whole_bucket() -> None:
    """Given 資料角色的 `ListBucket`／When 讀條件／Then 含 `site/*`，而且沒有裸 `*`。

    真實 S3 要有 `s3:ListBucket` 才會把「key 不存在」回成 404 而不是 403，
    `Repository.get_object` 的「不存在回 `None`」契約才成立（00A §3.8）。
    """
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


def test_the_website_url_is_an_output() -> None:
    """Given 部署／When 讀 outputs／Then 多了 website URL 一項（人工驗收要用它）。"""
    outputs = synth().find_outputs("*")
    assert "TrainingKbSiteUrl" in outputs
    assert "HTTP" in outputs["TrainingKbSiteUrl"]["Description"]
