"""infra/scripts/o3_report.py 的純函式測試：切點判定與報告產生，一律不連 AWS。"""

import sys
from pathlib import Path

# o3_report.py 是一次性的 spike 腳本，不在 src/ 的安裝套件裡，所以直接把它的目錄加進路徑。
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from o3_report import (  # noqa: E402
    PublicView,
    build_view,
    generation_of,
    is_partial,
    site_generation,
)


def test_is_partial_detects_pointer_and_cross_slug_mismatch() -> None:
    stamp = "2026-09-13T00:00:00Z"
    both_old = [PublicView("spike-a", "v1", "v1", None), PublicView("spike-b", "v1", "v1", None)]
    pointer_ahead = [PublicView("spike-a", "v1", "v2", stamp)]
    half_new = [PublicView("spike-a", "v2", "v2", stamp), PublicView("spike-b", "v1", "v1", None)]
    assert is_partial(both_old, expected="v1") is False
    assert is_partial(pointer_ahead, expected="v2") is True
    assert is_partial(half_new, expected="v2") is True


def test_missing_site_object_reads_as_no_public_version() -> None:
    """公開頁還沒寫出去時 `site_version` 是 `None`，不能當成「和指標一樣」。"""
    view = build_view(
        "spike-a", site_body=None, current_version="spike-a@v2", published_at="2026-09-13T00:00:00Z"
    )
    assert view == PublicView("spike-a", None, "v2", "2026-09-13T00:00:00Z")
    assert is_partial([view], expected="v2") is True


def test_missing_version_item_leaves_published_at_empty() -> None:
    """VERSION item 不存在（或 current_version 還沒設）時兩欄都是 `None`，不填猜測值。"""
    view = build_view(
        "spike-a",
        site_body=b'<html data-site-version="v1" data-published="true">',
        current_version=None,
        published_at=None,
    )
    assert view == PublicView("spike-a", "v1", None, None)
    assert is_partial([view], expected="v1") is True


def test_one_lagging_slug_out_of_three_is_partial() -> None:
    """三篇裡只要有一篇公開頁落後，整批就是 partial；不能以「多數已切換」宣稱發布成功。"""
    stamp = "2026-09-13T00:00:00Z"
    views = [
        PublicView("spike-a", "v2", "v2", stamp),
        PublicView("spike-b", "v2", "v2", stamp),
        PublicView("spike-c", "v1", "v2", stamp),
    ]
    assert is_partial(views, expected="v2") is True
    assert is_partial(views[:2], expected="v2") is False


def test_site_generation_reads_marker_and_generation_of_splits_version_id() -> None:
    assert site_generation(b'<html data-site-version="v2" data-published="true">') == "v2"
    assert site_generation(b"<html>no marker</html>") is None
    assert site_generation(None) is None
    assert generation_of("spike-a@v2") == "v2"
    assert generation_of(None) is None
    assert generation_of("spike-a") is None
