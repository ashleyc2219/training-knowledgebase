"""Phase 49 Task 2：改名收尾——PK 不變、舊名進 aliases、撞名整次拒絕（D06／D07、`REL` 3／15）。

**Given** 一個已經定位到的 Feature 與一對 `old_name`／`new_name`、**When** Phase 52 的
`UpdateAliases` 在發布成功之後呼叫、**Then** 只有 `name` 與 `aliases` 兩個欄位會變，主鍵
永遠是第一次建立時的值；任何一個目標名稱撞到別的 Feature 就整次拒絕，不留半套資料。

這支檔的 `fake_repo` 是**區域** fixture：`tests/unit/conftest.py` 只有 P15 的 `RecordingWriter`，
而該檔依 COMMON.md R3.6 只有 P55 能改。本檔不需要 writer——alias 更新完全不呼叫模型。
"""

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from training_kb.errors import CoordinationError, PermanentError
from training_kb.keys import META, feature_pk
from training_kb.models import Feature
from training_kb.pipelines.release import update_feature_aliases
from training_kb.repository import DynamoItem, DynamoValue

FIXED_TS = datetime(2026, 9, 14, 3, 0, 0, tzinfo=UTC)
FIRST_REVISION = 7
"""`revision_of` 回的值刻意不是 1：斷言 `expected_revision` 真的來自它，不是寫死的常數。"""


def feature(feature_id: str, *, name: str, aliases: list[str]) -> Feature:
    return Feature(feature_id=feature_id, name=name, aliases=aliases, first_seen=FIXED_TS)


class FakeRepository:
    """假 `Repository`：`scan_entity`／`revision_of`／`update_meta` 三個方法對齊 Phase 06／08。

    `update_meta` 照真實版本擋 `RESERVED_ATTRS`、比對 `expected_revision`、回**新的** revision，
    所以「先寫再檢查」這種錯法會在 `updates` 上留下痕跡而被斷言抓到。
    `scan_entity` 回 raw item 並多塞一筆關係邊，逼實作先濾 `SK == META`。
    """

    RESERVED = frozenset({"PK", "SK", "target", "entity", "_revision"})

    def __init__(self) -> None:
        self.features: list[Feature] = []
        self.revisions: dict[str, int] = {}
        self.updates: list[tuple[str, dict[str, DynamoValue], int]] = []
        self.revision_calls: list[str] = []

    def scan_entity(self, entity: str, *, consistent: bool = True,
                    meta_only: bool = True) -> list[DynamoItem]:
        rows: list[DynamoItem] = []
        for item in self.features:
            pk = feature_pk(item.feature_id)
            payload: DynamoItem = dict(item.model_dump(mode="json"))
            rows.append({"PK": pk, "SK": META, "entity": entity, "_revision": 1, **payload})
            if not meta_only:
                rows.append({"PK": pk, "SK": f"REFERENCES#{pk}", "entity": entity, "target": pk})
        return rows

    def revision_of(self, pk: str) -> int:
        self.revision_calls.append(pk)
        return self.revisions.get(pk, FIRST_REVISION)

    def update_meta(self, pk: str, changes: Mapping[str, DynamoValue], *,
                    expected_revision: int) -> int:
        if not changes:
            raise PermanentError(f"update_meta needs at least one change: {pk}")
        reserved = sorted(self.RESERVED.intersection(changes))
        if reserved:
            raise PermanentError(f"reserved attributes are not updatable: {reserved}")
        current = self.revisions.get(pk, FIRST_REVISION)
        if current != expected_revision:
            raise CoordinationError(f"stale revision for {pk}: {expected_revision} != {current}")
        self.updates.append((pk, dict(changes), expected_revision))
        self.revisions[pk] = current + 1
        return current + 1

    @property
    def updated_pk(self) -> str | None:
        """最後一次 `update_meta` 打到的 PK；沒寫過就是 `None`（撞名案例要斷言這個）。"""
        return self.updates[-1][0] if self.updates else None


@pytest.fixture
def fake_repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def target() -> Feature:
    """§2 的改版**前**狀態：PK 後綴 `Prepare`，顯示名稱還是舊的 `Meeting Summary`。"""
    return feature("Prepare", name="Meeting Summary", aliases=[])


def test_alias_update_keeps_primary_key_and_moves_old_name(fake_repo, target):
    """`REL` Rule 3／15：Given 改名完成 When 更新 alias Then PK 不動、舊名進 aliases。"""
    fake_repo.features = [target]

    updated = update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare",
                                     repository=fake_repo)

    assert fake_repo.updated_pk == "FEATURE#Prepare"
    assert (updated.feature_id, updated.name, updated.aliases) == (
        "Prepare", "Prepare", ["Meeting Summary"])
    assert fake_repo.updates == [
        ("FEATURE#Prepare", {"name": "Prepare", "aliases": ["Meeting Summary"]}, FIRST_REVISION)]


def test_expected_revision_comes_from_revision_of(fake_repo, target):
    """Given Phase 06 的樂觀鎖 When 更新 Then `expected_revision` 只能是 `revision_of(pk)`。"""
    pk = feature_pk("Prepare")
    fake_repo.features = [target]
    fake_repo.revisions[pk] = 12

    update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare",
                           repository=fake_repo)

    assert fake_repo.revision_calls == [pk]
    assert fake_repo.updates[-1][2] == 12


def test_alias_clash_rejects_the_whole_update(fake_repo, target):
    """D07：Given 新名稱是別人的 alias When 更新 Then `PermanentError`，`update_meta` 零次。"""
    fake_repo.features = [target, feature("Share", name="Share Summary", aliases=["prepare"])]

    with pytest.raises(PermanentError, match="衝突"):
        update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare",
                               repository=fake_repo)

    assert fake_repo.updated_pk is None
    assert fake_repo.updates == []


def test_clash_on_the_old_name_also_rejects_everything(fake_repo, target):
    """Given 舊名已被別的 Feature 當成現名 When 更新 Then 整次拒絕，不只搬一半。"""
    fake_repo.features = [target, feature("Share", name="Meeting Summary", aliases=[])]

    with pytest.raises(PermanentError, match="Share"):
        update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare",
                               repository=fake_repo)

    assert fake_repo.updates == []


def test_new_name_is_removed_from_its_own_aliases(fake_repo):
    """本計畫選擇：Given 自己的別名就是新名稱（只差大小寫）When 更新 Then 那個別名被移掉。"""
    target = feature("Prepare", name="Meeting Summary", aliases=["prepare", "Zeta"])
    fake_repo.features = [target]

    updated = update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare",
                                     repository=fake_repo)

    assert updated.aliases == ["Meeting Summary", "Zeta"]
    assert updated.name not in updated.aliases


def test_result_is_still_a_valid_feature(fake_repo, target):
    """`model_copy` 不重新驗證，所以自己檢查一次：結果餵回模型仍然合法。"""
    fake_repo.features = [target]

    updated = update_feature_aliases(target, old_name="  Meeting Summary  ",
                                     new_name="  Prepare  ", repository=fake_repo)

    assert Feature.model_validate(updated.model_dump()) == updated
    assert updated.name == "Prepare" and updated.aliases == ["Meeting Summary"]


def test_running_twice_gives_byte_identical_aliases(fake_repo, target):
    """Given 同一組輸入 When 連跑兩次 Then 兩次的 `name`／`aliases` 完全相同（aliases 有排序）。"""
    fake_repo.features = [target]

    first = update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare",
                                   repository=fake_repo)
    fake_repo.features = [first]
    second = update_feature_aliases(first, old_name="Meeting Summary", new_name="Prepare",
                                    repository=fake_repo)

    assert (second.name, second.aliases) == (first.name, first.aliases)
    assert second.feature_id == "Prepare"
    assert [pk for pk, _, _ in fake_repo.updates] == ["FEATURE#Prepare", "FEATURE#Prepare"]


def test_aliases_are_sorted(fake_repo):
    """Given 舊別名順序雜亂 When 更新 Then 寫出去的 aliases 是排序過的，重跑 byte 相同。"""
    target = feature("Prepare", name="Meeting Summary", aliases=["Zeta", "Alpha"])
    fake_repo.features = [target]

    updated = update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare",
                                     repository=fake_repo)

    assert updated.aliases == ["Alpha", "Meeting Summary", "Zeta"]


def test_second_rename_keeps_the_original_primary_key(fake_repo, target):
    """`REL` Rule 3 的 Identity 案例：Given 連續兩次改名 Then PK 始終是第一次建立的值。"""
    fake_repo.features = [target]
    once = update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare",
                                  repository=fake_repo)
    fake_repo.features = [once]

    twice = update_feature_aliases(once, old_name="Prepare", new_name="Meeting Prep",
                                   repository=fake_repo)

    assert twice.feature_id == "Prepare"
    assert {pk for pk, _, _ in fake_repo.updates} == {"FEATURE#Prepare"}
    assert (twice.name, twice.aliases) == ("Meeting Prep", ["Meeting Summary", "Prepare"])


@pytest.mark.parametrize(("old_name", "new_name"), [
    ("", "Prepare"),
    ("Meeting Summary", ""),
    ("   ", "Prepare"),
    ("Meeting Summary", "   "),
])
def test_empty_name_is_a_wiring_mistake(fake_repo, target, old_name, new_name):
    """Given 呼叫端接錯線（少一個名稱）When 更新 Then `PermanentError`，不寫入。"""
    fake_repo.features = [target]

    with pytest.raises(PermanentError, match="不可為空"):
        update_feature_aliases(target, old_name=old_name, new_name=new_name,
                               repository=fake_repo)

    assert fake_repo.updates == []
