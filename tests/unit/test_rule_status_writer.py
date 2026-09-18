"""Phase 55 Task 3：唯一寫入者、最近驗證時間與 handler 的 validate_rules 分支（VAL Rule 8）。

`apply_rule_status` 是全系統唯一寫 `RULE.status` 與最近驗證時間的位置；這支測試同時釘住
合法／非法轉移、冪等、以及「未核定批次不會走到寫入」。所有資料都是
`tests/unit/conftest.py` 的自含合成 fixture：綠燈只代表狀態機與寫入路徑正確，
**不代表** `R-007` 已成為 active，也不代表種子已核定或 O7 已通過。
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from training_kb.analytics.status_writer import (
    LEGAL_TRANSITIONS,
    VALIDATED_AT_KEY,
    apply_rule_status,
    load_validated_at,
    record_evaluation,
)
from training_kb.analytics.validation import evaluate_batch
from training_kb.errors import PermanentError
from training_kb.handlers import analytics as analytics_handler
from training_kb.handlers.analytics import validate_rules_action
from training_kb.models import RuleStatus

NOW = datetime(2026, 9, 1, tzinfo=UTC)
APPROVED = frozenset({"Button not found", "Missing information"})


def rules_event(batch, *, now: str = "2026-09-01T00:00:00Z") -> dict:
    """把 fixture 批次攤成 Lambda event；`approved_at` 走 ISO 字串（跨 JSON 的形狀）。"""
    return {"action": "validate_rules", "now": now,
            "batches": [asdict(batch) | {"approved_at": now}]}


# --- 唯一寫入者與最近驗證時間 ------------------------------------------------


def test_apply_rule_status_writes_status_and_validation_time(fake_repo) -> None:
    """Given candidate 規則，When 寫入 active，Then item 與單一驗證時間檔一起更新。"""
    rule = apply_rule_status("R-007", "active", repository=fake_repo, now=NOW)
    assert rule.status == "active"
    assert fake_repo.updated["RULE#R-007"]["status"] == "active"
    table = json.loads(fake_repo.objects[VALIDATED_AT_KEY].decode("utf-8"))
    assert table["R-007"] == "2026-09-01T00:00:00Z"
    assert load_validated_at(fake_repo)["R-007"] == NOW


def test_apply_rule_status_truncates_microseconds_before_writing(fake_repo) -> None:
    """Given 帶微秒的 now，Then 先截成整秒再寫（`clock.to_iso` 遇微秒直接丟錯）。"""
    apply_rule_status("R-007", "active", repository=fake_repo,
                      now=NOW.replace(microsecond=123456))
    table = json.loads(fake_repo.objects[VALIDATED_AT_KEY].decode("utf-8"))
    assert table["R-007"] == "2026-09-01T00:00:00Z"


def test_apply_rule_status_repeats_without_moving_the_revision(fake_repo) -> None:
    """Given 已經是目標狀態，When 再寫一次，Then 不製造無意義的 revision 位移。"""
    apply_rule_status("R-007", "active", repository=fake_repo, now=NOW)
    before = (dict(fake_repo.revisions), dict(fake_repo.objects))
    rule = apply_rule_status("R-007", "active", repository=fake_repo, now=NOW)
    assert rule.status == "active"
    assert (fake_repo.revisions, fake_repo.objects) == before


def test_apply_rule_status_rejects_unknown_rule(fake_repo) -> None:
    """Given 規則不存在，Then 是 `PermanentError`（不是 `revision_of` 的 `CoordinationError`）。"""
    with pytest.raises(PermanentError):
        apply_rule_status("R-404", "active", repository=fake_repo, now=NOW)
    assert fake_repo.updated == {} and fake_repo.objects == {}


def test_legal_transitions_are_exactly_the_three_allowed_moves() -> None:
    """Given `LEGAL_TRANSITIONS`，Then 只有三條：candidate→active／retired、active→retired。"""
    assert LEGAL_TRANSITIONS == frozenset({
        (RuleStatus.CANDIDATE, RuleStatus.ACTIVE),
        (RuleStatus.CANDIDATE, RuleStatus.RETIRED),
        (RuleStatus.ACTIVE, RuleStatus.RETIRED)})


@pytest.mark.parametrize("current, target", [("retired", "active"), ("retired", "candidate"),
                                             ("active", "candidate")])
def test_apply_rule_status_rejects_illegal_transition(fake_repo, current, target) -> None:
    """Given 非法轉移（含 retired 復活），Then `PermanentError` 且 item 完全不動。"""
    fake_repo.seed_rule("R-012", current)
    with pytest.raises(PermanentError):
        apply_rule_status("R-012", target, repository=fake_repo, now=NOW)
    assert fake_repo.updated == {}


def test_record_evaluation_writes_one_evidence_file_per_batch(fake_repo, batch) -> None:
    """Given 一個批次的評估，Then 證據檔含全部欄位（含兩個差值），一批一檔。

    `0.2 - 0.7` 的浮點值是 -0.49999999999999994，JSON round-trip 後 `== -0.5` 是 False，
    所以用 `pytest.approx`；**不在 `_delta` 裡四捨五入**——門檻比較一律吃未四捨五入的值。
    """
    key = record_evaluation(evaluate_batch(batch, approved=APPROVED, repository=fake_repo),
                            repository=fake_repo)
    assert key == "operations/analytics/rule-validation/R-007/fixture-b1.json"
    payload = json.loads(fake_repo.objects[key].decode("utf-8"))
    assert payload["rate_delta"] == pytest.approx(-0.5)
    assert payload["average_delta"] == pytest.approx(1.525)
    assert payload["version_ids"] == ["prepare-meeting@v1", "prepare-meeting@v2"]
    assert payload["verdict"] == "improved" and payload["decidable"] is True
    assert fake_repo.updated == {}          # 寫證據檔不等於改狀態


# --- handler 的 validate_rules 分支 ------------------------------------------


def test_validate_rules_action_evaluates_and_writes_status(fake_repo, batch) -> None:
    """Given 一個已核定批次，When 呼叫 action，Then 評估、寫證據檔並升為 active。"""
    result = validate_rules_action(rules_event(batch), repository=fake_repo, approved=APPROVED)
    assert result["results"] == [{"rule_id": "R-007", "status": "active",
                                  "verdicts": ["improved"]}]
    assert fake_repo.updated["RULE#R-007"]["status"] == "active"
    assert "operations/analytics/rule-validation/R-007/fixture-b1.json" in fake_repo.objects


def test_validate_rules_action_is_idempotent_for_the_same_now(fake_repo, batch) -> None:
    """Given 同一批次帶同一個 now 重跑，Then item、證據檔與驗證時間檔完全相同。"""
    event = rules_event(batch)
    first = validate_rules_action(event, repository=fake_repo, approved=APPROVED)
    snapshot = (dict(fake_repo.objects), fake_repo.rules["R-007"], dict(fake_repo.revisions))
    second = validate_rules_action(event, repository=fake_repo, approved=APPROVED)
    assert first == second
    assert (fake_repo.objects, fake_repo.rules["R-007"], fake_repo.revisions) == snapshot


def test_validate_rules_action_keeps_status_when_batch_is_not_approved(fake_repo,
                                                                       batch) -> None:
    """Given 未核定批次，Then 判定是 `undecidable`、狀態不變、`apply_rule_status` 沒被呼叫。"""
    event = rules_event(batch)
    event["batches"][0]["approved_by"] = None
    event["batches"][0]["approved_at"] = None
    result = validate_rules_action(event, repository=fake_repo, approved=APPROVED)
    assert result["results"] == [{"rule_id": "R-007", "status": "candidate",
                                  "verdicts": ["undecidable"]}]
    assert fake_repo.updated == {}
    assert VALIDATED_AT_KEY not in fake_repo.objects


def test_handler_dispatches_validate_rules_and_still_rejects_unknown_actions(
        fake_repo, batch, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given analytics Lambda，Then `validate_rules` 走新分支、未知 action 仍 `PermanentError`。"""
    monkeypatch.setattr(analytics_handler, "_wiring",
                        lambda: (fake_repo, APPROVED, "fixture"))
    analytics_handler._reset_wiring()
    result = analytics_handler.handler(rules_event(batch), None)
    assert result["action"] == "validate_rules"
    assert result["results"][0]["status"] == "active"
    with pytest.raises(PermanentError):
        analytics_handler.handler({"action": "curation"}, None)


# --- 修正波（final review B#4）：呼叫端義務與 event 形狀 ----------------------


def not_improved_event(batch, batch_id: str, when: str) -> dict:
    """同一條規則的一個「未改善」批次；`batch_id` 不同代表是不同的觀察窗口。"""
    return {"action": "validate_rules", "now": when,
            "batches": [asdict(batch) | {"batch_id": batch_id, "approved_at": when}]}


def test_validate_rules_only_sees_the_batches_in_this_event(fake_repo, batch) -> None:
    """Given 同一條規則的兩批分兩次 invoke，Then 第二次的判定只看得到自己那一批。

    `next_status` 的兩條判定都看「清單的最後兩筆」（VAL Rule 5／6），而本 action 只吃
    event 帶進來的 `batches`，**不回讀** `record_evaluation` 寫下的證據檔——證據檔沒有
    `approved_at`（排不出「最新」），`Repository` 也沒有前綴列舉（列不出同一條規則的全部
    批次），見 `validate_rules_action` 的 docstring。

    所以呼叫端有義務「一次帶上完整的決定性歷史」。這條測試把限制釘住，讓它是被記錄的
    契約，不是沒人發現的靜默失效：兩份證據檔都寫出來了，第二次的 `verdicts` 卻只有一筆。
    """
    fake_repo.seed_metrics(4.0, 3.0, 0.5, 0.5)      # 平均變差、rate 持平 -> not_improved

    validate_rules_action(not_improved_event(batch, "hist-b1", "2026-09-01T00:00:00Z"),
                          repository=fake_repo, approved=APPROVED)
    result = validate_rules_action(
        not_improved_event(batch, "hist-b2", "2026-09-02T00:00:00Z"),
        repository=fake_repo, approved=APPROVED)

    assert result["results"][0]["verdicts"] == ["not_improved"]   # 只有這一次那一筆
    assert result["results"][0]["status"] == "candidate"          # 拆成兩次就退不了役
    assert fake_repo.rules["R-007"].status is RuleStatus.CANDIDATE
    for batch_id in ("hist-b1", "hist-b2"):                      # 兩份證據檔都在
        assert f"operations/analytics/rule-validation/R-007/{batch_id}.json" in fake_repo.objects


@pytest.mark.parametrize("event", [
    {"action": "validate_rules", "batches": []},
    {"action": "validate_rules", "now": "2026-09-01T00:00:00Z"},
    {"action": "validate_rules", "now": 20260901, "batches": []},
    {"action": "validate_rules", "now": "not-a-time", "batches": []},
])
def test_a_malformed_validate_rules_event_is_a_permanent_error(fake_repo, event) -> None:
    """Given event 少欄位或型別不對，Then `PermanentError`（不是 KeyError／ValueError）。"""
    with pytest.raises(PermanentError):
        validate_rules_action(event, repository=fake_repo, approved=APPROVED)


@pytest.mark.parametrize("bad", ["不是物件", {"batch_id": "只有一個欄位"}])
def test_a_malformed_batch_is_a_permanent_error(fake_repo, bad) -> None:
    """Given 一筆 batch 形狀不對，Then `PermanentError`（不是 TypeError）。"""
    event = {"action": "validate_rules", "now": "2026-09-01T00:00:00Z", "batches": [bad]}
    with pytest.raises(PermanentError):
        validate_rules_action(event, repository=fake_repo, approved=APPROVED)
