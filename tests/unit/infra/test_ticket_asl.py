"""Phase 41 Task 2／3：`ticket-analysis` 的 ASL 結構與 `TrainingKbStack` 的 Template 斷言。

ASL 的 `Retry`／`Catch`／`TimeoutSeconds` **一律從 `training_kb.pipelines.asl` import**
再比對回去（Phase 29 的 `RETRY`／`CATCH`／`task_state`），本檔不抄任何字面值：抄一份就會
在 Phase 29 改動時默默分岔。
"""

import copy
import json
import pathlib
import sys

import pytest

from training_kb.errors import PermanentError, TransientError
from training_kb.handlers.github_webhook import SECRET_ENV
from training_kb.pipelines.asl import (
    ASL_LOCAL_PATH,
    CATCH,
    RETRY,
    assert_safe_asl,
    canonical_json,
)
from training_kb.pipelines.common import task_name
from training_kb.pipelines.ticket import TICKET_ANALYSIS_TASKS

# infra/ 是部署用的 CDK 程式，不在 src/ 的安裝套件裡，所以把專案根目錄加進路徑
# （同 tests/unit/test_data_stack.py 的既有作法）。
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aws_cdk as cdk  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from infra import training_kb_stack as stack_module  # noqa: E402
from infra.training_kb_stack import (  # noqa: E402
    CONTENT_BUCKET_CONTEXT,
    CONTENT_BUCKET_ENV,
    LAYER_PATH,
    TrainingKbStack,
)

ASL_PATH = PROJECT_ROOT / ASL_LOCAL_PATH.format(pipeline="ticket-analysis", number=1)
ARN = "${PipelineTaskFunctionArn}"
NEXT = {"EnsureEmbedding": "AssignCluster", "AssignCluster": "EvaluateRecurring",
        "EvaluateRecurring": "IsRecurring", "NameGap": "DecideAction",
        "DecideAction": "ChooseAction", "CreateFirstVersion": "PublishVersion",
        "PublishVersion": "Published"}


@pytest.fixture
def asl() -> dict:
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))


# --- Task 2：ASL 結構 --------------------------------------------------------


def test_every_task_state_equals_phase29_template_plus_parameters(asl: dict) -> None:
    """Given 七個 Task state，Then 除了 `Parameters` 逐欄等於 Phase 29 的 `task_state`。"""
    from training_kb.pipelines.asl import task_state
    assert len(RETRY) == 2 and RETRY[0]["ErrorEquals"] == ["TransientError"]   # D-53
    for name, next_state in NEXT.items():
        state, expected = asl["States"][name], task_state(ARN, next_state)
        expected["Parameters"] = {"pipeline": "ticket-analysis",
                                  "task": state["Parameters"]["task"], "state.$": "$"}
        assert state == expected, name        # Retry／Catch／TimeoutSeconds 全部來自 Phase 29


def test_asl_task_names_and_branches_match_python(asl: dict) -> None:
    """Given ASL 與 Python 兩邊，Then Task 名稱、封套與兩個 Choice 的分支都對得上。"""
    parameters = [asl["States"][name]["Parameters"] for name in NEXT]
    assert [row["task"] for row in parameters] == [task_name(t) for t in TICKET_ANALYSIS_TASKS]
    assert all(row["pipeline"] == "ticket-analysis" and row["state.$"] == "$"
               and "Payload" not in row for row in parameters)
    assert_safe_asl(asl)
    assert asl["StartAt"] == "EnsureEmbedding"
    assert asl["States"]["PipelineFailed"]["Type"] == "Fail"
    assert asl["States"]["ChooseAction"]["Default"] == CATCH[0]["Next"] == "PipelineFailed"
    assert asl["States"]["IsRecurring"]["Default"] == "NotRecurring"
    # Lambda runtime 把未攔截例外的類別名放進 errorType，ASL 就用它比對
    assert (TransientError.__name__, PermanentError.__name__) == ("TransientError",
                                                                  "PermanentError")


def test_four_succeed_states_and_the_two_choices(asl: dict) -> None:
    """Given 四個成功終點與兩個 Choice，Then 分支目標逐一對得上流程圖（§1）。"""
    succeed = {name for name, state in asl["States"].items() if state["Type"] == "Succeed"}
    assert succeed == {"Published", "Kept", "GapRetained", "NotRecurring"}
    assert asl["States"]["IsRecurring"]["Choices"] == [
        {"Variable": "$.is_recurring", "BooleanEquals": True, "Next": "NameGap"}]
    assert asl["States"]["ChooseAction"]["Choices"] == [
        {"Variable": "$.action", "StringEquals": "CREATE", "Next": "CreateFirstVersion"},
        {"Variable": "$.action", "StringEquals": "KEEP", "Next": "Kept"},
        {"Variable": "$.action", "StringEquals": "NO_FEATURE", "Next": "GapRetained"}]


def test_assert_safe_asl_rejects_the_same_file_without_a_catch(asl: dict) -> None:
    """Given 手動拿掉任何一個 `Catch`，Then 靜態檢查必須轉紅（文件 Task 2 Step 4）。"""
    broken = copy.deepcopy(asl)
    del broken["States"]["NameGap"]["Catch"]
    with pytest.raises(PermanentError, match="NameGap"):
        assert_safe_asl(broken)


def test_definition_file_is_canonical_bytes(asl: dict) -> None:
    """Given 部署與 S3 快照是同一份 bytes，Then 檔案本身就是 `canonical_json` 的輸出。"""
    assert ASL_PATH.read_bytes() == canonical_json(asl)


# --- Task 3：CDK Template -----------------------------------------------------

BUCKET = "training-kb-content-example"
"""已部署的實際 bucket 名（COMMON.md §1）；`load_settings` 的預設值在雲端不存在。"""

ACCOUNT, REGION = "111122223333", "us-east-1"


@pytest.fixture
def template(monkeypatch: pytest.MonkeyPatch) -> "Template":
    """合成 `TrainingKbApp`。

    **不建 `TrainingKbData`**：本 stack 用 `Table.from_table_name`／`Bucket.from_bucket_name`
    以純字串名稱接進既有資源，才能 `cdk deploy TrainingKbApp --exclusively` 單獨部署而
    不碰同一波次 Phase 57 正在改的 data stack（controller 2026-09-14 裁決）。

    layer 只要 asset 目錄存在就合成得出來，內容不影響任何斷言，所以這裡不跑 uv 安裝。
    """
    monkeypatch.setenv(SECRET_ENV, "unit-test-secret")
    (LAYER_PATH / "python").mkdir(parents=True, exist_ok=True)
    app = cdk.App(context={CONTENT_BUCKET_CONTEXT: BUCKET})
    stack = TrainingKbStack(app, "TrainingKbApp",
                            env=cdk.Environment(account=ACCOUNT, region=REGION))
    return Template.from_stack(stack)


def statements(template: "Template") -> list[dict]:
    return [statement
            for policy in template.find_resources("AWS::IAM::Policy").values()
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]]


def actions(statement: dict) -> list[str]:
    value = statement.get("Action", [])
    return value if isinstance(value, list) else [value]


def test_stack_has_one_standard_machine_and_two_named_lambdas(template: "Template") -> None:
    """Given 合成結果，Then 一條 Standard state machine ＋ 兩支具名 Lambda（D-23）。"""
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    template.has_resource_properties("AWS::StepFunctions::StateMachine", {
        "StateMachineName": "training-kb-ticket-analysis", "StateMachineType": "STANDARD",
        "DefinitionSubstitutions": Match.object_like(
            {"PipelineTaskFunctionArn": Match.any_value()})})
    functions = template.find_resources("AWS::Lambda::Function").values()
    handlers = {row["Properties"]["FunctionName"]: row["Properties"]["Handler"]
                for row in functions}
    # 用包含關係而不是等號：Phase 42／54 會在同一支 stack 再加 training-kb-import
    # 與 training-kb-analytics，那時這個斷言不該轉紅。
    assert handlers["training-kb-pipeline-task"] \
        == "training_kb.pipelines.common.pipeline_task_handler"
    assert handlers["training-kb-webhook"] == "training_kb.handlers.github_webhook.handler"


def test_both_lambdas_share_one_dependency_layer_and_get_the_real_bucket(
        template: "Template") -> None:
    """Given 兩支 Lambda，Then 共用同一支 layer，且 bucket 名不是 `load_settings` 的預設值。"""
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)
    for function in template.find_resources("AWS::Lambda::Function").values():
        properties = function["Properties"]
        assert len(properties["Layers"]) == 1        # pydantic／jsonschema 只從 layer 來
        assert properties["Architectures"] == ["x86_64"]
        assert properties["Runtime"] == "python3.12"
        variables = properties["Environment"]["Variables"]
        assert variables["TKB_CONTENT_BUCKET"] == BUCKET != "training-kb-content"
        assert variables["TKB_TABLE_NAME"] == "training_kb"
        assert variables["TKB_AWS_REGION"] == REGION
        # O5 BLOCKED：生成模型 ID 不得填猜測值（00A §3.5）
        assert "TKB_GENERATION_MODEL_ID" not in variables


def test_nothing_is_imported_from_another_stack(template: "Template") -> None:
    """Given `--exclusively` 單獨部署，Then 樣板不得有任何跨 stack `Fn::ImportValue`。"""
    assert "Fn::ImportValue" not in json.dumps(template.to_json())


def test_iam_covers_the_three_gaps_the_previous_batch_left(template: "Template") -> None:
    """Given 上一批留的三個缺口（REP §8-6、D-79），Then 三條授權都在這支 stack 裡。

    D-79 逐字的「`SK begins_with APPLIED_TO#`」在 IAM 做不到：DynamoDB 的條件鍵只有
    `dynamodb:LeadingKeys`（比 **PK**）等，**沒有**比 SK 的條件鍵。所以授權收斂成
    「單一 table、只有 `DeleteItem`、沒有 `dynamodb:*`」，範圍由程式層的
    `Repository.DELETABLE_RELATIONS` 白名單守住（controller 2026-09-14 裁決）。
    """
    rows = statements(template)
    delete = [row for row in rows if "dynamodb:DeleteItem" in actions(row)]
    assert len(delete) == 1
    assert not any(action.endswith(":*") or action == "dynamodb:*"
                   for row in rows for action in actions(row) if action.startswith("dynamodb:"))
    assert any("states:DescribeExecution" in actions(row) for row in rows)
    assert any("sts:GetCallerIdentity" in actions(row) for row in rows)
    assert any("s3:PutObject" in actions(row) and "site/" in json.dumps(row.get("Resource"))
               for row in rows)                                  # P24／P25 的公開前綴


def test_delete_item_is_scoped_to_the_single_table(template: "Template") -> None:
    """Given 唯一那條 `DeleteItem`，Then 資源只有這張表本體（連索引都不給）。"""
    delete = [row for row in statements(template) if "dynamodb:DeleteItem" in actions(row)][0]
    assert actions(delete) == ["dynamodb:DeleteItem"]
    resource = json.dumps(delete["Resource"])
    assert "table/training_kb" in resource and "index" not in resource


def test_bedrock_is_limited_to_the_approved_embedding_model(template: "Template") -> None:
    """Given O5 BLOCKED，Then 只授權已核定用途的 embedding 模型，不列生成模型。"""
    bedrock = [row for row in statements(template) if "bedrock:InvokeModel" in actions(row)]
    assert len(bedrock) == 1
    # 單元素的 Resource 會被 CDK 收成純字串，不是 list
    assert bedrock[0]["Resource"] == \
        f"arn:aws:bedrock:{REGION}::foundation-model/amazon.titan-embed-text-v2:0"


def test_only_the_webhook_has_a_public_function_url(template: "Template") -> None:
    """Given 公開入口只有 webhook，Then 只有一個 Function URL 且 `AuthType` 是 NONE。"""
    urls = template.find_resources("AWS::Lambda::Url")
    assert len(urls) == 1
    assert next(iter(urls.values()))["Properties"]["AuthType"] == "NONE"


def test_state_machine_logs_to_its_own_group(template: "Template") -> None:
    template.resource_count_is("AWS::Logs::LogGroup", 1)
    template.has_resource_properties("AWS::Logs::LogGroup", Match.object_like(
        {"LogGroupName": "/aws/vendedlogs/states/training-kb-ticket-analysis"}))
    template.has_resource_properties("AWS::StepFunctions::StateMachine", Match.object_like(
        {"LoggingConfiguration": Match.object_like({"Level": "ALL"})}))


def test_webhook_secret_comes_from_the_deploy_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 部署當下的 shell 帶進 `TKB_GITHUB_WEBHOOK_SECRET`，Then 缺值就當場 synth 失敗。

    值不寫進 CDK 程式或 repo；缺值時讓 `KeyError` 擋下來，比部署出一支永遠驗簽失敗的
    Lambda 好（Phase 41 §7 Task 3 Step 3）。
    """
    monkeypatch.delenv(SECRET_ENV, raising=False)
    (LAYER_PATH / "python").mkdir(parents=True, exist_ok=True)
    app = cdk.App(context={CONTENT_BUCKET_CONTEXT: BUCKET})
    with pytest.raises(KeyError, match=SECRET_ENV):
        TrainingKbStack(app, "TrainingKbApp",
                        env=cdk.Environment(account=ACCOUNT, region=REGION))


def test_missing_dependency_layer_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 還沒建 layer，Then synth 當場失敗並說出要跑哪一支腳本（不是部署後才爆）。"""
    monkeypatch.setenv(SECRET_ENV, "unit-test-secret")
    monkeypatch.setattr(stack_module, "LAYER_PATH", PROJECT_ROOT / "build" / "does-not-exist")
    app = cdk.App(context={CONTENT_BUCKET_CONTEXT: BUCKET})
    with pytest.raises(FileNotFoundError, match="build_lambda_layer"):
        TrainingKbStack(app, "TrainingKbApp",
                        env=cdk.Environment(account=ACCOUNT, region=REGION))


def test_content_bucket_has_no_silent_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 沒有 context 也沒有環境變數，Then 明確失敗，不退回 `training-kb-content`。"""
    monkeypatch.setenv(SECRET_ENV, "unit-test-secret")
    monkeypatch.delenv(CONTENT_BUCKET_ENV, raising=False)
    (LAYER_PATH / "python").mkdir(parents=True, exist_ok=True)
    with pytest.raises(PermanentError, match=CONTENT_BUCKET_ENV):
        TrainingKbStack(cdk.App(), "TrainingKbApp",
                        env=cdk.Environment(account=ACCOUNT, region=REGION))


def test_outputs_carry_what_the_next_phases_need(template: "Template") -> None:
    """Given 部署證據要沿用，Then 三個輸出都在（state machine ARN、Function URL、log group）。"""
    assert set(template.to_json()["Outputs"]) >= {
        "TicketAnalysisStateMachineArn", "WebhookFunctionUrl", "TicketAnalysisLogGroup"}
