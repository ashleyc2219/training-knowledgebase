"""領域列舉、嚴格模型基底、裸識別碼與內容草稿模型的單元測試（Phase 03）。"""

import pytest
from pydantic import ValidationError

from training_kb.models import (
    ProcStatus,
    ProcStep,
    ReleaseKind,
    ReleaseSource,
    RuleStatus,
    StepDraft,
    StepType,
    StrictModel,
    TicketSource,
    TutorialContent,
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


def test_step_rejects_prefixed_feature_id() -> None:
    with pytest.raises(ValidationError, match="bare identifier"):
        StepDraft(number=1, type="click_ui", text="開啟設定", feature_id="FEATURE#Prepare")


def test_draft_accepts_bare_feature_id_string_step_type_and_jsonpath_args() -> None:
    draft = StepDraft(number=1, type="click_ui", text="開啟設定", feature_id="Prepare")
    assert draft.type is StepType.CLICK_UI and draft.type == "click_ui"
    assert ProcStep(tool="parse_github_issue", args={"title": "$.issue.title"}).args[
        "title"
    ] == "$.issue.title"


def test_step_rejects_blank_text_and_zero_number() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        StepDraft(number=1, type="read", text="   ", feature_id="Prepare")
    with pytest.raises(ValidationError, match="1 or greater"):
        StepDraft(number=0, type="read", text="閱讀摘要", feature_id="Prepare")


def test_content_requires_contiguous_step_numbers_and_at_least_one_step() -> None:
    gap = [StepDraft(number=2, type="read", text="閱讀摘要", feature_id="Prepare")]
    for steps in (gap, []):
        with pytest.raises(ValidationError, match="contiguous"):
            TutorialContent(title="準備會議", problem="需要摘要", prerequisites=["已有會議"],
                            steps=steps, expected_outcome="可看到摘要")
    content = TutorialContent(
        title="準備會議", problem="需要摘要", prerequisites=[],
        steps=[StepDraft(number=1, type="read", text="閱讀摘要", feature_id="Prepare")],
        expected_outcome="可看到摘要",
    )
    assert content.prerequisites == []
