"""Phase 50 Task 1：`find_release_hits` 只把 Phase 27 的反查轉成 `StepHit` 座標（不連 AWS）。

`three_tutorials` 是本檔自備的 fixture，做法與 Phase 27 的 `tests/unit/test_graph_queries.py`
相同：被測的是**真的** `Repository`，只有底下的表換成記憶體裡的 `FakeTable`，所以
`scan_entity`／`query_by_target`／`get_steps`／`get_version` 與
`find_current_published_steps_referencing` 全部跑真的程式。`gsi_hide` 讓某個起點的邊暫時不
出現在 `by_target`（GSI 最終一致還沒傳播），`clear_steps` 只刪基表的 STEP item、GSI 候選照
留（基表資料不完整）。兩個鉤子都作用在真正的查詢路徑上，不是把答案直接餵給被測函式。

§2 的固定圖譜：A `prepare-meeting`（current `@v2`，四步，第 3 步引用 `FEATURE#Prepare`；
歷史版 `@v1` 第 3 步也引用它）、B `share-summary`（current `@v1`，兩步；另有未發布的 `@v2`，
第 1 步也引用它）、C `notification-settings`（current `@v1`，兩步）。
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.errors import PermanentError
from training_kb.keys import META, feature_pk, step_pk, tutorial_pk
from training_kb.models import Tutorial, TutorialStatus, TutorialVersion
from training_kb.pipelines.release import StepHit, find_release_hits
from training_kb.repository import Repository

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
FEATURE = "Prepare"
OTHER_FEATURE = "Share"
A, B, C = "prepare-meeting", "share-summary", "notification-settings"
A_V1, A_V2 = f"{A}@v1", f"{A}@v2"
B_V1, B_V2 = f"{B}@v1", f"{B}@v2"
C_V1 = f"{C}@v1"
A_V2_STEP3 = StepHit(A, A_V2, 3)


def step_text(version_id: str, number: int) -> str:
    return f"{version_id} 第 {number} 步"


# --- 假的儲存層（只實作 `Repository` 真的會送出的四個 boto3 操作） -------------


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


def _keys_only(item: Mapping[str, Any]) -> dict[str, Any]:
    """`by_target` 是 KEYS_ONLY：索引裡只有 `PK`／`SK`／`target`。"""
    return {"PK": item["PK"], "SK": item["SK"], "target": item["target"]}


class FakeTable:
    """記憶體表；`hidden` 讓某個起點在 GSI 暫時消失，`ghosts` 是基表讀不到的 GSI 候選。"""

    name = "fake_training_kb"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.ghosts: list[dict[str, Any]] = []
        self.hidden: set[str] = set()

    def put_item(self, **arguments: Any) -> dict[str, Any]:
        item = dict(arguments["Item"])
        self.items[(str(item["PK"]), str(item["SK"]))] = item
        return {}

    def get_item(self, **arguments: Any) -> dict[str, Any]:
        key = arguments["Key"]
        item = self.items.get((str(key["PK"]), str(key["SK"])))
        return {} if item is None else {"Item": dict(item)}

    def query(self, **arguments: Any) -> dict[str, Any]:
        condition = arguments["KeyConditionExpression"]
        if arguments.get("IndexName") == "by_target":
            rows = [_keys_only(item) for item in self.items.values()
                    if "target" in item and str(item["PK"]) not in self.hidden]
            rows.extend(dict(ghost) for ghost in self.ghosts)
        else:
            rows = [dict(item) for item in self.items.values()]
        found = [row for row in rows if _matches(row, condition)]
        return {"Items": sorted(found, key=lambda row: (str(row["PK"]), str(row["SK"])))}

    def scan(self, **arguments: Any) -> dict[str, Any]:
        condition = arguments.get("FilterExpression")
        return {"Items": [dict(item) for item in self.items.values()
                          if condition is None or _matches(item, condition)]}


class ReleaseGraphRepository(Repository):
    """真的 `Repository` + 種資料用的方法；反查與六個固定查詢一個都沒有被覆寫。"""

    def __init__(self) -> None:
        self.table = FakeTable()
        super().__init__(self.table)

    def add_tutorial(self, slug: str, *, current_version: str | None,
                     status: TutorialStatus = TutorialStatus.ACTIVE) -> None:
        self.put_meta(Tutorial(slug=slug, current_version=current_version, topic=slug,
                               feature_ids=[FEATURE], status=status,
                               successor=None, cluster_id=None))

    def add_version(self, version_id: str, *, published: bool) -> None:
        slug, _, number = version_id.partition("@v")
        self.put_meta(TutorialVersion(
            version_id=version_id, slug=slug, supersedes=None, reason="release:r_42",
            rules_applied=[], s3_key=f"tutorials/{slug}/v{number}.md",
            published_at=NOW if published else None))

    def add_step(self, version_id: str, number: int, feature_id: str,
                 text: str | None = None) -> None:
        self.put_edge(step_pk(version_id, number), "REFERENCES", feature_pk(feature_id),
                      {"type": "read", "text": text or step_text(version_id, number)})

    # --- 改資料：直接動假表，`Repository` 沒有、也不該有這些 API ---

    def set_current_version(self, slug: str, version_id: str | None) -> None:
        self.table.items[(tutorial_pk(slug), META)]["current_version"] = version_id

    def set_status(self, slug: str, status: str) -> None:
        self.table.items[(tutorial_pk(slug), META)]["status"] = status

    def gsi_hide(self, pk: str) -> None:
        """讓這個起點的邊暫時不出現在 `by_target`（GSI 最終一致，還沒傳播）。"""
        self.table.hidden.add(pk)

    def clear_steps(self, version_id: str) -> None:
        """只刪基表的 STEP item，GSI 候選照留：模擬「基表資料不完整」。"""
        for key in [key for key in self.table.items if key[0].startswith(f"STEP#{version_id}#")]:
            self.table.ghosts.append(_keys_only(self.table.items.pop(key)))


@pytest.fixture
def three_tutorials() -> ReleaseGraphRepository:
    repository = ReleaseGraphRepository()
    repository.add_tutorial(A, current_version=A_V2)
    repository.add_tutorial(B, current_version=B_V1)
    repository.add_tutorial(C, current_version=C_V1)
    for version_id in (A_V1, A_V2, B_V1, C_V1):
        repository.add_version(version_id, published=True)
    repository.add_version(B_V2, published=False)
    repository.add_step(A_V1, 3, FEATURE)                     # 歷史版也引用同一個 Feature
    for number in (1, 2, 4):
        repository.add_step(A_V2, number, OTHER_FEATURE)
    repository.add_step(A_V2, 3, FEATURE)
    repository.add_step(B_V1, 1, OTHER_FEATURE)
    repository.add_step(B_V1, 2, OTHER_FEATURE)
    repository.add_step(B_V2, 1, FEATURE)                     # 未發布版也引用同一個 Feature
    repository.add_step(C_V1, 1, "Notify")
    repository.add_step(C_V1, 2, "Notify")
    return repository


# --- Task 1：把 Phase 27 的反查包成 `StepHit` 座標 ---------------------------


def test_only_current_published_steps_are_hit(three_tutorials: ReleaseGraphRepository) -> None:
    """REL Rule 5／F17：Given 三篇教學與兩個非 current 已發布的引用，
    When 反查 `Prepare`，Then 只有 A `@v2` 第 3 步命中，歷史版與未發布版都不在，
    而 B、C 零命中（REL Rule 12 的 KEEP 前提）。"""
    assert find_release_hits(FEATURE, repository=three_tutorials) == (A_V2_STEP3,)


def test_stale_gsi_does_not_hide_a_base_table_edge(
        three_tutorials: ReleaseGraphRepository) -> None:
    """設計 §10：Given GSI 還沒反映這條邊，When 反查，Then 基表方向仍要補齊同一筆。"""
    three_tutorials.gsi_hide(step_pk(A_V2, 3))
    assert find_release_hits(FEATURE, repository=three_tutorials) == (A_V2_STEP3,)


def test_gsi_row_without_base_row_is_not_silently_dropped(
        three_tutorials: ReleaseGraphRepository) -> None:
    """Given 基表已無該步驟、GSI 還留著候選，When 反查，
    Then Phase 27 的 `PermanentError` 原樣往上拋，不被改判成空 tuple。"""
    three_tutorials.clear_steps(A_V2)
    with pytest.raises(PermanentError, match="STEP#prepare-meeting@v2#3"):
        find_release_hits(FEATURE, repository=three_tutorials)


def test_two_hits_in_one_tutorial_sort_by_number(
        three_tutorials: ReleaseGraphRepository) -> None:
    """Given 同一篇 current 已發布版有兩步引用，When 反查，Then 依 `number` 升序。"""
    three_tutorials.add_step(A_V2, 1, FEATURE)
    assert find_release_hits(FEATURE, repository=three_tutorials) == (
        StepHit(A, A_V2, 1), A_V2_STEP3)


def test_retired_tutorial_is_still_hit_because_it_keeps_a_published_current_version(
        three_tutorials: ReleaseGraphRepository) -> None:
    """現況核對（2026-09-14）：Given 該篇教學已退役，When 反查，Then 它**仍然**命中。

    Phase 50 文件 Task 1 Step 4 原本假設「`status="retired"` 的教學不納入，由 Phase 27 的篩選
    達成」，但既有程式不是這樣：`retire_tutorial` 只改 `status` 與 `successor`，
    `current_version` 與該版的 `published_at` 都保留（設計 §8.1 要求退役保留歷史），而
    Phase 27 的 `_is_current_published` 只看「是不是 current 而且已發布」，沒有看 `status`。
    本 Phase 依 D-38 只包裝、不得自己加一層篩選，所以照實斷言現況；要不要排除退役教學是
    Phase 27／Phase 52 的決定（報告 §9 已列給 controller）。
    """
    three_tutorials.set_status(A, "retired")
    assert find_release_hits(FEATURE, repository=three_tutorials) == (A_V2_STEP3,)


def test_tutorial_without_current_version_is_not_hit(
        three_tutorials: ReleaseGraphRepository) -> None:
    """Given 該篇教學還沒首次發布（`current_version` 是 `None`），When 反查，Then 零命中。"""
    three_tutorials.set_current_version(A, None)
    assert find_release_hits(FEATURE, repository=three_tutorials) == ()


def test_step_hit_is_hashable_and_ordered_for_union(
        three_tutorials: ReleaseGraphRepository) -> None:
    """00A §6.9：`StepHit` 是 frozen dataclass，呼叫端才能用 `set(direct) | set(net)` 取聯集。"""
    hits = find_release_hits(FEATURE, repository=three_tutorials)
    assert set(hits) | set(hits) == {A_V2_STEP3}
    assert (A_V2_STEP3.slug, A_V2_STEP3.version_id, A_V2_STEP3.number) == (A, A_V2, 3)
