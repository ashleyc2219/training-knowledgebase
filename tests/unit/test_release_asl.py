"""Phase 52 Task 2／3：`release-update` 的 ASL 失敗語意與本機三分支序列（不連 AWS）。

`Retry`／`Catch`／`TimeoutSeconds`／`Fail` state 名稱**一律從 `training_kb.pipelines.asl`
import** 再比對回去（Phase 29 的 `RETRY`／`CATCH`／`TASK_TIMEOUT_SECONDS`／`FAIL_STATE_NAME`／
`task_state`），本檔不抄任何字面值：抄一份就會在 Phase 29 改動時默默分岔（文件現況核對 4）。

CDK 的 Template 斷言不在本檔，在 `tests/unit/infra/test_release_machine.py`——那裡才吃得到
`tests/unit/infra/conftest.py` 的共用 `fake_layer`（**本計畫選擇（2026-09-14）**：不在
`tests/unit/` 再複製一份會分岔的 layer fixture）。
"""

import copy
import json
import pathlib
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws
from test_release_retire import (
    FEATURE,
    NOW,
    OPERATION,
    PROJECT,
    RELEASE_RENAMED,
    RetireRepository,
    accepted_operations,
)

from training_kb.content import (
    DIFF_CONTENT_TYPE,
    MARKDOWN_CONTENT_TYPE,
    VersionPlan,
    create_version,
    diff_key,
    markdown_key,
    put_private_artifact,
    render_markdown,
)
from training_kb.errors import PermanentError, PublishError, TransientError
from training_kb.keys import operation_ref, tutorial_pk
from training_kb.models import (
    Feature,
    ReleaseKind,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialVersion,
)
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.pipelines.asl import (
    ASL_LOCAL_PATH,
    CATCH,
    FAIL_STATE_NAME,
    RETRY,
    TASK_TIMEOUT_SECONDS,
    assert_safe_asl,
    canonical_json,
    task_state,
)
from training_kb.pipelines.common import Deps, task_name
from training_kb.pipelines.release import (
    RELEASE_STATE_FIELDS,
    RELEASE_UPDATE_TASKS,
    run_release_update,
    task_prepare_update,
    task_publish_batch,
    task_update_aliases,
)
from training_kb.repository import Repository

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
ASL_PATH = PROJECT_ROOT / ASL_LOCAL_PATH.format(pipeline="release-update", number=1)
ARN = "${PipelineTaskFunctionArn}"

NEXT = {"LocateFeature": "FindSteps", "FindSteps": "SafetyNet", "SafetyNet": "ChooseAction",
        "PrepareUpdate": "PublishBatch", "PublishBatch": "UpdateAliases",
        "UpdateAliases": "Succeeded", "RetireTutorials": "Succeeded"}
"""七個 Task state 與它們的 `Next`（文件 §6 的表）；`RetireTutorials` 不經 `PublishBatch`。"""

TASK_STATES = tuple(NEXT)

ORDER = ["locate_feature", "find_steps", "safety_net", "prepare_update",
         "publish_batch", "update_aliases", "retire"]
"""`Parameters.task` 的固定值（D-51）；`find_steps` 包的是 Phase 50 的 `find_release_hits`。"""


@pytest.fixture
def asl() -> dict:
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def keep_repo() -> RetireRepository:
    """**空的**圖譜：零個 Feature、零篇教學，所以定位與反查都必然零命中。"""
    repository = RetireRepository()
    repository.put_object(operation_ref(OPERATION, "input"),
                          json.dumps(RELEASE_RENAMED.model_dump(mode="json"),
                                     ensure_ascii=False, sort_keys=True).encode("utf-8"),
                          "application/json", if_none_match=True)
    return repository


@pytest.fixture
def keep_deps(keep_repo: RetireRepository, fake_writer: Any) -> Deps:
    """`fake_writer` 是 `tests/unit/conftest.py` 的 `RecordingWriter`（不連 Bedrock）。

    型別寫 `Any` 而不是 `RecordingWriter`：`tests/unit/conftest.py` 與
    `tests/unit/infra/conftest.py` 在 `prepend` 匯入模式下都叫 `conftest`，
    `from conftest import ...` 會依收集順序拿到不同的那一支（同時跑兩個目錄時直接 collect 失敗）。
    """
    return Deps(operations=accepted_operations(keep_repo, canonical_id="r_42"),
                now=lambda: NOW, repository=keep_repo, writer=fake_writer)


@pytest.fixture
def keep_state() -> dict:
    """接入層交給 `StartExecution` 的三個欄位，一個字都不多（文件 §2）。"""
    return {"operation_id": OPERATION, "project_id": PROJECT,
            "input_ref": operation_ref(OPERATION, "input")}


# --- Task 2：ASL 結構與失敗語意 ----------------------------------------------


def test_every_task_has_the_shared_retry_and_catch(asl: dict) -> None:
    """Given 七個 Task state，Then `Retry`／`Catch`／`TimeoutSeconds` 全部來自 Phase 29。

    JSON 讀回來的是 list、Phase 29 的常數是 tuple，所以拿 `task_state(...)` 產生的同一份
    形狀整個比對，而不是逐欄手寫字面值。
    """
    assert_safe_asl(asl)                                   # Phase 29 的遞迴檢查
    assert len(RETRY) == 2 and RETRY[0]["ErrorEquals"] == ["TransientError"]   # D-53
    for name, next_state in NEXT.items():
        state, expected = asl["States"][name], task_state(ARN, next_state)
        expected["Parameters"] = {"pipeline": "release-update",
                                  "task": state["Parameters"]["task"], "state.$": "$"}
        assert state == expected, name
        assert (state["Retry"], state["Catch"], state["TimeoutSeconds"]) \
            == (list(RETRY), list(CATCH), TASK_TIMEOUT_SECONDS), name
    assert asl["States"][FAIL_STATE_NAME]["Type"] == "Fail"


def test_task_envelope_is_the_direct_function_arn(asl: dict) -> None:
    """Given 直接函式 ARN（D-49），Then 封套只有三欄、沒有 `Payload` 外層。"""
    parameters = [asl["States"][name]["Parameters"] for name in TASK_STATES]
    assert [row["task"] for row in parameters] == ORDER
    assert all(set(row) == {"pipeline", "task", "state.$"} for row in parameters)
    assert all(row["pipeline"] == "release-update" and row["state.$"] == "$"
               for row in parameters)
    assert {asl["States"][name]["Resource"] for name in TASK_STATES} == {ARN}
    # Lambda runtime 把未攔截例外的類別名放進 errorType，ASL 就用它比對
    assert (TransientError.__name__, PermanentError.__name__) == ("TransientError",
                                                                  "PermanentError")


def test_choice_has_default_and_no_retry(asl: dict) -> None:
    """Given `ChooseAction` 是 Choice，Then 有 `Default`、沒有 Retry／Catch／End。"""
    choice = asl["States"]["ChooseAction"]
    assert choice["Type"] == "Choice"
    assert choice["Default"] == "RecordKeep"
    assert "Retry" not in choice and "Catch" not in choice and "End" not in choice
    assert choice["Choices"] == [
        {"Variable": "$.action", "StringEquals": "UPDATE", "Next": "PrepareUpdate"},
        {"Variable": "$.action", "StringEquals": "RETIRE", "Next": "RetireTutorials"}]
    assert asl["States"]["RetireTutorials"]["Next"] == "Succeeded"   # RETIRE 不經 PublishBatch


def test_keep_is_a_business_result_not_a_failure(asl: dict) -> None:
    """Given 零命中，Then `RecordKeep` 把 `action` 正規化成 KEEP 再走唯一的成功終點。"""
    assert asl["States"]["RecordKeep"] == {"Type": "Pass", "Result": "KEEP",
                                           "ResultPath": "$.action", "Next": "Succeeded"}
    succeed = {name for name, state in asl["States"].items() if state["Type"] == "Succeed"}
    assert succeed == {"Succeeded"}
    assert asl["StartAt"] == "LocateFeature"


def test_assert_safe_asl_rejects_the_same_file_without_a_catch(asl: dict) -> None:
    """Given 手動拿掉任何一個 `Catch`，Then 靜態檢查必須轉紅（文件 Task 2 Step 4）。"""
    broken = copy.deepcopy(asl)
    del broken["States"]["RetireTutorials"]["Catch"]
    with pytest.raises(PermanentError, match="RetireTutorials"):
        assert_safe_asl(broken)


def test_definition_file_is_canonical_bytes(asl: dict) -> None:
    """Given 部署與 S3 快照是同一份 bytes，Then 檔案本身就是 `canonical_json` 的輸出。"""
    assert ASL_PATH.read_bytes() == canonical_json(asl)


# --- Task 3：本機三分支序列 ---------------------------------------------------
#
# 器材直接沿用**同一個 Phase 的** `tests/unit/test_release_retire.py`（`tests/unit` 在
# `sys.path` 上，`tests/unit/test_rule_projection.py` 就是同一種寫法）：那支檔已經有一個
# 真的 `Repository` ＋ 記憶體表／bucket，再複製一份只會分岔。


def test_release_update_task_order_and_names() -> None:
    """Given `RELEASE_UPDATE_TASKS`，Then 七個 task 名稱與順序固定（D-51）。"""
    assert [task_name(task) for task in RELEASE_UPDATE_TASKS] == ORDER


def test_asl_task_names_match_python_tasks(asl: dict) -> None:
    """Given ASL 與 Python 兩邊，Then `Parameters.task` 與 `task_name(...)` 完全對得上。"""
    parameters = [asl["States"][name]["Parameters"] for name in TASK_STATES]
    assert {row["task"] for row in parameters} == {task_name(task)
                                                   for task in RELEASE_UPDATE_TASKS}
    assert {row["pipeline"] for row in parameters} == {"release-update"}
    assert all(row["state.$"] == "$" and "Payload" not in row for row in parameters)


def test_zero_hits_ends_as_keep(keep_deps: Deps, keep_state: dict) -> None:
    """Given 定位不到 Feature 又零命中，Then `action="KEEP"`、零版本、零發布（F17、F18）。"""
    result = run_release_update(keep_state, keep_deps)
    assert (result["action"], result["prepared_version_ids"]) == ("KEEP", [])
    assert result["feature_id"] is None and result["hit_refs"] == []
    assert keep_deps.need_repository().published_version_ids == []


def test_keep_state_carries_only_the_fixed_fields(keep_deps: Deps, keep_state: dict) -> None:
    """Given 固定 state（00A §7），Then 輸出沒有全文、evidence 或向量。"""
    result = run_release_update(keep_state, keep_deps)
    assert set(result) <= set(RELEASE_STATE_FIELDS)
    assert len(RELEASE_STATE_FIELDS) == 11


def test_update_only_tasks_are_no_ops_outside_their_branch(keep_state: dict,
                                                           keep_deps: Deps) -> None:
    """Given `action` 不是 UPDATE，Then 三個 UPDATE 專用 Task 都不呼叫 Phase 49–51／25。

    `deps` 沒有 writer，所以任何一個 Task 真的走進去就會以 `PermanentError` 現身；
    這同時證明 RETIRE 與 KEEP 兩條路徑一次模型都不會呼叫。
    """
    state = {**keep_state, "action": "KEEP", "feature_id": None, "hit_refs": [],
             "prepared_version_ids": []}
    without_writer = Deps(operations=keep_deps.operations, now=keep_deps.now,
                          repository=keep_deps.repository)
    assert task_prepare_update(state, without_writer)["prepared_version_ids"] == []
    assert task_publish_batch(state, without_writer) == state
    assert task_update_aliases(state, without_writer) == state


# --- Task 3 補充（修正回合 1）：UPDATE 分支的三個 Task 真的做事的那一半 ---------
#
# review Important 2：原本只有「不是我的分支 → 原樣回傳」的測試。這裡補上
# `task_update_aliases` 的成功與撞名，以及 `task_publish_batch` 的成功（含
# `publish_request_ref` 可讀）與交易條件不符。後者需要真的
# `Repository.transact_write`（走 `table.meta.client`），所以用 moto，形狀照
# `tests/unit/test_publisher_single.py`。


def renamed_state(**extra: Any) -> dict:
    """`ChooseAction` 判成 UPDATE 之後的 state（只有 ID 與 ref）。"""
    return {"operation_id": OPERATION, "project_id": PROJECT,
            "input_ref": operation_ref(OPERATION, "input"), "release_id": "r_42",
            "feature_id": FEATURE, "action": "UPDATE", "hit_refs": [],
            "prepared_version_ids": [], **extra}


@pytest.fixture
def alias_repo() -> RetireRepository:
    """只有一個 Feature `Prepare`（改名前的別名還沒收進去）與 renamed 事件的 canonical 輸入。"""
    repository = RetireRepository()
    repository.add_feature(FEATURE)
    repository.put_object(operation_ref(OPERATION, "input"),
                          json.dumps(RELEASE_RENAMED.model_dump(mode="json"),
                                     ensure_ascii=False, sort_keys=True).encode("utf-8"),
                          "application/json", if_none_match=True)
    return repository


@pytest.fixture
def alias_deps(alias_repo: RetireRepository) -> Deps:
    return Deps(operations=accepted_operations(alias_repo, canonical_id="r_42"),
                now=lambda: NOW, repository=alias_repo)


def test_renamed_update_folds_the_old_name_into_aliases(
        alias_repo: RetireRepository, alias_deps: Deps) -> None:
    """Given `renamed` 走到 `UpdateAliases`，Then 顯示名稱換掉、舊名收進 aliases、**PK 不變**。"""
    before = alias_repo.get_feature(FEATURE)
    result = task_update_aliases(renamed_state(), alias_deps)

    assert result["alias_update"] == {"feature_id": FEATURE, "name": "Prepare",
                                      "aliases": ["Meeting Summary"]}
    after = alias_repo.get_feature(FEATURE)
    assert after is not None and before is not None
    assert after.feature_id == before.feature_id == FEATURE      # 主鍵不動（D06）
    assert (after.name, after.aliases) == ("Prepare", ["Meeting Summary"])
    assert set(result) <= set(RELEASE_STATE_FIELDS)


def test_alias_clash_fails_the_task_instead_of_degrading_to_keep(
        alias_repo: RetireRepository, alias_deps: Deps) -> None:
    """Given 另一個 Feature 已經叫 `Meeting Summary`，Then `PermanentError` 從 Task 傳出（D07）。

    不降級成 KEEP、也不吞掉：`PermanentError` 一路往外，由 ASL 的 Catch 導向
    `PipelineFailed`。失敗之後被改名的那個 Feature 一個欄位都沒變（全有或全無）。
    """
    alias_repo.add_feature("Legacy", name="Meeting Summary")
    with pytest.raises(PermanentError, match="Legacy"):
        task_update_aliases(renamed_state(), alias_deps)
    unchanged = alias_repo.get_feature(FEATURE)
    assert unchanged is not None and (unchanged.name, unchanged.aliases) == (FEATURE, [])


def test_changed_release_does_not_touch_aliases(
        alias_repo: RetireRepository, alias_deps: Deps) -> None:
    """Given `kind=changed`（沒有改名），Then `UpdateAliases` 原樣回傳，Feature 不動。"""
    changed = RELEASE_RENAMED.model_copy(
        update={"kind": ReleaseKind.CHANGED, "old_name": None, "new_name": None})
    alias_repo.put_object(operation_ref(OPERATION, "input"),
                          json.dumps(changed.model_dump(mode="json"), ensure_ascii=False,
                                     sort_keys=True).encode("utf-8"),
                          "application/json", if_none_match=False)
    state = renamed_state()
    assert task_update_aliases(state, alias_deps) == state
    feature = alias_repo.get_feature(FEATURE)
    assert feature is not None and (feature.name, feature.aliases) == (FEATURE, [])


# --- `task_publish_batch`（moto：要真的 `Repository.transact_write`）------------

MOTO_REGION = "us-west-2"
TABLE_NAME = "training_kb"
BUCKET_NAME = "training-kb-content"
SLUG = "prepare-meeting"
V1, V2 = f"{SLUG}@v1", f"{SLUG}@v2"


def publish_content() -> TutorialContent:
    return TutorialContent(
        title="準備會議", problem="會議前的準備步驟散在多個頁面，新人找不到。",
        prerequisites=["已登入工作區"],
        steps=[StepDraft(number=number, type=StepType.CLICK_UI,
                         text=f"第 {number} 步。", feature_id=FEATURE)
               for number in (1, 2)],
        expected_outcome="會議開始前已備妥議程與摘要。")


class RejectingRepository(Repository):
    """真的 `Repository`，只有 `transact_write` 可以被指定成「條件不符」。

    `reject_index` 是 `None` 時完全走父類別（真的送交易給 moto）；設成 0 就模擬
    DynamoDB 擋下第一篇的切換——那是**回傳值**不是例外（Phase 07 的契約），所以這是
    唯一能在不改產品程式的前提下走到 `PublishResult.failed` 的接縫。
    """

    reject_index: int | None = None

    def __init__(self, table: Any, bucket: Any) -> None:
        super().__init__(table, bucket)
        self.bucket = bucket

    def transact_write(self, items: Any) -> int | None:
        if self.reject_index is not None:
            return self.reject_index
        return super().transact_write(items)


@pytest.fixture
def moto_repo() -> Iterator[RejectingRepository]:
    with mock_aws():
        table = boto3.resource("dynamodb", region_name=MOTO_REGION).create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"},
                       {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST")
        table.wait_until_exists()
        bucket = boto3.resource("s3", region_name=MOTO_REGION).Bucket(BUCKET_NAME)
        bucket.create(CreateBucketConfiguration={"LocationConstraint": MOTO_REGION})
        yield RejectingRepository(table, bucket)


@pytest.fixture
def publish_deps(moto_repo: RejectingRepository) -> Deps:
    """已發布的 v1 ＋ 由 Phase 23 `create_version` 寫好的未發布 v2（`prepared_version_ids`）。"""
    moto_repo.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    moto_repo.put_meta(Tutorial(slug=SLUG, current_version=None, topic="準備會議",
                                feature_ids=[FEATURE], status="active",
                                successor=None, cluster_id=None))
    moto_repo.put_meta(TutorialVersion(version_id=V1, slug=SLUG, supersedes=None,
                                       reason="gap:c12", rules_applied=[],
                                       s3_key=markdown_key(SLUG, 1), published_at=NOW))
    put_private_artifact(moto_repo, markdown_key(SLUG, 1),
                         render_markdown(publish_content()), MARKDOWN_CONTENT_TYPE)
    put_private_artifact(moto_repo, diff_key(SLUG, 1), "", DIFF_CONTENT_TYPE)
    pk = tutorial_pk(SLUG)
    moto_repo.update_meta(pk, {"current_version": V1},
                          expected_revision=moto_repo.revision_of(pk))
    create_version(VersionPlan(version_id=V2, slug=SLUG, number=2, supersedes=V1,
                               reason="release:r_42", rules_applied=(),
                               operation_id=OPERATION), publish_content(), moto_repo)
    operations = OperationCoordinator(moto_repo)
    operations.accept(AcceptOperation(operation_id=OPERATION, kind="release-update",
                                      canonical_id="r_42", project_id=PROJECT, now=NOW))
    return Deps(operations=operations, now=lambda: NOW, repository=moto_repo)


def publish_state() -> dict:
    return {"operation_id": OPERATION, "project_id": PROJECT,
            "input_ref": operation_ref(OPERATION, "input"), "release_id": "r_42",
            "feature_id": FEATURE, "action": "UPDATE", "hit_refs": [f"{V2}#1"],
            "prepared_version_ids": [V2]}


def test_publish_batch_writes_a_readable_publish_request(
        moto_repo: RejectingRepository, publish_deps: Deps) -> None:
    """Given 整批發布成功，Then `publish_request_ref` 指向**真的存在**的紀錄物件。

    review Important 1：這個 ref 以前指向一個 release-update 從來沒寫過的 key。
    內容與 P48 `task_prepare_batch` 同形狀（`version_ids` ＋ `staged_keys`）。
    """
    result = task_publish_batch(publish_state(), publish_deps)

    ref = result["publish_request_ref"]
    assert ref == operation_ref(OPERATION, "publish-request")
    body = moto_repo.get_object(str(ref))
    assert body is not None, f"{ref} 不存在"
    assert json.loads(body.decode("utf-8")) == {
        "version_ids": [V2],
        "staged_keys": [f"operations/{OPERATION}/site/tutorials/{SLUG}/v2.diff.txt",
                        f"operations/{OPERATION}/site/tutorials/{SLUG}/v2.html"]}
    version = moto_repo.get_version(V2)
    assert version is not None and version.published_at == NOW
    tutorial = moto_repo.get_tutorial(SLUG)
    assert tutorial is not None and tutorial.current_version == V2
    assert set(result) <= set(RELEASE_STATE_FIELDS)


def test_publish_batch_raises_when_the_transaction_is_rejected(
        moto_repo: RejectingRepository, publish_deps: Deps) -> None:
    """Given 交易條件不符（`PublishResult.failed` 有值），Then `PublishError` 往外丟。

    回一個看起來正常的 state 會讓執行走到 `Succeeded`，從外面看不出這次其實沒發布
    （設計 §14.2、F49）。丟出來之後 `current_version` 沒被切、`site/` 沒有新檔。
    """
    moto_repo.reject_index = 0
    with pytest.raises(PublishError, match="publish_rejected"):
        task_publish_batch(publish_state(), publish_deps)

    tutorial = moto_repo.get_tutorial(SLUG)
    assert tutorial is not None and tutorial.current_version == V1
    version = moto_repo.get_version(V2)
    assert version is not None and version.published_at is None
    assert [item.key for item in moto_repo.bucket.objects.filter(Prefix="site/")] == []
    # 失敗之後「本來要發布什麼」仍然留著，P59 的補償重送才有輸入
    assert moto_repo.get_object(operation_ref(OPERATION, "publish-request")) is not None
