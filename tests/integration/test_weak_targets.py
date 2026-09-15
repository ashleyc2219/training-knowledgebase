"""Phase 44 在真實查詢路徑（moto 單表）上的選取行為：只看 active 教學的已發布 current 版。

`REV` Rule 1 在這裡只是**相關**證據（primary 在 Phase 48 的排程）：本檔斷言的是「每次執行都
重新取 active 教學的已發布 `current_version`，並用該版截至 `now` 的全部有效回饋重算」，
不斷言「每日」。moto 的 PASS 只證明資料形狀與查詢路徑，不是實表行為的證據。

資料以設計 §11.2 的 A v1 八筆回饋為基準（評分 2、2、3、3、3、3、3、4 → 平均 23/8 = 2.875，
類別全部是「找不到按鈕」）。O7 未核定前它仍是**待核定的合成資料**，`mode="demo"` 的命中
不得說成正式門檻已滿足。
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest

from training_kb.keys import feedback_pk, version_pk
from training_kb.models import Feedback, Tutorial, TutorialStatus, TutorialVersion
from training_kb.pipelines.feedback import select_weak_targets
from training_kb.repository import Repository

NOW = datetime(2026, 9, 14, tzinfo=UTC)
SLUG = "prepare-meeting"
VERSION = "prepare-meeting@v1"
BUTTON = "找不到按鈕"
MISSING = "缺少資訊"
PENDING = "待分類"

DEMO_RATINGS: dict[str, int] = {
    "f_12": 2, "f_15": 2, "f_19": 3, "f_23": 3, "f_27": 3, "f_31": 3, "f_34": 3, "f_40": 4,
}
"""設計 §11.2 的 A v1 八筆；平均 23/8 = 2.875 < 3.5，demo 的 n >= 8 剛好成立。"""

DEMO_IDS = tuple(sorted(DEMO_RATINGS))


def tutorial(slug: str, current_version: str | None, *,
             status: TutorialStatus = TutorialStatus.ACTIVE) -> Tutorial:
    return Tutorial(slug=slug, current_version=current_version, topic=f"{slug} 教學",
                    feature_ids=["Prepare"], status=status)


def version(version_id: str, *, published: bool = True) -> TutorialVersion:
    slug = version_id.split("@")[0]
    return TutorialVersion(version_id=version_id, slug=slug, reason="首版", rules_applied=[],
                           s3_key=f"tutorials/{version_id}.md",
                           published_at=datetime(2026, 9, 1, tzinfo=UTC) if published else None)


def feedback(feedback_id: str, version_id: str, *, rating: int | None = 2,
             category: str | None = BUTTON, ts: datetime | None = None) -> Feedback:
    return Feedback(id=feedback_id, tutorial_version=version_id, rating=rating,
                    category=category, comment="按鈕在哪", user="u_01",
                    ts=NOW - timedelta(days=1) if ts is None else ts)


def save(repository: Repository, rows: Iterable[Feedback]) -> None:
    """一筆回饋 = `FEEDBACK#` 本體 + 指向該版的 `REFERS_TO` 邊（反查靠這條邊）。"""
    for row in rows:
        repository.put_meta(row)
        repository.put_edge(feedback_pk(row.id), "REFERS_TO", version_pk(row.tutorial_version))


def seed_demo_version(repository: Repository, slug: str, version_id: str, *,
                      status: TutorialStatus = TutorialStatus.ACTIVE,
                      published: bool = True, prefix: str = "") -> None:
    """一篇滿足 demo 三條件的教學：八筆同類低分掛在它的 `current_version` 上。"""
    repository.put_meta(tutorial(slug, version_id, status=status))
    repository.put_meta(version(version_id, published=published))
    save(repository, [feedback(f"{prefix}{fid}", version_id, rating=rating)
                      for fid, rating in DEMO_RATINGS.items()])


@pytest.fixture
def demo_repository(repository: Repository) -> Repository:
    """A：命中；B：current 未發布；C：retired；D：`current_version is None`。四者資料等價。"""
    seed_demo_version(repository, SLUG, VERSION)
    seed_demo_version(repository, "share-summary", "share-summary@v1",
                      published=False, prefix="b_")
    seed_demo_version(repository, "book-room", "book-room@v1",
                      status=TutorialStatus.RETIRED, prefix="c_")
    repository.put_meta(tutorial("invite-guest", None))
    return repository


@pytest.fixture
def repository_with_v2(demo_repository: Repository) -> Repository:
    """A 已經改版：`current_version` 是 v2（平均 4.4、n=10），v1 的八筆低分仍留在圖譜上。"""
    demo_repository.put_meta(version("prepare-meeting@v2"))
    demo_repository.put_meta(tutorial(SLUG, "prepare-meeting@v2"), create_only=False)
    save(demo_repository, [feedback(f"g_{index}", "prepare-meeting@v2",
                                    rating=4 if index < 6 else 5)
                           for index in range(10)])
    return demo_repository


def test_only_active_published_current_versions_are_selected(demo_repository: Repository) -> None:
    """Given 四篇資料等價的教學，When demo 模式選取，Then 只有 active + 已發布 current 的 A 命中。

    B（current 未發布）、C（retired）、D（`current_version is None`）三篇的回饋同樣滿足三條件，
    所以命中與否只可能來自這三道前置檢查（設計 §7.5）。
    """
    targets = select_weak_targets(repository=demo_repository, mode="demo", now=NOW)
    assert [target.version_id for target in targets] == [VERSION]
    assert targets[0].tutorial_id == SLUG
    assert targets[0].category == BUTTON
    assert targets[0].feedback_ids == DEMO_IDS
    categories = {row.category for row in demo_repository.list_feedback_of_version(VERSION)
                  if row.id in targets[0].feedback_ids}
    assert categories == {targets[0].category}      # 證據全屬同一類，沒有混類


def test_demo_sample_size_is_not_enough_for_formal_mode(demo_repository: Repository) -> None:
    """Given 同一批 demo 資料，When 用正式門檻，Then 回 `()`：n = 8 < 10（`REV` Rule 3）。"""
    assert select_weak_targets(repository=demo_repository, mode="formal", now=NOW) == ()


def test_old_version_feedback_is_not_mixed_into_the_current_one(
        repository_with_v2: Repository) -> None:
    """Given A 的 current 已是 v2（平均 4.4），When 選取，Then 回 `()`：不看舊版 v1 的低分。"""
    assert select_weak_targets(repository=repository_with_v2, mode="demo", now=NOW) == ()
