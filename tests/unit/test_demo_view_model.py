"""Phase 58 Task 3：四個 Dashboard 區塊的純計算 view model 與真實呼叫數。

Given Phase 56 的 Demo 種子（**明示的合成資料**）
When 算出 `dashboard_view`
Then 四個區塊名稱與 `DASHBOARD_BLOCKS` 逐字一致，每個數字都由 Phase 53／54 的函式
     由原始 Feedback／View／Ticket 重算，view model 自己一條公式都沒有。

`MET` Rule 11（**本 Phase 是 primary**）：重開票率必須同時顯示筆數、分子、分母與 proxy 說明，
零分母顯示「N/A：樣本不足」而不是 0%。

本檔不連 AWS、不呼叫模型、也**不 import streamlit**：資料來源是
`demo.view_model.SeedRepository`（把 `SeedBundle` 包成唯讀 Repository 形狀）。
"""

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from demo.seed_loader import BANNER, SeedBundle, load_seed
from demo.view_model import (
    CANDIDATE_NOTE,
    DASHBOARD_BLOCKS,
    NO_RATING,
    NO_SAMPLE,
    SYNTHETIC_NOTICE,
    TIME_KEYS,
    CallBreakdown,
    SeedRepository,
    call_breakdown,
    dashboard_view,
    load_dashboard,
)
from training_kb.models import TutorialVersion
from training_kb.writing.client import CallTrace

SEED_DIR = Path(__file__).resolve().parents[2] / "demo" / "seed"
BATCH = "demo-seed-01"
APPROVED = frozenset({"找不到按鈕", "缺少資訊"})
A_V1 = "prepare-meeting@v1"
A_V2 = "prepare-meeting@v2"
EMPTY_VERSION = "share-summary@v1"


@pytest.fixture(scope="module")
def bundle() -> SeedBundle:
    return load_seed(SEED_DIR)


@pytest.fixture
def repository(bundle: SeedBundle) -> SeedRepository:
    return SeedRepository(bundle)


@pytest.fixture
def view(repository: SeedRepository) -> dict[str, Any]:
    return dashboard_view(repository=repository, approved=APPROVED,
                          project_id="demo", batch=BATCH)


@pytest.fixture
def trace() -> CallTrace:
    """五筆：`embed` 一筆、`draft` 兩筆（attempt 1 與 2）、`name-gap` 一筆、Rote 節點一筆。"""
    trace = CallTrace()
    rows = (("embed", 1, "embedding"), ("draft", 1, "generation"), ("draft", 2, "generation"),
            ("name-gap", 1, "generation"), ("rote-agent", 1, "tool_use"))
    for node, attempt, kind in rows:
        trace.add({"operation_id": "op-ticket-analysis-demo", "node": node,
                   "model": "fake-model", "attempt": attempt, "kind": kind,
                   "started_at": "2026-09-14T00:00:00Z", "outcome": "success"})
    return trace


# --- MET Rule 11：四個區塊與重開票的分子分母 -----------------------------------


def test_dashboard_view_has_exactly_four_blocks(view: dict[str, Any]) -> None:
    """Given 種子 When 算 view Then 四個 key 逐字是 `DASHBOARD_BLOCKS`，區塊 3 有分子分母。"""
    assert tuple(view) == DASHBOARD_BLOCKS
    reopen = view["重開票筆數與分子分母"][A_V1]
    assert reopen["count"] == 7 and reopen["numerator"] == 7
    assert reopen["denominator"] == 10 and reopen["rate"] == 0.7
    assert "proxy" in reopen["note"]
    later = view["重開票筆數與分子分母"][A_V2]
    assert (later["count"], later["numerator"], later["denominator"], later["rate"]) == (
        2, 2, 10, 0.2)


def test_block_two_reports_unrounded_average_and_one_decimal_display(
        view: dict[str, Any]) -> None:
    """Given A 的兩版 When 讀區塊 2 Then 門檻值是未四捨五入的 2.875，畫面值才是 2.9。"""
    first = view["每版評分與回饋數"][A_V1]
    assert first["average"] == 2.875 and first["display"] == "2.9"
    assert first["sample_size"] == 8 and first["negative"] == 8
    second = view["每版評分與回饋數"][A_V2]
    assert second["average"] == 4.4 and second["display"] == "4.4"
    assert second["negative"] == 2


def test_zero_rating_version_shows_no_rating_not_zero(view: dict[str, Any]) -> None:
    """Given 零評分的版本 When 讀區塊 2 Then `average is None` 且畫面寫「尚無評分」，不是 0 分。"""
    row = view["每版評分與回饋數"][EMPTY_VERSION]
    assert row["average"] is None
    assert row["display"] == NO_RATING and row["note"] == NO_RATING
    assert row["sample_size"] == 0


def test_zero_viewer_version_shows_na_not_zero_percent(view: dict[str, Any]) -> None:
    """Given 零瀏覽的版本 When 讀區塊 3 Then `rate is None` 且寫「N/A：樣本不足」，不是 0%。"""
    row = view["重開票筆數與分子分母"][EMPTY_VERSION]
    assert row["rate"] is None and row["denominator"] == 0
    assert NO_SAMPLE in row["note"]
    assert "0%" not in row["note"]


# --- 區塊 1：即時執行與模擬歷史分開放，沒有把兩者相加的欄位 ----------------------


def test_block_one_keeps_simulated_history_and_live_run_in_two_keys(
        view: dict[str, Any]) -> None:
    """Given 全部是模擬回放的種子 When 讀區塊 1 Then 兩個 key 都在，且沒有合計欄位。"""
    block = view["最新教學與版本差異"]
    assert tuple(block) == TIME_KEYS
    assert set(block) == {"simulated_history", "live_run"}
    assert block["live_run"] == {}                 # 種子全部已發布，本次現場沒有新版本
    latest = block["simulated_history"]["prepare-meeting"]
    assert latest["version_id"] == A_V2
    assert latest["reason"] == "feedback:8 則 找不到按鈕"
    assert latest["diff"] and "@@" in latest["diff"]
    assert not any(name in block for name in ("total", "all", "combined", "sum"))


def test_block_one_lists_unpublished_versions_as_live_run(bundle: SeedBundle) -> None:
    """Given 現場流程剛建立一個未發布版本 When 讀區塊 1 Then 它落在 `live_run`，不混進歷史。"""
    draft = TutorialVersion(version_id="share-summary@v2", slug="share-summary",
                            supersedes=EMPTY_VERSION, reason="gap:c31",
                            rules_applied=["R-007"], s3_key="tutorials/share-summary/v2.md",
                            published_at=None)
    extended = dataclasses.replace(bundle, versions=(*bundle.versions, draft))
    block = dashboard_view(repository=SeedRepository(extended), approved=APPROVED,
                           project_id="demo", batch=BATCH)["最新教學與版本差異"]
    assert "share-summary@v2" in block["live_run"]
    assert block["live_run"]["share-summary@v2"]["rules_applied"] == ["R-007"]
    assert all(row["version_id"] != "share-summary@v2"
               for row in block["simulated_history"].values())


# --- 區塊 4：candidate 與 active 分開列，不寫成已有效 --------------------------


def test_block_four_separates_candidate_from_active(view: dict[str, Any]) -> None:
    """Given candidate 與 active 混合 When 讀區塊 4 Then 兩者分開計數，candidate 標「尚未生效」。"""
    block = view["規則狀態與來源證據"]
    assert block["counts"] == {"candidate": 1, "active": 1, "retired": 0}
    rows = {row["rule_id"]: row for row in block["rules"]}
    assert rows["R-007"]["status"] == "candidate"
    assert rows["R-007"]["status_note"] == CANDIDATE_NOTE
    assert rows["R-007"]["derived_from"] == "prepare-meeting@v1"
    assert len(rows["R-007"]["evidence"]) >= 5
    assert rows["R-012"]["status"] == "active" and rows["R-012"]["status_note"] != CANDIDATE_NOTE
    assert rows["R-012"]["applied_count"] == 2


# --- 合成資料標示 -------------------------------------------------------------


def test_synthetic_notice_matches_the_seed_loader_banner() -> None:
    """Given 兩支檔各有一個標示字串 When 比對 Then 逐字相同（只有一份真相）。"""
    assert SYNTHETIC_NOTICE == BANNER == "合成資料示範"


def test_every_number_row_is_marked_synthetic_with_the_batch(view: dict[str, Any]) -> None:
    """Given 四個區塊 When 走訪每一列 Then 每一列都帶 `SYNTHETIC_NOTICE` 與批次名稱。"""
    rows: list[dict[str, Any]] = []
    block_one = view["最新教學與版本差異"]
    rows += list(block_one["simulated_history"].values()) + list(block_one["live_run"].values())
    rows += list(view["每版評分與回饋數"].values())
    rows += list(view["重開票筆數與分子分母"].values())
    rows += [{"notice": view["規則狀態與來源證據"]["notice"]}]
    rows += list(view["規則狀態與來源證據"]["rules"])
    assert rows
    for row in rows:
        assert SYNTHETIC_NOTICE in row["notice"]
        assert BATCH in row["notice"]


# --- 呼叫數：含 embedding、Rote、Map 與重試 -----------------------------------


def test_call_breakdown_counts_every_attempt(trace: CallTrace) -> None:
    """Given 五筆 trace（含一次重試）When 算 breakdown Then total 5、retries 1、by_node 分得開。"""
    result = call_breakdown(trace)
    assert isinstance(result, CallBreakdown)
    assert result.total == 5 and result.retries == 1
    assert dict(result.by_node)["embed"] == 1
    assert dict(result.by_node)["draft"] == 2
    assert dict(result.by_node)["rote-agent"] == 1
    assert sum(count for _, count in result.by_node) == result.total


def test_call_breakdown_of_an_empty_trace_is_all_zero() -> None:
    """Given 現場還沒有任何模型呼叫 When 算 breakdown Then 三個欄位都是空的，不是猜的數字。"""
    result = call_breakdown(CallTrace())
    assert (result.total, result.retries, result.by_node) == (0, 0, ())


# --- 載入整份 dashboard（`demo/dashboard.py` 的唯一資料來源）--------------------


def test_load_dashboard_reports_o7_as_pending_not_passed() -> None:
    """Given 核定紀錄仍空著 When 載入 dashboard Then 寫「待維護者核定」，不得寫「O7 已通過」。"""
    data = load_dashboard(SEED_DIR)
    assert data.banner.batch == BATCH
    assert data.missing_approvals == ("R007-B1", "R012-B1", "R012-B2")
    assert "待維護者核定" in data.o7_line
    assert "已通過" not in data.o7_line
    assert tuple(data.blocks) == DASHBOARD_BLOCKS
    assert data.calls == CallBreakdown(0, 0, ())
