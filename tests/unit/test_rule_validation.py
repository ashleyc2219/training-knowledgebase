"""Phase 55 Task 1：批次評估、兩個差值與不可判定（VAL 1／3、MET 6）。

全部資料是 `tests/unit/conftest.py` 的**自含合成 fixture**，`approved_by` 只是欄位值。
測試綠燈只證明狀態機與比較邏輯正確，**不代表** `R-007` 已成為 active、也不代表種子
已核定或 O7 已通過（O7 由 Phase 56 的真實種子與維護者核定紀錄關閉）。
"""

from dataclasses import replace

import pytest

from training_kb.analytics.validation import evaluate_batch

APPROVED = frozenset({"找不到按鈕", "缺少資訊"})


# --- Task 1：批次評估、兩個差值與不可判定 ------------------------------------


def test_evaluate_batch_marks_improved_from_self_contained_fixture(fake_repo, batch) -> None:
    """Given 同篇前後兩版 2.875→4.4、0.7→0.2，When 評估批次，Then 回 `improved`。"""
    result = evaluate_batch(batch, approved=APPROVED, repository=fake_repo)
    assert result.verdict == "improved"
    assert (result.before_average, result.after_average) == (2.875, 4.4)
    assert (result.before_rate, result.after_rate) == (0.7, 0.2)


def test_evaluation_reports_both_deltas(fake_repo, batch) -> None:
    """Given 同一批次，When 評估，Then 同時得到評分差與重開票率差（MET Rule 6）。"""
    result = evaluate_batch(batch, approved=APPROVED, repository=fake_repo)
    assert round(result.average_delta, 3) == 1.525
    assert round(result.rate_delta, 3) == -0.5
    assert result.decidable is True


def test_evaluate_batch_is_undecidable_when_batch_is_not_approved(fake_repo, batch) -> None:
    """Given 批次沒有核定，When 評估，Then 是 `undecidable` 而不是失敗批次（VAL Rule 3）。"""
    result = evaluate_batch(replace(batch, approved_by=None, approved_at=None),
                            approved=APPROVED, repository=fake_repo)
    assert result.verdict == "undecidable"
    assert "batch_not_approved" in result.reasons
    assert result.decidable is False


@pytest.mark.parametrize("prepare, reason", [
    (lambda repo: repo.set_version("prepare-meeting@v2", published=False),
     "unpublished_comparison"),
    (lambda repo: repo.set_version("prepare-meeting@v1", slug="share-summary"), "cross_tutorial"),
    (lambda repo: repo.seed_metrics(2.875, None, 0.7, 0.2), "missing_average"),
    (lambda repo: repo.seed_metrics(2.875, 4.4, 0.7, None), "zero_denominator"),
])
def test_incomplete_batches_are_undecidable(fake_repo, batch, prepare, reason) -> None:
    """Given 對照不完整（未發布／跨教學／缺平均／零分母），Then 一律 `undecidable`。

    四個案例**都不得**回 `not_improved`：資料不足併進未改善，會讓兩個不完整批次
    直接把規則退役（設計 §12.2）。
    """
    prepare(fake_repo)
    result = evaluate_batch(batch, approved=APPROVED, repository=fake_repo)
    assert result.verdict == "undecidable"
    assert result.decidable is False and reason in result.reasons
