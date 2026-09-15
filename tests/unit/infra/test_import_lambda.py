"""Phase 42 Task 4：`training-kb-import` 在 `TrainingKbStack` 裡的接線與最小 IAM。

合成出來的 CloudFormation 樣板當字典查（CDK `Template`），所以這支測試不需要 AWS 憑證，
也不代表真的部署過——實機證據在 Phase 42 報告 §4 的 `aws lambda invoke` 原文。

守四件事（00A D-56、D-58、文件 §7 Task 4 Step 3）：

```text
名稱與 handler   training-kb-import / training_kb.handlers.import_.handler
沒有公開入口     全 stack 只有 Phase 30 的 webhook 有 AWS::Lambda::Url
最小 IAM         table／bucket 讀寫 ＋ ticket-analysis 的 states:StartExecution
沒有的東西       bedrock:InvokeModel、dynamodb:DeleteItem、release-update 的授權
```
"""

import json
import pathlib
import sys
from typing import Any

import pytest

from training_kb.content import PUBLIC_SITE_PREFIX
from training_kb.handlers.github_webhook import SECRET_ENV
from training_kb.handlers.import_ import IMPORT_DEADLINE_SECONDS
from training_kb.keys import OPERATIONS_PREFIX

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aws_cdk as cdk  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from infra.training_kb_data_stack import PRIVATE_PREFIXES, TARGET_INDEX  # noqa: E402
from infra.training_kb_stack import (  # noqa: E402
    CONTENT_BUCKET_CONTEXT,
    IMPORT_FUNCTION,
    IMPORT_HANDLER,
    LAYER_PATH,
    TICKET_ANALYSIS_MACHINE,
    TrainingKbStack,
)

BUCKET = "training-kb-content-example"
ACCOUNT, REGION = "111122223333", "us-east-1"
IMPORT_ROLE_PREFIX = "ImportFunctionServiceRole"


@pytest.fixture
def template(monkeypatch: pytest.MonkeyPatch) -> Template:
    """與 `test_ticket_asl.py` 同一種合成方式（純字串名稱接既有 table／bucket）。"""
    monkeypatch.setenv(SECRET_ENV, "unit-test-secret")
    (LAYER_PATH / "python").mkdir(parents=True, exist_ok=True)
    app = cdk.App(context={CONTENT_BUCKET_CONTEXT: BUCKET})
    stack = TrainingKbStack(app, "TrainingKbApp",
                            env=cdk.Environment(account=ACCOUNT, region=REGION))
    return Template.from_stack(stack)


def import_function(template: Template) -> dict[str, Any]:
    functions = [row for row in template.find_resources("AWS::Lambda::Function").values()
                 if row["Properties"]["FunctionName"] == IMPORT_FUNCTION]
    assert len(functions) == 1, f"{IMPORT_FUNCTION} 應該恰好一支"
    properties: dict[str, Any] = functions[0]["Properties"]
    return properties


def import_statements(template: Template) -> list[dict[str, Any]]:
    """只屬於匯入 Lambda 角色的 IAM 敘述；別支 Lambda 的授權不入選。"""
    return [statement
            for name, policy in template.find_resources("AWS::IAM::Policy").items()
            if name.startswith(IMPORT_ROLE_PREFIX)
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]]


def actions(statement: dict[str, Any]) -> list[str]:
    value = statement.get("Action", [])
    return value if isinstance(value, list) else [value]


def test_import_lambda_is_wired_with_the_fixed_name_and_handler(template: Template) -> None:
    """Given 合成結果／When 找 `training-kb-import`／Then 名稱與 handler 逐字相同（D-56）。"""
    template.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": IMPORT_FUNCTION, "Handler": IMPORT_HANDLER})
    assert IMPORT_HANDLER == "training_kb.handlers.import_.handler"


def test_import_lambda_shares_phase41_layer_and_environment(template: Template) -> None:
    """Given 匯入 Lambda／When 看 layer 與環境／Then 沿用 P41 的 layer 與 `base_env`（R2）。

    `Code.from_asset("src")` 只帶原始碼，`pydantic`／`jsonschema` 一定要從 layer 來；
    自己再做一支 layer 會讓同一份相依在帳號裡有兩個版本。
    """
    properties = import_function(template)
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)
    assert len(properties["Layers"]) == 1
    assert properties["Architectures"] == ["x86_64"] and properties["Runtime"] == "python3.12"
    variables = properties["Environment"]["Variables"]
    assert variables["TKB_CONTENT_BUCKET"] == BUCKET
    assert variables["TKB_TABLE_NAME"] == "training_kb"
    assert "TKB_GENERATION_MODEL_ID" not in variables   # O5 BLOCKED，不得填猜測值
    assert SECRET_ENV not in variables                  # 匯入沒有公開入口，不需要驗簽密鑰


def test_the_import_timeout_matches_the_deadline_constant(template: Template) -> None:
    """Given `IMPORT_DEADLINE_SECONDS`／When 看 Lambda 逾時／Then 兩個數字一致。"""
    assert import_function(template)["Timeout"] == int(IMPORT_DEADLINE_SECONDS) == 300


def test_only_the_webhook_has_a_function_url(template: Template) -> None:
    """Given 全 stack／When 數 `AWS::Lambda::Url`／Then 只有 Phase 30 的 webhook 有一個。

    匯入這支只給維護者用 boto3 `invoke` 呼叫；沒有公開入口就沒有驗簽需求。
    """
    template.resource_count_is("AWS::Lambda::Url", 1)
    urls = list(template.find_resources("AWS::Lambda::Url").values())
    target = json.dumps(urls[0]["Properties"]["TargetFunctionArn"])
    assert "WebhookFunction" in target and "ImportFunction" not in target


def test_the_import_role_can_start_only_ticket_analysis(template: Template) -> None:
    """Given 匯入角色／When 找 `states:StartExecution`／Then 只授權 ticket-analysis。

    `release` 分支要啟動的 `training-kb-release-update` 在 Phase 52 才建立，那時由 P52
    補 `grant_start_execution(import_fn)`；現在授權一條不存在的 state machine 沒有意義。
    """
    starts = [row for row in import_statements(template)
              if any(action.startswith("states:Start") for action in actions(row))]
    assert len(starts) == 1
    # 資源是同一支 stack 內 state machine 的 `Ref`（logical id），不是名稱字串；
    # 那條 state machine 的 `StateMachineName` 就是 `training-kb-ticket-analysis`。
    resource = json.dumps(starts[0]["Resource"])
    assert "TicketAnalysis" in resource and "release-update" not in resource
    template.has_resource_properties("AWS::StepFunctions::StateMachine", {
        "StateMachineName": TICKET_ANALYSIS_MACHINE})
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": Match.object_like({"Statement": Match.array_with([
            Match.object_like({"Action": "states:StartExecution"})])})})


def test_the_import_role_reads_and_writes_the_table_and_bucket(template: Template) -> None:
    """Given 匯入角色／When 看資料授權／Then table 與 bucket 都在，且沒有多給。"""
    granted = {action for row in import_statements(template) for action in actions(row)}
    assert {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Scan",
            "s3:GetObject", "s3:PutObject", "s3:ListBucket"} <= granted
    # 這條路徑不查 GSI 也不做交易：`Query`／`BatchGetItem`／`ConditionCheckItem` 都不給，
    # 索引 ARN 自然也不在資源清單裡。
    assert {"dynamodb:Query", "dynamodb:BatchGetItem", "dynamodb:ConditionCheckItem"}.isdisjoint(
        granted)
    assert f"/index/{TARGET_INDEX}" not in json.dumps(import_statements(template))


def test_the_import_role_cannot_touch_the_public_site(template: Template) -> None:
    """Given 匯入角色／When 看 S3 資源／Then 只有 `operations/*`，**沒有** `site/*`。

    `_grant_data` 的預設前綴是最寬的那一組（含公開的 `site/`），新的呼叫端必須明寫自己
    真正需要的最小集合（controller 2026-09-14）。匯入既不寫教學也不發布：`feedback`／
    `view` 一個 S3 物件都不寫，`ticket`／`release` 只寫 `operations/<op>/input.json`。
    """
    resources = json.dumps([row.get("Resource") for row in import_statements(template)])
    assert f"{OPERATIONS_PREFIX}*" in resources
    assert PUBLIC_SITE_PREFIX not in resources
    assert all(prefix not in resources for prefix in PRIVATE_PREFIXES
               if prefix != OPERATIONS_PREFIX)


def test_the_import_role_gets_no_model_and_no_delete(template: Template) -> None:
    """Given 匯入角色／When 檢查禁止清單／Then 沒有 bedrock、沒有 DeleteItem、沒有萬用字元。

    這條路徑零模型呼叫（`category` 的模型判定在 Phase 43 才加），也不刪任何邊
    （D-79 的唯一一條 `DeleteItem` 只屬於 pipeline task function）。
    """
    granted = {action for row in import_statements(template) for action in actions(row)}
    assert not any(action.startswith("bedrock:") for action in granted)
    assert "dynamodb:DeleteItem" not in granted
    assert not any(action.endswith(":*") for action in granted)
