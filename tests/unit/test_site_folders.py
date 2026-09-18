"""站台依功能分資料夾（2026-09-17）：分組規則、資料夾 slug、資料夾頁與站台索引的 gallery。

Given 幾篇用到不同功能組合的教學
When  依 `feature_ids` 分資料夾、渲染站台索引與資料夾頁
Then  一篇教學出現在它用到的每個資料夾、沒有功能的進「Uncategorized」、只列已上架的、
      每個連結都是相對路徑、名稱來自 `Feature.name`、惡意文字被跳脫。
"""

from datetime import UTC, datetime

import pytest

from training_kb.models import Feature, Tutorial, TutorialStatus
from training_kb.site import (
    FEATURES_DIR,
    UNCATEGORIZED_FEATURE,
    SiteRenderer,
    escape_text,
    folder_slug,
    group_by_feature,
)

NOW = datetime(2026, 9, 17, tzinfo=UTC)


def tutorial(slug: str, topic: str, features: list[str], *, current: str | None = "v1",
             status: TutorialStatus = TutorialStatus.ACTIVE) -> Tutorial:
    return Tutorial(slug=slug, current_version=None if current is None else f"{slug}@{current}",
                    topic=topic, feature_ids=features, status=status, successor=None,
                    cluster_id=None)


PREPARE = tutorial("prepare-meeting", "準備會議", ["Open Meeting", "Prepare"])
SHARE = tutorial("share-summary", "分享摘要", ["Open Meeting", "Share Link"])
SETTINGS = tutorial("notification-settings", "設定通知", ["Settings Page"], current="v2",
                    status=TutorialStatus.RETIRED)
ORPHAN = tutorial("orphan", "沒有功能的教學", [])
DRAFT = tutorial("draft-only", "<草稿>", ["Open Meeting"], current=None)
ALL = [PREPARE, SHARE, SETTINGS, ORPHAN, DRAFT]


@pytest.fixture
def renderer() -> SiteRenderer:
    return SiteRenderer()


# --- 分組 -----------------------------------------------------------------------


def test_group_by_feature_puts_a_tutorial_in_every_folder_it_uses() -> None:
    folders = dict(group_by_feature(ALL))
    assert [row.slug for row in folders["Open Meeting"]] == ["prepare-meeting", "share-summary"]
    assert [row.slug for row in folders["Prepare"]] == ["prepare-meeting"]
    assert [row.slug for row in folders["Share Link"]] == ["share-summary"]
    assert [row.slug for row in folders["Settings Page"]] == ["notification-settings"]


def test_group_by_feature_orders_folders_by_size_then_name() -> None:
    names = [feature_id for feature_id, _ in group_by_feature(ALL)]
    assert names[0] == "Open Meeting"                       # 兩篇，最多
    assert names[1:] == sorted(names[1:])                   # 其餘一篇的依名稱


def test_tutorials_without_features_land_in_the_uncategorized_folder() -> None:
    folders = dict(group_by_feature(ALL))
    assert [row.slug for row in folders[UNCATEGORIZED_FEATURE]] == ["orphan"]


def test_unpublished_tutorials_are_in_no_folder() -> None:
    slugs = {row.slug for _, rows in group_by_feature(ALL) for row in rows}
    assert "draft-only" not in slugs


# --- slug -----------------------------------------------------------------------


@pytest.mark.parametrize(("feature_id", "expected"), [
    ("Open Meeting", "open-meeting"),
    ("Prepare", "prepare"),
    ("  Share  Link  ", "share-link"),
    ("通知設定", "通知設定"),
    ("Notification/Channel v2", "notification-channel-v2"),
])
def test_folder_slug_is_stable_lowercase_and_readable(feature_id: str, expected: str) -> None:
    assert folder_slug(feature_id) == expected
    assert folder_slug(feature_id) == folder_slug(feature_id)


def test_folder_slug_of_all_symbols_falls_back_to_a_hash() -> None:
    slug = folder_slug("***")
    assert slug.startswith("f-") and len(slug) == 12
    assert slug == folder_slug("***") and slug != folder_slug("???")


# --- 站台索引：資料夾 gallery -------------------------------------------------------


def test_site_index_shows_one_folder_card_per_feature_with_links(renderer: SiteRenderer) -> None:
    page = renderer.render_site_index(ALL)
    assert 'class="folders"' in page
    # Open Meeting／Prepare／Share Link／Settings Page／Uncategorized
    assert page.count('class="folder"') == 5
    assert f'href="{FEATURES_DIR}/open-meeting/index.html"' in page
    uncategorized = escape_text(folder_slug(UNCATEGORIZED_FEATURE))
    assert f'href="{FEATURES_DIR}/{uncategorized}/index.html"' in page
    assert "2 tutorials" in page and "1 tutorial<" in page
    # 每個資料夾裡直接列出教學（連到教學索引），不點進資料夾也找得到
    assert 'href="tutorials/prepare-meeting/index.html"' in page
    assert 'href="tutorials/notification-settings/index.html"' in page
    assert "draft-only" not in page and "&lt;草稿&gt;" not in page


def test_site_index_uses_feature_names_when_given(renderer: SiteRenderer) -> None:
    features = [Feature(feature_id="Prepare", name="Meeting Summary", aliases=[], first_seen=NOW)]
    page = renderer.render_site_index(ALL, features)
    assert '<span class="folder-name">Meeting Summary</span>' in page
    # 沒給 Feature 就印 feature_id
    assert '<span class="folder-name">Open Meeting</span>' in page


def test_site_index_escapes_hostile_feature_ids(renderer: SiteRenderer) -> None:
    hostile = tutorial("x", "x", ['<img src=x onerror=alert(1)>'])
    page = renderer.render_site_index([hostile])
    assert "<img" not in page and "&lt;img" in page
    assert "http://" not in page and "https://" not in page


# --- 資料夾頁 ---------------------------------------------------------------------


def test_folder_index_lists_the_tutorials_as_cards(renderer: SiteRenderer) -> None:
    page = renderer.render_folder_index("Open Meeting", [PREPARE, SHARE, DRAFT])
    assert 'data-folder="Open Meeting"' in page
    assert "<h1>Open Meeting</h1>" in page
    assert page.count('class="card"') == 2
    assert 'href="../../tutorials/prepare-meeting/index.html"' in page
    assert 'href="../../tutorials/share-summary/index.html"' in page
    assert "draft-only" not in page
    assert 'href="../../index.html"' in page                  # 頂欄回站台索引
    assert '<span class="chip">v1</span>' in page


def test_folder_index_shows_feature_name_aliases_and_retired_tag(renderer: SiteRenderer) -> None:
    feature = Feature(feature_id="Settings Page", name="設定頁", aliases=["Preferences"],
                      first_seen=NOW)
    page = renderer.render_folder_index("Settings Page", [SETTINGS], feature)
    assert "<h1>設定頁</h1>" in page
    assert "Preferences" in page
    assert '<span class="tag-retired">Retired</span>' in page
    assert '<span class="chip">v2</span>' in page


def test_folder_index_never_loads_the_widget_or_external_assets(renderer: SiteRenderer) -> None:
    page = renderer.render_folder_index("Prepare", [PREPARE])
    assert "widget.js" not in page and "tkb-widget" not in page
    assert 'href="/site/assets/style.css"' in page
    assert "http://" not in page and "cdn" not in page


# --- 版本頁與教學索引連回資料夾 -----------------------------------------------------


def test_version_and_tutorial_pages_link_to_their_folders(renderer: SiteRenderer) -> None:
    from training_kb.models import (
        StepDraft,
        StepType,
        TutorialContent,
        TutorialStep,
        TutorialVersion,
    )

    version = TutorialVersion(version_id="prepare-meeting@v1", slug="prepare-meeting",
                              supersedes=None, reason="gap:c1", rules_applied=[],
                              s3_key="tutorials/prepare-meeting/v1.md", published_at=NOW)
    steps = [TutorialStep(tutorial_version=version.version_id, number=1, type=StepType.READ,
                          text="開啟會議。", feature_id="Open Meeting")]
    content = TutorialContent(
        title="準備會議", problem="p", prerequisites=["已登入"],
        steps=[StepDraft(number=1, type=StepType.READ, text="開啟會議。",
                         feature_id="Open Meeting")],
        expected_outcome="o")
    page = renderer.render_version_page(PREPARE, version, steps, content)
    index = renderer.render_tutorial_index(PREPARE, [version])
    for html in (page, index):
        assert f'href="../../{FEATURES_DIR}/open-meeting/index.html"' in html
        assert f'href="../../{FEATURES_DIR}/prepare/index.html"' in html
