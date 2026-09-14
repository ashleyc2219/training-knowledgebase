"""infra/scripts/o3_report.py 的純函式測試：切點判定與報告產生，一律不連 AWS。"""

import sys
from pathlib import Path
from typing import Any, cast

import pytest

# o3_report.py 是一次性的 spike 腳本，不在 src/ 的安裝套件裡，所以直接把它的目錄加進路徑。
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from o3_report import (  # noqa: E402
    CutPointResult,
    PublicView,
    build_view,
    generation_of,
    is_partial,
    o3_verdict,
    render_o3_report,
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


STAMP = "2026-09-13T00:00:00Z"


def _result(cut_point: str, views: list[PublicView], exposed: tuple[str, ...],
            partial: bool) -> CutPointResult:
    return CutPointResult(cast(Any, cut_point), tuple(views), exposed, partial, f"{cut_point} 觀察")


@pytest.fixture
def sample_results() -> list[CutPointResult]:
    """寫死的五列觀察值，形狀與真實 spike 一致；這條是純函式測試，不需要 AWS。"""
    return [
        _result(
            "a1_before_transact",
            [PublicView("spike-a", "v1", "v1", None), PublicView("spike-b", "v1", "v1", None)],
            (),
            False,
        ),
        _result(
            "a2_after_transact_before_site",
            [PublicView("spike-a", "v1", "v2", STAMP), PublicView("spike-b", "v1", "v2", STAMP)],
            (),
            True,
        ),
        _result(
            "a3_after_first_site_before_second",
            [PublicView("spike-a", "v2", "v2", STAMP), PublicView("spike-b", "v1", "v2", STAMP)],
            ("<html data-site-version=\"v2\">",),
            True,
        ),
        _result(
            "b1_after_site_before_transact",
            [PublicView("spike-a", "v2", "v1", None), PublicView("spike-b", "v2", "v1", None)],
            ("<html data-site-version=\"v2\">",),
            True,
        ),
        _result(
            "c1_after_delete_site",
            [PublicView("spike-a", "v1", "v2", STAMP), PublicView("spike-b", "v1", "v2", STAMP)],
            ("<html data-site-version=\"v2\">",),
            True,
        ),
    ]


def test_report_lists_every_cut_point_and_blocks_on_partial(
    sample_results: list[CutPointResult],
) -> None:
    report = render_o3_report(
        sample_results, run_id="spike-1",
        table="training_kb_spike", bucket="training-kb-spike", region="ap-northeast-1",
    )
    assert o3_verdict(sample_results) == "FAIL"
    assert "a3_after_first_site_before_second" in report
    assert "阻擋公開路徑" in report
    assert "CloudFront" not in report


def test_report_keeps_run_context_and_three_undecided_exits(
    sample_results: list[CutPointResult],
) -> None:
    """報告六欄齊全，且 FAIL 時三個決策出口都標「尚未核定」，不建議放寬 F49。"""
    report = render_o3_report(
        sample_results, run_id="spike-1",
        table="training_kb_spike", bucket="training-kb-spike", region="us-east-1",
    )
    assert "us-east-1" in report and "training_kb_spike" in report
    assert "training-kb-spike" in report and "spike-1" in report
    for point in ("a1_before_transact", "a2_after_transact_before_site",
                  "b1_after_site_before_transact", "c1_after_delete_site"):
        assert point in report
    assert report.count("尚未核定") == 3
    assert "50" in report
    assert "放寬 F49" not in report.replace("不得放寬 F49", "")


def test_verdict_is_pass_only_when_no_cut_point_is_partial(
    sample_results: list[CutPointResult],
) -> None:
    clean = [
        _result(row.cut_point, list(row.views), row.exposed_bodies, False)
        for row in sample_results
    ]
    assert o3_verdict(clean) == "PASS"
    assert "整體判定：PASS" in render_o3_report(
        clean, run_id="spike-1", table="t", bucket="b", region="us-east-1"
    )
