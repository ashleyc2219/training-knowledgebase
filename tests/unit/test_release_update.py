"""Phase 51 Task 1／2／3：UPDATE 精準改寫的範圍、reason／diff、lease 與重送（不連 AWS）。

本檔自備全部器材，**不動** `tests/unit/conftest.py`（COMMON.md R3.6 只有 P55 能改）：

- `repo` 是一個**真的** `Repository`，只有底下的表換成 `FakeTable`、bucket 換成 `FakeBucket`。
  所以 `allocate_version`／`create_version`／`verify_version_complete` 跑的都是 Phase 20／23
  的真程式，「重送拿回同一版號」是被真的條件寫入與 operation 紀錄驗出來的。
- `FakeWriter` 記的是有 `.user`／`.node` 屬性的 dataclass、回覆放在單數的 `.reply`，
  與共用 `RecordingWriter`（`replies` 是依序 pop 的 list、`calls` 記 dict）形狀不同，
  Phase 51 文件 §7 的片段就是照這個形狀寫的。
- `ops` 是真的 `OperationCoordinator`，只多記一份 `accepted_ids`（依接受順序）。

固定種子（§2 的例子）：`prepare-meeting@v2` 四步、只命中第 3 步；`weekly-digest@v1` 兩步、
命中第 2 步；另有一篇 `legacy-guide` 已退役，用來證明 UPDATE 不替退役教學建新版。
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.exceptions import ClientError

from training_kb.clock import now_utc, to_iso
from training_kb.content import (
    TutorialContent,
    diff_key,
    markdown_key,
    parse_markdown,
    render_markdown,
)
from training_kb.errors import ContentError, CoordinationError, PermanentError, TransientError
from training_kb.keys import META, operation_ref
from training_kb.models import (
    AuthoringRule,
    Feature,
    Release,
    RuleStatus,
    StepDraft,
    StepType,
    Tutorial,
    TutorialStatus,
    TutorialVersion,
)
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.pipelines.release import (
    REWRITE_NODE,
    StepHit,
    assert_unchanged,
    prepare_update,
)
from training_kb.repository import Repository

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
PROJECT = "demo"
OPERATION = "op-release-r_42"
FEATURE = "Prepare"
OTHER_FEATURE = "Share"
A, B, RETIRED = "prepare-meeting", "weekly-digest", "legacy-guide"
A_V2, B_V1, RETIRED_V1 = f"{A}@v2", f"{B}@v1", f"{RETIRED}@v1"

HITS_STEP3 = (StepHit(A, A_V2, 3),)
"""Phase 50 的輸出：只命中 A 的第 3 步。"""

OLD_STEP3 = "在右上角選擇 Meeting Summary，查看會前摘要。"
NEW_STEP3 = "在會議頁面右上角選擇 Prepare，查看會前摘要。"
NEW_STEP2_OF_B = "在週報頁面選擇 Prepare 匯出摘要。"


def rewrite(number: int, text: str, *, feature_id: str = FEATURE,
            step_type: str = "click_ui") -> dict[str, Any]:
    """一筆 `StepRewrite.steps` 元素；四個欄位都是 schema 的 required。"""
    return {"number": number, "text": text, "feature_id": feature_id, "type": step_type}


def rule(rule_id: str, applies_when: str, *, status: str = "active") -> AuthoringRule:
    return AuthoringRule(rule_id=rule_id, rule=f"{rule_id} 的規則文字", applies_when=applies_when,
                         evidence=[f"fb-{rule_id}-{index}" for index in range(5)],
                         status=status, applied_to=[], derived_from=A_V2)


RELEASE_R42 = Release(id="r_42", source="github_pr", feature=FEATURE, kind="renamed",
                      old_name="Meeting Summary", new_name=FEATURE,
                      evidence="PR #42 rename Meeting Summary -> Prepare", ts=NOW)
RELEASE_REMOVED = Release(id="r_99", source="github_pr", feature=FEATURE, kind="removed",
                          evidence="PR #99 remove Prepare", ts=NOW)


def content_a() -> TutorialContent:
    """`prepare-meeting@v2` 的原文：四步，只有第 3 步會被命中。"""
    return TutorialContent(
        title="會前準備教學",
        problem="不知道怎麼在會議前拿到摘要。",
        prerequisites=["已登入", "已建立會議"],
        steps=[
            StepDraft(number=1, type=StepType.CLICK_UI, text="在側欄點選會議。",
                      feature_id=FEATURE),
            StepDraft(number=2, type=StepType.CLICK_UI, text="在會議詳情頁確認參與者。",
                      feature_id=FEATURE),
            StepDraft(number=3, type=StepType.CLICK_UI, text=OLD_STEP3, feature_id=FEATURE),
            # 第 4 步刻意引用**另一個** Feature：`allowed_features` 才會有兩個值，
            # 「模型把第 3 步改指 Share」才過得了 Phase 18 的 validator、真的走到 D06 的檢查。
            StepDraft(number=4, type=StepType.READ, text="回到會議列表確認摘要已更新。",
                      feature_id=OTHER_FEATURE),
        ],
        expected_outcome="會前摘要已經可以在會議頁面看到。",
    )


def content_b() -> TutorialContent:
    """`weekly-digest@v1` 的原文：兩步，命中第 2 步。"""
    return TutorialContent(
        title="週報摘要教學",
        problem="不知道週報怎麼匯出。",
        prerequisites=["已登入"],
        steps=[
            StepDraft(number=1, type=StepType.READ, text="打開週報頁面。", feature_id=FEATURE),
            StepDraft(number=2, type=StepType.CLICK_UI, text="選擇 Meeting Summary 匯出。",
                      feature_id=FEATURE),
        ],
        expected_outcome="週報摘要已匯出。",
    )


def step_of(content: TutorialContent, number: int) -> StepDraft:
    """`TutorialContent` 沒有 `.step()`（00A 現況核對），helper 寫在測試檔裡。"""
    return next(step for step in content.steps if step.number == number)


def sections_of(content: TutorialContent) -> tuple[str, str, list[str], str]:
    """`TutorialContent` 沒有 `.sections()`；四個非步驟段落。"""
    return content.title, content.problem, content.prerequisites, content.expected_outcome


# --- 假的 Writer -------------------------------------------------------------


@dataclass
class JsonCall:
    """一次 `generate_json`：屬性存取版，因為共用 `RecordingWriter` 記的是 dict。"""

    system: str
    user: str
    schema: Mapping[str, Any]
    node: str


@dataclass
class FakeWriter:
    """只夠跑 `prepare_update` 的假 Writer（O5 BLOCKED，一次真實 Bedrock 都不會發生）。

    `reply` 是「所有教學共用」的預設回覆；`replies_by_slug` 讓兩篇教學各給一份。
    `request_attempts` 與共用 `RecordingWriter` 同名同義：真的送出去幾次。
    """

    reply: Mapping[str, Any] | None = None
    replies_by_slug: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    json_calls: list[JsonCall] = field(default_factory=list)
    request_attempts: int = 0

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        raise AssertionError("prepare_update 不呼叫 embedding")

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self.request_attempts += 1
        self.json_calls.append(JsonCall(system=system, user=user, schema=schema, node=node))
        for slug, reply in self.replies_by_slug.items():
            if slug in user:
                return dict(reply)
        if self.reply is None:
            raise AssertionError("FakeWriter 沒有排好回覆")
        return dict(self.reply)

    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError("prepare_update 不呼叫 tool use")


# --- 假的儲存層：真的 `Repository`，只有底下的表與 bucket 換成記憶體 ----------


def _conditional_check_failed(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, operation)


def _matches(item: Mapping[str, Any], condition: Any) -> bool:
    """用 boto3 的 `get_expression()` 走一遍條件；多送一種條件出來就 `AssertionError`。"""
    expression = condition.get_expression()
    operator = expression["operator"]
    values = expression["values"]
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
        self.fail_next_edge = False

    def put_item(self, **arguments: Any) -> dict[str, Any]:
        item = dict(arguments["Item"])
        key = (str(item["PK"]), str(item["SK"]))
        if self.fail_next_edge and not str(item["SK"]) == META:
            self.fail_next_edge = False
            raise TransientError(f"寫關係時中斷：{key}")
        condition = arguments.get("ConditionExpression")
        if condition == "attribute_not_exists(PK)" and key in self.items:
            raise _conditional_check_failed("PutItem")
        if condition == "#revision = :current":
            values = arguments["ExpressionAttributeValues"]
            current = self.items.get(key, {}).get("_revision")
            if current != values[":current"]:
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


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class FakeBucket:
    """記憶體 bucket：`IfNoneMatch` 撞鍵回 S3 的 412（`PreconditionFailed`）。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **arguments: Any) -> None:
        key = str(arguments["Key"])
        if arguments.get("IfNoneMatch") == "*" and key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[key] = bytes(arguments["Body"])

    def Object(self, key: str) -> _FakeObject:  # noqa: N802 - 照 boto3 resource 的名字
        return _FakeObject(self, key)


class UpdateRepository(Repository):
    """真的 `Repository` ＋ 種資料與觀察用的方法；查詢與寫入一個都沒有被覆寫。"""

    def __init__(self) -> None:
        self.table = FakeTable()
        self.bucket = FakeBucket()
        super().__init__(self.table, self.bucket)

    # --- 種資料 ---

    def add_tutorial(self, slug: str, *, current_version: str,
                     status: str = "active") -> None:
        self.put_meta(Tutorial(slug=slug, current_version=current_version, topic=slug,
                               feature_ids=[FEATURE], status=status,
                               successor=None, cluster_id=None))

    def add_published_version(self, version_id: str, content: TutorialContent) -> None:
        slug, _, number = version_id.partition("@v")
        key = markdown_key(slug, int(number))
        self.put_meta(TutorialVersion(version_id=version_id, slug=slug, supersedes=None,
                                      reason="create:seed", rules_applied=[], s3_key=key,
                                      published_at=NOW))
        self.bucket.objects[key] = render_markdown(content).encode("utf-8")

    def add_feature(self, feature_id: str) -> None:
        self.put_meta(Feature(feature_id=feature_id, name=feature_id, aliases=[],
                              first_seen=NOW))

    def add_rules(self, rules: Sequence[AuthoringRule]) -> None:
        for item in rules:
            self.put_meta(item)
        validated = {item.rule_id: to_iso(NOW) for item in rules}
        self.bucket.objects["operations/rules/validated_at.json"] = json.dumps(
            validated, ensure_ascii=False).encode("utf-8")

    def fail_next_edge_write(self) -> None:
        """下一筆關係邊寫入丟 `TransientError`，模擬「寫關係時中斷」這個切點。"""
        self.table.fail_next_edge = True

    # --- 觀察 ---

    def _release_versions(self) -> list[dict[str, Any]]:
        """本次 Release 建出來的 VERSION item；種子版本的 reason 是 `create:seed`，不算。"""
        return [item for (pk, sk), item in self.table.items.items()
                if pk.startswith("VERSION#") and sk == META
                and str(item.get("reason", "")).startswith("release:")]

    @property
    def created_versions(self) -> list[str]:
        return sorted(str(item["version_id"]) for item in self._release_versions())

    @property
    def published_version_ids(self) -> list[str]:
        return sorted(str(item["version_id"]) for item in self._release_versions()
                      if item.get("published_at") is not None)

    def saved_content(self, version_id: str) -> TutorialContent:
        slug, _, number = version_id.partition("@v")
        body = self.bucket.objects[markdown_key(slug, int(number))]
        return parse_markdown(body.decode("utf-8"))


class RecordingCoordinator(OperationCoordinator):
    """真的 `OperationCoordinator`，只多記一份依接受順序排列的 `accepted_ids`。"""

    def __init__(self, repository: Repository) -> None:
        super().__init__(repository)
        self.accepted_ids: list[str] = []

    def accept(self, request: AcceptOperation) -> Any:
        self.accepted_ids.append(request.operation_id)
        return super().accept(request)


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def repo() -> UpdateRepository:
    """§2 的固定圖譜：A 已發布 v2、B 已發布 v1、`legacy-guide` 已退役。"""
    repository = UpdateRepository()
    repository.add_feature(FEATURE)
    repository.add_feature(OTHER_FEATURE)
    repository.add_tutorial(A, current_version=A_V2)
    repository.add_published_version(A_V2, content_a())
    repository.add_tutorial(B, current_version=B_V1)
    repository.add_published_version(B_V1, content_b())
    repository.add_tutorial(RETIRED, current_version=RETIRED_V1, status="retired")
    repository.add_published_version(RETIRED_V1, content_b())
    return repository


@pytest.fixture
def ops(repo: UpdateRepository) -> RecordingCoordinator:
    """記憶體 O2 帳本；父 operation `op-release-r_42` 在建立時就已經接受好。"""
    coordinator = RecordingCoordinator(repo)
    coordinator.accept(AcceptOperation(operation_id=OPERATION, kind="release-update",
                                       canonical_id="r_42", project_id=PROJECT, now=NOW))
    coordinator.accepted_ids.clear()
    return coordinator


@pytest.fixture
def fake_writer() -> FakeWriter:
    return FakeWriter(reply={"steps": [rewrite(3, NEW_STEP3)]})


@pytest.fixture
def hits_two_tutorials() -> tuple[StepHit, ...]:
    """兩篇教學各命中一步；刻意反序傳入，證明輸出依 slug 升序。"""
    return (StepHit(B, B_V1, 2), StepHit(A, A_V2, 3))


# --- Task 1：只改命中步驟，其餘逐字相同（REL Rule 10、11） --------------------


def test_only_hit_steps_change_and_others_are_byte_for_byte(
        repo: UpdateRepository, ops: RecordingCoordinator, fake_writer: FakeWriter) -> None:
    """Given `prepare-meeting@v2` 四步、Phase 50 只命中第 3 步，
    When 跑 `prepare_update`，Then 只有第 3 步的 text 不同，
    第 1／2／4 步與四個段落逐字相同（REL Rule 10、11）。"""
    base = content_a()
    plans = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id=OPERATION)
    draft = repo.saved_content(plans[0].version_id)
    assert plans[0].version_id == f"{A}@v3"
    assert [step.number for step in draft.steps
            if step.text != step_of(base, step.number).text] == [3]
    assert step_of(draft, 3).text == NEW_STEP3
    for number in (1, 2, 4):
        assert step_of(draft, number).model_dump() == step_of(base, number).model_dump()
    assert sections_of(draft) == sections_of(base)


def test_model_touching_an_extra_step_is_rejected(
        repo: UpdateRepository, ops: RecordingCoordinator, fake_writer: FakeWriter) -> None:
    """Given 模型多改了沒被命中的第 2 步，When 跑 `prepare_update`，
    Then `ContentError`，而且一個版本都沒有建立（REL Rule 10）。

    現況核對 2026-09-14：Phase 文件 §7 的片段斷言 `match="改寫集合"`，但**越界改寫**會先被
    Phase 18 的 `step_rewrite_validator` 以固定錯誤碼 `step_number_not_in_hit_set` 擋下
    （它排在 `_apply_rewrite` 之前）。兩者都是 `ContentError`、都不建立版本；
    `改寫集合` 那條訊息由「漏回」與「重複回」兩個案例覆蓋。
    """
    fake_writer.reply = {"steps": [rewrite(3, "新的第三步。"),
                                   rewrite(2, "偷改的第二步。", step_type="read")]}
    with pytest.raises(ContentError, match="step_number_not_in_hit_set"):
        prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                       operations=ops, operation_id=OPERATION)
    assert repo.created_versions == []


def test_model_answering_the_same_step_twice_is_rejected(
        repo: UpdateRepository, ops: RecordingCoordinator, fake_writer: FakeWriter) -> None:
    """Given 模型對同一個命中步驟回了兩份互相矛盾的改寫，When 跑 `prepare_update`，
    Then `ContentError`：不可以靜靜取最後一筆，那會讓同一份輸入重送得到不同結果。"""
    fake_writer.reply = {"steps": [rewrite(3, NEW_STEP3), rewrite(3, "另一種第三步。")]}
    with pytest.raises(ContentError, match="改寫集合"):
        prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                       operations=ops, operation_id=OPERATION)
    assert repo.created_versions == []


def test_model_missing_the_hit_step_is_rejected(
        repo: UpdateRepository, ops: RecordingCoordinator, fake_writer: FakeWriter) -> None:
    """Given 模型漏回命中步驟（空陣列），When 跑 `prepare_update`，
    Then `ContentError`，沒有版本被建立。"""
    fake_writer.reply = {"steps": []}
    with pytest.raises(ContentError, match="改寫集合"):
        prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                       operations=ops, operation_id=OPERATION)
    assert repo.created_versions == []


def test_model_moving_the_step_to_another_feature_is_rejected(
        repo: UpdateRepository, ops: RecordingCoordinator, fake_writer: FakeWriter) -> None:
    """Given 模型把第 3 步改指別的 Feature，When 跑 `prepare_update`，
    Then `ContentError`：改名不搬移 Feature 主鍵（D06）。

    `Share` 是第 4 步引用的既有 Feature，所以它過得了 Phase 18 的 `allowed_features`
    白名單，真正擋下來的是 `_apply_rewrite` 的「命中步驟的 feature_id 不可改變」。
    """
    fake_writer.reply = {"steps": [rewrite(3, NEW_STEP3, feature_id=OTHER_FEATURE)]}
    with pytest.raises(ContentError, match="不可改變引用的 Feature"):
        prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                       operations=ops, operation_id=OPERATION)
    assert repo.created_versions == []


def test_blank_rewritten_text_is_rejected(
        repo: UpdateRepository, ops: RecordingCoordinator, fake_writer: FakeWriter) -> None:
    """Given 改寫文字去掉空白之後是空的，When 跑 `prepare_update`，
    Then `ContentError`，沒有版本被建立。"""
    fake_writer.reply = {"steps": [rewrite(3, "   ")]}
    with pytest.raises(ContentError, match="空"):
        prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                       operations=ops, operation_id=OPERATION)
    assert repo.created_versions == []


def test_assert_unchanged_rejects_a_different_step_count() -> None:
    """Given 草稿的步驟數量與基底不同，When 呼叫 `assert_unchanged`，
    Then `ContentError`：UPDATE 不得增刪步驟。"""
    base = content_a()
    draft = base.model_copy(update={"steps": base.steps[:3]})
    with pytest.raises(ContentError, match="步驟數量"):
        assert_unchanged(base, draft, frozenset({3}))


def test_assert_unchanged_rejects_a_changed_section() -> None:
    """Given 草稿改了標題，When 呼叫 `assert_unchanged`，
    Then `ContentError`：四個段落必須逐字相同（REL Rule 11）。"""
    base = content_a()
    draft = base.model_copy(update={"title": "偷改的標題"})
    with pytest.raises(ContentError, match="段落"):
        assert_unchanged(base, draft, frozenset({3}))


def test_removed_release_never_enters_update(
        repo: UpdateRepository, ops: RecordingCoordinator, fake_writer: FakeWriter) -> None:
    """Given `kind="removed"` 誤入本函式，When 跑 `prepare_update`，
    Then `PermanentError`：退役是 Phase 52 的事（REL Rule 8）。"""
    with pytest.raises(PermanentError, match="renamed"):
        prepare_update(RELEASE_REMOVED, HITS_STEP3, repository=repo, writer=fake_writer,
                       operations=ops, operation_id=OPERATION)
    assert repo.created_versions == []
    assert fake_writer.request_attempts == 0
