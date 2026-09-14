"""Phase 27：`find_current_published_steps_referencing` 在 moto 本機表上的行為。

涵蓋 GSI 落後、歷史版、未發布版與空分頁四種情況（`repository`／`paged_repository`／`table`
fixture 來自 `tests/integration/conftest.py`，owner 是 Phase 06，本 Phase 不改它）。

**moto 全綠只證明資料形狀與分頁邏輯。** moto 的 GSI 是即時的，所以「GSI 落後」只能用
`query_by_target` 回空清單來模擬；真實 DynamoDB 的最終一致行為要靠 §8 的人工驗收
（先寫一筆新的 `REFERENCES` 邊、立刻查一次，並保存當下 `query_by_target` 的回傳存證）。
本檔任何一條 PASS 都不代表 O2／O3 已通過。
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.errors import PermanentError
from training_kb.keys import feature_pk, step_pk, tutorial_pk
from training_kb.models import (
    Feature,
    Tutorial,
    TutorialStatus,
    TutorialVersion,
)
from training_kb.repository import Repository

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
FEATURE = "Prepare"
SLUG = "prepare-meeting"
OTHER_SLUG = "share-summary"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
OTHER_V1 = f"{OTHER_SLUG}@v1"
DRAFT = f"{OTHER_SLUG}@v2"


# --- 共用器材 ---------------------------------------------------------------


def put_version(repository: Repository, version_id: str, *, published: bool) -> None:
    slug, _, number = version_id.partition("@v")
    repository.put_meta(TutorialVersion(
        version_id=version_id, slug=slug, supersedes=None, reason="gap:c12",
        rules_applied=[], s3_key=f"tutorials/{slug}/v{number}.md",
        published_at=NOW if published else None))


def put_tutorial(repository: Repository, slug: str, *, current_version: str | None,
                 feature_id: str) -> None:
    repository.put_meta(Tutorial(slug=slug, current_version=current_version, topic=slug,
                                 feature_ids=[feature_id], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id=None))


def put_step(repository: Repository, version_id: str, number: int) -> None:
    repository.put_edge(step_pk(version_id, number), "REFERENCES", feature_pk(FEATURE),
                        {"type": "read", "text": f"{version_id} 第 {number} 步"})


def blind_gsi(repository: Repository) -> None:
    """讓 `query_by_target` 永遠回空清單，模擬 GSI 還沒把任何邊傳播出來。

    moto 的 GSI 是即時的，沒有辦法讓某一筆索引項目暫時消失，所以把整個候選來源關掉；
    這是比真實落後更嚴格的情況：結果集合必須完全由基表一致讀取決定。
    """
    def nothing(target_pk: str) -> list[dict[str, Any]]:
        assert target_pk.startswith("FEATURE#"), target_pk
        return []

    repository.query_by_target = nothing  # 只改這一個 instance，fixture 每個測試都是新的


@pytest.fixture
def graph(repository: Repository) -> Repository:
    """§2 的固定種子：Prepare 被歷史版、current 已發布版與未發布草稿版各引用一次。"""
    repository.put_meta(Feature(feature_id=FEATURE, name=FEATURE,
                               aliases=["Meeting Summary"], first_seen=NOW))
    put_tutorial(repository, SLUG, current_version=V2, feature_id=FEATURE)
    put_tutorial(repository, OTHER_SLUG, current_version=OTHER_V1, feature_id=FEATURE)
    for version_id in (V1, V2, OTHER_V1):
        put_version(repository, version_id, published=True)
    put_version(repository, DRAFT, published=False)
    put_step(repository, V1, 3)
    put_step(repository, V2, 3)
    put_step(repository, DRAFT, 1)
    return repository


# --- Task 2：歷史版、未發布版、GSI 落後與空分頁 -----------------------------


def test_only_the_current_published_version_is_returned(graph: Repository) -> None:
    """歷史版 v1 與未發布的 `share-summary@v2` 都命中同一個 Feature，但都不是目前已發布版。"""
    steps = graph.find_current_published_steps_referencing(FEATURE)
    assert [(step.tutorial_version, step.number) for step in steps] == [(V2, 3)]
    assert steps[0].text == f"{V2} 第 3 步"
    assert steps[0].feature_id == FEATURE


def test_base_table_check_survives_a_silent_gsi(graph: Repository) -> None:
    """GSI 一筆候選都沒給，基表一致讀取仍然要回齊目前已發布版的引用（設計 §10）。"""
    blind_gsi(graph)
    steps = graph.find_current_published_steps_referencing(FEATURE)
    assert [(step.tutorial_version, step.number) for step in steps] == [(V2, 3)]


def test_current_version_without_published_at_is_excluded(graph: Repository) -> None:
    """只把 `current_version` 切到草稿版不算發布：`published_at` 是空的就不回傳。"""
    pk = tutorial_pk(OTHER_SLUG)
    graph.update_meta(pk, {"current_version": DRAFT},
                      expected_revision=graph.revision_of(pk))
    steps = graph.find_current_published_steps_referencing(FEATURE)
    assert [(step.tutorial_version, step.number) for step in steps] == [(V2, 3)]


def test_empty_pages_do_not_end_the_walk(graph: Repository,
                                         paged_repository: Repository) -> None:
    """`page_size=1` 讓帶 filter 的 Scan 出現「這一頁零筆但游標還在」，提前停止就會漏資料。"""
    assert [(step.tutorial_version, step.number)
            for step in paged_repository.find_current_published_steps_referencing(FEATURE)] == [
        (V2, 3)]
    assert [version.version_id for version in
            paged_repository.list_versions_of_tutorial(SLUG)] == [V1, V2]


def test_gsi_candidate_without_base_step_fails_loudly(graph: Repository, table: Any) -> None:
    """邊少了 `entity` 屬性：`by_target` 看得到它，`scan_entity` 卻掃不到 -> 基表資料不完整。

    這是 §6 說的那個情況，只能直接對 moto 的表動手寫（`put_edge` 一定會補上 `entity`）。
    目前已發布版的候選在基表讀不到就必須明確失敗，不靜默跳過、也不在查詢裡補邊（Phase 28 才補）。
    """
    table.put_item(Item={"PK": step_pk(V2, 7), "SK": f"REFERENCES#{feature_pk(FEATURE)}",
                         "target": feature_pk(FEATURE), "type": "read", "text": "漏了 entity"})
    with pytest.raises(PermanentError, match=r"STEP#prepare-meeting@v2#7"):
        graph.find_current_published_steps_referencing(FEATURE)


def test_history_candidate_without_base_step_is_skipped(graph: Repository, table: Any) -> None:
    """同樣缺 `entity`，但落在歷史版上：不是目前已發布版就只跳過，不是錯誤。"""
    table.put_item(Item={"PK": step_pk(V1, 7), "SK": f"REFERENCES#{feature_pk(FEATURE)}",
                         "target": feature_pk(FEATURE), "type": "read", "text": "漏了 entity"})
    steps = graph.find_current_published_steps_referencing(FEATURE)
    assert [(step.tutorial_version, step.number) for step in steps] == [(V2, 3)]
