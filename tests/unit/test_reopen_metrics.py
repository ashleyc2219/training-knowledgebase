"""Phase 54：O4 重開票窗口、分子分母去重與 `VersionMetrics` 組裝。

**O4 尚未核定**（COMMON.md §2）。窗口 `[p, p + 14 天)` 與 UTC 編碼是設計 §12.1 的**建議**，
本批依它實作；本檔的端點測試（`ticket.ts == p`、`ticket.ts == p + 14 天`）就是核定時要改的
唯一兩處，連同 `reopen_window` 一共三個地方，**不得刪**。

資料全部是設計 §11.3 的**合成**配方（`RUN` 1 的「明示合成」；維護者核定紀錄屬 Phase 56），
不是實測值。View 由本檔自己造（Phase 42 的固定匯入同波次，不等它）。
"""

from datetime import UTC, datetime, timedelta

import pytest

from training_kb.analytics.reopen import reopen_window

P1 = datetime(2026, 8, 1, tzinfo=UTC)


def test_reopen_window_is_left_closed_right_open_o4_pending() -> None:
    """Given 發布時刻 p，When 取窗口，Then 得到左含右不含的 `[p, p + 14 天)`。"""
    start, end = reopen_window(P1)
    assert (start, end) == (P1, datetime(2026, 8, 15, tzinfo=UTC))
    assert start <= P1 < end                    # 左端包含 p 本身
    assert end - start == timedelta(days=14)
    assert reopen_window(P1, days=7)[1] == datetime(2026, 8, 8, tzinfo=UTC)


def test_reopen_window_rejects_naive_datetime() -> None:
    """Given 沒有時區的 datetime，When 取窗口，Then 直接 `ValueError`（不猜 UTC）。"""
    with pytest.raises(ValueError):
        reopen_window(datetime(2026, 8, 1))
