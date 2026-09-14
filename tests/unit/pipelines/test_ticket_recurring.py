"""Phase 39 Task 1／Task 2：UTC 日界線窗口與「同群五筆才算 recurring」。

窗口是**日期集合**不是時間區間：同一個 UTC 日不管幾點都落在同一個桶裡，所以
`2026-08-31T00:00:00Z` 在窗口內、`2026-08-30T23:59:59Z` 在窗口外（設計 §7.3、F11）。

`5` 的唯一來源是 `Thresholds.recurring_tickets`，測試一律引用 `RECURRING_MIN_TICKETS`
這個別名，不在檔案裡再寫一份字面值（00A §5.4、D-35）。

`fake_repo` 直接沿用 `tests/unit/pipelines/conftest.py`（Phase 38 建立、明列給 P39 用）的
那一份：`is_recurring` 只需要 `list_tickets`，而它已經照真實 `Repository` 濾 `project_id`
並依 `id` 升序。本檔只加一個模組層級的 `saved_ticket` 工廠——conftest 的模組層級函式不會
出現在測試模組的命名空間裡，但自己檔案裡的會。
"""

from datetime import date

import pytest

from training_kb.clock import parse_iso, utc_date
from training_kb.errors import PermanentError
from training_kb.models import Ticket
from training_kb.pipelines.ticket import (
    RECURRING_DAYS,
    RECURRING_MIN_TICKETS,
    is_recurring,
    recurring_window,
)

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


# --- Task 2：四筆不算 recurring、五筆才算 -----------------------------------

PROJECT = "demo"
"""conftest 的 `fake_repo.list_tickets` 會照真實版本濾 `project_id`，全檔只用這一個專案。"""

THREE = ["09-10", "09-11", "09-12"]
FOUR = ["09-09", *THREE]


def saved_ticket(repo, ticket_id, *, cluster, ts):
    """寫一筆同專案工單並回傳它；`ts` 是字串，用 Phase 02 的 `parse_iso` 轉成 `datetime`。

    同時進 `items`（模擬接入層已建立）與 `tickets`（`list_tickets` 的來源）。`tickets`
    是 list 而不是 dict，所以同一個 `id` 放兩次會留下兩筆——「依 `Ticket.id` 去重」
    這條規則才驗得到。
    """
    ticket = Ticket(id=ticket_id, source="github_issue", text=f"{ticket_id} 的原始提問",
                    author="reporter", ts=parse_iso(ts), project_id=PROJECT, cluster_id=cluster)
    repo.save_ticket(ticket)
    repo.tickets.append(ticket)
    return ticket


def test_threshold_is_an_alias_of_the_config_field():
    """模組裡沒有第二份 `5`：常數就是 `Thresholds.recurring_tickets`（00A §5.4、D-35）。"""
    from training_kb.config import Thresholds

    assert RECURRING_MIN_TICKETS == Thresholds().recurring_tickets


@pytest.mark.parametrize(("others", "expected"), [(THREE, False), (FOUR, True)])
def test_is_recurring_needs_five_tickets_in_window(fake_repo, others, expected):
    target = saved_ticket(fake_repo, "t_881", cluster="c12", ts="2026-09-13T02:00:00Z")
    for index, day in enumerate(others):
        saved_ticket(fake_repo, f"t_90{index}", cluster="c12", ts=f"2026-{day}T09:00:00Z")
    assert is_recurring(target, repository=fake_repo) is expected


def test_out_of_window_and_other_cluster_do_not_count(fake_repo):
    target = saved_ticket(fake_repo, "t_881", cluster="c12", ts="2026-09-13T02:00:00Z")
    saved_ticket(fake_repo, "t_901", cluster="c12", ts="2026-08-30T23:59:59Z")   # 窗口外
    saved_ticket(fake_repo, "t_902", cluster="c99", ts="2026-09-12T09:00:00Z")   # 別群
    for index, day in enumerate(THREE):
        saved_ticket(fake_repo, f"t_91{index}", cluster="c12", ts=f"2026-{day}T09:00:00Z")
    assert is_recurring(target, repository=fake_repo) is False


def test_two_tickets_on_the_same_utc_day_each_count_once(fake_repo):
    """日期只拿來過濾，不拿來去重：同一天的兩筆是兩筆（設計 §7.3）。"""
    target = saved_ticket(fake_repo, "t_881", cluster="c12", ts="2026-09-13T02:00:00Z")
    saved_ticket(fake_repo, "t_901", cluster="c12", ts="2026-09-12T00:00:01Z")
    saved_ticket(fake_repo, "t_902", cluster="c12", ts="2026-09-12T23:59:58Z")
    saved_ticket(fake_repo, "t_903", cluster="c12", ts="2026-09-11T09:00:00Z")
    saved_ticket(fake_repo, "t_904", cluster="c12", ts="2026-09-10T09:00:00Z")
    assert is_recurring(target, repository=fake_repo) is True


def test_the_same_ticket_id_twice_counts_once(fake_repo):
    """去重的判準是 `Ticket.id`：掃描重複回同一筆不該把四筆變成五筆。"""
    target = saved_ticket(fake_repo, "t_881", cluster="c12", ts="2026-09-13T02:00:00Z")
    for index, day in enumerate(THREE):
        saved_ticket(fake_repo, f"t_90{index}", cluster="c12", ts=f"2026-{day}T09:00:00Z")
    fake_repo.tickets.append(fake_repo.tickets[-1])          # 同一個 id 再出現一次
    assert len(fake_repo.list_tickets(PROJECT)) == 5         # 掃描看得到五列
    assert is_recurring(target, repository=fake_repo) is False


def test_anchor_itself_counts_even_before_the_scan_sees_it(fake_repo):
    """觸發本輪的那一筆一定算一筆，即使還沒寫回表也一樣（Phase 41 的 Task 順序）。"""
    target = Ticket(id="t_881", source="github_issue", text="會前摘要在哪裡",
                    author="reporter", ts=parse_iso("2026-09-13T02:00:00Z"),
                    project_id=PROJECT, cluster_id="c12")
    for index, day in enumerate(FOUR):
        saved_ticket(fake_repo, f"t_90{index}", cluster="c12", ts=f"2026-{day}T09:00:00Z")
    assert is_recurring(target, repository=fake_repo) is True


def test_unclustered_ticket_is_a_permanent_error(fake_repo):
    """Phase 38 還沒寫回 `cluster_id` 就問 recurring，是流程順序錯，不是「不算 recurring」。"""
    target = Ticket(id="t_881", source="github_issue", text="會前摘要在哪裡",
                    author="reporter", ts=parse_iso("2026-09-13T02:00:00Z"),
                    project_id=PROJECT)
    with pytest.raises(PermanentError, match="尚未分群"):
        is_recurring(target, repository=fake_repo)
