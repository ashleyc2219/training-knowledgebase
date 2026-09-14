"""Phase 19：只有 active 且 `applies_when` 命中的規則能進一般寫作路徑。"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.rules import select_active_rules


def dt(day: int) -> datetime:
    return datetime(2026, 9, day, tzinfo=UTC)


def rule(rule_id: str, status: str, applies_when: StepType,
         derived_from: str = "prepare-meeting@v1") -> AuthoringRule:
    return AuthoringRule(rule_id=rule_id, rule="點 UI 時寫出頁面、位置與結果",
                         applies_when=applies_when,
                         evidence=["f_12", "f_13", "f_14", "f_15", "f_16"],
                         status=RuleStatus(status), applied_to=[], derived_from=derived_from)


def test_only_active_matching_rules_are_selected() -> None:
    rules = [rule("R-007", "active", StepType.CLICK_UI),
             rule("R-008", "candidate", StepType.CLICK_UI),
             rule("R-009", "active", StepType.INPUT)]
    selected = select_active_rules(rules, StepType.CLICK_UI, {"R-007": dt(2), "R-009": dt(3)})
    assert [item.rule_id for item in selected] == ["R-007"]


def test_retired_rule_never_enters_normal_writing() -> None:
    rules = [rule("R-006", "retired", StepType.CLICK_UI),
             rule("R-007", "active", StepType.CLICK_UI)]
    selected = select_active_rules(rules, StepType.CLICK_UI, {"R-006": dt(3), "R-007": dt(1)})
    assert [item.rule_id for item in selected] == ["R-007"]


def test_applies_when_only_accepts_a_single_step_type() -> None:
    with pytest.raises(ValidationError):
        rule("R-010", "active", "step.type == click_ui AND step.text ~ 按鈕")


def test_rule_from_another_tutorial_is_selected_for_a_new_slug() -> None:
    borrowed = rule("R-007", "active", StepType.CLICK_UI, "prepare-meeting@v1")
    selected = select_active_rules([borrowed], StepType.CLICK_UI, {"R-007": dt(2)})
    assert [item.rule_id for item in selected] == ["R-007"]


@pytest.mark.parametrize("step_type, expected", [
    (StepType.CLICK_UI, ["R-007"]), (StepType.INPUT, ["R-009"]), (StepType.READ, []),
])
def test_each_step_type_gets_its_own_rules(step_type, expected) -> None:
    rules = [rule("R-007", "active", StepType.CLICK_UI), rule("R-009", "active", StepType.INPUT)]
    validated = {"R-007": dt(2), "R-009": dt(3)}
    assert [item.rule_id for item in select_active_rules(rules, step_type, validated)] == expected
