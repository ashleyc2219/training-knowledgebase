"""Phase 41 Task 3：真實 AWS 上 `training-kb-ticket-analysis` 的執行證據（`aws` marker）。

**只讀**：本檔不啟動新的執行，只核對已部署的 state machine 與 Phase 41 當天跑出來的三次
執行（Standard workflow 的 execution history 預設保留 90 天）。要重跑證據時照
`docs/plan/report/phases/2026-09-14-Phase41-REP.md` §3 的指令重新啟動同名執行。

未設 `TKB_RUN_AWS_INTEGRATION=1` 時由 `tests/conftest.py` 自動 skip（00A D-41）。

三次執行分別證明三件事：

| execution | 證明 |
|---|---|
| `op-ticket-t_881` | O5 BLOCKED 下唯一跑得到 `SUCCEEDED` 的路徑：已有 `embedding`、同群不到五筆。 |
| `op-ticket-t_883` | 注入的 `TransientError` **逐字**命中第一條 retrier，重試恰兩次。 |
| `op-ticket-t_882` | `PermanentError` 不在 `ErrorEquals` 裡，一次失敗就進 Catch。 |

**直接函式 ARN 的失敗事件是 `LambdaFunctionFailed`（`lambdaFunctionFailedEventDetails`），
不是 `TaskFailed`**：00A §3.7 與 Phase 41 文件寫的 `taskFailedEventDetails.error` 在這個
整合方式下永遠是空的，實證要看 `lambdaFunctionFailedEventDetails.error`（見 §5 與最後一條
測試）。
"""

import json
import pathlib

import boto3
import pytest

from training_kb.config import load_settings
from training_kb.pipeline_starter import STATE_MACHINE_SEGMENT, state_machine_arns
from training_kb.pipelines.asl import ASL_LOCAL_PATH, ASL_SNAPSHOT_KEY
from training_kb.repository import Repository

pytestmark = pytest.mark.aws

REGION = "us-east-1"
SUCCEEDED_EXECUTION = "op-ticket-t_881"
FAULT_EXECUTION = "op-ticket-t_883"
MODEL_BLOCKED_EXECUTION = "op-ticket-t_882"
NOT_RECURRING_TASKS = ["EnsureEmbedding", "AssignCluster", "EvaluateRecurring"]
LOCAL_ASL = pathlib.Path(ASL_LOCAL_PATH.format(pipeline="ticket-analysis", number=1))
DEFINITION_PLACEHOLDER = "${PipelineTaskFunctionArn}"


@pytest.fixture(scope="module")
def client() -> object:
    return boto3.client("stepfunctions", region_name=REGION)


@pytest.fixture(scope="module")
def machine_arn() -> str:
    """由 `STATE_MACHINE_NAMES` ＋ STS 帳號推導，**不寫死帳號**（A3 的同一條推導）。"""
    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    return state_machine_arns(region=REGION, account_id=account)["ticket-analysis"]


def execution_arn(machine_arn: str, name: str) -> str:
    return f"{machine_arn.replace(STATE_MACHINE_SEGMENT, ':execution:')}:{name}"


def history(client: object, machine_arn: str, name: str) -> list[dict]:
    pages = client.get_paginator("get_execution_history").paginate(  # type: ignore[attr-defined]
        executionArn=execution_arn(machine_arn, name), maxResults=200)
    return [event for page in pages for event in page["events"]]


def entered(events: list[dict]) -> list[str]:
    return [event["stateEnteredEventDetails"]["name"]
            for event in events if event["type"] == "TaskStateEntered"]


def lambda_failures(events: list[dict]) -> list[tuple[str, str]]:
    return [(event["lambdaFunctionFailedEventDetails"]["error"],
             event["lambdaFunctionFailedEventDetails"]["cause"])
            for event in events if event["type"] == "LambdaFunctionFailed"]


def test_deployed_definition_is_the_local_file_with_the_arn_substituted(
        client: object, machine_arn: str) -> None:
    """Given 部署好的 Standard workflow，Then 定義就是本地 v1.json 換掉那一個佔位符。"""
    described = client.describe_state_machine(stateMachineArn=machine_arn)  # type: ignore[attr-defined]
    assert (described["type"], described["status"]) == ("STANDARD", "ACTIVE")
    resource = json.loads(described["definition"])["States"]["EnsureEmbedding"]["Resource"]
    expected = json.loads(LOCAL_ASL.read_text(encoding="utf-8")
                          .replace(DEFINITION_PLACEHOLDER, resource))
    assert json.loads(described["definition"]) == expected
    assert resource.endswith(":function:training-kb-pipeline-task")   # 直接函式 ARN，無信封


def test_asl_snapshot_in_s3_is_the_deployed_bytes() -> None:
    """Given 執行教學流程 Rule 10，Then S3 私有快照與部署的定義是同一份 bytes。"""
    settings = load_settings()
    repository = Repository(
        boto3.resource("dynamodb", region_name=REGION).Table(settings.table_name),
        boto3.resource("s3", region_name=REGION).Bucket(settings.content_bucket))
    key = ASL_SNAPSHOT_KEY.format(pipeline="ticket-analysis", number=1)
    assert repository.get_object(key) == LOCAL_ASL.read_bytes()


def test_not_recurring_execution_succeeded_with_three_task_states(
        client: object, machine_arn: str) -> None:
    """Given 已有 `embedding`、同群不到五筆，Then `SUCCEEDED` 且只進三個 Task。"""
    described = client.describe_execution(  # type: ignore[attr-defined]
        executionArn=execution_arn(machine_arn, SUCCEEDED_EXECUTION))
    assert described["status"] == "SUCCEEDED"
    output = json.loads(described["output"])
    assert output["is_recurring"] is False
    assert (output["ticket_id"], output["cluster_id"]) == ("t_881", "c1")
    assert "version_id" not in output and "gap_ref" not in output
    events = history(client, machine_arn, SUCCEEDED_EXECUTION)
    assert entered(events) == NOT_RECURRING_TASKS
    assert [event["stateEnteredEventDetails"]["name"]
            for event in events if event["type"] == "SucceedStateEntered"] == ["NotRecurring"]


def test_injected_transient_error_is_retried_exactly_twice(
        client: object, machine_arn: str) -> None:
    """Given 注入的 `TransientError`，Then 三次失敗（首次＋兩次重試）後 `PipelineFailed`。

    `error` 逐字是 `TransientError` 才代表 `ErrorEquals: ["TransientError"]` 真的命中；
    命不中就只會有一次失敗，重試是假的（00A §3.7 指定由本 Phase 實證的那一項）。
    """
    described = client.describe_execution(  # type: ignore[attr-defined]
        executionArn=execution_arn(machine_arn, FAULT_EXECUTION))
    assert (described["status"], described["error"]) == ("FAILED", "PipelineFailed")
    events = history(client, machine_arn, FAULT_EXECUTION)
    failures = lambda_failures(events)
    assert [error for error, _ in failures] == ["TransientError"] * 3
    assert all("ticket-analysis:name_gap" in cause for _, cause in failures)
    assert entered(events) == [*NOT_RECURRING_TASKS, "NameGap"]
    assert [event["type"] for event in events][-2:] == ["FailStateEntered", "ExecutionFailed"]


def test_permanent_error_goes_straight_to_catch(client: object, machine_arn: str) -> None:
    """Given 模型節點回 `PermanentError`（O5 BLOCKED），Then 一次失敗就進 Catch。"""
    described = client.describe_execution(  # type: ignore[attr-defined]
        executionArn=execution_arn(machine_arn, MODEL_BLOCKED_EXECUTION))
    assert (described["status"], described["error"]) == ("FAILED", "PipelineFailed")
    failures = lambda_failures(history(client, machine_arn, MODEL_BLOCKED_EXECUTION))
    assert [error for error, _ in failures] == ["PermanentError"]     # 不重試
    assert json.loads(failures[0][1])["errorType"] == "PermanentError"


def test_direct_arn_integration_never_emits_task_failed(
        client: object, machine_arn: str) -> None:
    """Given 直接函式 ARN，Then 失敗事件是 `LambdaFunctionFailed` 而不是 `TaskFailed`。

    00A §3.7 與 Phase 41 文件寫的是 `taskFailedEventDetails.error`；那個欄位只在
    `arn:aws:states:::lambda:invoke` 這種最佳化整合下才會出現。本 Phase 用直接函式 ARN
    （D-49：沒有 `Payload` 外層），所以實證要看 `lambdaFunctionFailedEventDetails`。
    """
    for name in (FAULT_EXECUTION, MODEL_BLOCKED_EXECUTION):
        events = history(client, machine_arn, name)
        assert [event for event in events if event["type"] == "TaskFailed"] == []
        assert lambda_failures(events)
