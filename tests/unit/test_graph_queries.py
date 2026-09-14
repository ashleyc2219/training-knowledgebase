"""Phase 27：六種固定圖譜查詢的篩選、排序、alias 撞名與零 AI 呼叫（不連 AWS）。

`repo` 是本檔自備的 fixture：一個**真的** `Repository`，只是底下的表換成記憶體裡的
`FakeTable`。`FakeTable` 只實作 `Repository` 會用到的四個 boto3 操作
（`put_item`／`get_item`／`query`／`scan`），所以 `query_pk`／`query_by_target`／
`scan_entity`／`get_steps`／`get_meta` 與被測的六個固定查詢全部跑真的程式，
被換掉的只有儲存層；`paginate`／`gsi_hide`／`gsi_only_edge` 這些鉤子也因此作用在
真正的分頁迴圈與 GSI 候選路徑上，而不是把答案直接餵給被測方法。

§2 的固定種子：`FEATURE#Prepare` 被三個步驟引用——`prepare-meeting@v1 #3`（歷史版）、
`prepare-meeting@v2 #3`（current 已發布版）、`share-summary@v2 #1`（尚未發布的草稿版）。
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.errors import PermanentError
from training_kb.keys import META, feature_pk, rule_pk, step_pk, tutorial_pk, version_pk
from training_kb.models import Feature, Tutorial, TutorialStatus, TutorialVersion
from training_kb.repository import Repository, version_sort_key

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
FEATURE = "Prepare"
ALIAS = "Meeting Summary"
SLUG = "prepare-meeting"
OTHER_SLUG = "share-summary"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
V10 = f"{SLUG}@v10"
OTHER_V1 = f"{OTHER_SLUG}@v1"
DRAFT = f"{OTHER_SLUG}@v2"
RULE = "R-007"


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


def _keys_only(item: Mapping[str, Any]) -> dict[str, Any]:
    """`by_target` 是 KEYS_ONLY：索引裡只有 `PK`／`SK`／`target`，內容要回基表拿。"""
    return {"PK": item["PK"], "SK": item["SK"], "target": item["target"]}


class FakeTable:
    """記憶體表：只實作 `Repository` 用到的四個 boto3 操作，其餘一律不提供。

    `scan` 依 `pages` 切頁（沒指定就只有一頁），**空的一頁仍然帶 `LastEvaluatedKey`**，
    所以 `Repository._paged` 提早停止會被抓到。`query` 分兩種：帶 `IndexName` 的走
    最終一致的 `by_target`（可用 `hidden` 讓某個起點暫時消失、用 `ghosts` 加一筆基表沒有的
    候選），其餘走基表。
    """

    name = "fake_training_kb"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.ghosts: list[dict[str, Any]] = []
        self.hidden: set[str] = set()
        self.pages: list[list[tuple[str, str]]] = []

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


class GraphRepository(Repository):
    """真的 `Repository` + 種資料用的方法；六個固定查詢一個都沒有被覆寫。"""

    def __init__(self) -> None:
        self.table = FakeTable()
        super().__init__(self.table)

    # --- 種資料 ---

    def add_feature(self, *, feature_id: str, name: str,
                    aliases: Sequence[str] = ()) -> None:
        self.put_meta(Feature(feature_id=feature_id, name=name, aliases=list(aliases),
                              first_seen=NOW))

    def add_tutorial(self, slug: str, *, current_version: str | None,
                     feature_ids: Sequence[str]) -> None:
        self.put_meta(Tutorial(slug=slug, current_version=current_version, topic=slug,
                               feature_ids=list(feature_ids), status=TutorialStatus.ACTIVE,
                               successor=None, cluster_id=None))

    def add_version(self, version_id: str, *, published: bool,
                    rules_applied: Sequence[str] = ()) -> None:
        slug, _, number = version_id.partition("@v")
        self.put_meta(TutorialVersion(
            version_id=version_id, slug=slug, supersedes=None, reason="gap:c12",
            rules_applied=list(rules_applied), s3_key=f"tutorials/{slug}/v{number}.md",
            published_at=NOW if published else None))

    def add_step(self, version_id: str, number: int, feature_id: str = FEATURE) -> None:
        self.put_edge(step_pk(version_id, number), "REFERENCES", feature_pk(feature_id),
                      {"type": "read", "text": f"{version_id} 第 {number} 步"})

    def add_edge(self, pk: str, relation: str, target: str) -> None:
        self.put_edge(pk, relation, target)

    # --- 改資料：直接動假表，`Repository` 沒有、也不該有這些 API ---

    def _meta(self, pk: str) -> dict[str, Any]:
        return self.table.items[(pk, META)]

    def set_rules_applied(self, version_id: str, rules: Sequence[str]) -> None:
        self._meta(version_pk(version_id))["rules_applied"] = list(rules)

    def set_current_version(self, slug: str, version_id: str | None) -> None:
        self._meta(tutorial_pk(slug))["current_version"] = version_id

    def set_status(self, slug: str, status: str) -> None:
        self._meta(tutorial_pk(slug))["status"] = status

    # --- 分頁與 GSI 鉤子 ---

    def paginate(self, *pages: Iterable[str]) -> None:
        """把這些版本安排到指定的 Scan 分頁；沒被點名的 item 一律留在第 0 頁。

        允許空頁：空頁仍然帶 `LastEvaluatedKey`，所以「空的一頁不等於沒有下一頁」
        會被真的 `_paged` 迴圈驗到。沒建過的版本會補建成已發布版。
        """
        for page in pages:
            for version_id in page:
                if self.get_version(version_id) is None:
                    self.add_version(version_id, published=True)
        self.table.pages = [[(version_pk(version_id), META) for version_id in page]
                            for page in pages]

    def gsi_hide(self, pk: str) -> None:
        """讓這個起點的邊暫時不出現在 `by_target`（GSI 最終一致，還沒傳播）。"""
        self.table.hidden.add(pk)

    def gsi_only_edge(self, pk: str, relation: str, target: str) -> None:
        """只出現在 `by_target` 候選、基表讀不到的邊（基表資料不完整）。"""
        self.table.ghosts.append({"PK": pk, "SK": f"{relation}#{target}", "target": target})


@pytest.fixture
def repo() -> GraphRepository:
    repository = GraphRepository()
    repository.add_feature(feature_id=FEATURE, name=FEATURE, aliases=[ALIAS])
    repository.add_feature(feature_id="Share", name="Share")
    repository.add_tutorial(SLUG, current_version=V2, feature_ids=[FEATURE])
    repository.add_tutorial(OTHER_SLUG, current_version=OTHER_V1, feature_ids=["Share"])
    repository.add_version(V1, published=True)
    repository.add_version(V2, published=True, rules_applied=[RULE])
    repository.add_version(OTHER_V1, published=True)
    repository.add_version(DRAFT, published=False)
    repository.add_step(V1, 3)
    repository.add_step(V2, 3)
    repository.add_step(DRAFT, 1)
    repository.add_edge(rule_pk(RULE), "APPLIED_TO", version_pk(V2))
    return repository


# --- Task 1：Feature 定位與版本清單 -----------------------------------------


def test_find_feature_prefers_name_over_alias_and_rejects_duplicate_alias(repo) -> None:
    """設計 §7.4：先比 name 再比 alias；D07 要求 alias 唯一，撞名不自行挑一個。"""
    assert repo.find_feature_by_name_or_alias("Prepare").feature_id == "Prepare"
    assert repo.find_feature_by_name_or_alias("Meeting Summary").feature_id == "Prepare"
    assert repo.find_feature_by_name_or_alias("Nope") is None
    repo.add_feature(feature_id="Notify", name="Notify", aliases=["Meeting Summary"])
    with pytest.raises(PermanentError, match="Meeting Summary"):
        repo.find_feature_by_name_or_alias("Meeting Summary")


def test_list_versions_of_tutorial_sorts_by_number_and_reads_every_page(repo) -> None:
    """GPH Rule 4：含未發布版，依版號升序；第二頁為空但仍有下一頁，不得提早停止。"""
    repo.paginate(["prepare-meeting@v1", "prepare-meeting@v2"], [], ["prepare-meeting@v10"])
    ids = [version.version_id for version in repo.list_versions_of_tutorial("prepare-meeting")]
    assert ids == ["prepare-meeting@v1", "prepare-meeting@v2", "prepare-meeting@v10"]
    assert version_sort_key("prepare-meeting@v10") == ("prepare-meeting", 10)
    with pytest.raises(PermanentError, match="prepare-meeting"):
        version_sort_key("prepare-meeting")


def test_list_versions_of_tutorial_keeps_drafts_and_skips_other_slugs(repo) -> None:
    """回傳**全部**版本（含未發布），篩已發布是呼叫端的事（P24 索引頁）；別篇不入選。"""
    versions = repo.list_versions_of_tutorial(OTHER_SLUG)
    assert [(version.version_id, version.published_at is None) for version in versions] == [
        (OTHER_V1, False), (DRAFT, True)]


def test_relation_edges_are_never_mistaken_for_versions(repo) -> None:
    """D29：`entity` 等於 PK 前綴，所以 `SUPERSEDES` 邊也被掃到；`SK != META` 要先濾掉。"""
    repo.add_edge(version_pk(V2), "SUPERSEDES", version_pk(V1))
    assert [version.version_id for version in repo.list_versions_of_tutorial(SLUG)] == [V1, V2]
