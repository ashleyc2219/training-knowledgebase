"""Phase 26 Task 3：退役版本頁的固定過期說明與後繼導向（不連 AWS）。

`render_version_page` 的簽名到 Phase 57 都不變（00A §6.7），所以本檔只斷言**內容契約**：

```text
status=retired          -> 一行 <p class="retired">，文字逐字等於 RETIRED_NOTICE
successor 非空          -> 再一行 <p class="successor">，裡面是一個可點的相對連結
successor 為空          -> 完全不輸出第二行（F19：無後繼仍完成退役，但不導向）
status=active           -> 兩行都不輸出
任何情況               -> 頁面裡找不到 release:<id>、使用者 ID 或回饋原文（設計 §13）
```

連結是**明確可點的提示**，不做自動跳轉：連續跳轉會把循環藏起來，讀者被推來推去也看不出
自己在哪一篇。完整的退役頁樣式、版本選擇與 diff 檢視留給 Phase 57。
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from training_kb.content import RETIRED_NOTICE
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

SLUG = "meeting-summary"
SUCCESSOR = "prepare-meeting"
FEATURE = "Summary"
V2 = f"{SLUG}@v2"
NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
REASON = "release:r_88"
"""私有的退役原因；`r_88` 是上游識別碼，一個字都不准出現在公開頁（設計 §13）。"""

PRIVATE_USER = "u_gh-4242"
PRIVATE_COMMENT = "這篇根本找不到按鈕，白忙一小時。"

Rendered = tuple[Tutorial, TutorialVersion, list[TutorialStep], TutorialContent]


class Fixtures:
    """`(Tutorial, TutorialVersion, list[TutorialStep], TutorialContent)` 四件一組的器材。

    `tests/unit/conftest.py` 的 owner 是 Phase 15（00A §3.2），本 Phase 不是它的修改者，
    所以共用器材留在使用它的測試檔裡，與 Phase 23／24 的做法一致。
    """

    @staticmethod
    def retired(*, successor: str | None = SUCCESSOR,
                prerequisites: Sequence[str] = ("已登入工作區",)) -> Rendered:
        return Fixtures._page(status=TutorialStatus.RETIRED, successor=successor,
                              prerequisites=prerequisites)

    @staticmethod
    def active(*, successor: str | None = None) -> Rendered:
        return Fixtures._page(status=TutorialStatus.ACTIVE, successor=successor,
                              prerequisites=("已登入工作區",))

    @staticmethod
    def _page(*, status: TutorialStatus, successor: str | None,
              prerequisites: Sequence[str]) -> Rendered:
        tutorial = Tutorial(slug=SLUG, current_version=V2, topic="會議摘要",
                            feature_ids=[FEATURE], status=status, successor=successor,
                            cluster_id="c12")
        version = TutorialVersion(version_id=V2, slug=SLUG, supersedes=f"{SLUG}@v1",
                                  reason=REASON, rules_applied=[],
                                  s3_key=f"tutorials/{SLUG}/v2.md", published_at=NOW)
        steps = [TutorialStep(tutorial_version=V2, number=1, type=StepType.READ,
                              text="打開摘要頁。", feature_id=FEATURE)]
        content = TutorialContent(
            title="會議摘要",
            problem="會議後沒有人整理摘要，決議找不到。",
            prerequisites=list(prerequisites),
            steps=[StepDraft(number=1, type=StepType.READ, text="打開摘要頁。",
                             feature_id=FEATURE)],
            expected_outcome="會議結束十分鐘內產生摘要。",
        )
        return tutorial, version, steps, content


@pytest.fixture
def renderer() -> SiteRenderer:
    return SiteRenderer()


@pytest.fixture
def fixtures() -> Fixtures:
    return Fixtures()


def test_retired_page_shows_notice_and_optional_successor(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """逐字取自 Phase 26 §7 Task 3 Step 1。"""
    page = renderer.render_version_page(*fixtures.retired(successor=SUCCESSOR))
    assert 'class="retired"' in page and RETIRED_NOTICE in page
    assert SUCCESSOR in page
    assert REASON not in page and "r_88" not in page
    assert 'class="successor"' not in renderer.render_version_page(
        *fixtures.retired(successor=None))


def test_retired_page_links_to_the_successor_tutorial_index(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """連結指向後繼教學的版本紀錄頁，而且是同一個 `site/tutorials/` 下的相對路徑。"""
    page = renderer.render_version_page(*fixtures.retired(successor=SUCCESSOR))
    assert f'<a href="../{SUCCESSOR}/index.html">' in page
    assert "http://" not in page and "https://" not in page


def test_active_page_has_neither_retired_line(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """還在維護的教學兩行都不輸出，即使它身上已經有 successor。"""
    page = renderer.render_version_page(*fixtures.active(successor=SUCCESSOR))
    assert 'class="retired"' not in page
    assert 'class="successor"' not in page
    assert RETIRED_NOTICE not in page


def test_retired_page_escapes_the_successor_slug(renderer: SiteRenderer) -> None:
    """`bare_id` 只擋 `#` 與控制字元，`<`／`"` 是放行的，所以 slug 也必須逃脫。"""
    page = renderer.render_version_page(*Fixtures.retired(successor='evil"><b>x'))
    assert "<b>x" not in page
    assert "&lt;b&gt;x" in page
    assert '"><b>' not in page


def test_retired_page_never_leaks_private_data(
        renderer: SiteRenderer, fixtures: Fixtures) -> None:
    """公開頁全文搜尋：找不到上游 ID、使用者 ID 或回饋原文（設計 §13、00A §3.8）。"""
    page = renderer.render_version_page(
        *fixtures.retired(prerequisites=("已登入工作區",)))
    for secret in (REASON, "r_88", PRIVATE_USER, PRIVATE_COMMENT, "c12", "operations/"):
        assert secret not in page
