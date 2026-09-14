"""Phase 23：`verify_version_complete` 只用基表一致讀取核對，缺任何一塊都回 `False`。

共用器材（`four_step_content`／`version_plan`／`build_ready_v2`／`fail_next`）直接 import
`test_create_version.py`：`tests/integration/conftest.py` 的 owner 是 Phase 06、修改者只有
Phase 07 與 Phase 08（00A §3.2），本 Phase 不是其中之一，所以兩支測試檔共用同一份器材而不是
往 conftest 加東西；`repository`／`table`／`bucket` 三個 moto fixture 仍然來自 conftest。

**核對不走 `by_target` GSI。** 它只有最終一致，剛寫入的邊可能還讀不到，用它核對會誤判
「關係不完整」，更糟的是誤判「完整」而讓 Phase 24 發布出一個缺邊的版本（設計 §10）。
"""

from typing import Any

import pytest
from test_create_version import (
    SLUG,
    V1,
    V2_PLAN,
    ReadyVersion,
    build_ready_v2,
    fail_next,
    four_step_content,
    seed_feature_and_tutorial,
    version_plan,
)

from training_kb.content import create_version, markdown_key, verify_version_complete
from training_kb.errors import ContentError, TransientError
from training_kb.keys import version_pk
from training_kb.repository import Repository

V2 = f"{SLUG}@v2"


@pytest.fixture
def seeded_feature(repository: Repository) -> Repository:
    seed_feature_and_tutorial(repository)
    return repository


@pytest.fixture
def ready_v2(repository: Repository, table: Any, bucket: Any) -> ReadyVersion:
    """已經跑完 `create_version` 的未發布 v2；`delete_*` 方法用來製造各種缺漏。"""
    return build_ready_v2(repository, table, bucket)


def test_ready_version_is_complete(ready_v2: ReadyVersion) -> None:
    """沒有動過手腳的 v2 是完整的，而且仍然未發布。"""
    assert verify_version_complete(V2, ready_v2.repository) is True
    assert ready_v2.version.published_at is None
    assert ready_v2.version.s3_key == markdown_key(SLUG, 2)


@pytest.mark.parametrize("break_it", ["delete_md", "delete_diff", "delete_step_edge",
                                      "delete_feature", "delete_supersedes_edge"])
def test_incomplete_version_is_not_complete(ready_v2: ReadyVersion, break_it: str) -> None:
    """五種缺漏：S3 全文、差異檔、步驟引用邊、被引用的 Feature、`SUPERSEDES` 邊。"""
    getattr(ready_v2, break_it)()
    assert verify_version_complete(V2, ready_v2.repository) is False


@pytest.mark.parametrize("break_it", ["delete_applied_to_edge", "delete_tutorial"])
def test_missing_applied_to_or_tutorial_is_not_complete(ready_v2: ReadyVersion,
                                                        break_it: str) -> None:
    """`APPLIED_TO` 邊與 TUTORIAL item 也在核對範圍內（`rules_applied` 是套用關係的權威）。"""
    getattr(ready_v2, break_it)()
    assert verify_version_complete(V2, ready_v2.repository) is False


def test_two_reference_edges_on_one_step_are_rejected(ready_v2: ReadyVersion) -> None:
    """§8 Boundary：一步兩條引用邊也是不完整，訊息要說得出「應恰好一條」。"""
    ready_v2.add_second_step_edge()
    assert verify_version_complete(V2, ready_v2.repository) is False
    with pytest.raises(Exception, match="應恰好一條"):
        create_version(version_plan(V2, number=2, supersedes=V1, reason="release:r_42",
                                    rules_applied=("R-007",)),
                       four_step_content(), ready_v2.repository)


@pytest.mark.parametrize("break_it", ["add_extra_step_item", "add_extra_applied_to_edge",
                                      "add_extra_supersedes_edge"])
def test_extra_relations_are_not_complete(ready_v2: ReadyVersion, break_it: str) -> None:
    """核對不只驗「不缺」，也要驗「不多」：多出來的 STEP／`APPLIED_TO`／`SUPERSEDES` 都不完整。

    只驗「不缺」時，上一版留下的第 5 步會跟著發布出去；`rules_applied=[]` 卻有
    `RULE#R-999 APPLIED_TO` 邊會讓權威欄位與邊互相矛盾（D17）；兩條 `SUPERSEDES` 會讓
    版本鏈分岔。三種都必須讓 Phase 24 停下來。
    """
    getattr(ready_v2, break_it)()
    assert verify_version_complete(V2, ready_v2.repository) is False


def test_corrupt_edge_target_is_a_problem_not_an_exception(ready_v2: ReadyVersion) -> None:
    """損壞的 `target` 讓核對回 `False`，而不是把 `ValueError` 丟給 Phase 24。"""
    ready_v2.corrupt_step_target()
    assert verify_version_complete(V2, ready_v2.repository) is False
    with pytest.raises(ContentError, match="版本核對失敗"):
        create_version(version_plan(V2, **V2_PLAN), four_step_content(), ready_v2.repository)


def test_missing_version_item_is_not_complete(seeded_feature: Repository) -> None:
    """連 VERSION item 都沒有時不必再讀 S3，直接回 `False`。"""
    assert verify_version_complete(V2, seeded_feature) is False


def test_interrupted_write_keeps_private_artifacts(seeded_feature: Repository) -> None:
    """寫 VERSION item 時中斷：私有 `.md` 留著（F36），版本不存在，核對回 `False`。"""
    repository = seeded_feature
    fail_next(repository, "put_meta")
    plan = version_plan(V1, number=1, supersedes=None, reason="gap:c12")
    with pytest.raises(TransientError):
        create_version(plan, four_step_content(), repository)
    assert repository.object_exists("tutorials/prepare-meeting/v1.md")
    assert repository.get_version(V1) is None
    assert verify_version_complete(V1, repository) is False


def test_interrupted_edge_write_is_resumable(seeded_feature: Repository) -> None:
    """寫邊時中斷：VERSION 在、邊不齊，核對回 `False`；同一份 plan 重送就補齊。"""
    repository = seeded_feature
    plan = version_plan(V1, number=1, supersedes=None, reason="gap:c12")
    fail_next(repository, "put_edge")
    with pytest.raises(TransientError):
        create_version(plan, four_step_content(), repository)
    assert repository.get_version(V1) is not None
    assert repository.query_pk(version_pk(V1)) != []
    assert verify_version_complete(V1, repository) is False

    version = create_version(plan, four_step_content(), repository)
    assert version.published_at is None
    assert verify_version_complete(V1, repository) is True
