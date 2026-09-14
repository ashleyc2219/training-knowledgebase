"""Phase 26 Task 1／Task 2：後繼四項檢查與「退役保留歷史」（不連 AWS）。

`repo` 是本檔自備的 fixture：一個**真的** `Repository`，只是底下的表換成記憶體裡的
`FakeTable`、bucket 換成 `FakeBucket`。`get_tutorial`／`revision_of`／`update_meta`
（含保留屬性守門與 revision compare-and-swap）全部跑 Phase 06 的真程式，
被換掉的只有儲存層——所以「第二次退役零次條件寫入」「revision 不符要轉成可重試錯誤」
這兩件事是被真的 CAS 驗出來的，不是假物件直接餵答案。

§2 的固定種子（全部是 slug，不是 PK）：

```text
meeting-summary   active、current=@v2、successor=None      <- 被退役的主角
prepare-meeting   active、current=@v2                      <- 唯一合法的後繼
already-retired   retired、current=@v1                     <- 不可公開：已退役
never-published   active、current=None                     <- 不可公開：沒有已發布版本
cycles-back       active、current=@v1、successor=主角      <- 兩層環
loop-b <-> loop-c active、current=@v1、互指                <- 三層環（不含起點）
```
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.exceptions import ClientError

from training_kb.content import resolve_successor
from training_kb.keys import step_pk
from training_kb.models import (
    StepType,
    Tutorial,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.repository import DynamoValue, Repository

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
SLUG = "meeting-summary"
SUCCESSOR = "prepare-meeting"
REASON = "release:r_88"
MARKDOWN_KEY = f"tutorials/{SLUG}/v2.md"
MARKDOWN = "# 會議摘要\n\n## Steps\n\n1. (type=read, feature=Summary) 打開摘要頁。\n"


# --- 假的儲存層 -------------------------------------------------------------


def _conditional_check_failed(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, operation)


class FakeTable:
    """記憶體表：只實作本 Phase 會用到的三個 boto3 操作，其餘一律不提供。

    支援的條件式刻意窄到只有 `Repository` 真的會送出的兩種（`attribute_not_exists(PK)`
    與 `#revision = :expected`）：多送一種出來就會 `AssertionError` 而不是默默放行，
    假表因此不會比真表寬鬆。`writes` 記下每次 `put_item` 的 PK，
    `versions_written` 靠它斷言「退役期間沒有建立任何 VERSION item」。
    """

    name = "fake_training_kb"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.writes: list[str] = []

    def put_item(self, **arguments: Any) -> dict[str, Any]:
        item = dict(arguments["Item"])
        key = (str(item["PK"]), str(item["SK"]))
        if arguments.get("ConditionExpression") == "attribute_not_exists(PK)" and key in self.items:
            raise _conditional_check_failed("PutItem")
        self.items[key] = item
        self.writes.append(key[0])
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
        field, operator, placeholder = str(arguments["ConditionExpression"]).split(" ")
        assert operator == "=", f"假表不支援的條件：{operator}"
        if item is None or item.get(names[field]) != values[placeholder]:
            raise _conditional_check_failed("UpdateItem")
        expression = str(arguments["UpdateExpression"])
        assert expression.startswith("SET "), f"假表不支援的更新式：{expression}"
        for assignment in expression.removeprefix("SET ").split(", "):
            name, separator, value = assignment.partition(" = ")
            assert separator, f"假表不支援的更新式：{expression}"
            item[names[name]] = values[value]
        return {}


class FakeBucket:
    """記憶體 bucket：只實作 `put_object`。退役不該碰 S3，寫進來就會被 `objects` 的比對抓到。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **arguments: Any) -> None:
        self.objects[str(arguments["Key"])] = bytes(arguments["Body"])


class RecordingRepository(Repository):
    """真的 `Repository`，只多記「`update_meta` 被呼叫幾次、帶了什麼」。

    冪等的可觀察定義就是這個計數：第二次退役必須**零次**條件寫入，而不是「寫了一次
    但值剛好一樣」——後者會把 `_revision` 往上推，讓同時在讀的人白白失敗一次。
    """

    def __init__(self, table: FakeTable, bucket: FakeBucket) -> None:
        super().__init__(table, bucket)
        self.update_calls: list[tuple[str, dict[str, Any]]] = []

    def update_meta(self, pk: str, changes: Mapping[str, DynamoValue], *,
                    expected_revision: int) -> int:
        self.update_calls.append((pk, dict(changes)))
        return super().update_meta(pk, changes, expected_revision=expected_revision)

    @property
    def objects(self) -> dict[str, bytes]:
        """假 bucket 的內容；退役不碰 S3，所以整份 dict 在退役前後必須相同。"""
        objects: dict[str, bytes] = self._bucket.objects
        return objects

    @property
    def versions_written(self) -> list[str]:
        """這次呼叫期間新建的 `VERSION` item；退役完成後必須是空的。"""
        return [pk for pk in self._table.writes if pk.startswith("VERSION#")]

    def raw_items(self) -> dict[tuple[str, str], dict[str, Any]]:
        items: dict[tuple[str, str], dict[str, Any]] = self._table.items
        return items

    def forget_writes(self) -> None:
        self._table.writes.clear()


# --- 種子 -------------------------------------------------------------------


def _tutorial(slug: str, *, current: str | None, status: TutorialStatus = TutorialStatus.ACTIVE,
              successor: str | None = None) -> Tutorial:
    return Tutorial(slug=slug, current_version=current, topic=f"{slug} 的主題",
                    feature_ids=["Summary"], status=status, successor=successor,
                    cluster_id=None)


def _version(slug: str, number: int, *, supersedes: str | None,
             published_at: datetime | None) -> TutorialVersion:
    return TutorialVersion(version_id=f"{slug}@v{number}", slug=slug, supersedes=supersedes,
                           reason=REASON, rules_applied=[],
                           s3_key=f"tutorials/{slug}/v{number}.md", published_at=published_at)


def _seed(repository: Repository) -> None:
    """五篇教學＋主角的兩個版本與步驟＋一份 S3 全文；全部走真的 `put_meta`／`put_edge`。"""
    for tutorial in (
        _tutorial(SLUG, current=f"{SLUG}@v2"),
        _tutorial(SUCCESSOR, current=f"{SUCCESSOR}@v2"),
        _tutorial("already-retired", current="already-retired@v1",
                  status=TutorialStatus.RETIRED),
        _tutorial("never-published", current=None),
        _tutorial("cycles-back", current="cycles-back@v1", successor=SLUG),
        _tutorial("loop-b", current="loop-b@v1", successor="loop-c"),
        _tutorial("loop-c", current="loop-c@v1", successor="loop-b"),
    ):
        repository.put_meta(tutorial)
    repository.put_meta(_version(SLUG, 1, supersedes=None, published_at=NOW))
    repository.put_meta(_version(SLUG, 2, supersedes=f"{SLUG}@v1", published_at=NOW))
    repository.put_meta(_version(SUCCESSOR, 2, supersedes=None, published_at=NOW))
    step = TutorialStep(tutorial_version=f"{SLUG}@v2", number=1, type=StepType.READ,
                        text="打開摘要頁。", feature_id="Summary")
    repository.put_edge(step_pk(step.tutorial_version, step.number), "REFERENCES",
                        "FEATURE#Summary", {"type": step.type.value, "text": step.text})
    repository.put_object(MARKDOWN_KEY, MARKDOWN.encode("utf-8"),
                          "text/markdown; charset=utf-8", if_none_match=False)


@pytest.fixture
def repo() -> RecordingRepository:
    repository = RecordingRepository(FakeTable(), FakeBucket())
    _seed(repository)
    repository.forget_writes()
    return repository


# --- 歷史快照 ---------------------------------------------------------------


@dataclass(frozen=True)
class VersionsSnapshot:
    """退役前後要逐字相同的東西：`VERSION`／`STEP` item 的完整內容，加上 S3 全文 bytes。"""

    items: tuple[tuple[str, str], ...]
    markdown: bytes


def snapshot_versions(repository: RecordingRepository, slug: str) -> VersionsSnapshot:
    rows = sorted(
        (f"{pk}|{sk}", json.dumps(item, sort_keys=True, ensure_ascii=False, default=str))
        for (pk, sk), item in repository.raw_items().items()
        if pk.startswith((f"VERSION#{slug}@", f"STEP#{slug}@"))
    )
    return VersionsSnapshot(items=tuple(rows), markdown=repository.objects[MARKDOWN_KEY])


# --- Task 1：後繼合法性檢查 -------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    ["meeting-summary", "not-exists", "already-retired", "never-published", "cycles-back"],
)
def test_resolve_successor_rejects_invalid_targets(
        candidate: str, repo: RecordingRepository) -> None:
    """逐字取自 Phase 26 §7 Task 1 Step 1：自身、不存在、已退役、未發布、兩層環。"""
    assert resolve_successor(SLUG, candidate, repository=repo) is None


def test_resolve_successor_accepts_active_published_other(repo: RecordingRepository) -> None:
    assert resolve_successor(SLUG, SUCCESSOR, repository=repo) == SUCCESSOR


def test_resolve_successor_rejects_three_node_cycle(repo: RecordingRepository) -> None:
    """`loop-b -> loop-c -> loop-b` 是不含起點的環；`visited` 集合要擋得住。"""
    assert resolve_successor(SLUG, "loop-b", repository=repo) is None


def test_resolve_successor_of_none_is_none_not_an_error(repo: RecordingRepository) -> None:
    """沒有後繼不是錯誤（F19）：回 `None`，不丟例外。"""
    assert resolve_successor(SLUG, None, repository=repo) is None
