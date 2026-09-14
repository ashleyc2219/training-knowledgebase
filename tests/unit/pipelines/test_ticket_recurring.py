"""Phase 39 Task 1／Task 2：UTC 日界線窗口與「同群五筆才算 recurring」。

窗口是**日期集合**不是時間區間：同一個 UTC 日不管幾點都落在同一個桶裡，所以
`2026-08-31T00:00:00Z` 在窗口內、`2026-08-30T23:59:59Z` 在窗口外（設計 §7.3、F11）。

`5` 的唯一來源是 `Thresholds.recurring_tickets`，測試一律引用 `RECURRING_MIN_TICKETS`
這個別名，不在檔案裡再寫一份字面值（00A §5.4、D-35）。
"""

from datetime import date

import pytest

from training_kb.clock import parse_iso, utc_date
from training_kb.errors import PermanentError
from training_kb.pipelines.ticket import RECURRING_DAYS, recurring_window

# --- Task 1：固定 UTC 日界線窗口 --------------------------------------------


def test_window_has_exactly_fourteen_dates():
    window = recurring_window(date(2026, 9, 13))
    assert len(window) == 14
    assert date(2026, 9, 13) in window        # 當日
    assert date(2026, 8, 31) in window        # 前第 13 個日期
    assert date(2026, 8, 30) not in window


def test_utc_day_boundary_is_the_cut_line():
    window = recurring_window(date(2026, 9, 13))
    assert utc_date(parse_iso("2026-08-31T00:00:00Z")) in window
    assert utc_date(parse_iso("2026-08-30T23:59:59Z")) not in window
    assert utc_date(parse_iso("2026-09-13T23:59:59Z")) in window


def test_window_length_comes_from_the_module_constant():
    """`14` 在 `Thresholds` 沒有對應欄位，所以唯一一份就是 `RECURRING_DAYS`（00A §5.4）。"""
    assert len(recurring_window(date(2026, 9, 13))) == RECURRING_DAYS


@pytest.mark.parametrize("days", [0, -1])
def test_window_rejects_non_positive_days(days):
    with pytest.raises(PermanentError, match="窗口天數"):
        recurring_window(date(2026, 9, 13), days)


def test_same_utc_day_maps_to_one_bucket():
    """同一個 UTC 日的兩個時刻換算後相等，日期分桶才會把它們算進同一天。"""
    assert utc_date(parse_iso("2026-09-13T00:00:01Z")) == utc_date(
        parse_iso("2026-09-13T23:59:58Z"))
