"""Phase 42 Task 4：`training-kb-import` 在 `TrainingKbStack` 裡的接線與最小 IAM。

合成出來的 CloudFormation 樣板當字典查（CDK `Template`），所以這支測試不需要 AWS 憑證，
也不代表真的部署過——實機證據在 Phase 42 報告 §4 的 `aws lambda invoke` 原文。

守四件事（00A D-56、D-58、文件 §7 Task 4 Step 3）：

```text
名稱與 handler   training-kb-import / training_kb.handlers.import_.handler
沒有公開入口     全 stack 只有 Phase 30 的 webhook 有 AWS::Lambda::Url
最小 IAM         table（GetItem/PutItem/UpdateItem/Scan、不含索引）＋ S3 operations/*
                 ＋ ticket-analysis 與 release-update 兩條具名 ARN 的
                 states:StartExecution／states:DescribeExecution
沒有的東西       dynamodb:DeleteItem、site/*、GSI、sts:GetCallerIdentity、萬用字元動作
```

Phase 43 在檔尾追加了自己的區段（匯入路徑開始分類留言，所以多一條 `bedrock:InvokeModel`）；
上面「沒有的東西」原本列的 `bedrock:InvokeModel` 因此改成由 Phase 43 的兩條測試界定範圍。
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
    TICKET_ANALYSIS_MACHINE,
    TrainingKbStack,
)

BUCKET = "training-kb-content-example"
ACCOUNT, REGION = "111122223333", "us-east-1"
IMPORT_ROLE_PREFIX = "ImportFunctionServiceRole"


@pytest.fixture
def template(monkeypatch: pytest.MonkeyPatch, fake_layer: pathlib.Path) -> Template:
    """與 `test_ticket_asl.py` 同一種合成方式（純字串名稱接既有 table／bucket）。

    `fake_layer` 來自 `tests/unit/infra/conftest.py`：layer 守門走 monkeypatch 的
    `tmp_path`，**不在工作樹 `mkdir`**，乾淨 clone 上也合成得出來。
    """
    monkeypatch.setenv(SECRET_ENV, "unit-test-secret")
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


def test_the_import_role_can_start_exactly_the_two_named_machines(template: Template) -> None:
    """Given 匯入角色／When 找 `states:StartExecution`／Then 兩條具名 ARN，沒有萬用字元。

    ARN 由**名稱**組出來（`Stack.format_arn`），不是 `machine.grant_start_execution(...)`：
    `training-kb-release-update` 要到 Phase 52 才有 construct，而 IAM 允許引用尚不存在的
    資源。這樣 P52 建那條 state machine 時不必回頭碰這支 Lambda（controller 2026-09-14）。
    `training-kb-feedback-review`（P48）不在清單裡：固定匯入不啟動它。
    """
    starts = [row for row in import_statements(template)
              if any(action.startswith("states:Start") for action in actions(row))]
    assert len(starts) == 1
    resource = json.dumps(starts[0]["Resource"])
    for name in (TICKET_ANALYSIS_MACHINE, "training-kb-release-update"):
        assert f":stateMachine:{name}" in resource, name
    assert "feedback-review" not in resource
    assert "*" not in resource
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


def test_the_import_role_can_describe_only_those_two_machines_executions(
        template: Template) -> None:
    """Given 匯入角色／When 找 `states:DescribeExecution`／Then 只到那兩條的 execution ARN。

    `ticket`／`release` 分支走 `BotoPipelineStarter.start`，它在 `ExecutionAlreadyExists`
    時會 `DescribeExecution` 把既有執行撿回來（續跑）；少了這條授權那一路會變成
    `AccessDeniedException`（review 修正回合 1 的 Minor 4）。
    """
    describes = [row for row in import_statements(template)
                 if "states:DescribeExecution" in actions(row)]
    assert len(describes) == 1
    # 資源是 `Fn::Join`（`aws` partition 是 pseudo parameter），所以比對序列化後的字串。
    resources = describes[0]["Resource"]
    assert len(resources) == 2
    for arn, name in zip(resources, (TICKET_ANALYSIS_MACHINE, "training-kb-release-update"),
                         strict=True):
        assert f":execution:{name}:*" in json.dumps(arn), name


def test_the_import_role_gets_no_caller_identity(template: Template) -> None:
    """Given 匯入角色／When 檢查禁止清單／Then 沒有 `sts:GetCallerIdentity`。

    AWS 文件明示 `sts:GetCallerIdentity` **不需要任何權限**（也無法用 IAM policy 拒絕），
    所以誰都不必給。

    **現況核對（2026-09-15，修正波 final review C#1）：** 本測試原本的理由寫成「ARN 推導
    那條是 webhook 那支 Lambda 的路徑（P41 的 `_grant_execution_lookup`），匯入這支用不到
    就不給」——那個說法暗示 webhook 需要它。實際上匯入的 `ticket`／`release` 分支**也會**
    走 `ingress._build_wiring` → `get_caller_identity`，兩支都不需要授權；webhook 那條
    `Resource: "*"` 已經在修正波刪掉（`check_iam` 逐字判 fail）。
    """
    granted = {action for row in import_statements(template) for action in actions(row)}
    assert "sts:GetCallerIdentity" not in granted


def test_the_import_role_gets_no_model_and_no_delete(template: Template) -> None:
    """Given 匯入角色／When 檢查禁止清單／Then 沒有 DeleteItem、沒有萬用字元、模型只有一個動作。

    這支 Lambda 不刪任何邊（D-79 的唯一一條 `DeleteItem` 只屬於 pipeline task function）。

    **現況核對（2026-09-14，Phase 43）：** 原本這裡斷言「一個 `bedrock:` 動作都沒有」，
    理由是「這條路徑零模型呼叫（`category` 的模型判定在 Phase 43 才加）」。Phase 43 已經
    把留言分類接上匯入路徑，所以改成「唯一被允許的模型動作是 `bedrock:InvokeModel`」，
    範圍與資源由 `test_import_lambda_can_invoke_only_the_approved_generation_model` 守。
    紅燈源自 Phase 43 改的共用檔，由 Phase 43 負責修（COMMON.md R3.5）。
    """
    granted = {action for row in import_statements(template) for action in actions(row)}
    assert {action for action in granted if action.startswith("bedrock:")} == {
        "bedrock:InvokeModel"}
    assert "dynamodb:DeleteItem" not in granted
    assert not any(action.endswith(":*") for action in granted)


# --- Phase 43：匯入 Lambda 開始分類留言 ------------------------------------------
#
# 追加一條 IAM 斷言（本計畫選擇 2026-09-14：沿用 P42 建立的這支檔，00A §3.3 沒有給
# Phase 43 專屬的 infra 測試檔名）。上面 P42 的
# `test_the_import_role_gets_no_model_and_no_delete` 原本斷言「沒有任何 bedrock 動作」，
# 本 Phase 讓匯入路徑開始呼叫模型，所以那條改成「只有 `bedrock:InvokeModel` 一個動作、
# 資源仍然只有已核定的模型 ARN」——紅燈源自本 Phase 改的共用檔，由本 Phase 負責（R3.5）。


def test_import_lambda_can_invoke_only_the_approved_generation_model(template: Template) -> None:
    """Given 匯入角色／When 找 bedrock 授權／Then 恰好一條 `InvokeModel`，資源是具名模型 ARN。

    Phase 43 的 `classify_feedback_category` 在未勾選且留言非空時會呼叫一次
    `Writer.generate_json`；沒有這條權限，雲端第一次分類就 `AccessDeniedException`。

    **O5 BLOCKED**：`TKB_GENERATION_MODEL_ID` 仍不得填猜測值，所以已核定的模型 ARN
    目前只有 embedding 那一個（與 P41 給 `task_fn`／`webhook_fn` 的寫法、範圍完全相同）。
    這條測試守的是「有授權、且不是萬用字元」，不是「生成模型已核定」。
    """
    bedrock = [row for row in import_statements(template)
               if any(action.startswith("bedrock:") for action in actions(row))]
    assert len(bedrock) == 1
    assert actions(bedrock[0]) == ["bedrock:InvokeModel"]
    resource = json.dumps(bedrock[0]["Resource"])
    assert ":foundation-model/" in resource and "*" not in resource
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": Match.object_like({"Statement": Match.array_with([
            Match.object_like({"Action": "bedrock:InvokeModel"})])})})


def test_the_import_lambda_still_has_no_new_environment_variables(template: Template) -> None:
    """Given Phase 43 的改動／When 看環境變數／Then 一個都沒有新增（O5 BLOCKED）。"""
    variables = import_function(template)["Environment"]["Variables"]
    assert "TKB_GENERATION_MODEL_ID" not in variables
    assert not any(name.startswith("TKB_FEEDBACK") for name in variables)
