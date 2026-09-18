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

import re
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from training_kb.content import RETIRED_NOTICE
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
    CURRENT_LABEL,
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
CATEGORIES = ("Button not found", "Missing information")
"""類別清單由呼叫端注入（P43 的 `approved_categories`），`site.py` 一個字都不寫。"""


def claims_delivery(text: str) -> bool:
    """頁面或腳本是否暗示「系統已收到回饋」：拿掉 `not sent` 這個片語後，sent／submitted／
    received／thank 任一出現就算（英文版的「已送出」「感謝回饋」禁令）。"""
    stripped = re.sub(r"(?i)not[ -]sent", "", text)
    return re.search(r"(?i)\b(sent|submitted|received|thank)", stripped) is not None


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
    assert "View changes since v2" in page
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


def test_version_page_without_supersedes_but_with_an_older_current_raises(
        renderer: SiteRenderer, steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given 目前版本是 v2、這一版卻是沒有 `supersedes` 的 v3／When 渲染／Then `PermanentError`。

    00A §6.7 明訂這裡丟 `PermanentError`（不是 `PublishError`）：資料不完整是永久性錯誤，
    重試同一份輸入不會變好，輸出半對的頁面比停下來危險。
    """
    with pytest.raises(PermanentError, match="supersedes"):
        renderer.render_version_page(make_tutorial(current_version=V2),
                                     make_version(V3, supersedes=None), steps, content)


def test_a_version_number_gap_without_supersedes_is_legitimate(
        renderer: SiteRenderer, steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given v1 永久失敗、v3 是第一個成功的版本／When 渲染／Then 正常輸出無前版文案。

    本計畫選擇（2026-09-14）：守門條件是「有更舊的已發布版卻缺 `supersedes`」，不是
    00A §6.7 字面上的「版號大於 1」。理由在 `site._diff_block` 的 docstring：
    `content._base_version` 在 `current_version is None` 時回 `(None, 0)`，
    `_next_free_number` 又會跳過永久失敗占用的號碼，所以 `v3 + supersedes=None` 是合法資料
    （設計 §8.1 允許版號缺口）。`tests/integration/test_batch_publish_cutpoints.py`（P25）
    seed 的 `prepare-meeting@v2 + supersedes=None` 就是這一類。
    """
    page = renderer.render_version_page(make_tutorial(current_version=None),
                                        make_version(V3, supersedes=None), steps, content)
    assert NO_PREVIOUS_TEXT in page
    page_as_current = renderer.render_version_page(
        make_tutorial(current_version=V3), make_version(V3, supersedes=None), steps, content)
    assert NO_PREVIOUS_TEXT in page_as_current


def test_version_switch_marks_the_current_version(
        renderer: SiteRenderer, steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given `tutorial.current_version` 等於本頁／When 渲染／Then 標「目前版本」。

    舊版頁不得自稱目前版本：讀者是從教學索引點進歷史版的，沒有標記就分不出來。
    """
    current = renderer.render_version_page(make_tutorial(current_version=V3),
                                           make_version(V3), steps, content)
    assert f"({CURRENT_LABEL})" in current
    older = renderer.render_version_page(make_tutorial(current_version=V3),
                                         make_version(V2, supersedes=V1),
                                         make_steps(V2), make_content())
    assert f"({CURRENT_LABEL})" not in older
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
    assert "已核定" not in page and "approved" not in page.lower()
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
    assert not claims_delivery(page)


def test_version_page_loads_only_local_assets(
        renderer: SiteRenderer, tutorial: Tutorial,
        steps: list[TutorialStep], content: TutorialContent) -> None:
    """Given 預設 asset_prefix／When 渲染／Then 只引用同 bucket 的樣式與腳本，不連 CDN。"""
    page = renderer.render_version_page(tutorial, make_version(V3), steps, content)
    assert f'href="/{SITE_PREFIX}assets/style.css"' in page
    assert f'src="/{SITE_PREFIX}assets/widget.js"' in page
    assert "http://" not in page and "https://" not in page
    assert "cdn" not in page


# --- Task 2：退役頁、後繼連結與索引頁的公開界線 ------------------------------


def test_retired_page_keeps_text_and_disables_widget(renderer: SiteRenderer) -> None:
    """Given 已退役且有後繼／When 渲染版本頁／Then 原文留著、widget 整段消失。"""
    tutorial = make_tutorial(status=TutorialStatus.RETIRED, successor="share-summary")
    content = make_content()
    page = renderer.render_version_page(tutorial, make_version(V3), make_steps(), content)
    assert RETIRED_NOTICE in page
    assert 'data-retired="true"' in page
    assert escape_text(content.steps[0].text) in page
    assert 'href="../share-summary/index.html"' in page
    assert "http-equiv" not in page
    assert "tkb-download" not in page


def test_retired_page_collects_nothing_at_all(renderer: SiteRenderer) -> None:
    """Given 已退役／When 渲染／Then 評分、類別、留言、使用者 ID 與狀態列全部不輸出。

    本計畫選擇：退役頁只保留歷史原文，連瀏覽紀錄也不再收集（設計 §8.4）。
    """
    page = renderer.render_version_page(
        make_tutorial(status=TutorialStatus.RETIRED, successor=None),
        make_version(V3), make_steps(), make_content())
    for element in ("tkb-widget", "tkb-user", "tkb-comment", "tkb-view", "tkb-status",
                    'data-rating="1"', NOT_SENT_TEXT):
        assert element not in page
    for category in CATEGORIES:
        assert category not in page


def test_retired_page_renders_a_self_successor_as_is(renderer: SiteRenderer) -> None:
    """Given `successor` 等於自身／When 渲染／Then renderer 原樣輸出，不重判一次。

    合法性責任在 Phase 26 的 `resolve_successor`（四項檢查含「非自身」），renderer 不碰
    儲存層也就不重判：重判要多讀一次 DynamoDB，而且會讓兩處判斷遲早分岔
    （`site.py::_successor_line` 的既有註解寫的就是這個理由）。
    """
    page = renderer.render_version_page(
        make_tutorial(status=TutorialStatus.RETIRED, successor=SLUG),
        make_version(V3), make_steps(), make_content())
    assert f'<a href="../{SLUG}/index.html">' in page


def test_a_blank_successor_cannot_even_be_constructed() -> None:
    """Given 空白 successor／When 建 `Tutorial`／Then 模型層就擋下來，到不了 renderer。

    所以「successor 為空白字串」這個邊界不需要 renderer 再判一次（`bare_id` 已經擋掉
    空字串與前後留白），renderer 只要處理 `None`。
    """
    with pytest.raises(ValidationError):
        make_tutorial(status=TutorialStatus.RETIRED, successor=" ")
    with pytest.raises(ValidationError):
        make_tutorial(status=TutorialStatus.RETIRED, successor="")


def test_tutorial_index_hides_unpublished_versions(renderer: SiteRenderer) -> None:
    """Given 一個已發布、一個未發布／When 渲染索引／Then 只有已發布的那一版有連結。

    「沒有連結的 URL」不算私有（設計 §9.3、§13），所以未發布版連版號都不能出現。
    """
    v1 = make_version(V1, supersedes=None, published_at=NOW)
    draft = make_version(V2, supersedes=V1, published_at=None)
    page = renderer.render_tutorial_index(make_tutorial(current_version=V1), [v1, draft])
    assert 'href="v1.html"' in page
    assert "v2.html" not in page
    assert V1 in page
    assert V2 not in page


def test_tutorial_index_keeps_the_order_it_was_given(renderer: SiteRenderer) -> None:
    """Given 呼叫端已排好序／When 渲染索引／Then renderer 不重排。

    本計畫選擇（2026-09-14）：Phase 57 文件的 Task 2 Step 3 寫「依版號升序排序」，但
    `Publisher.write_tutorial_index` 已經用 `list_versions_of_tutorial`（升序）再 `[::-1]`
    反轉成「版號大的在前」，而且 `test_publisher_single.py` 正在斷言那個順序。兩份排序邏輯
    遲早分岔，所以 renderer 不排序、只過濾（00A R5：既有程式優先）。
    """
    v1 = make_version(V1, supersedes=None, published_at=NOW)
    v3 = make_version(V3, published_at=NOW)
    page = renderer.render_tutorial_index(make_tutorial(), [v3, v1])
    assert page.index(V3) < page.index(V1)
    assert 'data-site-version="v3"' in page
    assert f"({CURRENT_LABEL})" in page


def test_tutorial_index_loads_the_stylesheet_but_no_widget(renderer: SiteRenderer) -> None:
    """Given 教學索引／When 渲染／Then 只引樣式，不引 widget，也不連回站台索引。

    最後一項是 Phase 26 `test_tutorial_index_omits_the_link_when_the_successor_was_rejected`
    的既有斷言（整頁不得含 `index.html`）在守；這裡順手把「不引 widget」一起鎖住。
    """
    page = renderer.render_tutorial_index(
        make_tutorial(current_version=None), [])
    assert f'href="/{SITE_PREFIX}assets/style.css"' in page
    assert "widget.js" not in page
    assert "tkb-widget" not in page


def test_site_index_links_each_tutorial_index(renderer: SiteRenderer) -> None:
    """Given 兩篇教學（一篇沒發布過）／When 渲染站台索引／Then 只有已上架的那篇有連結。"""
    listed = make_tutorial(current_version=V3)
    hidden = make_tutorial(current_version=None).model_copy(
        update={"slug": "draft-only", "topic": "草稿"})
    page = renderer.render_site_index([listed, hidden])
    assert f'href="tutorials/{SLUG}/index.html"' in page
    assert "draft-only" not in page
    assert NOTICE in page and BATCH in page
