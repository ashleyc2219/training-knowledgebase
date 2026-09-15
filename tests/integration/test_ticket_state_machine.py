"""Phase 41 Task 3：真實 AWS 上 `training-kb-ticket-analysis` 的執行證據（`aws` marker）。

兩組測試：

1. **自足的一次真實執行**（`test_not_recurring_run_...`）：自己種一筆**已有 embedding**、
   同群只有自己的合成工單 → `start-execution`（名稱帶時間戳，不會撞名）→ 等到終態 →
   斷言 `SUCCEEDED`、`NotRecurring`、三個 Task、0 次 Bedrock → **把自己種的資料刪掉**。
   這是 O5 BLOCKED 下唯一跑得到 `SUCCEEDED` 的路徑（工單已有向量，前三個節點不碰模型）。
2. **歷史證據的快照斷言**（`test_historical_*`）：Phase 41 當天跑的三次 execution，
   證明 retry／catch 的錯誤名稱。Standard workflow 的 history 預設保留 90 天，過期之後
   這三條會 `skip`（不是 fail）——要重建證據就照
   `docs/plan/report/phases/2026-09-14-Phase41-REP.md` §3 的指令重跑。

未設 `TKB_RUN_AWS_INTEGRATION=1` 時由 `tests/conftest.py` 自動 skip（00A D-41）；
`TKB_CONTENT_BUCKET` 沒設時整支 skip（`load_settings` 的預設值 `training-kb-content`
在這個帳號不存在，裸跑會對著不存在的 bucket 做事）。

**直接函式 ARN 的失敗事件是 `LambdaFunctionFailed`（`lambdaFunctionFailedEventDetails`），
不是 `TaskFailed`**：00A §3.7 與 Phase 41 文件寫的 `taskFailedEventDetails.error` 在這個
整合方式下永遠是空的（見最後一條測試）。
"""

import json
import os
import pathlib
import time
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError

from training_kb.clock import now_utc
from training_kb.config import Settings, load_settings
from training_kb.keys import operation_ref, ticket_pk
from training_kb.models import Ticket
from training_kb.pipeline_starter import STATE_MACHINE_SEGMENT, state_machine_arns
from training_kb.pipelines.asl import ASL_LOCAL_PATH, ASL_SNAPSHOT_KEY
from training_kb.repository import Repository

pytestmark = pytest.mark.aws

REGION = "us-east-1"
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCAL_ASL = PROJECT_ROOT / ASL_LOCAL_PATH.format(pipeline="ticket-analysis", number=1)
DEFINITION_PLACEHOLDER = "${PipelineTaskFunctionArn}"
NOT_RECURRING_TASKS = ["EnsureEmbedding", "AssignCluster", "EvaluateRecurring"]
VECTOR = [0.1] * 1024
"""1024 維是 Titan 的維度契約（P16）；**合成值**，不是真的向量。"""

EXECUTION_TIMEOUT_SECONDS = 90
POLL_SECONDS = 3

HISTORICAL = {"succeeded": "op-ticket-t_881", "fault": "op-ticket-t_883",
              "model_blocked": "op-ticket-t_882"}
"""Phase 41 當天的三次 execution；見模組 docstring 第 2 點。"""


@pytest.fixture(scope="module")
def settings() -> Settings:
    if not os.environ.get("TKB_CONTENT_BUCKET"):
        pytest.skip("需要 TKB_CONTENT_BUCKET（load_settings 的預設 bucket 在本帳號不存在）")
    return load_settings()


@pytest.fixture(scope="module")
def client() -> Any:
    return boto3.client("stepfunctions", region_name=REGION)


@pytest.fixture(scope="module")
def repository(settings: Settings) -> Repository:
    return Repository(boto3.resource("dynamodb", region_name=REGION).Table(settings.table_name),
                      boto3.resource("s3", region_name=REGION).Bucket(settings.content_bucket))


@pytest.fixture(scope="module")
def machine_arn() -> str:
    """由 `STATE_MACHINE_NAMES` ＋ STS 帳號推導，**不寫死帳號**（報告 §4 的 A3 同一條推導）。"""
    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    return state_machine_arns(region=REGION, account_id=account)["ticket-analysis"]


def execution_arn(machine_arn: str, name: str) -> str:
    return f"{machine_arn.replace(STATE_MACHINE_SEGMENT, ':execution:')}:{name}"


def history(client: Any, machine_arn: str, name: str) -> list[dict[str, Any]]:
    pages = client.get_paginator("get_execution_history").paginate(
        executionArn=execution_arn(machine_arn, name), maxResults=200)
    return [event for page in pages for event in page["events"]]


def entered(events: list[dict[str, Any]]) -> list[str]:
    return [event["stateEnteredEventDetails"]["name"]
            for event in events if event["type"] == "TaskStateEntered"]


def lambda_failures(events: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(event["lambdaFunctionFailedEventDetails"]["error"],
             event["lambdaFunctionFailedEventDetails"]["cause"])
            for event in events if event["type"] == "LambdaFunctionFailed"]


def describe_historical(client: Any, machine_arn: str, name: str) -> dict[str, Any]:
    """歷史 execution；已經過了 90 天保留期就 skip（不是 fail）。"""
    try:
        described: dict[str, Any] = client.describe_execution(
            executionArn=execution_arn(machine_arn, name))
    except ClientError as error:
        if error.response["Error"]["Code"] == "ExecutionDoesNotExist":
            pytest.skip(f"歷史 execution {name} 已超過保留期；照報告 §3 的指令重跑")
        raise
    return described


@pytest.fixture
def seeded_ticket(repository: Repository) -> Iterator[Ticket]:
    """一筆**合成**工單：已有 embedding、自己一群（同群 < 5）。用完刪掉，不留在表裡。

    `cluster_id` 刻意不是 `c<數字>`，所以它不會影響 `new_cluster_id` 的編號，也不會混進
    Demo 的 `c1`。
    """
    stamp = int(time.time())
    ticket = Ticket(id=f"t_p41sm{stamp}", source="github_issue",
                    text=f"[合成資料] Phase 41 整合測試 {stamp}", author="p41-integration",
                    ts=now_utc(), project_id=load_settings().project_id,
                    cluster_id=f"cp41sm{stamp}", embedding=list(VECTOR))
    operation_id = f"op-ticket-{ticket.id}"
    repository.put_meta(ticket, create_only=True)
    repository.put_object(operation_ref(operation_id, "input"),
                          json.dumps(ticket.model_dump(mode="json"), ensure_ascii=False,
                                     sort_keys=True).encode("utf-8"),
                          "application/json", if_none_match=False)
    yield ticket
    table = boto3.resource("dynamodb", region_name=REGION).Table(load_settings().table_name)
    table.delete_item(Key={"PK": ticket_pk(ticket.id), "SK": "META"})
    boto3.resource("s3", region_name=REGION).Object(
        load_settings().content_bucket, operation_ref(operation_id, "input")).delete()


def run_to_completion(client: Any, machine_arn: str, name: str,
                      payload: dict[str, str]) -> dict[str, Any]:
    """啟動一次執行並等到終態；逾時就 fail 並附上目前狀態。"""
    client.start_execution(stateMachineArn=machine_arn, name=name, input=json.dumps(payload))
    arn = execution_arn(machine_arn, name)
    deadline = time.monotonic() + EXECUTION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        described: dict[str, Any] = client.describe_execution(executionArn=arn)
        if described["status"] != "RUNNING":
            return described
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"{name} 超過 {EXECUTION_TIMEOUT_SECONDS} 秒仍在 RUNNING")


# --- 1. 自足的一次真實執行 ----------------------------------------------------


def test_not_recurring_run_succeeds_without_calling_the_model(
        client: Any, machine_arn: str, repository: Repository, seeded_ticket: Ticket) -> None:
    """Given 已有 embedding、同群只有自己，Then 真實 AWS 上 `SUCCEEDED` 走 `NotRecurring`。

    這是 O5 BLOCKED 下唯一跑得到 `SUCCEEDED` 的路徑：`ensure_embedding` 先一致讀表，
    看到 `embedding` 非空就原樣回傳，所以 `EnsureEmbedding`／`AssignCluster`／
    `EvaluateRecurring` 三個節點**一次 Bedrock 都不呼叫**。真的呼叫到 Titan 的話，
    本帳號會回 `ValidationException`（O5 BLOCKED），這次執行就不會是 `SUCCEEDED`。
    """
    operation_id = f"op-ticket-{seeded_ticket.id}"
    described = run_to_completion(client, machine_arn, operation_id, {
        "operation_id": operation_id, "project_id": seeded_ticket.project_id,
        "input_ref": operation_ref(operation_id, "input")})

    assert described["status"] == "SUCCEEDED", described.get("cause")
    output = json.loads(described["output"])
    assert output["is_recurring"] is False
    assert (output["ticket_id"], output["cluster_id"]) \
        == (seeded_ticket.id, seeded_ticket.cluster_id)
    assert "version_id" not in output and "gap_ref" not in output
    events = history(client, machine_arn, operation_id)
    assert entered(events) == NOT_RECURRING_TASKS
    assert [event["stateEnteredEventDetails"]["name"]
            for event in events if event["type"] == "SucceedStateEntered"] == ["NotRecurring"]
    # 向量沒有被改寫 ＝ 這次執行沒有叫過 Titan
    stored = repository.get_meta(ticket_pk(seeded_ticket.id), Ticket, consistent=True)
    assert stored is not None and stored.embedding == VECTOR


# --- 2. 部署結果與快照 --------------------------------------------------------


def test_deployed_definition_is_the_local_file_with_the_arn_substituted(
        client: Any, machine_arn: str) -> None:
    """Given 部署好的 Standard workflow，Then 定義就是本地 v1.json 換掉那一個佔位符。"""
    described = client.describe_state_machine(stateMachineArn=machine_arn)
    assert (described["type"], described["status"]) == ("STANDARD", "ACTIVE")
    resource = json.loads(described["definition"])["States"]["EnsureEmbedding"]["Resource"]
    expected = json.loads(LOCAL_ASL.read_text(encoding="utf-8")
                          .replace(DEFINITION_PLACEHOLDER, resource))
    assert json.loads(described["definition"]) == expected
    assert resource.endswith(":function:training-kb-pipeline-task")   # 直接函式 ARN，無信封


def test_asl_snapshot_in_s3_is_the_deployed_bytes(repository: Repository) -> None:
    """Given 執行教學流程 Rule 10，Then S3 私有快照與部署的定義是同一份 bytes。"""
    key = ASL_SNAPSHOT_KEY.format(pipeline="ticket-analysis", number=1)
    assert repository.get_object(key) == LOCAL_ASL.read_bytes()


# --- 3. 歷史證據（Phase 41 當天的三次 execution）------------------------------


def test_historical_injected_transient_error_is_retried_exactly_twice(
        client: Any, machine_arn: str) -> None:
    """Given 注入的 `TransientError`，Then 三次失敗（首次＋兩次重試）後 `PipelineFailed`。

    `error` 逐字是 `TransientError` 才代表 `ErrorEquals: ["TransientError"]` 真的命中；
    命不中就只會有一次失敗，重試是假的（00A §3.7 指定由本 Phase 實證的那一項）。
    """
    name = HISTORICAL["fault"]
    described = describe_historical(client, machine_arn, name)
    assert (described["status"], described["error"]) == ("FAILED", "PipelineFailed")
    events = history(client, machine_arn, name)
    failures = lambda_failures(events)
    assert [error for error, _ in failures] == ["TransientError"] * 3
    assert all("ticket-analysis:name_gap" in cause for _, cause in failures)
    assert entered(events) == [*NOT_RECURRING_TASKS, "NameGap"]
    assert [event["type"] for event in events][-2:] == ["FailStateEntered", "ExecutionFailed"]


def test_historical_permanent_error_goes_straight_to_catch(
        client: Any, machine_arn: str) -> None:
    """Given 模型節點回 `PermanentError`（O5 BLOCKED），Then 一次失敗就進 Catch。"""
    name = HISTORICAL["model_blocked"]
    described = describe_historical(client, machine_arn, name)
    assert (described["status"], described["error"]) == ("FAILED", "PipelineFailed")
    failures = lambda_failures(history(client, machine_arn, name))
    assert [error for error, _ in failures] == ["PermanentError"]     # 不重試
    assert json.loads(failures[0][1])["errorType"] == "PermanentError"


def test_historical_direct_arn_integration_never_emits_task_failed(
        client: Any, machine_arn: str) -> None:
    """Given 直接函式 ARN，Then 失敗事件是 `LambdaFunctionFailed` 而不是 `TaskFailed`。

    00A §3.7 與 Phase 41 文件寫的是 `taskFailedEventDetails.error`；那個欄位只在
    `arn:aws:states:::lambda:invoke` 這種最佳化整合下才會出現。本 Phase 用直接函式 ARN
    （D-49：沒有 `Payload` 外層），所以實證要看 `lambdaFunctionFailedEventDetails`。
    """
    for name in (HISTORICAL["fault"], HISTORICAL["model_blocked"]):
        describe_historical(client, machine_arn, name)
        events = history(client, machine_arn, name)
        assert [event for event in events if event["type"] == "TaskFailed"] == []
        assert lambda_failures(events)
