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

from training_kb.content import resolve_successor, retire_tutorial
from training_kb.errors import PermanentError, TransientError
from training_kb.keys import META, step_pk, tutorial_pk
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
OTHER_SUCCESSOR = "later-guide"
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
        self.bump_before_update: str | None = None
        """插隊模擬：在 `update_item` 真的比對條件之前，先把這個 PK 的 `_revision` 加一，
        等於「別人在我讀完 revision 之後、寫進去之前改了這一篇」。"""

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
        if item is not None and self.bump_before_update == str(key["PK"]):
            item["_revision"] = int(item["_revision"]) + 1
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
        _tutorial(OTHER_SUCCESSOR, current=f"{OTHER_SUCCESSOR}@v1"),
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


# --- Task 2：退役保留歷史且不被後繼阻擋 -------------------------------------


def test_retire_completes_even_when_successor_is_invalid(repo: RecordingRepository) -> None:
    """逐字取自 Phase 26 §7 Task 2 Step 1：後繼無效不能阻擋退役，歷史一個 byte 都不准動。"""
    before = snapshot_versions(repo, SLUG)
    result = retire_tutorial(
        SLUG, reason=REASON, successor="not-exists",
        repository=repo, now=NOW,
    )
    assert result.status == TutorialStatus.RETIRED
    assert result.successor is None
    assert result.current_version == f"{SLUG}@v2"
    assert snapshot_versions(repo, SLUG) == before
    assert repo.objects[MARKDOWN_KEY] == before.markdown
    assert repo.versions_written == []


def test_retire_writes_a_valid_successor(repo: RecordingRepository) -> None:
    result = retire_tutorial(SLUG, reason=REASON, successor=SUCCESSOR,
                             repository=repo, now=NOW)
    assert (result.status, result.successor) == (TutorialStatus.RETIRED, SUCCESSOR)
    assert repo.update_calls == [(tutorial_pk(SLUG), {"status": "retired",
                                                      "successor": SUCCESSOR})]


def test_retire_only_touches_status_and_successor(repo: RecordingRepository) -> None:
    """`TUTORIAL` item 只准多出 `status`／`successor`／`_revision` 的變動（D-40）。

    特別擋掉 `retired_at`／`retired_reason`：多一個屬性，下一次 `get_meta` 就會在嚴格模型
    上炸掉，而且是到那時候才炸——所以在這裡就比對整份屬性名集合。
    """
    key = (tutorial_pk(SLUG), META)
    before = dict(repo.raw_items()[key])
    retire_tutorial(SLUG, reason=REASON, successor=SUCCESSOR, repository=repo, now=NOW)
    after = dict(repo.raw_items()[key])
    changed = {"status", "successor", "_revision"}
    assert set(after) == set(before)
    assert {k: v for k, v in after.items() if k not in changed} == \
           {k: v for k, v in before.items() if k not in changed}
    assert after["_revision"] == before["_revision"] + 1


def test_retiring_twice_writes_nothing_the_second_time(repo: RecordingRepository) -> None:
    """冪等的可觀察定義：第二次**零次** `update_meta`，回傳與第一次相同。"""
    first = retire_tutorial(SLUG, reason=REASON, successor=SUCCESSOR, repository=repo, now=NOW)
    calls = len(repo.update_calls)
    revision = repo.revision_of(tutorial_pk(SLUG))
    second = retire_tutorial(SLUG, reason=REASON, successor=SUCCESSOR, repository=repo, now=NOW)
    assert second == first
    assert len(repo.update_calls) == calls
    assert repo.revision_of(tutorial_pk(SLUG)) == revision


@pytest.mark.parametrize("later", [None, OTHER_SUCCESSOR])
def test_second_retire_never_overwrites_an_existing_successor(
        repo: RecordingRepository, later: str | None) -> None:
    """改後繼是維護者的另一次明確決定，不是再退役一次的副作用。"""
    retire_tutorial(SLUG, reason=REASON, successor=SUCCESSOR, repository=repo, now=NOW)
    result = retire_tutorial(SLUG, reason=REASON, successor=later, repository=repo, now=NOW)
    assert result.successor == SUCCESSOR


def test_retire_rejects_blank_reason(repo: RecordingRepository) -> None:
    with pytest.raises(PermanentError, match="原因"):
        retire_tutorial(SLUG, reason=" ", successor=None, repository=repo, now=NOW)
    assert repo.update_calls == []


def test_retire_rejects_naive_now(repo: RecordingRepository) -> None:
    """時間一律 aware UTC；`to_iso` 在寫入之前就擋掉，不會留下半套退役。"""
    with pytest.raises(ValueError, match="timezone"):
        retire_tutorial(SLUG, reason=REASON, successor=None, repository=repo,
                        now=datetime(2026, 9, 14, 9, 0))
    assert repo.update_calls == []


def test_retire_rejects_unknown_slug(repo: RecordingRepository) -> None:
    with pytest.raises(PermanentError, match="找不到教學"):
        retire_tutorial("no-such-tutorial", reason=REASON, successor=None,
                        repository=repo, now=NOW)


def test_retire_turns_a_stale_revision_into_a_retryable_error(
        repo: RecordingRepository) -> None:
    """有人在讀 revision 與寫入之間插隊：轉成可重試錯誤，不靜默覆蓋對方的修改。"""
    repo.raw_items()  # 先讓種子落地，再打開插隊開關
    repo._table.bump_before_update = tutorial_pk(SLUG)
    with pytest.raises(TransientError, match="有人同時改過"):
        retire_tutorial(SLUG, reason=REASON, successor=SUCCESSOR, repository=repo, now=NOW)
    assert repo.get_tutorial(SLUG) is not None
    tutorial = repo.get_tutorial(SLUG)
    assert tutorial is not None and tutorial.status == TutorialStatus.ACTIVE
