"""Phase 24 Task 1：最小公開頁 renderer（版本頁、教學索引、站台索引）。

三個 render 方法的簽名到 [Phase 57] 都不改，Phase 57 只換實作，所以本檔只斷言
**內容契約**（逃脫、五段標題、版號、退役提示、索引只列已發布／已上架），不斷言版面細節。

`data-published` 由 00A §3.8 與 §6.7 要求：`published_at is None` 的頁面帶
`data-published="false"`，只能存在於私有 staging；`Publisher.commit` 在交易成功後重新渲染，
所以寫進 `site/` 的一律是 `"true"`（該行為由 `test_publisher_single.py` 斷言）。

**單元測試全綠不代表 O3 通過**：本檔不碰 DynamoDB、S3，也不證明任何發布切點。
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from training_kb.errors import PublishError
from training_kb.models import (
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.site import SiteRenderer

SLUG = "prepare-meeting"
FEATURE = "Prepare"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
NOW = datetime(2026, 9, 14, 0, 30, tzinfo=UTC)
STEP_TEXT = "開啟行事曆。"


class Fixtures:
    """`(Tutorial, TutorialVersion, list[TutorialStep], TutorialContent)` 四件一組的器材。

    `tests/unit/conftest.py` 的 owner 是 Phase 15（00A §3.2），本 Phase 不是它的修改者，
    所以共用器材留在使用它的測試檔裡，與 Phase 23 的做法一致。
    """

    @staticmethod
    def active_v1(
        *,
        step_text: str = STEP_TEXT,
        title: str = "準備會議",
        version_id: str = V1,
        status: TutorialStatus = TutorialStatus.ACTIVE,
        current_version: str | None = None,
        published_at: datetime | None = None,
        prerequisites: Sequence[str] = ("已登入工作區",),
    ) -> tuple[Tutorial, TutorialVersion, list[TutorialStep], TutorialContent]:
        tutorial = Tutorial(slug=SLUG, current_version=current_version, topic="準備會議",
                            feature_ids=[FEATURE], status=status, successor=None,
                            cluster_id="c12")
        version = TutorialVersion(version_id=version_id, slug=SLUG, supersedes=None,
                                  reason="gap:c12", rules_applied=[],
                                  s3_key=f"tutorials/{SLUG}/v1.md", published_at=published_at)
        steps = [TutorialStep(tutorial_version=version_id, number=1, type=StepType.READ,
                              text=step_text, feature_id=FEATURE)]
        content = TutorialContent(
            title=title,
            problem="會議前的準備步驟散在多個頁面，新人找不到。",
            prerequisites=list(prerequisites),
            steps=[StepDraft(number=1, type=StepType.READ, text=step_text,
                             feature_id=FEATURE)],
            expected_outcome="會議開始前已備妥議程與摘要。",
        )
        return tutorial, version, steps, content


@pytest.fixture
def renderer() -> SiteRenderer:
    """00A §6.7：四個 keyword 參數全部有預設值，`SiteRenderer()` 永遠成立。"""
    return SiteRenderer()


@pytest.fixture
def fixtures() -> Fixtures:
    return Fixtures()


# --- Task 1：最小 SiteRenderer 與逃脫 ---------------------------------------


def test_render_version_page_escapes_text_and_shows_version(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """逐字取自 Phase 24 §7 Task 1 Step 1。"""
    tutorial, version, steps, content = fixtures.active_v1(step_text="開啟 <會議> 頁面")
    page = renderer.render_version_page(tutorial, version, steps, content)
    assert "&lt;會議&gt;" in page
    assert "<會議>" not in page
    assert "prepare-meeting@v1" in page
    assert 'class="retired"' not in page
    for section in ("Problem", "Prerequisites", "Steps", "Expected Outcome"):
        assert f"<h2>{section}</h2>" in page


def test_render_version_page_marks_unpublished_pages(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """00A §3.8：`published_at is None` 的頁面帶 `data-published="false"`。"""
    tutorial, version, steps, content = fixtures.active_v1()
    assert 'data-published="false"' in renderer.render_version_page(
        tutorial, version, steps, content)
    tutorial, version, steps, content = fixtures.active_v1(published_at=NOW)
    page = renderer.render_version_page(tutorial, version, steps, content)
    assert 'data-published="true"' in page
    assert 'data-published="false"' not in page


def test_render_version_page_marks_retired_tutorial(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """退役提示是固定佔位（Phase 26／57 才定案文字），不顯示退役原因。"""
    tutorial, version, steps, content = fixtures.active_v1(status=TutorialStatus.RETIRED)
    page = renderer.render_version_page(tutorial, version, steps, content)
    assert 'class="retired"' in page
    assert "gap:c12" not in page


def test_render_version_page_refuses_out_of_sync_steps(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """已保存步驟與公開內容不同步時停下來，不輸出半對的頁面。"""
    tutorial, version, steps, content = fixtures.active_v1()
    drifted = [steps[0].model_copy(update={"text": "換掉的步驟文字。"})]
    with pytest.raises(PublishError, match="不同步"):
        renderer.render_version_page(tutorial, version, drifted, content)


def test_render_tutorial_index_lists_only_published_versions(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """教學索引只列 `published_at` 非空的版本，並標出 `current_version`。"""
    tutorial, published, _, _ = fixtures.active_v1(current_version=V1, published_at=NOW)
    draft = published.model_copy(update={"version_id": V2, "supersedes": V1,
                                         "published_at": None})
    page = renderer.render_tutorial_index(tutorial, [published, draft])
    assert V1 in page
    assert V2 not in page
    assert 'data-site-version="v1"' in page


def test_render_site_index_lists_only_tutorials_with_current_version(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """站台索引只列 `current_version` 非空的 Tutorial，而且教學主題經過逃脫。"""
    listed, _, _, _ = fixtures.active_v1(current_version=V1)
    hidden = listed.model_copy(update={"slug": "draft-only", "topic": "<草稿>",
                                       "current_version": None})
    page = renderer.render_site_index([listed, hidden])
    assert "準備會議" in page
    assert "<草稿>" not in page
    assert "draft-only" not in page
