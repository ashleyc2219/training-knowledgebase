"""Phase 48 Task 3：真實 AWS 上 `training-kb-feedback-review` 的執行證據（`aws` marker）。

四組測試，每一組都**自足**（seed → start → 等終態 → 斷言 → 清理），不依賴別的 Phase 留在
正式表裡的資料：

1. **部署結果**：部署中的定義就是本地 `v1.json` 換掉那一個佔位符；S3 私有快照與它逐 byte
   相同（`RUN` Rule 10）。
2. **每日排程**：`aws scheduler get-schedule` 的 cron／時區／input／目標 ARN（`REV` Rule 1）。
3. **`{"mode":"staging"}`**：`ListTargets` 一次就 `PermanentError` → Catch → `PipelineFailed`，
   **不重試、不讀資料、零次 Bedrock**。
4. **零弱教學目標**：這是 **O5 BLOCKED 之下唯一跑得到 `SUCCEEDED` 的雲端路徑**——五個 Task
   全部進去、`prepared_version_ids == []`、`publish_request_ref is null`、零次 Bedrock。
   前置由測試自己補齊（見 `rules_for_existing_groups`）。
5. **有目標的路徑（O5 BLOCKED 證據）**：測試自己種五筆同類回饋造出一個新的 candidate 組，
   `propose_candidate` 必然要打模型 → `PermanentError`（`generation_model_id 還沒有實測值`）
   → Catch → `PipelineFailed`。**那是 BLOCKED 證據，不是 bug，也不是通過。**

未設 `TKB_RUN_AWS_INTEGRATION=1` 時由 `tests/conftest.py` 自動 skip（00A D-41）；
`TKB_CONTENT_BUCKET` 沒設時整支 skip（`load_settings` 的預設值 `training-kb-content`
在這個帳號不存在，裸跑會對著不存在的 bucket 做事）。

**直接函式 ARN 的失敗事件是 `LambdaFunctionFailed`（`lambdaFunctionFailedEventDetails`），
不是 `TaskFailed`**（Phase 41 §7 A2 已在 `ticket-analysis` 上實證，本檔在
`feedback-review` 上再驗一次）。

**O3 FAIL**：本檔沒有任何一次執行走到發布切點（O5 先擋住），所以**不宣稱**多篇整批發布
已驗收；整批切點的可觀察結果在 moto 上（`tests/integration/test_batch_publish_cutpoints.py`
與 `tests/unit/test_feedback_review_flow.py`）。
"""

import json
import os
import pathlib
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest

from training_kb.clock import now_utc
from training_kb.config import Settings, load_settings
from training_kb.ingress import DEFAULT_FEEDBACK_CATEGORIES
from training_kb.keys import feedback_pk, operation_ref, ops_pk, rule_pk, version_pk
from training_kb.models import AuthoringRule, Feedback, RuleStatus, StepType, Tutorial
from training_kb.pipeline_starter import STATE_MACHINE_SEGMENT, state_machine_arns
from training_kb.pipelines.asl import ASL_LOCAL_PATH, ASL_SNAPSHOT_KEY
from training_kb.pipelines.feedback import (
    candidate_groups,
    candidate_rule_id,
    review_operation_id,
    select_weak_targets,
)
from training_kb.repository import Repository, item_to_model

pytestmark = pytest.mark.aws

REGION = "us-east-1"
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCAL_ASL = PROJECT_ROOT / ASL_LOCAL_PATH.format(pipeline="feedback-review", number=1)
DEFINITION_PLACEHOLDER = "${PipelineTaskFunctionArn}"
REVIEW_TASKS = ["ListTargets", "EvaluateTargets", "PrepareBatch", "InspectBatch", "CommitBatch"]
SCHEDULE_NAME = "training-kb-feedback-review-daily"
CATEGORY = "Button not found"

EXECUTION_TIMEOUT_SECONDS = 120
POLL_SECONDS = 3


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
    """由 `STATE_MACHINE_NAMES` ＋ STS 帳號推導，**不寫死帳號**（同 P41 的整合測試）。"""
    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    return state_machine_arns(region=REGION, account_id=account)["feedback-review"]


@pytest.fixture(scope="module")
def table(settings: Settings) -> Any:
    return boto3.resource("dynamodb", region_name=REGION).Table(settings.table_name)


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


def run_to_completion(client: Any, machine_arn: str, name: str,
                      payload: dict[str, str]) -> dict[str, Any]:
    """啟動一次執行並等到終態；逾時就 fail 並附上目前狀態。

    執行名稱帶時間戳（不是裸 `operation_id`）：同一天重跑同一條測試才不會撞到
    `ExecutionAlreadyExists`。正式路徑的名稱仍由 `ingress.execution_name(operation_id)` 決定。
    """
    client.start_execution(stateMachineArn=machine_arn, name=name, input=json.dumps(payload))
    arn = execution_arn(machine_arn, name)
    deadline = time.monotonic() + EXECUTION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        described: dict[str, Any] = client.describe_execution(executionArn=arn)
        if described["status"] != "RUNNING":
            return described
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"{name} 超過 {EXECUTION_TIMEOUT_SECONDS} 秒仍在 RUNNING")


def stamped(prefix: str) -> str:
    return f"p48-{prefix}-{int(time.time())}"


def today_operation_id(settings: Settings) -> str:
    """雲端那一次執行會用到的當日 `operation_id`；與 Lambda 內算出來的是同一個函式。"""
    class _Deps:
        def need_settings(self) -> Settings:
            return settings

        def now(self) -> datetime:
            return datetime.now(UTC)

    return review_operation_id({}, _Deps())   # type: ignore[arg-type]


def published_targets(repository: Repository) -> list[str]:
    """目前表裡 active 且 current 已發布的版本 ID；與 `_review_targets` 同一套條件。"""
    found: list[str] = []
    for item in repository.scan_entity("TUTORIAL"):
        tutorial = item_to_model(item, Tutorial)
        if tutorial.status.value != "active" or tutorial.current_version is None:
            continue
        version = repository.get_version(tutorial.current_version)
        if version is not None and version.published_at is not None:
            found.append(version.version_id)
    return sorted(found)


@pytest.fixture
def rules_for_existing_groups(repository: Repository, table: Any) -> Iterator[list[str]]:
    """讓「零次 Bedrock」成立的前置：每個既有 candidate 組都先有一條規則。

    `propose_candidate` 在 `RULE#<rule_id>` 已存在時**原樣回傳既有規則、不再打模型**
    （P47 §7.2 第 2 點），所以只要把既有證據組對應的規則先放進表裡，整條流程就一次模型
    都不用呼叫。放進去的是**明示的合成資料**（`rule` 以 `[合成資料]` 開頭），而且只建立
    本來不存在的那幾條，測試結束一律刪掉，不留在正式表裡。
    """
    created: list[str] = []
    for version_id in published_targets(repository):
        for group in candidate_groups(repository.list_feedback_of_version(version_id),
                                      DEFAULT_FEEDBACK_CATEGORIES):
            rule_id = candidate_rule_id(group)
            if repository.get_meta(rule_pk(rule_id), AuthoringRule) is not None:
                continue
            repository.put_meta(AuthoringRule(
                rule_id=rule_id, rule="[合成資料] Phase 48 整合測試的佔位規則，勿當成模型輸出。",
                applies_when=StepType.CLICK_UI, evidence=list(group.feedback_ids),
                status=RuleStatus.CANDIDATE, applied_to=[], derived_from=group.version_id))
            created.append(rule_id)
    yield created
    for rule_id in created:
        table.delete_item(Key={"PK": rule_pk(rule_id), "SK": "META"})


@pytest.fixture
def seeded_candidate_group(repository: Repository, table: Any) -> Iterator[str]:
    """五筆**合成**同類回饋掛在某一篇既有已發布版本上，造出一個沒有規則的 candidate 組。

    `rating=5` 是刻意的：這一組只觸發 candidate 分支，不會變成弱教學，所以雲端這次執行
    不會試圖建版或發布（O3 FAIL，不在這裡碰發布切點）。用完把五筆 item 與五條邊都刪掉。
    """
    targets = published_targets(repository)
    if not targets:
        pytest.skip("正式表裡沒有 active 且已發布的版本，種不出 candidate 組")
    version_id = targets[0]
    stamp = int(time.time())
    ids = [f"f_p48sm{stamp}_{index}" for index in range(5)]
    for feedback_id in ids:
        repository.put_meta(Feedback(id=feedback_id, tutorial_version=version_id, rating=5,
                                     category=CATEGORY, comment="[合成資料] Phase 48 整合測試",
                                     user=f"p48-{stamp}", ts=now_utc()))
        repository.put_edge(feedback_pk(feedback_id), "REFERS_TO", version_pk(version_id))
    yield version_id
    for feedback_id in ids:
        table.delete_item(Key={"PK": feedback_pk(feedback_id), "SK": "META"})
        table.delete_item(Key={"PK": feedback_pk(feedback_id),
                               "SK": f"REFERS_TO#{version_pk(version_id)}"})


@pytest.fixture
def clean_operation(settings: Settings, table: Any) -> Iterator[str]:
    """本次執行會用到的當日 operation；測試結束把 `OPS#` 與它底下的物件清掉。

    留著不清會讓隔天以前的重跑都命中同一筆 `duplicate`，也會把合成資料留在正式表裡。
    """
    operation_id = today_operation_id(settings)
    yield operation_id
    table.delete_item(Key={"PK": ops_pk(operation_id), "SK": "META"})
    bucket = boto3.resource("s3", region_name=REGION).Bucket(settings.content_bucket)
    for name in ("review-no-change", "review-result"):
        bucket.Object(operation_ref(operation_id, name)).delete()


# --- 1. 部署結果與快照 --------------------------------------------------------


def test_deployed_definition_is_the_local_file_with_the_arn_substituted(
        client: Any, machine_arn: str) -> None:
    """Given 部署好的 Standard workflow，Then 定義就是本地 v1.json 換掉那一個佔位符。"""
    described = client.describe_state_machine(stateMachineArn=machine_arn)
    assert (described["type"], described["status"]) == ("STANDARD", "ACTIVE")
    definition = json.loads(described["definition"])
    resource = definition["States"]["ListTargets"]["Resource"]
    expected = json.loads(LOCAL_ASL.read_text(encoding="utf-8")
                          .replace(DEFINITION_PLACEHOLDER, resource))
    assert definition == expected
    assert resource.endswith(":function:training-kb-pipeline-task")   # 直接函式 ARN，無信封


def test_asl_snapshot_in_s3_is_the_deployed_bytes(repository: Repository) -> None:
    """Given 執行教學流程 Rule 10，Then S3 私有快照與部署的定義是同一份 bytes。"""
    key = ASL_SNAPSHOT_KEY.format(pipeline="feedback-review", number=1)
    assert repository.get_object(key) == LOCAL_ASL.read_bytes()


# --- 2. 每日排程（`REV` Rule 1）-----------------------------------------------


def test_daily_schedule_starts_only_this_machine_at_utc_0030(machine_arn: str) -> None:
    """Given EventBridge Scheduler，Then 每天 UTC 00:30 用固定 input 啟動這一條 state machine。"""
    schedule = boto3.client("scheduler", region_name=REGION).get_schedule(Name=SCHEDULE_NAME)
    assert schedule["ScheduleExpression"] == "cron(30 0 * * ? *)"
    assert schedule["ScheduleExpressionTimezone"] == "UTC"
    assert schedule["FlexibleTimeWindow"]["Mode"] == "OFF"      # 準點，不在窗口內隨機延後
    assert schedule["State"] == "ENABLED"
    assert schedule["Target"]["Arn"] == machine_arn
    assert json.loads(schedule["Target"]["Input"]) == {"mode": "formal"}


# --- 3. 不需要模型的失敗路徑 --------------------------------------------------


def test_unknown_mode_fails_at_list_targets_without_calling_the_model(
        client: Any, machine_arn: str) -> None:
    """Given `{"mode":"staging"}`，Then `ListTargets` 一次 `PermanentError` 就進 Catch。

    `PermanentError` 刻意不在 `RETRY[0].ErrorEquals` 裡，所以**只會失敗一次**（不是三次）：
    資料確定不合法時空等三次沒有意義（00A §3.7）。
    """
    name = stamped("staging")
    described = run_to_completion(client, machine_arn, name, {"mode": "staging"})
    assert (described["status"], described["error"]) == ("FAILED", "PipelineFailed")
    events = history(client, machine_arn, name)
    assert entered(events) == ["ListTargets"]         # 連 EvaluateTargets 都沒進去
    failures = lambda_failures(events)
    assert [error for error, _ in failures] == ["PermanentError"]      # 不重試
    assert "未知的 review mode" in json.loads(failures[0][1])["errorMessage"]
    assert [event for event in events if event["type"] == "TaskFailed"] == []   # 直接函式 ARN
    assert [event["type"] for event in events][-2:] == ["FailStateEntered", "ExecutionFailed"]


# --- 4. O5 BLOCKED 之下唯一跑得到 SUCCEEDED 的路徑 ----------------------------


def test_zero_weak_target_run_succeeds_without_calling_the_model(
        client: Any, machine_arn: str, repository: Repository, settings: Settings,
        rules_for_existing_groups: list[str], clean_operation: str) -> None:
    """Given 沒有弱教學、每個 candidate 組都已有規則，Then 五個 Task 全跑完且 `SUCCEEDED`。

    這條是 §8.1 驗收矩陣的 Boundary 那一列在雲端的實證：`prepared_version_ids == []`、
    `publish_request_ref is null`、**零次 Bedrock**，所以 O5 BLOCKED 擋不住它。
    有弱教學時這條路一定會打模型，屆時自動 skip 而不是硬跑成失敗。
    """
    weak = select_weak_targets(repository=repository, mode="formal", now=datetime.now(UTC),
                               thresholds=settings.thresholds)
    if weak:
        pytest.skip(f"正式表裡目前有弱教學（{[row.version_id for row in weak]}），會需要模型")

    name = stamped("succeeded")
    described = run_to_completion(client, machine_arn, name, {"mode": "formal"})
    assert described["status"] == "SUCCEEDED", described.get("cause")
    output = json.loads(described["output"])
    assert output["operation_id"] == clean_operation
    assert output["prepared_version_ids"] == [] and output["publish_request_ref"] is None
    assert output["target_version_ids"] == published_targets(repository)
    assert set(output) == {"operation_id", "project_id", "mode", "target_version_ids",
                           "candidate_rule_ids", "prepared_version_ids",
                           "publish_request_ref", "result_ref"}          # 00A §7 八個欄位
    events = history(client, machine_arn, name)
    assert entered(events) == REVIEW_TASKS
    assert [event["stateEnteredEventDetails"]["name"]
            for event in events if event["type"] == "SucceedStateEntered"] == ["Succeeded"]
    body = repository.get_object(str(output["result_ref"]))
    assert body is not None
    assert json.loads(body.decode("utf-8"))["published_version_ids"] == []


# --- 5. 有目標的路徑：O5 BLOCKED 證據（保留 FAIL，不宣稱通過）-----------------


def test_a_candidate_group_without_a_rule_is_blocked_by_o5(
        client: Any, machine_arn: str, seeded_candidate_group: str,
        clean_operation: str) -> None:
    """Given 一個還沒有規則的 candidate 組，Then `EvaluateTargets` 走 Catch → `PipelineFailed`。

    **這是 O5 BLOCKED 的證據，不是 bug，也不是通過**（`docs/plan/report/o5-20260915T030245Z.md`）：
    `propose_candidate` 一定要呼叫生成模型，而 `TKB_GENERATION_MODEL_ID` 沒有實測值，
    `BedrockWriter` 當場丟 `PermanentError`。整次執行 `FAILED`，**沒有任何 `published_at`
    被切換、`site/` 沒有新物件**——O3 的發布切點在這條路上根本到不了。
    """
    name = stamped("blocked")
    described = run_to_completion(client, machine_arn, name, {"mode": "formal"})
    assert (described["status"], described["error"]) == ("FAILED", "PipelineFailed")
    events = history(client, machine_arn, name)
    assert entered(events) == ["ListTargets", "EvaluateTargets"]   # 沒有走到發布三個 Task
    failures = lambda_failures(events)
    assert [error for error, _ in failures] == ["PermanentError"]
    cause = json.loads(failures[0][1])
    assert cause["errorType"] == "PermanentError"
    assert "generation_model_id" in cause["errorMessage"]           # O5 原文
    assert [event for event in events if event["type"] == "TaskFailed"] == []
