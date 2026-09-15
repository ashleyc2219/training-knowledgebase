"""Phase 52 Task 2：`training-kb-release-update` 在 `TrainingKbStack` 裡的 Template 斷言。

放在 `tests/unit/infra/` 是為了吃到 `tests/unit/infra/conftest.py` 的共用 `fake_layer`
（**本計畫選擇（2026-09-14）**：不在 `tests/unit/test_release_asl.py` 再複製一份會分岔的
layer fixture；ASL 本身的結構斷言仍在那支檔）。

本檔只斷言**本 Phase 新增的東西**，不重複 Phase 41／42／54 已經守住的部分：
第二條 state machine 存在、共用同一支 Lambda、沒有第四條 pipeline、沒有新的 Lambda 函式。
"""

import json
import pathlib
import sys

import pytest
from aws_cdk.assertions import Match, Template

from training_kb.pipeline_starter import STATE_MACHINE_NAMES

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aws_cdk as cdk  # noqa: E402

from infra.training_kb_stack import (  # noqa: E402
    CONTENT_BUCKET_CONTEXT,
    PIPELINE_TASK_FUNCTION,
    RELEASE_UPDATE_MACHINE,
    TrainingKbStack,
)
from training_kb.handlers.github_webhook import SECRET_ENV  # noqa: E402

BUCKET = "training-kb-content-example"
ACCOUNT, REGION = "111122223333", "us-east-1"

EXPECTED_FUNCTIONS = {PIPELINE_TASK_FUNCTION, "training-kb-webhook",
                      "training-kb-analytics", "training-kb-import"}
"""P41／P42／P54 的四支具名 Lambda；**本 Phase 一支都不加**（D-23）。"""


@pytest.fixture
def template(monkeypatch: pytest.MonkeyPatch, fake_layer: pathlib.Path) -> Template:
    """`fake_layer` 來自 `tests/unit/infra/conftest.py`（不在工作樹裡 `mkdir`）。"""
    monkeypatch.setenv(SECRET_ENV, "unit-test-secret")
    app = cdk.App(context={CONTENT_BUCKET_CONTEXT: BUCKET})
    return Template.from_stack(TrainingKbStack(
        app, "TrainingKbApp", env=cdk.Environment(account=ACCOUNT, region=REGION)))


def machines(template: Template) -> dict[str, dict]:
    return {row["Properties"]["StateMachineName"]: row["Properties"]
            for row in template.find_resources("AWS::StepFunctions::StateMachine").values()}


def statements(template: Template) -> list[dict]:
    return [statement
            for policy in template.find_resources("AWS::IAM::Policy").values()
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]]


def actions(statement: dict) -> list[str]:
    value = statement.get("Action", [])
    return value if isinstance(value, list) else [value]


def test_release_update_is_a_standard_workflow_with_the_fixed_name(
        template: Template) -> None:
    """Given 本 Phase 的交付物，Then 恰多一條名為 `training-kb-release-update` 的 Standard。"""
    assert RELEASE_UPDATE_MACHINE == STATE_MACHINE_NAMES["release-update"]
    found = machines(template)
    assert RELEASE_UPDATE_MACHINE in found
    assert found[RELEASE_UPDATE_MACHINE]["StateMachineType"] == "STANDARD"
    # 不得長出第四條 pipeline：名稱只能落在 `STATE_MACHINE_NAMES` 的三個值裡
    assert set(found) <= set(STATE_MACHINE_NAMES.values())


def test_no_new_lambda_function_comes_from_this_phase(template: Template) -> None:
    """Given D-23，Then 七個 Task 共用 Phase 41 的函式，本 Phase 不建第二個 Lambda。"""
    names = {row["Properties"]["FunctionName"]
             for row in template.find_resources("AWS::Lambda::Function").values()}
    assert names == EXPECTED_FUNCTIONS
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)   # 沿用同一支相依 layer


def test_definition_substitutes_the_shared_function_arn(template: Template) -> None:
    """Given ASL 的 `${PipelineTaskFunctionArn}`，Then 代入的是共用 Lambda 的 ARN。

    `DefinitionBody.from_file(...)` 會把定義上傳成 CDK asset，所以樣板裡只有
    `DefinitionS3Location`（沒有 `DefinitionString` 可以比對）；定義**內容**的斷言在
    `tests/unit/test_release_asl.py`，這裡只驗接線。
    """
    properties = machines(template)[RELEASE_UPDATE_MACHINE]
    assert set(properties["DefinitionSubstitutions"]) == {"PipelineTaskFunctionArn"}
    arn = json.dumps(properties["DefinitionSubstitutions"]["PipelineTaskFunctionArn"])
    assert "PipelineTaskFunction" in arn                        # GetAtt 指向那一支函式
    assert set(properties["DefinitionS3Location"]) == {"Bucket", "Key"}
    invokes = [row for row in statements(template)
               if "lambda:InvokeFunction" in actions(row)
               and "PipelineTaskFunction" in json.dumps(row["Resource"])]
    assert invokes                                              # task_fn.grant_invoke(machine)


def test_release_update_logs_to_its_own_group(template: Template) -> None:
    """Given 證據要看得到，Then 它有自己的 log group 且 `Level` 是 ALL。"""
    template.has_resource_properties("AWS::Logs::LogGroup", Match.object_like(
        {"LogGroupName": f"/aws/vendedlogs/states/{RELEASE_UPDATE_MACHINE}"}))
    assert machines(template)[RELEASE_UPDATE_MACHINE]["LoggingConfiguration"]["Level"] == "ALL"


def role_statements(template: Template, function_name: str) -> list[dict]:
    """某一支 Lambda 的 role 上掛的全部 policy 敘述（形狀照 `test_ticket_asl.py`）。"""
    functions = template.find_resources("AWS::Lambda::Function")
    role_id = next(row["Properties"]["Role"]["Fn::GetAtt"][0]
                   for row in functions.values()
                   if row["Properties"]["FunctionName"] == function_name)
    return [statement
            for policy in template.find_resources("AWS::IAM::Policy").values()
            if any(ref.get("Ref") == role_id for ref in policy["Properties"]["Roles"])
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]]


def test_start_execution_is_limited_to_the_webhook_and_the_import_lambda(
        template: Template) -> None:
    """Given Phase 60 的 IAM 核對表，Then 只有 webhook 與 import 啟得動這條 pipeline。

    webhook 那一條是 `grant_start_execution`（資源是 `{"Ref": <state machine>}`）；import
    那一條是 Phase 42 用**名稱**組出的 ARN，一次授權兩條 pipeline（controller 2026-09-14），
    所以本 Phase 不再對 import 呼叫第二次 grant。全 stack 只有這兩個角色拿得到
    `states:StartExecution`，而且沒有任何一條用萬用字元指向全部 state machine。
    """
    machine_id = next(logical for logical, row
                      in template.find_resources("AWS::StepFunctions::StateMachine").items()
                      if row["Properties"]["StateMachineName"] == RELEASE_UPDATE_MACHINE)
    granted = {name for name in EXPECTED_FUNCTIONS
               for row in role_statements(template, name)
               if "states:StartExecution" in actions(row)
               and (machine_id in json.dumps(row["Resource"])
                    or RELEASE_UPDATE_MACHINE in json.dumps(row["Resource"]))}
    assert granted == {"training-kb-webhook", "training-kb-import"}
    starts = [row for row in statements(template) if "states:StartExecution" in actions(row)]
    assert all("stateMachine:*" not in json.dumps(row["Resource"]) for row in starts)


def test_describe_execution_now_covers_both_pipelines(template: Template) -> None:
    """Given P32 的續跑判斷，Then webhook 對兩條 state machine 的 execution 都查得到。"""
    lookups = [json.dumps(row["Resource"]) for row in statements(template)
               if "states:DescribeExecution" in actions(row)]
    assert any(f"execution:{RELEASE_UPDATE_MACHINE}:*" in row for row in lookups)
    assert any("execution:training-kb-ticket-analysis:*" in row for row in lookups)
