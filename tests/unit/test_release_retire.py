"""Phase 52 Task 1：`kind=removed` 的 RETIRE 分支與 D-83 退役索引頁重寫（不連 AWS）。

本檔自備全部器材，**不動** `tests/unit/conftest.py`（COMMON.md R3.6 只有 P55 能改）：

- `repo` 是一個**真的** `Repository`，只有底下的表換成 `FakeTable`、bucket 換成 `FakeBucket`
  （形狀照 `tests/unit/test_release_update.py`，那支檔證明過 `put_meta`／`update_meta` 的
  compare-and-swap 與 `IfNoneMatch` 都跑得起來）。所以 `retire_tutorial`（P26）、
  `resolve_successor`、`Publisher._write_tutorial_index`（P24）跑的都是真程式。
- `ops` 是真的 `OperationCoordinator`，父 operation `op-release-r_43` 在 fixture 就接受好
  （雲端由 P32 的接入層寫，本機自己補）。
- **一個模型呼叫都不會發生**：`deps.writer` 是 `NoModelWriter`，任何一次 `embed`／
  `generate_json` 都當場 `AssertionError`。RETIRE 與 KEEP 兩條分支能在 O5 BLOCKED 的
  真實 AWS 上跑到 `SUCCEEDED`，靠的就是這件事。

固定種子：`prepare-meeting@v2`（命中，維護者指定後繼 `share-summary`）、
`notification-settings@v1`（命中，未指定後繼 → F19 仍退役）、`share-summary@v1`（後繼本身，
必須 active 且有已發布版，`resolve_successor` 才會採用）。
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.exceptions import ClientError

from training_kb.clock import to_iso
from training_kb.content import (
    PUBLIC_SITE_PREFIX,
    RETIRED_NOTICE,
    markdown_key,
    render_markdown,
)
from training_kb.errors import PermanentError
from training_kb.keys import META, feature_pk, operation_ref, step_pk
from training_kb.models import (
    Feature,
    Release,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialVersion,
)
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.pipelines.common import Deps
from training_kb.pipelines.release import (
    RELEASE_STATE_FIELDS,
    StepHit,
    retire_for_release,
    run_release_update,
    task_retire,
    task_safety_net,
)
from training_kb.publishing import site_key, tutorial_index_key
from training_kb.repository import Repository

NOW = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
PROJECT = "demo"
OPERATION = "op-release-r_43"
FEATURE = "Prepare"
A, C, SUCCESSOR = "prepare-meeting", "notification-settings", "share-summary"
OTHER_FEATURE = "Share"
A_V2, C_V1, SUCCESSOR_V1 = f"{A}@v2", f"{C}@v1", f"{SUCCESSOR}@v1"

HITS_TWO = (StepHit(C, C_V1, 1), StepHit(A, A_V2, 3))
"""刻意反序傳入，證明 `retire_for_release` 的輸出依 slug 升序。"""

HITS_STEP3 = (StepHit(A, A_V2, 3),)

RELEASE_REMOVED = Release(id="r_43", source="github_pr", feature=FEATURE, kind="removed",
                          evidence="PR #43 remove Prepare", ts=NOW)
RELEASE_RENAMED = Release(id="r_42", source="github_pr", feature=FEATURE, kind="renamed",
                          old_name="Meeting Summary", new_name=FEATURE,
                          evidence="PR #42 rename", ts=NOW)


def content_of(slug: str) -> TutorialContent:
    """任一篇教學的最小合法原文；退役不看內容，所以三篇共用同一個形狀。"""
    return TutorialContent(
        title=f"{slug} 教學", problem="示範用的問題描述。", prerequisites=["已登入"],
        steps=[StepDraft(number=number, type=StepType.CLICK_UI, text=f"第 {number} 步。",
                         feature_id=FEATURE) for number in (1, 2, 3)],
        expected_outcome="示範用的預期結果。")


# --- 假的儲存層：真的 `Repository`，只有底下的表與 bucket 換成記憶體 ----------


def _conditional_check_failed(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, operation)


def _matches(item: Mapping[str, Any], condition: Any) -> bool:
    expression = condition.get_expression()
    operator, values = expression["operator"], expression["values"]
    if operator == "AND":
        return all(_matches(item, value) for value in values)
    actual = item.get(values[0].name)
    if operator == "=":
        return actual == values[1]
    if operator == "begins_with":
        return isinstance(actual, str) and actual.startswith(values[1])
    raise AssertionError(f"假表不支援的條件：{operator}")


class FakeTable:
    """記憶體表：只實作 `Repository` 真的會送出的四個 boto3 操作與兩種條件式。"""

    name = "fake_training_kb"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def put_item(self, **arguments: Any) -> dict[str, Any]:
        item = dict(arguments["Item"])
        key = (str(item["PK"]), str(item["SK"]))
        condition = arguments.get("ConditionExpression")
        if condition == "attribute_not_exists(PK)" and key in self.items:
            raise _conditional_check_failed("PutItem")
        if condition == "#revision = :current":
            values = arguments["ExpressionAttributeValues"]
            if self.items.get(key, {}).get("_revision") != values[":current"]:
                raise _conditional_check_failed("PutItem")
        self.items[key] = item
        return {}

    def get_item(self, **arguments: Any) -> dict[str, Any]:
        key = arguments["Key"]
        item = self.items.get((str(key["PK"]), str(key["SK"])))
        return {} if item is None else {"Item": dict(item)}

    def update_item(self, **arguments: Any) -> dict[str, Any]:
        key = arguments["Key"]
        item = self.items.get((str(key["PK"]), str(key["SK"])))
        names: Mapping[str, str] = arguments["ExpressionAttributeNames"]
        values: Mapping[str, Any] = arguments["ExpressionAttributeValues"]
        field_name, operator, placeholder = str(arguments["ConditionExpression"]).split(" ")
        assert operator == "=", f"假表不支援的條件：{operator}"
        if item is None or item.get(names[field_name]) != values[placeholder]:
            raise _conditional_check_failed("UpdateItem")
        expression = str(arguments["UpdateExpression"])
        assert expression.startswith("SET "), f"假表不支援的更新式：{expression}"
        for assignment in expression.removeprefix("SET ").split(", "):
            name, separator, value = assignment.partition(" = ")
            assert separator, f"假表不支援的更新式：{expression}"
            item[names[name]] = values[value]
        return {}

    def query(self, **arguments: Any) -> dict[str, Any]:
        rows = [dict(item) for item in self.items.values()]
        if arguments.get("IndexName") == "by_target":
            rows = [{"PK": row["PK"], "SK": row["SK"], "target": row["target"]}
                    for row in rows if "target" in row]
        found = [row for row in rows if _matches(row, arguments["KeyConditionExpression"])]
        return {"Items": sorted(found, key=lambda row: (str(row["PK"]), str(row["SK"])))}

    def scan(self, **arguments: Any) -> dict[str, Any]:
        condition = arguments.get("FilterExpression")
        return {"Items": [dict(item) for item in self.items.values()
                          if condition is None or _matches(item, condition)]}


class _MissingKey(ClientError):
    def __init__(self, key: str) -> None:
        super().__init__({"Error": {"Code": "NoSuchKey"}}, f"GetObject {key}")


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _FakeObject:
    def __init__(self, bucket: "FakeBucket", key: str) -> None:
        self._bucket = bucket
        self._key = key

    def get(self) -> dict[str, Any]:
        body = self._bucket.objects.get(self._key)
        if body is None:
            raise _MissingKey(self._key)
        return {"Body": _Body(body)}

    def load(self) -> None:
        if self._key not in self._bucket.objects:
            raise _MissingKey(self._key)


class FakeBucket:
    """記憶體 bucket：`IfNoneMatch` 撞鍵回 S3 的 412（`PreconditionFailed`）。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.writes: list[str] = []

    def put_object(self, **arguments: Any) -> None:
        key = str(arguments["Key"])
        if arguments.get("IfNoneMatch") == "*" and key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[key] = bytes(arguments["Body"])
        self.writes.append(key)

    def Object(self, key: str) -> _FakeObject:  # noqa: N802 - 照 boto3 resource 的名字
        return _FakeObject(self, key)


class RetireRepository(Repository):
    """真的 `Repository` ＋ 種資料與觀察用的方法；查詢與寫入一個都沒有被覆寫。"""

    def __init__(self) -> None:
        self.table = FakeTable()
        self.bucket = FakeBucket()
        super().__init__(self.table, self.bucket)

    def add_published_tutorial(self, slug: str) -> None:
        """一篇 active 教學 ＋ 一個已發布版本 ＋ 已經在公開站上的版本頁。"""
        version_id = f"{slug}@v{2 if slug == A else 1}"
        _, _, number = version_id.partition("@v")
        self.put_meta(Tutorial(slug=slug, current_version=version_id, topic=f"{slug} 教學",
                               feature_ids=[FEATURE], status="active", successor=None,
                               cluster_id=None))
        self.put_meta(TutorialVersion(version_id=version_id, slug=slug, supersedes=None,
                                      reason="create:seed", rules_applied=[],
                                      s3_key=markdown_key(slug, int(number)), published_at=NOW))
        self.bucket.objects[markdown_key(slug, int(number))] = \
            render_markdown(content_of(slug)).encode("utf-8")
        self.bucket.objects[PUBLIC_SITE_PREFIX + site_key(version_id)] = \
            f"<article>{version_id}</article>".encode()

    def add_feature(self, feature_id: str, *, aliases: tuple[str, ...] = ()) -> None:
        self.put_meta(Feature(feature_id=feature_id, name=feature_id, aliases=list(aliases),
                              first_seen=NOW))

    def add_steps(self, version_id: str, feature_id: str) -> None:
        """種 STEP 邊（`REFERENCES#FEATURE#…`）；Phase 27 的反查與 `get_steps` 都靠它。"""
        for number in (1, 2, 3):
            self.put_edge(step_pk(version_id, number), "REFERENCES", feature_pk(feature_id),
                          {"type": "click_ui", "text": f"第 {number} 步。"})

    @property
    def published_version_ids(self) -> list[str]:
        """本次 Release 發布出去的版本；RETIRE 不建版，所以永遠應該是空的。"""
        return sorted(str(item["version_id"]) for (pk, sk), item in self.table.items.items()
                      if pk.startswith("VERSION#") and sk == META
                      and str(item.get("reason", "")).startswith("release:"))


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def repo() -> RetireRepository:
    repository = RetireRepository()
    for slug in (A, C, SUCCESSOR):
        repository.add_published_tutorial(slug)
    repository.put_object(operation_ref(OPERATION, "input"),
                          json.dumps(RELEASE_REMOVED.model_dump(mode="json"),
                                     ensure_ascii=False, sort_keys=True).encode("utf-8"),
                          "application/json", if_none_match=True)
    repository.put_object(operation_ref(OPERATION, "successors"),
                          json.dumps({A: SUCCESSOR}, ensure_ascii=False).encode("utf-8"),
                          "application/json", if_none_match=True)
    return repository


def accepted_operations(repository: Repository, *,
                        canonical_id: str = "r_43") -> OperationCoordinator:
    """父 operation 已接受的帳本；雲端由 P32 的接入層寫，本機自己補（`tests/unit` 共用）。"""
    coordinator = OperationCoordinator(repository)
    coordinator.accept(AcceptOperation(operation_id=OPERATION, kind="release-update",
                                       canonical_id=canonical_id, project_id=PROJECT, now=NOW))
    return coordinator


@pytest.fixture
def ops(repo: RetireRepository) -> OperationCoordinator:
    return accepted_operations(repo)


class NoModelWriter:
    """實作 Phase 15 的 `Writer`，但每一個方法都當場失敗。

    比 `writer=None` 強：`None` 只證明「沒有接線」，這個會在**真的想呼叫模型**時指出是哪一個
    節點，所以「RETIRE 與 KEEP 零模型呼叫」是被證出來的，不是被 `need_writer()` 擋下來的。
    """

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        raise AssertionError(f"這條路徑不得呼叫 embedding：{node}")

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError(f"這條路徑不得呼叫生成模型：{node}")

    def converse_with_tools(self, system: str, messages: Any, tools: Any, *,
                            operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError(f"這條路徑不得呼叫 tool use：{node}")


@pytest.fixture
def local_deps(repo: RetireRepository, ops: OperationCoordinator) -> Deps:
    """RETIRE 路徑一個模型呼叫都沒有，所以 `writer` 是會爆炸的 `NoModelWriter`。"""
    return Deps(operations=ops, now=lambda: NOW, repository=repo, writer=NoModelWriter())


@pytest.fixture
def retire_state() -> dict[str, Any]:
    """`task_safety_net` 交給 `RetireTutorials` 的 state（只有 ID 與 ref）。"""
    return {"operation_id": OPERATION, "project_id": PROJECT,
            "input_ref": operation_ref(OPERATION, "input"), "release_id": "r_43",
            "feature_id": FEATURE, "action": "RETIRE", "hit_refs": [f"{A_V2}#3"]}


# --- Task 1：removed 走 RETIRE，successor 只來自維護者 ------------------------


def test_removed_retires_each_hit_tutorial(repo: RetireRepository) -> None:
    """Given 一則 `removed` 命中兩篇教學，When `retire_for_release`，
    Then 兩篇都退役、依 slug 升序回傳，未指定後繼的那篇仍完成退役（F19）。"""
    retired = retire_for_release(RELEASE_REMOVED, HITS_TWO, repository=repo,
                                 successor_by_slug={A: SUCCESSOR}, now=NOW)
    assert retired == (C, A)                                    # slug 升序
    assert repo.get_tutorial(A).status is TutorialStatus.RETIRED
    assert repo.get_tutorial(A).successor == SUCCESSOR
    assert repo.get_tutorial(C).status is TutorialStatus.RETIRED
    assert repo.get_tutorial(C).successor is None               # 未指定仍完成退役（F19）


def test_successor_is_never_taken_from_the_release(repo: RetireRepository) -> None:
    """Given 事件 evidence 裡寫著 `successor:`，Then 它不被採用（F54）。"""
    tainted = RELEASE_REMOVED.model_copy(update={"evidence": f"successor: {SUCCESSOR}"})
    retire_for_release(tainted, HITS_STEP3, repository=repo, successor_by_slug={}, now=NOW)
    assert repo.get_tutorial(A).status is TutorialStatus.RETIRED
    assert repo.get_tutorial(A).successor is None


def test_non_removed_kinds_are_a_wiring_error(repo: RetireRepository) -> None:
    """Given `kind=renamed` 誤接進退役函式，Then `PermanentError`（不重試、不退役）。"""
    with pytest.raises(PermanentError, match="removed"):
        retire_for_release(RELEASE_RENAMED, HITS_STEP3, repository=repo,
                           successor_by_slug={}, now=NOW)
    assert repo.get_tutorial(A).status is TutorialStatus.ACTIVE


def test_retire_task_writes_the_operation_record(
        repo: RetireRepository, local_deps: Deps, retire_state: dict[str, Any]) -> None:
    """Given `task_retire`，Then `operations/<op>/retire.json` 是每篇一筆的 JSON 陣列。"""
    result = task_retire(retire_state, local_deps)
    body = json.loads(repo.get_object(operation_ref(OPERATION, "retire")).decode("utf-8"))
    assert body == [{"slug": A, "reason": "release:r_43", "retired_at": to_iso(NOW),
                     "successor": SUCCESSOR}]
    assert result["result_ref"] == operation_ref(OPERATION, "retire")


def test_retire_task_is_a_no_op_for_other_actions(
        repo: RetireRepository, local_deps: Deps, retire_state: dict[str, Any]) -> None:
    """Given `action` 不是 RETIRE，Then state 原樣回傳、沒有任何教學被退役。"""
    result = task_retire({**retire_state, "action": "UPDATE"}, local_deps)
    assert result == {**retire_state, "action": "UPDATE"}
    assert repo.get_tutorial(A).status is TutorialStatus.ACTIVE
    assert repo.get_object(operation_ref(OPERATION, "retire")) is None


def test_resending_the_same_operation_does_not_rewrite_the_record(
        repo: RetireRepository, local_deps: Deps, retire_state: dict[str, Any]) -> None:
    """Given 同 `operation_id` 重送，Then `retire.json` 不重寫、也沒有第二次退役。"""
    task_retire(retire_state, local_deps)
    first = repo.get_object(operation_ref(OPERATION, "retire"))
    writes = [key for key in repo.bucket.writes if key.endswith("retire.json")]
    task_retire(retire_state, local_deps)
    assert repo.get_object(operation_ref(OPERATION, "retire")) == first
    assert [key for key in repo.bucket.writes if key.endswith("retire.json")] == writes


def test_retired_tutorial_keeps_its_history(
        repo: RetireRepository, local_deps: Deps, retire_state: dict[str, Any]) -> None:
    """Given 退役完成，Then `current_version`、VERSION item 與 S3 全文全部保留（設計 §8.4）。"""
    task_retire(retire_state, local_deps)
    tutorial = repo.get_tutorial(A)
    assert tutorial.current_version == A_V2
    assert repo.get_version(A_V2).published_at == NOW
    assert repo.get_object(markdown_key(A, 2)) is not None


# --- Task 1 Step 3b：D-83 只重寫教學索引頁 ------------------------------------


def test_retire_rewrites_only_the_tutorial_index(
        repo: RetireRepository, local_deps: Deps, retire_state: dict[str, Any]) -> None:
    """Given 退役完成，Then 索引頁含退役提示與後繼、版本頁 bytes 未變、零新版本（D-83）。"""
    version_page = PUBLIC_SITE_PREFIX + site_key(A_V2)
    before = repo.get_object(version_page)
    task_retire(retire_state, local_deps)
    index = repo.get_object(PUBLIC_SITE_PREFIX + tutorial_index_key(A)).decode("utf-8")
    assert RETIRED_NOTICE in index and SUCCESSOR in index
    assert repo.get_object(version_page) == before      # 已發布版本頁的 bytes 未變
    assert repo.published_version_ids == []             # 沒有新版本被發布


def test_index_rewrite_happens_after_status_is_retired(
        repo: RetireRepository, local_deps: Deps, retire_state: dict[str, Any]) -> None:
    """Given 索引內容讀 `get_tutorial(slug).status`，Then 順序是先退役再重寫索引。"""
    task_retire(retire_state, local_deps)
    assert repo.get_tutorial(A).status is TutorialStatus.RETIRED
    index = repo.get_object(PUBLIC_SITE_PREFIX + tutorial_index_key(A)).decode("utf-8")
    assert 'class="tutorial-index"' in index
    assert A_V2 in index                                # 版本清單仍列已發布版


def test_only_the_retired_slug_gets_a_new_index(
        repo: RetireRepository, local_deps: Deps, retire_state: dict[str, Any]) -> None:
    """Given 只命中一篇，Then 只有那一篇的索引頁被寫，站台索引與別篇都沒動。"""
    task_retire(retire_state, local_deps)
    public = [key for key in repo.bucket.writes if key.startswith(PUBLIC_SITE_PREFIX)]
    assert public == [PUBLIC_SITE_PREFIX + tutorial_index_key(A)]


# --- Task 3：三分支串接（RETIRE 走完整條序列，一次模型都不呼叫）-----------------


@pytest.fixture
def flow_repo(repo: RetireRepository) -> RetireRepository:
    """在 Task 1 的種子上再補 Feature 與 STEP 邊，讓 `locate_feature`／`find_release_hits`
    在**字串層**就命中：`prepare-meeting` 引用 `Prepare`，另外兩篇引用 `Share`。

    `Prepare` 的 aliases 帶著改名前的 `Meeting Summary`：`renamed` 事件因此在第 1 層就對上，
    `needs_safety_net` 回 `False`，連一次 `embed` 都不會發生（F16）。"""
    repo.add_feature(FEATURE, aliases=("Meeting Summary",))
    repo.add_feature(OTHER_FEATURE)
    repo.add_steps(A_V2, FEATURE)
    repo.add_steps(C_V1, OTHER_FEATURE)
    repo.add_steps(SUCCESSOR_V1, OTHER_FEATURE)
    return repo


@pytest.fixture
def start_state() -> dict[str, Any]:
    """接入層交給 `StartExecution` 的三個欄位，一個字都不多（文件 §2）。"""
    return {"operation_id": OPERATION, "project_id": PROJECT,
            "input_ref": operation_ref(OPERATION, "input")}


def test_removed_release_runs_end_to_end_as_retire(
        flow_repo: RetireRepository, local_deps: Deps, start_state: dict[str, Any]) -> None:
    """Given 一則 `removed`，When 跑完整條 `run_release_update`，Then 只有 RETIRE 分支動作。

    `deps.writer` 是 `NoModelWriter`，所以這條路徑只要呼叫任何模型就會當場失敗
    ——這正是雲端可以在 O5 BLOCKED 下跑到 `SUCCEEDED` 的原因。
    """
    result = run_release_update(start_state, local_deps)
    assert (result["release_id"], result["feature_id"]) == ("r_43", FEATURE)
    assert (result["action"], result["hit_refs"]) == ("RETIRE", [f"{A_V2}#{n}" for n in (1, 2, 3)])
    assert result["result_ref"] == operation_ref(OPERATION, "retire")
    assert set(result) <= set(RELEASE_STATE_FIELDS)
    assert flow_repo.get_tutorial(A).status is TutorialStatus.RETIRED
    assert flow_repo.get_tutorial(C).status is TutorialStatus.ACTIVE      # 沒引用就不動
    assert flow_repo.published_version_ids == []
    index = flow_repo.get_object(PUBLIC_SITE_PREFIX + tutorial_index_key(A)).decode("utf-8")
    assert RETIRED_NOTICE in index and SUCCESSOR in index                 # D-83


def test_renamed_with_direct_hits_chooses_update_without_the_model(
        flow_repo: RetireRepository, local_deps: Deps) -> None:
    """Given `renamed` 且 alias 已對上、反查有命中，Then `action="UPDATE"` 且零模型呼叫。

    `needs_safety_net` 在這個組合回 `False`（F16），所以連一次 `embed` 都不會發生
    ——雲端的 BLOCKED 切點因此落在 `PrepareUpdate` 而不是 `SafetyNet`。
    """
    flow_repo.put_object(operation_ref(OPERATION, "input"),
                         json.dumps(RELEASE_RENAMED.model_dump(mode="json"),
                                    ensure_ascii=False, sort_keys=True).encode("utf-8"),
                         "application/json", if_none_match=False)
    state = {"operation_id": OPERATION, "project_id": PROJECT,
             "input_ref": operation_ref(OPERATION, "input"), "release_id": "r_42",
             "feature_id": FEATURE, "hit_refs": [f"{A_V2}#3"], "prepared_version_ids": []}
    result = task_safety_net(state, local_deps)          # writer 一被碰就 AssertionError
    assert result["action"] == "UPDATE"
    assert result["hit_refs"] == [f"{A_V2}#3"]
