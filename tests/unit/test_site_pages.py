"""Phase 57：完整教學站的版本頁、教學索引與退役頁（純字串，不連 AWS）。

本檔只斷言**內容契約**，不斷言版面細節；Phase 24／26 已經鎖住的斷言留在它們自己的檔案
（`test_site_renderer.py`、`test_retired_page.py`、`test_retire_tutorial.py`），本檔不重抄，
也不得與它們衝突。

站內 `href` 一律是**同目錄的相對檔名**（`v2.html`、`v3.diff.txt`、`index.html`），
後繼教學是 `../<slug>/index.html`（00A D-78）：`site.py` 不能 import `publishing`
（`publishing.py` 已經 `from training_kb.site import SiteRenderer`，反向 import 會循環），
而且 href 不是 S3 key，四個 key helper 仍然是 `publishing` 的唯一來源（D-54）。

**單元測試全綠不代表 O3 通過**：本檔不碰 DynamoDB、S3，也不證明任何發布切點。
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from training_kb.errors import PermanentError
from training_kb.models import (
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.site import (
    NO_PREVIOUS_TEXT,
    NOT_SENT_TEXT,
    SITE_PREFIX,
    SiteRenderer,
    escape_text,
)

SLUG = "prepare-meeting"
FEATURE = "Prepare"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
V3 = f"{SLUG}@v3"
NOW = datetime(2026, 9, 14, 0, 30, tzinfo=UTC)
STEP_TEXT = "開啟行事曆。"
REASON = "release:r_42"
"""私有的建版原因；`r_42` 是上游識別碼，一個字都不准出現在公開頁（設計 §13）。"""

NOTICE = "合成資料示範"
BATCH = "demo-seed-01"
CATEGORIES = ("找不到按鈕", "缺少資訊")
"""類別清單由呼叫端注入（P43 的 `approved_categories`），`site.py` 一個字都不寫。"""


def make_tutorial(*, status: TutorialStatus = TutorialStatus.ACTIVE,
                  successor: str | None = None,
                  current_version: str | None = V3) -> Tutorial:
    return Tutorial(slug=SLUG, current_version=current_version, topic="準備會議",
                    feature_ids=[FEATURE], status=status, successor=successor,
                    cluster_id="c12")


def make_version(version_id: str = V3, *, supersedes: str | None = V2,
                 published_at: datetime | None = NOW) -> TutorialVersion:
    return TutorialVersion(version_id=version_id, slug=SLUG, supersedes=supersedes,
                           reason=REASON, rules_applied=[],
                           s3_key=f"tutorials/{SLUG}/v1.md", published_at=published_at)


def make_steps(version_id: str = V3, *, text: str = STEP_TEXT) -> list[TutorialStep]:
    return [TutorialStep(tutorial_version=version_id, number=1, type=StepType.READ,
                         text=text, feature_id=FEATURE)]


def make_content(*, text: str = STEP_TEXT, title: str = "準備會議",
                 prerequisites: Sequence[str] = ("已登入工作區",)) -> TutorialContent:
    return TutorialContent(
        title=title,
        problem="會議前的準備步驟散在多個頁面，新人找不到。",
        prerequisites=list(prerequisites),
        steps=[StepDraft(number=1, type=StepType.READ, text=text, feature_id=FEATURE)],
        expected_outcome="會議開始前已備妥議程與摘要。",
    )


@pytest.fixture
def renderer() -> SiteRenderer:
    """帶橫幅與類別的 renderer；四個參數仍然全部有預設值（00A D-20）。"""
    return SiteRenderer(notice=NOTICE, batch=BATCH, categories=CATEGORIES)


@pytest.fixture
def tutorial() -> Tutorial:
    return make_tutorial()


@pytest.fixture
def steps() -> list[TutorialStep]:
    return make_steps()


@pytest.fixture
def content() -> TutorialContent:
    return make_content()


# --- Task 1：版本選擇、差異連結與未發布標記 ----------------------------------


def test_version_page_links_previous_diff(
        renderer: SiteRenderer, tutorial: Tutorial,
        steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given 已發布的 v3（`supersedes=v2`）／When 渲染版本頁／Then 三個同目錄相對連結都在。"""
    version = make_version(V3, supersedes=V2)
    page = renderer.render_version_page(tutorial, version, steps, content)
    assert 'data-published="true"' in page
    assert "查看與 v2 的差異" in page
    assert 'href="v3.diff.txt"' in page
    assert 'href="v2.html"' in page
    assert 'href="index.html"' in page
    assert REASON not in page and "r_42" not in page


def test_version_page_v1_says_no_previous(
        renderer: SiteRenderer, tutorial: Tutorial, content: TutorialContent) -> None:
    """Given v1（`supersedes=None`）／When 渲染／Then 固定文案，沒有 v0 連結。"""
    page = renderer.render_version_page(
        make_tutorial(current_version=V1), make_version(V1, supersedes=None),
        make_steps(V1), content)
    assert NO_PREVIOUS_TEXT in page
    assert "v0.diff.txt" not in page
    assert "v0.html" not in page


def test_version_page_without_supersedes_beyond_v1_raises(
        renderer: SiteRenderer, tutorial: Tutorial,
        steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given v3 卻沒有 `supersedes`／When 渲染／Then `PermanentError`，不輸出半對的頁面。

    00A §6.7 明訂這裡丟 `PermanentError`（不是 `PublishError`）：資料不完整是永久性錯誤，
    重試同一份輸入不會變好。
    """
    with pytest.raises(PermanentError, match="supersedes"):
        renderer.render_version_page(tutorial, make_version(V3, supersedes=None),
                                     steps, content)


def test_version_switch_marks_the_current_version(
        renderer: SiteRenderer, steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given `tutorial.current_version` 等於本頁／When 渲染／Then 標「目前版本」。

    舊版頁不得自稱目前版本：讀者是從教學索引點進歷史版的，沒有標記就分不出來。
    """
    current = renderer.render_version_page(make_tutorial(current_version=V3),
                                           make_version(V3), steps, content)
    assert "（目前版本）" in current
    older = renderer.render_version_page(make_tutorial(current_version=V3),
                                         make_version(V2, supersedes=V1),
                                         make_steps(V2), make_content())
    assert "（目前版本）" not in older
    assert 'href="v3.html"' not in older


def test_version_page_never_guesses_the_version_list(
        renderer: SiteRenderer, tutorial: Tutorial,
        steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given v3／When 渲染／Then 只連上一版與版本紀錄頁，不用 `v1..vN` 推算清單。

    設計 §8.1 允許永久失敗留下版號缺口，`v1..vN` 會產生死連結。
    """
    page = renderer.render_version_page(tutorial, make_version(V3), steps, content)
    assert 'href="v1.html"' not in page


def test_version_page_escapes_hostile_step_text(
        renderer: SiteRenderer, tutorial: Tutorial) -> None:
    """Given 步驟文字是 `<script>alert(1)</script>`／When 渲染／Then 只剩實體字。"""
    hostile = "<script>alert(1)</script>"
    page = renderer.render_version_page(tutorial, make_version(V3),
                                        make_steps(text=hostile),
                                        make_content(text=hostile))
    assert "&lt;script&gt;" in page
    assert "<script>alert(1)</script>" not in page


def test_version_page_shows_the_synthetic_banner(
        renderer: SiteRenderer, tutorial: Tutorial,
        steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given notice 與 batch／When 渲染／Then 兩者都在橫幅裡，而且經過逃脫。

    O7 未到（P56 首驗）：批次只能照抄 `demo/seed` 的名稱，不得寫成「已核定」。
    """
    page = renderer.render_version_page(tutorial, make_version(V3), steps, content)
    assert NOTICE in page and BATCH in page
    assert "已核定" not in page
    plain = SiteRenderer().render_version_page(tutorial, make_version(V3), steps, content)
    assert 'class="banner"' not in plain


def test_version_page_widget_offers_download_but_never_claims_sent(
        renderer: SiteRenderer, tutorial: Tutorial,
        steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given 在維護的教學／When 渲染／Then widget 有評分、類別、下載與「尚未送出」文案。"""
    page = renderer.render_version_page(tutorial, make_version(V3), steps, content)
    assert 'id="tkb-widget"' in page
    assert 'id="tkb-download"' in page and 'id="tkb-view"' in page
    assert 'id="tkb-user"' in page and 'id="tkb-comment"' in page
    for rating in range(1, 6):
        assert f'data-rating="{rating}"' in page
    for category in CATEGORIES:
        assert f'data-category="{escape_text(category)}"' in page
    assert NOT_SENT_TEXT in page
    assert "已送出" not in page.replace(NOT_SENT_TEXT, "")
    assert "感謝回饋" not in page


def test_version_page_loads_only_local_assets(
        renderer: SiteRenderer, tutorial: Tutorial,
        steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given 預設 asset_prefix／When 渲染／Then 只引用同 bucket 的樣式與腳本，不連 CDN。"""
    page = renderer.render_version_page(tutorial, make_version(V3), steps, content)
    assert f'href="/{SITE_PREFIX}assets/style.css"' in page
    assert f'src="/{SITE_PREFIX}assets/widget.js"' in page
    assert "http://" not in page and "https://" not in page
    assert "cdn" not in page
