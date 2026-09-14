"""領域列舉、嚴格模型基底與裸識別碼的單元測試（Phase 03 Task 1）。"""

import pytest
from pydantic import ValidationError

from training_kb.models import (
    ProcStatus,
    ReleaseKind,
    ReleaseSource,
    RuleStatus,
    StepType,
    StrictModel,
    TicketSource,
    TutorialStatus,
    bare_id,
)

EXPECTED = {
    TicketSource: ["github_issue", "discord", "email"],
    ReleaseSource: ["github_pr", "changelog"],
    ReleaseKind: ["renamed", "changed", "removed"],
    StepType: ["click_ui", "input", "read"],
    TutorialStatus: ["active", "retired"],
    RuleStatus: ["candidate", "active", "retired"],
    ProcStatus: ["active", "retired"],
}


def test_enum_members_are_upper_case_with_lower_values() -> None:
    assert len(EXPECTED) == 7
    for enum_type, values in EXPECTED.items():
        assert [member.value for member in enum_type] == values
        assert [member.name for member in enum_type] == [v.upper() for v in values]
    assert StepType.CLICK_UI == "click_ui"
    with pytest.raises(ValueError):
        StepType("click")


def test_strict_model_forbids_extra_and_is_frozen() -> None:
    class Probe(StrictModel):
        name: str

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Probe(name="x", priority=1)
    probe = Probe(name="x")
    with pytest.raises(ValidationError, match="Instance is frozen"):
        probe.name = "y"


def test_bare_id_rejects_prefix_and_keeps_version_shape() -> None:
    assert bare_id("prepare-meeting@v2") == "prepare-meeting@v2"
    for bad in ("FEATURE#Prepare", "", " Prepare", "Prepare\n"):
        with pytest.raises(ValueError, match="bare identifier"):
            bare_id(bad)
