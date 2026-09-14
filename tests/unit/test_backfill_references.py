"""Phase 28 Task 1／2：只補缺的 `REFERENCES` 引用邊，不替換錯邊、不改歷史、不產新版。

`repo` 是本檔自備的 fixture：一個**真的** `Repository`，只是底下的 DynamoDB 表與 S3 bucket
換成記憶體裡的 `FakeTable`／`FakeBucket`。`backfill_references`／`rebuild_rule_projection`
與它們用到的 `list_edges`／`put_edge`／`scan_entity`／`get_meta`／`update_meta`／`delete_edge`
全部跑真的程式，被換掉的只有儲存層——Phase 文件原本寫「假 `Repository`」，那樣一來
「只補缺的邊」「不替換錯邊」都會變成在測假物件（沿用 Phase 27 `test_graph_queries.py` 的作法）。

Phase 文件也寫「fixture 放 `conftest.py`」，但 `tests/unit/conftest.py` 的 owner 是 P15、
修改者只有 P55（00A §3.2），本 Phase 不是它的修改者，所以共用器材留在本檔，
`test_rule_projection.py` 直接 import（與 Phase 23 的 `test_version_complete.py` 同一個作法）。

§2 的固定種子（`prepare-meeting` 三版 + `share-summary` 兩版）：
`prepare-meeting@v2` 已發布、S3 全文四步，第 1–3 步引用 `Prepare`、第 4 步引用
**基表不存在的** `Ghost`（`unresolved` 案例的來源）；`share-summary@v2` 是
`published_at is None` 的草稿版。
"""

import io
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.exceptions import ClientError

from training_kb.content import markdown_key, parse_markdown, render_markdown
from training_kb.errors import PermanentError
from training_kb.keys import (
    META,
    feature_pk,
    rule_pk,
    step_pk,
    version_pk,
)
from training_kb.models import (
    AuthoringRule,
    Feature,
    RuleStatus,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialVersion,
)
from training_kb.repository import BackfillReport, Repository

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
SLUG = "prepare-meeting"
OTHER_SLUG = "share-summary"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
V3 = f"{SLUG}@v3"
OTHER_V1 = f"{OTHER_SLUG}@v1"
DRAFT = f"{OTHER_SLUG}@v2"
FEATURE = "Prepare"
OTHER_FEATURE = "Notify"
GHOST = "Ghost"
RULE = "R-007"

STEP3_PK = step_pk(V2, 3)
STEP4_PK = step_pk(V2, 4)

_TEXTS = ("開啟行事曆。", "選擇今天的會議。", "開啟摘要。", "確認摘要內容。")
_TYPES = ("read", "click_ui", "click_ui", "read")
_FEATURES = (FEATURE, FEATURE, FEATURE, GHOST)


# --- 假的儲存層 -------------------------------------------------------------


def _matches(item: Mapping[str, Any], condition: Any) -> bool:
    """用 boto3 的 `get_expression()` 走一遍條件；只支援 `Repository` 真的會送出的三種。

    支援集合刻意窄：`Repository` 多送一種條件出來，這裡就會 `AssertionError` 而不是
    默默放行，假表因此不會比真表寬鬆。
    """
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


def _conditional_check_failed(operation: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conditional"}},
        operation,
    )


class FakeTable:
    """記憶體表：只實作 `Repository` 用到的五個 boto3 操作，其餘一律不提供。

    `scan` 依 `pages` 切頁（沒指定就只有一頁），**空的一頁仍然帶 `LastEvaluatedKey`**，
    所以 `Repository._paged` 提早停止會被抓到。`update_item` 只支援 `update_meta` 真的送出
    的那一種運算式（`SET` 加上 `#revision = :expected` 的條件），條件不符就丟
    `ConditionalCheckFailedException`，讓 `CoordinationError` 走真的路徑產生。
    `written_pks` 記下每一次 `put_item` 的 PK：backfill 不得寫到 `VERSION#`／`RULE#`。
    """

    name = "fake_training_kb"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.pages: list[list[tuple[str, str]]] = []
        self.written_pks: set[str] = set()

    def put_item(self, **arguments: Any) -> dict[str, Any]:
        item = dict(arguments["Item"])
        self.items[(str(item["PK"]), str(item["SK"]))] = item
        self.written_pks.add(str(item["PK"]))
        return {}

    def get_item(self, **arguments: Any) -> dict[str, Any]:
        key = arguments["Key"]
        item = self.items.get((str(key["PK"]), str(key["SK"])))
        return {} if item is None else {"Item": dict(item)}

    def delete_item(self, **arguments: Any) -> dict[str, Any]:
        key = arguments["Key"]
        self.items.pop((str(key["PK"]), str(key["SK"])), None)
        return {}

    def update_item(self, **arguments: Any) -> dict[str, Any]:
        key = arguments["Key"]
        item = self.items.get((str(key["PK"]), str(key["SK"])))
        names = dict(arguments.get("ExpressionAttributeNames") or {})
        values = dict(arguments.get("ExpressionAttributeValues") or {})
        if item is None:
            raise _conditional_check_failed("UpdateItem")
        condition = str(arguments.get("ConditionExpression") or "")
        if condition:
            left, separator, right = condition.partition(" = ")
            assert separator, f"假表不支援的條件：{condition}"
            if item.get(names[left]) != values[right]:
                raise _conditional_check_failed("UpdateItem")
        expression = str(arguments["UpdateExpression"])
        assert expression.startswith("SET "), f"假表不支援的運算式：{expression}"
        for assignment in expression.removeprefix("SET ").split(", "):
            name, separator, value = assignment.partition(" = ")
            assert separator, f"假表不支援的指派：{assignment}"
            item[names[name]] = values[value]
        self.written_pks.add(str(key["PK"]))
        return {}

    def query(self, **arguments: Any) -> dict[str, Any]:
        rows = [dict(item) for item in self.items.values()]
        found = [row for row in rows if _matches(row, arguments["KeyConditionExpression"])]
        return {"Items": sorted(found, key=lambda row: (str(row["PK"]), str(row["SK"])))}

    def scan(self, **arguments: Any) -> dict[str, Any]:
        pages = self._scan_pages()
        index = int(dict(arguments.get("ExclusiveStartKey") or {}).get("page", 0))
        condition = arguments.get("FilterExpression")
        items = [dict(item) for item in pages[index]
                 if condition is None or _matches(item, condition)]
        response: dict[str, Any] = {"Items": items}
        if index + 1 < len(pages):
            response["LastEvaluatedKey"] = {"page": index + 1}
        return response

    def _scan_pages(self) -> list[list[dict[str, Any]]]:
        if not self.pages:
            return [list(self.items.values())]
        planned = {key for page in self.pages for key in page}
        first = [item for key, item in self.items.items() if key not in planned]
        return [first, *([self.items[key] for key in page if key in self.items]
                         for page in self.pages)]


class FakeObject:
    """`bucket.Object(key)` 的回傳；只有 `Repository.get_object`／`object_exists` 用得到。"""

    def __init__(self, store: "FakeBucket", key: str) -> None:
        self._store = store
        self._key = key

    def _body(self) -> bytes:
        if self._key not in self._store.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")
        return self._store.objects[self._key]

    def get(self) -> dict[str, Any]:
        return {"Body": io.BytesIO(self._body())}

    def load(self) -> None:
        self._body()


class FakeBucket:
    """記憶體 S3：`written_s3_keys` 記下每一次 `put_object`，backfill 一個都不該有。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.written_s3_keys: set[str] = set()

    def put_object(self, **arguments: Any) -> dict[str, Any]:
        key = str(arguments["Key"])
        body = arguments["Body"]
        self.objects[key] = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.written_s3_keys.add(key)
        return {}

    def Object(self, key: str) -> FakeObject:  # noqa: N802 - boto3 resource 的方法名
        return FakeObject(self, key)


# --- 快照 -------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """執行前後要逐項比對的東西；`written_*` 是**上一次快照之後**寫過的鍵。

    取快照會把寫入紀錄清空，所以「`before = snapshot()` → 動作 → `after = snapshot()`」
    之後，`after.written_pks` 恰好是那個動作寫過的 PK。
    """

    versions: tuple[str, ...]
    objects: dict[str, bytes]
    published_at: dict[str, str | None]
    current_version: str | None
    steps_text: dict[int, str]
    written_pks: set[str]
    written_s3_keys: set[str]


# --- 真的 Repository + 種資料／改資料的方法 ---------------------------------


def four_step_content(*, features: Sequence[str] = _FEATURES) -> TutorialContent:
    """§2 的四步草稿；第 4 步預設引用基表不存在的 `Ghost`（`unresolved` 的來源）。"""
    steps = [
        StepDraft(number=index + 1, type=StepType(_TYPES[index]), text=_TEXTS[index],
                  feature_id=features[index])
        for index in range(4)
    ]
    return TutorialContent(title="準備會議", problem="會議前的準備步驟散在多個頁面。",
                           prerequisites=["已登入工作區"], steps=steps,
                           expected_outcome="會議開始前已備妥議程與摘要。")


class MaintenanceRepository(Repository):
    """真的 `Repository` + 種資料用的方法；Phase 28 的三個方法一個都沒有被覆寫。"""

    def __init__(self) -> None:
        self.table = FakeTable()
        self.store = FakeBucket()
        super().__init__(self.table, self.store)

    # --- 種資料 ---

    def add_feature(self, feature_id: str) -> None:
        self.put_meta(Feature(feature_id=feature_id, name=feature_id, aliases=[],
                              first_seen=NOW))

    def add_tutorial(self, slug: str, *, current_version: str | None) -> None:
        self.put_meta(Tutorial(slug=slug, current_version=current_version, topic=slug,
                               feature_ids=[FEATURE], status=TutorialStatus.ACTIVE,
                               successor=None, cluster_id=None))

    def add_version(self, version_id: str, *, published: bool,
                    rules_applied: Sequence[str] = ()) -> None:
        slug, _, number = version_id.partition("@v")
        self.put_meta(TutorialVersion(
            version_id=version_id, slug=slug, supersedes=None, reason="gap:c12",
            rules_applied=list(rules_applied), s3_key=markdown_key(slug, int(number)),
            published_at=NOW if published else None))

    def add_markdown(self, version_id: str, content: TutorialContent) -> None:
        slug, _, number = version_id.partition("@v")
        self.store.objects[markdown_key(slug, int(number))] = render_markdown(
            content).encode("utf-8")

    def add_steps(self, version_id: str, content: TutorialContent) -> None:
        for step in content.steps:
            self.put_edge(step_pk(version_id, step.number), "REFERENCES",
                          feature_pk(step.feature_id),
                          {"type": str(step.type), "text": step.text})

    def add_rule(self, rule_id: str, applied_to: Sequence[str]) -> None:
        self.put_meta(AuthoringRule(
            rule_id=rule_id, rule="每一步都要寫出畫面上看得到的按鈕名稱。",
            applies_when=StepType.CLICK_UI, evidence=[f"f_{index}" for index in range(1, 6)],
            status=RuleStatus.ACTIVE, applied_to=list(applied_to), derived_from="f_1"))

    def add_edge(self, pk: str, relation: str, target: str) -> None:
        self.put_edge(pk, relation, target)

    # --- 改資料：直接動假表，`Repository` 沒有、也不該有這些 API ---

    def _meta(self, pk: str) -> dict[str, Any]:
        return self.table.items[(pk, META)]

    def drop_edge(self, pk: str, relation: str, target: str | None = None) -> None:
        prefix = f"{relation}#" if target is None else f"{relation}#{target}"
        for key in [key for key in self.table.items
                    if key[0] == pk and key[1].startswith(prefix)]:
            del self.table.items[key]

    def set_edge(self, pk: str, relation: str, target: str) -> None:
        """把這個起點的該種邊換成恰好一條指向 `target` 的邊，原有的屬性照搬過去。

        這是「錯邊」：形狀完全正常（`put_edge` 寫得出來），只是指向另一個 Feature。
        """
        existing = [dict(item) for key, item in self.table.items.items()
                    if key[0] == pk and key[1].startswith(f"{relation}#")]
        attrs = {key: value for key, value in (existing[0] if existing else {}).items()
                 if key not in {"PK", "SK", "target", "entity", "_revision"}}
        self.drop_edge(pk, relation)
        self.put_edge(pk, relation, target, attrs)
        self.table.written_pks.discard(pk)

    def set_rules_applied(self, version_id: str, rules: Sequence[str]) -> None:
        self._meta(version_pk(version_id))["rules_applied"] = list(rules)

    def paginate(self, *pages: Iterable[str]) -> None:
        """把這幾個版本安排到指定的 Scan 分頁；沒被點名的 item 一律留在第 0 頁。

        允許空頁：空頁仍然帶 `LastEvaluatedKey`，所以「空的一頁不等於沒有下一頁」
        會被真的 `_paged` 迴圈驗到。
        """
        self.table.pages = [[(version_pk(version_id), META) for version_id in page]
                            for page in pages]

    # --- 讀資料 ---

    def edge_item(self, pk: str, relation: str) -> dict[str, Any]:
        rows = self.list_edges(pk, relation)
        assert len(rows) == 1, f"{pk} 的 {relation} 邊有 {len(rows)} 條"
        return dict(rows[0])

    def edge_targets(self, pk: str, relation: str) -> list[str]:
        return sorted(str(row["target"]) for row in self.list_edges(pk, relation))

    def get_rule(self, rule_id: str) -> AuthoringRule:
        rule = self.get_meta(rule_pk(rule_id), AuthoringRule)
        assert rule is not None, f"找不到規則 {rule_id}"
        return rule

    def markdown_step(self, version_id: str, number: int) -> StepDraft:
        body = self.get_object(self._meta(version_pk(version_id))["s3_key"])
        assert body is not None, f"{version_id} 沒有 S3 全文"
        return parse_markdown(body.decode("utf-8")).steps[number - 1]

    def snapshot(self, slug: str = SLUG) -> Snapshot:
        """記下版本清單、S3 物件、發布欄位、該篇 v2 的各步文字，並**清空**寫入紀錄。"""
        versions = tuple(sorted(
            json.dumps(item, sort_keys=True, default=str)
            for (pk, sort_key), item in self.table.items.items()
            if pk.startswith("VERSION#") and sort_key == META))
        published = {
            str(item["version_id"]): item.get("published_at")
            for (pk, sort_key), item in self.table.items.items()
            if pk.startswith("VERSION#") and sort_key == META}
        tutorial = self.get_tutorial(slug)
        written_pks, written_s3 = set(self.table.written_pks), set(self.store.written_s3_keys)
        self.table.written_pks.clear()
        self.store.written_s3_keys.clear()
        return Snapshot(
            versions=versions,
            objects=dict(self.store.objects),
            published_at=published,
            current_version=None if tutorial is None else tutorial.current_version,
            steps_text={step.number: step.text for step in self.get_steps(V2)},
            written_pks=written_pks,
            written_s3_keys=written_s3,
        )

    def full_snapshot(self) -> Snapshot:
        return self.snapshot(SLUG)


@pytest.fixture
def repo() -> MaintenanceRepository:
    repository = MaintenanceRepository()
    repository.add_feature(FEATURE)
    repository.add_feature(OTHER_FEATURE)
    repository.add_tutorial(SLUG, current_version=V3)
    repository.add_tutorial(OTHER_SLUG, current_version=OTHER_V1)
    content = four_step_content()
    for version_id, published, rules in ((V1, True, ()), (V2, True, (RULE,)),
                                         (V3, True, (RULE,)), (OTHER_V1, True, (RULE,)),
                                         (DRAFT, False, ())):
        repository.add_version(version_id, published=published, rules_applied=rules)
        repository.add_markdown(version_id, content)
    repository.add_steps(V2, content)
    repository.add_edge(version_pk(V3), "SUPERSEDES", version_pk(V2))
    repository.add_rule(RULE, [V2, V3, OTHER_V1])
    repository.add_edge(rule_pk(RULE), "APPLIED_TO", version_pk(V2))
    repository.add_edge(rule_pk(RULE), "APPLIED_TO", version_pk(V3))
    return repository


# --- Task 1：只補缺邊，不替換錯邊 -------------------------------------------


def test_backfill_adds_missing_edge_only(repo: MaintenanceRepository) -> None:
    """GPH Rule 7：漏掉的引用邊依 S3 全文補回來；其餘三步與版本清單完全不動。"""
    repo.drop_edge(STEP3_PK, "REFERENCES")
    before = repo.snapshot(SLUG)
    report = repo.backfill_references(V2)
    assert report.added == (STEP3_PK,)
    assert report.conflicts == () and report.unresolved == ()
    restored = repo.edge_item(STEP3_PK, "REFERENCES")
    assert restored["SK"] == f"REFERENCES#{feature_pk(FEATURE)}" and restored["entity"] == "STEP"
    assert restored["target"] == feature_pk(FEATURE)
    assert restored["text"] == repo.markdown_step(V2, 3).text
    assert restored["type"] == str(repo.markdown_step(V2, 3).type)
    # 建立教學版本 Rule 8／10：補出來的 item 與 Phase 23 寫的一模一樣，沒有第三類屬性。
    assert set(restored) == {"PK", "SK", "target", "entity", "type", "text"}
    assert repo.snapshot(SLUG).versions == before.versions


def test_backfill_records_conflict_without_replacing(repo: MaintenanceRepository) -> None:
    """D05、F40：已有指向別的 Feature 的邊時只記錄，邊維持原樣，也不追加第二條。"""
    repo.set_edge(STEP3_PK, "REFERENCES", feature_pk(OTHER_FEATURE))
    before = repo.edge_item(STEP3_PK, "REFERENCES")
    report = repo.backfill_references(V2)
    assert report.added == ()
    assert report.conflicts == (STEP3_PK,)
    assert repo.edge_item(STEP3_PK, "REFERENCES") == before
    assert len(repo.list_edges(STEP3_PK, "REFERENCES")) == 1


def test_backfill_refuses_unpublished_version(repo: MaintenanceRepository) -> None:
    """設計 §10：`published_at is None` 的版本可能正在建版途中，補寫會把半成品補成完整。"""
    version = repo.get_version(DRAFT)
    assert version is not None and version.published_at is None
    with pytest.raises(PermanentError, match=DRAFT):
        repo.backfill_references(DRAFT)


def test_backfill_refuses_a_version_that_does_not_exist(repo: MaintenanceRepository) -> None:
    """不存在的版本與未發布版同一條路徑：不補半成品，也不順手建立版本。"""
    with pytest.raises(PermanentError, match="nope@v1"):
        repo.backfill_references("nope@v1")
    assert repo.get_version("nope@v1") is None


def test_backfill_refuses_a_published_version_without_markdown(
        repo: MaintenanceRepository) -> None:
    """沒有全文就沒有「應該是什麼」的權威，一律拒絕，而不是把缺邊當成沒有那一步。"""
    del repo.store.objects[markdown_key(SLUG, 2)]
    with pytest.raises(PermanentError, match=V2):
        repo.backfill_references(V2)


def test_backfill_lists_unknown_features_as_unresolved(repo: MaintenanceRepository) -> None:
    """設計 §10：不能確認恰好一個既有 Feature 就列為待處理，**不建立 Feature**、不補邊。"""
    repo.drop_edge(STEP4_PK, "REFERENCES")
    report = repo.backfill_references(V2)
    assert report.added == () and report.conflicts == ()
    assert report.unresolved == (STEP4_PK,)
    assert repo.list_edges(STEP4_PK, "REFERENCES") == []
    assert repo.get_feature(GHOST) is None
    assert [str(item["PK"]) for item in repo.scan_entity("FEATURE")] == [
        feature_pk(FEATURE), feature_pk(OTHER_FEATURE)]


def test_backfill_is_idempotent(repo: MaintenanceRepository) -> None:
    """§8 Boundary：連跑兩次，第二次 `added` 為空、`conflicts`／`unresolved` 內容不變。"""
    repo.drop_edge(STEP3_PK, "REFERENCES")
    repo.drop_edge(STEP4_PK, "REFERENCES")
    repo.set_edge(step_pk(V2, 1), "REFERENCES", feature_pk(OTHER_FEATURE))
    first = repo.backfill_references(V2)
    assert first.added == (STEP3_PK,)
    second = repo.backfill_references(V2)
    assert second.added == ()
    assert second.conflicts == first.conflicts == (step_pk(V2, 1),)
    assert second.unresolved == first.unresolved == (STEP4_PK,)


def test_backfill_report_fields_are_sorted_step_pks(repo: MaintenanceRepository) -> None:
    """三個欄位都是排序去重的步驟 PK；`#10` 不得靠字典序排到 `#3` 前面。"""
    content = four_step_content()
    ten_steps = TutorialContent(
        title=content.title, problem=content.problem, prerequisites=content.prerequisites,
        steps=[StepDraft(number=index + 1, type=StepType.READ, text=f"第 {index + 1} 步。",
                         feature_id=GHOST) for index in range(10)],
        expected_outcome=content.expected_outcome)
    repo.add_markdown(V1, ten_steps)
    report = repo.backfill_references(V1)
    assert report.unresolved == tuple(step_pk(V1, number) for number in range(1, 11))
    assert report.added == () and report.conflicts == ()


# --- Task 2：不改歷史、不產新版 ---------------------------------------------


def test_backfill_never_touches_history_or_creates_versions(
        repo: MaintenanceRepository) -> None:
    """F40：只寫 `added` 那幾個 `STEP#` PK，其餘 item、S3 物件與發布欄位一個都不動。"""
    repo.drop_edge(STEP3_PK, "REFERENCES")
    before = repo.full_snapshot()
    repo.backfill_references(V2)
    after = repo.full_snapshot()
    assert after.versions == before.versions
    assert after.objects == before.objects                 # S3 .md／.diff byte 相同
    assert after.published_at == before.published_at
    assert after.current_version == before.current_version
    assert after.written_pks == {STEP3_PK}
    assert after.written_s3_keys == set()
    others = {number: text for number, text in after.steps_text.items() if number != 3}
    assert others == before.steps_text
    assert after.steps_text[3] == repo.markdown_step(V2, 3).text


def test_backfill_does_not_write_anything_when_nothing_is_missing(
        repo: MaintenanceRepository) -> None:
    """全部一致時是純讀取：一筆 item 都不重寫，冪等不靠「寫同樣的值」達成。"""
    before = repo.full_snapshot()
    report = repo.backfill_references(V2)
    after = repo.full_snapshot()
    assert report == BackfillReport((), (), ())
    assert after.written_pks == set() and after.written_s3_keys == set()
    assert after.versions == before.versions


def test_backfill_leaves_conflicting_edges_byte_identical(
        repo: MaintenanceRepository) -> None:
    """§8 Failure：錯邊案例執行前後整筆 item 相同，也沒有新版本、沒有新 S3 物件。"""
    repo.set_edge(STEP3_PK, "REFERENCES", feature_pk(OTHER_FEATURE))
    before_edge = repo.edge_item(STEP3_PK, "REFERENCES")
    before = repo.full_snapshot()
    repo.backfill_references(V2)
    after = repo.full_snapshot()
    assert repo.edge_item(STEP3_PK, "REFERENCES") == before_edge
    assert after.written_pks == set() and after.written_s3_keys == set()
    assert after.versions == before.versions
    assert after.published_at == before.published_at
