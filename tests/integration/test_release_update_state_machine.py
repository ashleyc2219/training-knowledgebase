"""Phase 52 Task 3：真實 AWS 上 `training-kb-release-update` 的執行證據（`aws` marker）。

三組測試：

1. **自足的一次真實執行**（`test_removed_release_retires_and_rewrites_the_index`）：自己種
   一個 Feature、一篇要退役的教學與一篇後繼（slug 都帶時間戳，不會撞名）→ `start-execution`
   → 等到終態 → 斷言 `SUCCEEDED`、節點順序、`status=retired`、`retire.json`、**退役索引頁**
   （D-83）與**版本頁 bytes 未變** → **把自己種的東西全部刪掉**並重建站台索引。
   這是 O5 BLOCKED 下唯一跑得到 `SUCCEEDED` 的路徑：`locate_feature` 在字串層命中、
   `removed` 有命中就不觸發 `safety_net`、`retire_tutorial` 與索引重寫都不呼叫模型。
2. **部署結果與快照**：`describe-state-machine` 與 `stepfunctions/release-update/v1.json`。
3. **歷史證據的快照斷言**：Phase 52 當天跑的四次 execution，證明 Retry／Catch 的錯誤名稱與
   三條 BLOCKED 路徑（O5）的原文。Standard workflow 的 history 預設保留 90 天，過期之後
   這幾條會 `skip`（不是 fail）——要重建證據就照
   `docs/plan/report/phases/2026-09-14-Phase52-REP.md` §3／§4 的指令重跑。

未設 `TKB_RUN_AWS_INTEGRATION=1` 時由 `tests/conftest.py` 自動 skip（00A D-41）；
`TKB_CONTENT_BUCKET` 沒設時整支 skip（`load_settings` 的預設值 `training-kb-content`
在這個帳號不存在，裸跑會對著不存在的 bucket 做事）。

**直接函式 ARN 的失敗事件是 `LambdaFunctionFailed`（`lambdaFunctionFailedEventDetails`），
不是 `TaskFailed`**（Phase 41 已實證，本 Phase 再驗一次）。
"""

import json
import os
import time
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError

from training_kb.clock import now_utc
from training_kb.config import Settings, load_settings
from training_kb.content import PUBLIC_SITE_PREFIX, RETIRED_NOTICE, allocate_version, create_version
from training_kb.keys import feature_pk, operation_ref, step_pk, tutorial_pk, version_pk
from training_kb.models import (
    Feature,
    Release,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
)
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.pipeline_starter import STATE_MACHINE_SEGMENT, state_machine_arns
from training_kb.pipelines.asl import ASL_LOCAL_PATH, ASL_SNAPSHOT_KEY
from training_kb.publishing import (
    Publisher,
    PublishRequest,
    site_diff_key,
    site_key,
    tutorial_index_key,
)
from training_kb.repository import Repository
from training_kb.site import SiteRenderer

pytestmark = pytest.mark.aws

REGION = "us-east-1"
PIPELINE = "release-update"
LOCAL_ASL = ASL_LOCAL_PATH.format(pipeline=PIPELINE, number=1)
DEFINITION_PLACEHOLDER = "${PipelineTaskFunctionArn}"

RETIRE_TASKS = ["LocateFeature", "FindSteps", "SafetyNet", "RetireTutorials"]
"""RETIRE 分支的四個 Task；`PrepareUpdate`／`PublishBatch`／`UpdateAliases` 都被跳過。"""

EXECUTION_TIMEOUT_SECONDS = 120
POLL_SECONDS = 4

HISTORICAL = {
    "retire": "op-release-p52r20260915",
    "retire_resend": "op-release-p52r20260915-resend",
    "retire_fault": "op-release-p52r20260915-fault",
    "update_blocked": "op-release-p52n20260915",
    "safety_net_blocked": "op-release-p52k20260915",
    "locate_semantic_blocked": "op-release-p52u20260915",
}
"""Phase 52 當天的六次 execution；見模組 docstring 第 3 點。"""


@pytest.fixture(scope="module")
def settings() -> Settings:
    if not os.environ.get("TKB_CONTENT_BUCKET"):
        pytest.skip("需要 TKB_CONTENT_BUCKET（load_settings 的預設 bucket 在本帳號不存在）")
    return load_settings()


@pytest.fixture(scope="module")
def client() -> Any:
    return boto3.client("stepfunctions", region_name=REGION)


@pytest.fixture(scope="module")
def table(settings: Settings) -> Any:
    return boto3.resource("dynamodb", region_name=REGION).Table(settings.table_name)


@pytest.fixture(scope="module")
def repository(settings: Settings, table: Any) -> Repository:
    return Repository(table,
                      boto3.resource("s3", region_name=REGION).Bucket(settings.content_bucket))


@pytest.fixture(scope="module")
def machine_arn(settings: Settings) -> str:
    """由 `STATE_MACHINE_NAMES` ＋ STS 帳號推導，**不寫死帳號**。

    刻意依賴 `settings`：它是唯一會 `pytest.skip` 的地方，缺 `TKB_CONTENT_BUCKET` 時
    整支檔（連只看 Step Functions 的那幾條）都要一起 skip，才與模組 docstring 一致。
    """
    assert settings.content_bucket                      # 走過 settings 的 skip 守門
    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    return state_machine_arns(region=REGION, account_id=account)[PIPELINE]


def execution_arn(machine_arn: str, name: str) -> str:
    return f"{machine_arn.replace(STATE_MACHINE_SEGMENT, ':execution:')}:{name}"


def history(client: Any, machine_arn: str, name: str) -> list[dict[str, Any]]:
    pages = client.get_paginator("get_execution_history").paginate(
        executionArn=execution_arn(machine_arn, name), maxResults=200)
    return [event for page in pages for event in page["events"]]


def entered(events: list[dict[str, Any]], kind: str = "TaskStateEntered") -> list[str]:
    return [event["stateEnteredEventDetails"]["name"]
            for event in events if event["type"] == kind]


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
            pytest.skip(f"歷史 execution {name} 已超過保留期；照報告 §4 的指令重跑")
        raise
    return described


def demo_content(topic: str, feature_id: str) -> TutorialContent:
    """**合成資料**：兩步，都引用同一個 Feature，所以反查一定命中。"""
    return TutorialContent(
        title=topic, problem="[合成資料] 整合測試用的問題描述。",
        prerequisites=["[合成資料] 已登入示範環境"],
        steps=[StepDraft(number=1, type=StepType.CLICK_UI,
                         text="[合成資料] 在側欄點選示範項目。", feature_id=feature_id),
               StepDraft(number=2, type=StepType.READ,
                         text="[合成資料] 確認畫面出現示範結果。", feature_id=feature_id)],
        expected_outcome="[合成資料] 看得到示範結果。")


def publish_demo(repository: Repository, operations: OperationCoordinator,
                 slug: str, feature_id: str) -> str:
    """種一篇 active 且已發布 v1 的合成教學，回傳 `version_id`（走真的發布路徑）。"""
    now = now_utc()
    repository.put_meta(Tutorial(slug=slug, current_version=None, topic=f"[合成資料] {slug}",
                                 feature_ids=[feature_id], status="active",
                                 successor=None, cluster_id=None))
    operation_id = f"op-seed-{slug}"
    operations.accept(AcceptOperation(operation_id=operation_id, kind="ticket-analysis",
                                      canonical_id=slug, project_id="demo", now=now))
    plan = allocate_version(slug, operation_id, operations, repository=repository,
                            reason="seed:phase52-integration", rules_applied=[])
    create_version(plan, demo_content(f"[合成資料] {slug}", feature_id), repository)
    publisher = Publisher(repository, SiteRenderer(), operations)
    prepared = publisher.prepare(
        PublishRequest(version_ids=(plan.version_id,), operation_id=operation_id), now=now)
    assert publisher.commit(prepared, now=now).failed is None
    return plan.version_id


def purge(table: Any, bucket: Any, *, slugs: tuple[str, ...], feature_id: str,
          operation_ids: tuple[str, ...]) -> None:
    """把這支測試種的東西全部刪乾淨（`DeleteItem` 只在測試用，不是產品路徑）。"""
    for slug in slugs:
        version_id = f"{slug}@v1"
        for key in (f"tutorials/{slug}/v1.md", f"tutorials/{slug}/v1.diff",
                    PUBLIC_SITE_PREFIX + site_key(version_id),
                    PUBLIC_SITE_PREFIX + site_diff_key(version_id),
                    PUBLIC_SITE_PREFIX + tutorial_index_key(slug)):
            bucket.Object(key).delete()
        for number in (1, 2):
            table.delete_item(Key={"PK": step_pk(version_id, number),
                                   "SK": f"REFERENCES#{feature_pk(feature_id)}"})
        table.delete_item(Key={"PK": version_pk(version_id), "SK": "META"})
        table.delete_item(Key={"PK": tutorial_pk(slug), "SK": "META"})
        table.delete_item(Key={"PK": f"LEASE#{tutorial_pk(slug)}", "SK": "META"})
    table.delete_item(Key={"PK": feature_pk(feature_id), "SK": "META"})
    for operation_id in operation_ids:
        for name in ("input", "successors", "retire"):
            bucket.Object(operation_ref(operation_id, name)).delete()
        for key in bucket.objects.filter(Prefix=f"operations/{operation_id}/"):
            key.delete()
        table.delete_item(Key={"PK": f"OPS#{operation_id}", "SK": "META"})


@pytest.fixture
def seeded(repository: Repository, table: Any) -> Iterator[dict[str, str]]:
    """一個 Feature、一篇待退役教學、一篇後繼、一則 `removed` Release 與它的 ledger。

    `operation_id` 帶時間戳，所以每次跑都是新的 execution 名稱，不會撞到保留期內的舊執行。
    """
    stamp = int(time.time())
    feature_id, feature_name = f"P52IT{stamp}", f"[合成資料] P52 整合測試功能 {stamp}"
    retiring, successor = f"demo-p52it-{stamp}", f"demo-p52it-next-{stamp}"
    release_id = f"p52it{stamp}"
    operation_id = f"op-release-{release_id}"
    now = now_utc()
    operations = OperationCoordinator(repository)
    repository.put_meta(Feature(feature_id=feature_id, name=feature_name, aliases=[],
                                first_seen=now))
    # 後繼那篇刻意引用**另一個** Feature，這樣 removed 的反查只會命中待退役那一篇
    repository.put_meta(Feature(feature_id=f"{feature_id}Other",
                                name=f"{feature_name}（後繼）", aliases=[], first_seen=now))
    publish_demo(repository, operations, successor, f"{feature_id}Other")
    version_id = publish_demo(repository, operations, retiring, feature_id)
    release = Release(id=release_id, source="github_pr", feature=feature_name, kind="removed",
                      evidence=f"[合成資料] PR 移除 {feature_name}", ts=now)
    operations.accept(AcceptOperation(operation_id=operation_id, kind="release",
                                      canonical_id=release_id, project_id="demo", now=now))
    repository.put_object(operation_ref(operation_id, "input"),
                          json.dumps(release.model_dump(mode="json"), ensure_ascii=False,
                                     sort_keys=True).encode("utf-8"),
                          "application/json", if_none_match=False)
    repository.put_object(operation_ref(operation_id, "successors"),
                          json.dumps({retiring: successor}, ensure_ascii=False).encode("utf-8"),
                          "application/json", if_none_match=False)
    yield {"operation_id": operation_id, "release_id": release_id, "retiring": retiring,
           "successor": successor, "version_id": version_id, "feature_id": feature_id}
    bucket = boto3.resource("s3", region_name=REGION).Bucket(load_settings().content_bucket)
    purge(table, bucket, slugs=(retiring, successor), feature_id=feature_id,
          operation_ids=(operation_id, f"op-seed-{retiring}", f"op-seed-{successor}"))
    for number in (1, 2):                       # 後繼那篇的步驟引用的是另一個 Feature
        table.delete_item(Key={"PK": step_pk(f"{successor}@v1", number),
                               "SK": f"REFERENCES#{feature_pk(feature_id + 'Other')}"})
    table.delete_item(Key={"PK": feature_pk(f"{feature_id}Other"), "SK": "META"})
    # 站台索引是可重建的投影，清完資料就重建一次，不留指向已刪教學的連結
    Publisher(repository, SiteRenderer(), operations).write_site_index()


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


def test_removed_release_retires_and_rewrites_the_index(
        client: Any, machine_arn: str, repository: Repository,
        seeded: dict[str, str]) -> None:
    """Given `kind=removed` 命中一篇教學，Then 真實 AWS 上 `SUCCEEDED` 且只走 RETIRE 分支。

    同時是 **D-83 的雲端證據**：退役之後只有教學索引頁被重寫，版本頁的 bytes 完全未變，
    而且沒有任何新版本被發布（F49 的反面：本來就不該有東西要發布）。
    """
    operation_id, slug = seeded["operation_id"], seeded["retiring"]
    version_page = PUBLIC_SITE_PREFIX + site_key(seeded["version_id"])
    before = repository.get_object(version_page)

    described = run_to_completion(client, machine_arn, operation_id, {
        "operation_id": operation_id, "project_id": "demo",
        "input_ref": operation_ref(operation_id, "input")})

    assert described["status"] == "SUCCEEDED", described.get("cause")
    output = json.loads(described["output"])
    assert output["action"] == "RETIRE"
    assert output["prepared_version_ids"] == []
    # RETIRE 不經 PublishBatch／UpdateAliases，所以這兩個欄位根本不會出現
    assert "publish_request_ref" not in output and "alias_update" not in output
    assert output["result_ref"] == operation_ref(operation_id, "retire")
    events = history(client, machine_arn, operation_id)
    assert entered(events) == RETIRE_TASKS                     # 不經 PublishBatch
    assert entered(events, "SucceedStateEntered") == ["Succeeded"]
    assert lambda_failures(events) == []                       # 一次模型呼叫都沒有

    tutorial = repository.get_tutorial(slug)
    assert tutorial is not None
    assert tutorial.status is TutorialStatus.RETIRED
    assert tutorial.successor == seeded["successor"]
    assert tutorial.current_version == seeded["version_id"]    # 歷史保留
    record = json.loads(repository.get_object(
        operation_ref(operation_id, "retire")).decode("utf-8"))
    assert record == [{"slug": slug, "reason": f"release:{seeded['release_id']}",
                       "retired_at": record[0]["retired_at"],
                       "successor": seeded["successor"]}]

    index = repository.get_object(PUBLIC_SITE_PREFIX + tutorial_index_key(slug))
    assert index is not None
    assert RETIRED_NOTICE in index.decode("utf-8")             # D-83
    assert seeded["successor"] in index.decode("utf-8")
    assert repository.get_object(version_page) == before       # 版本頁 bytes 未變


# --- 2. 部署結果與快照 --------------------------------------------------------


def test_deployed_definition_is_the_local_file_with_the_arn_substituted(
        client: Any, machine_arn: str) -> None:
    """Given 部署好的 Standard workflow，Then 定義就是本地 v1.json 換掉那一個佔位符。"""
    described = client.describe_state_machine(stateMachineArn=machine_arn)
    assert (described["name"], described["type"], described["status"]) \
        == ("training-kb-release-update", "STANDARD", "ACTIVE")
    definition = json.loads(described["definition"])
    resource = definition["States"]["LocateFeature"]["Resource"]
    with open(LOCAL_ASL, encoding="utf-8") as handle:
        expected = json.loads(handle.read().replace(DEFINITION_PLACEHOLDER, resource))
    assert definition == expected
    assert resource.endswith(":function:training-kb-pipeline-task")   # 直接函式 ARN，無信封


def test_asl_snapshot_in_s3_is_the_deployed_bytes(repository: Repository) -> None:
    """Given 執行教學流程 Rule 10，Then S3 私有快照與部署的定義是同一份 bytes。"""
    with open(LOCAL_ASL, "rb") as handle:
        local = handle.read()
    assert repository.get_object(ASL_SNAPSHOT_KEY.format(pipeline=PIPELINE, number=1)) == local


# --- 3. 歷史證據（Phase 52 當天的六次 execution）------------------------------


def test_historical_resend_is_idempotent(client: Any, machine_arn: str) -> None:
    """Given 同一個 `operation_id` 重送，Then 一樣 `SUCCEEDED` 且輸出逐字相同。"""
    first = describe_historical(client, machine_arn, HISTORICAL["retire"])
    again = describe_historical(client, machine_arn, HISTORICAL["retire_resend"])
    assert (first["status"], again["status"]) == ("SUCCEEDED", "SUCCEEDED")
    assert json.loads(first["output"]) == json.loads(again["output"])


def test_historical_injected_transient_error_is_retried_exactly_twice(
        client: Any, machine_arn: str) -> None:
    """Given 注入的 `TransientError`，Then 三次失敗（首次＋兩次重試）後 `PipelineFailed`。"""
    name = HISTORICAL["retire_fault"]
    described = describe_historical(client, machine_arn, name)
    assert (described["status"], described["error"]) == ("FAILED", "PipelineFailed")
    events = history(client, machine_arn, name)
    failures = lambda_failures(events)
    assert [error for error, _ in failures] == ["TransientError"] * 3
    assert all("release-update:retire" in cause for _, cause in failures)
    assert entered(events) == RETIRE_TASKS
    assert [event["type"] for event in events][-2:] == ["FailStateEntered", "ExecutionFailed"]


@pytest.mark.parametrize(("key", "node"), [
    ("update_blocked", "PrepareUpdate"),
    ("safety_net_blocked", "SafetyNet"),
    ("locate_semantic_blocked", "LocateFeature"),
])
def test_historical_model_nodes_are_blocked_by_o5(
        client: Any, machine_arn: str, key: str, node: str) -> None:
    """Given O5 BLOCKED，Then 三個需要模型的節點各以 `PermanentError` 一次就進 Catch。

    這是**要保存的 BLOCKED 證據，不是 bug，也不是通過**（`docs/plan/report/
    o5-20260915T030245Z.md`）：`PermanentError` 不在 `RETRY` 的 `ErrorEquals` 裡，
    所以不空等三次，直接 `Catch` → `PipelineFailed`，零新版本公開。
    """
    described = describe_historical(client, machine_arn, HISTORICAL[key])
    assert (described["status"], described["error"]) == ("FAILED", "PipelineFailed")
    events = history(client, machine_arn, HISTORICAL[key])
    assert entered(events)[-1] == node
    failures = lambda_failures(events)
    assert [error for error, _ in failures] == ["PermanentError"]        # 不重試
    assert json.loads(failures[0][1])["errorType"] == "PermanentError"
    assert [event for event in events if event["type"] == "TaskFailed"] == []
