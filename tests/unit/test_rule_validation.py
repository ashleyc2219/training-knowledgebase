"""Phase 55 Task 1／2：批次評估、兩個差值、不可判定與狀態轉移（VAL 1–7、MET 6）。

全部資料是 `tests/unit/conftest.py` 的**自含合成 fixture**，`approved_by` 只是欄位值。
測試綠燈只證明狀態機與比較邏輯正確，**不代表** `R-007` 已成為 active、也不代表種子
已核定或 O7 已通過（O7 由 Phase 56 的真實種子與維護者核定紀錄關閉）。
"""

from dataclasses import replace

import pytest

from training_kb.analytics.validation import (
    RuleEvaluation,
    curation_groups,
    evaluate_batch,
    next_status,
    validated_conflict,
)

APPROVED = frozenset({"Button not found", "Missing information"})


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


# --- Task 2：兩項嚴格改善、連續兩批退役、衝突與 curation ---------------------


def ev(batch_id: str, verdict: str, versions: tuple[str, ...] = ("a@v1", "a@v2"),
       approved: bool = True) -> RuleEvaluation:
    """測試檔內的本地小工具：組出只保留判定所需欄位的 `RuleEvaluation`。"""
    return RuleEvaluation(
        batch_id=batch_id, rule_id="R-007", verdict=verdict, reasons=(),
        before_average=None, after_average=None, before_rate=None, after_rate=None,
        version_ids=frozenset(versions), approved=approved,
        average_delta=None, rate_delta=None, decidable=verdict != "undecidable")


@pytest.mark.parametrize("before_avg, after_avg, before_rate, after_rate, expected", [
    (2.875, 4.4, 0.7, 0.2, "improved"),        # 兩項都嚴格改善
    (2.875, 4.4, 0.7, 0.7, "not_improved"),    # rate 持平
    (2.875, 2.875, 0.7, 0.2, "not_improved"),  # 平均持平
    (2.875, 4.4, 0.2, 0.7, "not_improved"),    # rate 反而上升
    (4.4, 2.875, 0.7, 0.2, "not_improved"),    # 平均反而下降
])
def test_only_two_strict_improvements_count(fake_repo, batch, before_avg, after_avg,
                                            before_rate, after_rate, expected) -> None:
    """Given 四種持平／反向組合，Then 只有兩項都嚴格改善才算 `improved`（VAL Rule 2）。"""
    fake_repo.seed_metrics(before_avg, after_avg, before_rate, after_rate)
    assert evaluate_batch(batch, approved=APPROVED, repository=fake_repo).verdict == expected


def test_candidate_needs_improved_to_become_active() -> None:
    """Given candidate，Then 只有最新一批 `improved` 才升 active；`retired` 是終態。"""
    assert next_status("candidate", [ev("b1", "improved")], None) == "active"
    assert next_status("candidate", [ev("b1", "not_improved")], None) == "candidate"
    assert next_status("candidate", [ev("b1", "undecidable")], None) == "candidate"
    assert next_status("retired", [ev("b1", "improved")], None) == "retired"


def test_two_non_overlapping_unimproved_batches_retire_the_rule() -> None:
    """Given 兩個不重疊且已核定的未改善批次，Then active 與 candidate 都退役（VAL 5／6）。"""
    b1 = ev("b1", "not_improved", versions=("a@v1", "a@v2"))
    b2 = ev("b2", "not_improved", versions=("a@v3", "a@v4"))
    assert next_status("active", [b1, b2], None) == "retired"
    assert next_status("candidate", [b1, b2], None) == "retired"


def test_overlapping_undecidable_or_unapproved_batches_never_retire() -> None:
    """Given 重疊／不可判定／未核定批次，Then 一律不退役（VAL Rule 3 的反例）。"""
    over = [ev("b1", "not_improved", versions=("a@v1", "a@v2")),
            ev("b2", "not_improved", versions=("a@v2", "a@v3"))]
    weak = [ev("b3", "undecidable", versions=("a@v1", "a@v2")),
            ev("b4", "undecidable", versions=("a@v3", "a@v4"))]
    unapproved = [ev("b5", "not_improved", versions=("a@v1", "a@v2"), approved=False),
                  ev("b6", "not_improved", versions=("a@v3", "a@v4"), approved=False)]
    for batches in (over, weak, unapproved):
        assert next_status("active", batches, None) == "active"
        assert next_status("candidate", batches, None) == "candidate"


def test_conflict_retires_only_the_candidate(fake_repo) -> None:
    """Given 已驗證的衝突判定，Then 只退役提出衝突的 candidate，不動既有 active。"""
    judgement = {"conflicts": True, "rule_ids": ["R-006"], "evidence": ["fx_1"]}
    conflict = validated_conflict(judgement, fake_repo.rules["R-007"], repository=fake_repo)
    assert conflict == judgement
    assert next_status("candidate", [], conflict) == "retired"
    assert next_status("active", [], conflict) == "active"


@pytest.mark.parametrize("broken", [{"rule_ids": ["R-999"]},   # 指向不存在的規則
                                    {"rule_ids": ["R-013"]},   # applies_when 不同
                                    {"evidence": ["fx_999"]},  # 證據回查不到
                                    {"evidence": []},
                                    {"conflicts": False}])
def test_unverifiable_conflict_is_ignored(fake_repo, broken) -> None:
    """Given 驗不過的衝突判定，Then 回 `None`（模型原始輸出不得直接寫狀態，F55）。"""
    judgement = {"conflicts": True, "rule_ids": ["R-006"], "evidence": ["fx_1"]} | broken
    assert validated_conflict(judgement, fake_repo.rules["R-007"],
                              repository=fake_repo) is None


def test_curation_only_groups_and_never_changes_status(fake_repo, rules) -> None:
    """Given 四條規則（含一條 retired），Then curation 只分組、不寫任何資料（VAL Rule 7）。"""
    assert curation_groups(rules) == (("R-006", "R-007"),)   # read 扣掉 retired 只剩一條
    assert fake_repo.updated == {}
