"""Phase 54：O4 重開票窗口、分子分母去重與 `VersionMetrics` 組裝。

**O4 尚未核定**（COMMON.md §2）。窗口 `[p, p + 14 天)` 與 UTC 編碼是設計 §12.1 的**建議**，
本批依它實作；本檔的端點測試（`ticket.ts == p`、`ticket.ts == p + 14 天`）就是核定時要改的
唯一兩處，連同 `reopen_window` 一共三個地方，**不得刪**。

資料全部是設計 §11.3 的**合成**配方（`RUN` 1 的「明示合成」；維護者核定紀錄屬 Phase 56），
不是實測值。View 由本檔自己造（Phase 42 的固定匯入同波次，不等它）。
"""

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from training_kb.analytics.reopen import ReopenStats, reopen_stats, reopen_window
from training_kb.models import Ticket, TutorialView

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


# --- Task 2：分子分母去重與六種邊界 ------------------------------------------

V1 = "prepare-meeting@v1"
VIEW_TS = datetime(2026, 8, 2, 9, tzinfo=UTC)
TICKET_TS = datetime(2026, 8, 3, 10, tzinfo=UTC)


def view(user: str, ts: datetime = VIEW_TS, version: str = V1) -> TutorialView:
    return TutorialView(tutorial_version=version, user=user, ts=ts)


def ticket(tid: str, author: str, ts: datetime = TICKET_TS, cluster: str = "c12") -> Ticket:
    return Ticket(id=tid, source="email", author=author, ts=ts, project_id="demo",
                  text="看過準備會議教學後，仍找不到第三步的按鈕",
                  cluster_id=cluster, feature_ids=[], embedding=None)


def ten_viewers() -> list[TutorialView]:
    return [view(f"u_{n:02d}") for n in range(1, 11)]


def seven_reopens() -> list[Ticket]:
    return [ticket(f"t_200{n}", f"u_{n:02d}") for n in range(1, 8)]


def test_reopen_stats_reproduces_design_v1_seven_over_ten() -> None:
    """Given 設計 §11.3 的 A v1 合成配方，Then 重算出 7 筆／7 人／10 人／0.7。"""
    stats = reopen_stats(ten_viewers(), seven_reopens(), cluster_id="c12", published_at=P1)
    assert stats == ReopenStats(count=7, reopen_users=7, viewers=10, rate=0.7)


def test_reopen_stats_ignores_tickets_opened_before_the_view() -> None:
    """Given 同一人先開票後瀏覽，Then 不計分子，`count` 也不增加（F41 的先後條件）。"""
    early = datetime(2026, 8, 2, 8, tzinfo=UTC)          # 比同人的 view 早一小時
    stats = reopen_stats([view("u_01")], [ticket("t_2001", "u_01", early)],
                         cluster_id="c12", published_at=P1)
    assert stats == ReopenStats(count=0, reopen_users=0, viewers=1, rate=0.0)


def test_reopen_stats_counts_the_same_viewer_once_in_the_denominator() -> None:
    """Given `u_01` 瀏覽兩次，Then 分母仍是 10（同人只算一次）。"""
    views = [*ten_viewers(), view("u_01", datetime(2026, 8, 4, 9, tzinfo=UTC))]
    stats = reopen_stats(views, seven_reopens(), cluster_id="c12", published_at=P1)
    assert (stats.viewers, stats.reopen_users, stats.count) == (10, 7, 7)


def test_reopen_stats_counts_tickets_and_users_separately() -> None:
    """Given `u_01` 開兩張同群工單，Then `count` 加 1 而 `reopen_users` 不變。"""
    tickets = [*seven_reopens(), ticket("t_2008", "u_01")]
    stats = reopen_stats(ten_viewers(), tickets, cluster_id="c12", published_at=P1)
    assert (stats.count, stats.reopen_users, stats.rate) == (8, 7, 0.7)


def test_reopen_stats_ignores_other_clusters() -> None:
    """Given 工單屬於別的 cluster，Then 完全不計（D-29：同題比 cluster，不比標題）。"""
    tickets = [ticket(f"t_200{n}", f"u_{n:02d}", cluster="c99") for n in range(1, 8)]
    stats = reopen_stats(ten_viewers(), tickets, cluster_id="c12", published_at=P1)
    assert stats == ReopenStats(count=0, reopen_users=0, viewers=10, rate=0.0)


def test_reopen_stats_excludes_both_window_endpoints_o4_pending() -> None:
    """Given `ticket.ts == p + 14 天` 與 `ticket.ts == p`，Then 兩者都不計入。

    **O4 待核定**：右端不含是本計畫選擇；`ts == p` 不計是因為窗口內不可能有更早的 View
    （`view.ts < ticket.ts` 是嚴格小於）。核定改成右含時，只有本測試與 `reopen_window` 要改。
    """
    outside = [ticket("t_2001", "u_01", P1 + timedelta(days=14))]
    at_start = [ticket("t_2002", "u_01", P1)]
    for tickets in (outside, at_start):
        stats = reopen_stats(ten_viewers(), tickets, cluster_id="c12", published_at=P1)
        assert (stats.count, stats.reopen_users, stats.viewers) == (0, 0, 10)


def test_reopen_stats_without_viewers_reports_none_not_zero_percent() -> None:
    """Given 零瀏覽者但有工單，Then `viewers == 0` 且 `rate is None`（不是 0%）。"""
    stats = reopen_stats([], seven_reopens(), cluster_id="c12", published_at=P1)
    assert stats == ReopenStats(count=0, reopen_users=0, viewers=0, rate=None)
    assert reopen_stats([], [], cluster_id="c12", published_at=P1).rate is None


def test_reopen_stats_denominator_never_accepts_feedback() -> None:
    """Given `MET` 4，Then 簽名只有 views／tickets／cluster_id／published_at 四個參數。

    分母只能來自 `TUTORIAL_VIEW`：留過回饋不是「看過教學」的證據（設計 §12.1）。
    這個斷言就是那條停止點——有人想塞 `feedback=` 進來會當場紅燈。
    """
    assert list(inspect.signature(reopen_stats).parameters) == [
        "views", "tickets", "cluster_id", "published_at"]


P2 = datetime(2026, 8, 20, tzinfo=UTC)


def test_reopen_stats_reproduces_design_v2_two_over_ten() -> None:
    """Given 設計 §11.3 的 A v2 合成配方，Then 重算出 2 筆／2 人／10 人／0.2。"""
    views = [view(f"u_{n:02d}", datetime(2026, 8, 21, 9, tzinfo=UTC), "prepare-meeting@v2")
             for n in range(1, 11)]
    tickets = [ticket("t_2101", "u_01", datetime(2026, 8, 22, 10, tzinfo=UTC)),
               ticket("t_2102", "u_02", datetime(2026, 8, 22, 10, tzinfo=UTC))]
    stats = reopen_stats(views, tickets, cluster_id="c12", published_at=P2)
    assert (stats.count, stats.reopen_users, stats.viewers) == (2, 2, 10)
    assert stats.rate == 0.2
