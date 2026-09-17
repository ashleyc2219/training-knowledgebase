"""`Publisher.publish_recorded_pages`：替「表裡已標發布、公開站卻沒有頁面」的版本補頁。

Given 用 `apply_seed` 種進 moto 的一篇教學（四個版本都帶 `published_at`，私有全文與 diff 都在，
      但 `site/` 一個物件都沒有）
When  呼叫 `publish_recorded_pages(slug)`
Then  每個已發布版本得到一個版本頁與一個 diff 副本；既有的公開頁一個 byte 都不動；
      第二次呼叫什麼都不寫；之後重建索引就能連到每一頁。

這條路徑只給種子資料用：正常的發布一律走 `prepare → inspect → commit`。
"""

from datetime import UTC, datetime
from pathlib import Path

from demo.seed_loader import apply_seed, load_seed
from training_kb.content import PUBLIC_SITE_PREFIX
from training_kb.operations import OperationCoordinator
from training_kb.publishing import Publisher, site_diff_key, site_key, tutorial_index_key
from training_kb.repository import Repository
from training_kb.site import SiteRenderer

SEED_DIR = Path(__file__).resolve().parents[2] / "demo" / "seed"
NOW = datetime(2026, 9, 17, tzinfo=UTC)
SLUG = "weekly-digest"
VERSIONS = tuple(f"{SLUG}@v{number}" for number in (1, 2, 3, 4))


def _public(repository: Repository, relative: str) -> bytes | None:
    return repository.get_object(f"{PUBLIC_SITE_PREFIX}{relative}")


def test_recorded_pages_are_created_once_and_never_overwritten(repository: Repository) -> None:
    apply_seed(load_seed(SEED_DIR), repository=repository, now=NOW)
    publisher = Publisher(repository, SiteRenderer(), OperationCoordinator(repository))
    assert _public(repository, site_key(VERSIONS[3])) is None

    # v1 已經有一份公開頁（模擬先前發布過）：補頁時必須原封不動。
    existing = b"<!doctype html><article data-published=\"true\">existing v1</article>"
    repository.put_object(f"{PUBLIC_SITE_PREFIX}{site_key(VERSIONS[0])}", existing,
                          "text/html; charset=utf-8", if_none_match=True)

    written = publisher.publish_recorded_pages(SLUG)

    assert written == tuple(
        key for version_id in VERSIONS[1:]
        for key in (site_key(version_id), site_diff_key(version_id)))
    assert _public(repository, site_key(VERSIONS[0])) == existing
    page = _public(repository, site_key(VERSIONS[3]))
    assert page is not None and b'data-published="true"' in page
    assert b"data-published=\"false\"" not in page
    assert _public(repository, site_diff_key(VERSIONS[3])) is not None

    # 第二次：全部都在了，一個都不寫。
    before = {key: _public(repository, key) for key in written}
    assert publisher.publish_recorded_pages(SLUG) == ()
    assert {key: _public(repository, key) for key in written} == before


def test_recorded_pages_then_index_rebuild_links_every_version(repository: Repository) -> None:
    apply_seed(load_seed(SEED_DIR), repository=repository, now=NOW)
    publisher = Publisher(repository, SiteRenderer(), OperationCoordinator(repository))
    publisher.publish_recorded_pages(SLUG)
    publisher.write_tutorial_index(SLUG)
    publisher.write_site_index()

    index = _public(repository, tutorial_index_key(SLUG))
    assert index is not None
    text = index.decode("utf-8")
    for number in (1, 2, 3, 4):
        assert f'href="v{number}.html"' in text
        assert _public(repository, site_key(f"{SLUG}@v{number}")) is not None
    assert 'data-site-version="v4"' in text
    home = _public(repository, "index.html")
    assert home is not None and f'href="tutorials/{SLUG}/index.html"' in home.decode("utf-8")


def test_tutorial_without_published_versions_writes_nothing(repository: Repository) -> None:
    apply_seed(load_seed(SEED_DIR), repository=repository, now=NOW)
    publisher = Publisher(repository, SiteRenderer(), OperationCoordinator(repository))
    assert publisher.publish_recorded_pages("no-such-tutorial") == ()
