"""Phase 54 Task 4：`training-kb-analytics` 在 `TrainingKbStack` 裡的 `Template` 斷言。

`Template.from_stack` 只做本機合成，不連 AWS。

**斷言用包含式，不是四支 Lambda 的字典等號**（Phase 54 §7 Task 4 的降級條款）：本 Phase
落地時 Phase 42 的 `training-kb-import` 尚未進 stack，而 Phase 48／52 之後還會再加資源。
等號會讓別人的 Phase 一落地就把這個檔轉紅，而正確的反應**不是**刪別人的資源讓等號成立。
"""

import pathlib
import sys

import pytest

from training_kb.handlers.github_webhook import SECRET_ENV

# infra/ 是部署用的 CDK 程式，不在 src/ 的安裝套件裡（同 tests/unit/infra/test_ticket_asl.py）。
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aws_cdk as cdk  # noqa: E402
from aws_cdk.assertions import Template  # noqa: E402

from infra.training_kb_stack import (  # noqa: E402
    ANALYTICS_FUNCTION,
    CONTENT_BUCKET_CONTEXT,
    TrainingKbStack,
)

BUCKET = "training-kb-content-example"
ACCOUNT, REGION = "111122223333", "us-east-1"
ANALYTICS_HANDLER = "training_kb.handlers.analytics.handler"


@pytest.fixture
def template(monkeypatch: pytest.MonkeyPatch, fake_layer: pathlib.Path) -> "Template":
    # Phase 42 代改（controller 2026-09-14 核准的 R3.6 例外）：原本在工作樹
    # `mkdir(build/lambda-layer/python)`，`is_built()` 收緊之後在乾淨 clone 上會
    # FileNotFoundError。改用 tests/unit/infra/conftest.py 的共用 `fake_layer`。
    monkeypatch.setenv(SECRET_ENV, "unit-test-secret")
    app = cdk.App(context={CONTENT_BUCKET_CONTEXT: BUCKET})
    stack = TrainingKbStack(app, "TrainingKbApp",
                            env=cdk.Environment(account=ACCOUNT, region=REGION))
    return Template.from_stack(stack)


def functions(template: "Template") -> dict[str, dict]:
    return {row["Properties"]["FunctionName"]: row["Properties"]
            for row in template.find_resources("AWS::Lambda::Function").values()}


def statements(template: "Template") -> list[dict]:
    return [statement
            for policy in template.find_resources("AWS::IAM::Policy").values()
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]]


def actions(statement: dict) -> list[str]:
    value = statement.get("Action", [])
    return value if isinstance(value, list) else [value]


def test_stack_wires_the_analytics_lambda(template: "Template") -> None:
    """Given 合成結果，Then `training-kb-analytics` 在裡面且 handler 路徑正確（D-56、D-58）。"""
    properties = functions(template)[ANALYTICS_FUNCTION]
    assert ANALYTICS_FUNCTION == "training-kb-analytics"
    assert properties["Handler"] == ANALYTICS_HANDLER


def test_analytics_lambda_shares_the_phase41_dependency_layer(template: "Template") -> None:
    """Given COMMON R2，Then 它用 Phase 41 那支唯一的 layer，沒有第二支。

    `Code.from_asset("src")` 不含 `pydantic`／`jsonschema`；少了 layer 這支 Lambda 會在
    雲端第一次 import 就爆，而 synth 完全看不出來。
    """
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)
    properties = functions(template)[ANALYTICS_FUNCTION]
    assert len(properties["Layers"]) == 1
    assert properties["Runtime"] == "python3.12"
    assert properties["Architectures"] == ["x86_64"]
    variables = properties["Environment"]["Variables"]
    assert variables["TKB_CONTENT_BUCKET"] == BUCKET != "training-kb-content"
    assert variables["TKB_TABLE_NAME"] == "training_kb"
    assert "TKB_GENERATION_MODEL_ID" not in variables      # O5 BLOCKED，不填猜測值


def test_analytics_lambda_has_no_function_url(template: "Template") -> None:
    """Given 維護者用 boto3 `invoke`，Then 全 stack 只有 webhook 那一個 Function URL。"""
    template.resource_count_is("AWS::Lambda::Url", 1)
    urls = [row["Properties"] for row in template.find_resources("AWS::Lambda::Url").values()]
    assert not any(ANALYTICS_FUNCTION in str(row) for row in urls)


def test_analytics_role_stays_minimal(template: "Template") -> None:
    """Given 它不啟動任何 pipeline、不呼叫模型、不刪邊，Then 角色裡沒有那三種授權。

    權限刻意涵蓋 Phase 55 的寫入（D-58：Phase 55 不再動 CDK），但範圍仍只有
    table ＋ 五個 key 前綴，與 Phase 41 兩支 Lambda 同一個形狀。
    """
    roles = template.find_resources("AWS::IAM::Role")
    policies = {name: policy["Properties"]
                for name, policy in template.find_resources("AWS::IAM::Policy").items()}
    analytics_roles = [name for name in roles if "Analytics" in name]
    assert len(analytics_roles) == 1
    rows = [statement
            for policy in policies.values()
            if any(analytics_roles[0] in str(ref) for ref in policy.get("Roles", []))
            for statement in policy["PolicyDocument"]["Statement"]]
    assert rows, "analytics 角色應該有 table／bucket 的授權"
    granted = {action for row in rows for action in actions(row)}
    assert not granted & {"states:StartExecution", "bedrock:InvokeModel",
                          "dynamodb:DeleteItem", "sts:GetCallerIdentity"}
    assert {"dynamodb:Query", "dynamodb:Scan", "s3:GetObject"} <= granted


def test_only_one_dynamodb_delete_statement_survives_the_new_lambda(
        template: "Template") -> None:
    """Given 多了一支 Lambda，Then D-79 的「只有一條 `DeleteItem`」仍然成立。"""
    delete = [row for row in statements(template) if "dynamodb:DeleteItem" in actions(row)]
    assert len(delete) == 1


def test_no_new_state_machine_or_schedule_comes_from_this_phase(template: "Template") -> None:
    """Given 本 Phase 不建 state machine、不加排程，Then 沒有一條 state machine 屬於它。

    現況核對 2026-09-14（Phase 52 代改）：原本是 `resource_count_is(..., 1)`。Phase 48／52
    會在同一支 stack 加上 `feedback-review`／`release-update`，數量不再是 1；Phase 54 要守的
    是「analytics 自己不建 state machine、不加排程」，所以改成用名稱判斷。
    """
    names = {row["Properties"]["StateMachineName"] for row in
             template.find_resources("AWS::StepFunctions::StateMachine").values()}
    assert names and all("analytics" not in name for name in names)
    template.resource_count_is("AWS::Events::Rule", 0)
