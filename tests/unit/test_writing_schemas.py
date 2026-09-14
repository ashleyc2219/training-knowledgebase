"""八個模型輸出 schema 的一正一反案例（00B Rule 8 的 primary 斷言）。"""

from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from training_kb.writing.schemas import SCHEMAS, TutorialDraft, WeakDiagnosis, validate_schema

SCHEMA_NAMES = ("GapNaming", "TutorialDraft", "StepRewrite", "CommentClassification",
                "RuleProposal", "ConflictJudgement", "StepConfirmation", "WeakDiagnosis")

# 每個 schema 的合法樣本：同一份也拿來衍生「少一個 required」與「多一個欄位」兩種反例。
VALID: dict[str, dict[str, Any]] = {
    "GapNaming": {"gap": "找不到會前摘要入口", "feature_id": "Prepare"},
    "TutorialDraft": {
        "title": "準備會議", "problem": "找不到會前摘要入口", "prerequisites": ["無"],
        "steps": [{"number": 1, "type": "click_ui", "text": "點開 Prepare 分頁",
                   "feature_id": "Prepare"}],
        "expected_outcome": "看得到會前摘要"},
    "StepRewrite": {"steps": [{"number": 3, "type": "read", "text": "改看新版摘要",
                               "feature_id": "Prepare"}]},
    "CommentClassification": {"category": "找不到按鈕"},
    "RuleProposal": {"rule": "點擊步驟要寫出按鈕所在頁面", "applies_when": "click_ui",
                     "evidence": ["fx_1", "fx_2", "fx_3", "fx_4", "fx_5"],
                     "derived_from": "prepare-meeting@v2"},
    "ConflictJudgement": {"conflicts": True, "rule_ids": ["R-006"], "evidence": ["fx_1"]},
    "StepConfirmation": {"confirmed_step_numbers": [3], "reason": "第 3 步提到舊名稱"},
    "WeakDiagnosis": {"items": [{"number": 3, "reason": "沒有指出按鈕位置"}]},
}

# 邊界：schema 必須接受的合法「空」形狀，不可用 minItems 把它們擋掉。
BOUNDARY: list[tuple[str, dict[str, Any]]] = [
    ("GapNaming", {"gap": "找不到會前摘要入口", "feature_id": None}),
    ("WeakDiagnosis", {"items": []}),
    ("StepConfirmation", {"confirmed_step_numbers": [], "reason": "沒有步驟提到這個功能"}),
    ("ConflictJudgement", {"conflicts": False, "rule_ids": [], "evidence": []}),
]

# enum、型別與下限的反例：每一條都對應第 5 節表格的一句話。
ENUM_AND_BOUND: list[tuple[str, dict[str, Any]]] = [
    ("GapNaming", {"gap": "", "feature_id": "Prepare"}),
    ("TutorialDraft", {**VALID["TutorialDraft"], "prerequisites": []}),
    ("TutorialDraft", {**VALID["TutorialDraft"], "steps": []}),
    ("TutorialDraft", {**VALID["TutorialDraft"],
                       "steps": [{"number": 1, "type": "scroll", "text": "捲動",
                                  "feature_id": "Prepare"}]}),
    ("StepRewrite", {"steps": [{"number": 0, "type": "read", "text": "t",
                                "feature_id": "Prepare"}]}),
    ("StepRewrite", {"steps": [{"number": 1, "type": "read", "text": "t"}]}),
    ("StepRewrite", {"steps": [{"index": 1, "type": "read", "text": "t",
                                "feature_id": "Prepare"}]}),
    ("CommentClassification", {"category": ""}),
    ("RuleProposal", {**VALID["RuleProposal"], "applies_when": "click"}),
    ("RuleProposal", {**VALID["RuleProposal"], "evidence": ["fx_1", "fx_2", "fx_3", "fx_4"]}),
    ("ConflictJudgement", {**VALID["ConflictJudgement"], "conflicts": "true"}),
    ("StepConfirmation", {"confirmed_step_numbers": [1.5], "reason": "r"}),
    ("StepConfirmation", {"confirmed_step_numbers": [1], "reason": ""}),
    ("WeakDiagnosis", {"items": [{"number": 3, "reason": ""}]}),
]

REQUIRED_CASES = [(name, field) for name in SCHEMA_NAMES for field in VALID[name]]


def test_tutorial_draft_requires_all_five_sections() -> None:
    with pytest.raises(ValidationError):
        validate_schema(TutorialDraft, {"title": "準備會議", "steps": []})


def test_weak_diagnosis_uses_items_with_number_and_reason() -> None:
    validate_schema(WeakDiagnosis, {"items": [{"number": 3, "reason": "沒有指出按鈕位置"}]})
    with pytest.raises(ValidationError):
        validate_schema(WeakDiagnosis, {"items": [{"index": 3, "reason": "沒有指出按鈕位置"}]})


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_every_schema_forbids_extra_properties(name: str) -> None:
    assert SCHEMAS[name]["additionalProperties"] is False


def test_schema_map_is_keyed_by_id_and_covers_the_eight_names() -> None:
    assert sorted(SCHEMAS) == sorted(SCHEMA_NAMES)
    assert all(SCHEMAS[name]["$id"] == name for name in SCHEMA_NAMES)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_valid_payload_passes(name: str) -> None:
    validate_schema(SCHEMAS[name], VALID[name])


@pytest.mark.parametrize(("name", "payload"), BOUNDARY)
def test_boundary_payload_passes(name: str, payload: dict[str, Any]) -> None:
    validate_schema(SCHEMAS[name], payload)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_extra_top_level_property_is_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_schema(SCHEMAS[name], {**VALID[name], "admin": True})


@pytest.mark.parametrize(("name", "field"), REQUIRED_CASES)
def test_missing_required_property_is_rejected(name: str, field: str) -> None:
    payload = {key: value for key, value in VALID[name].items() if key != field}
    with pytest.raises(ValidationError):
        validate_schema(SCHEMAS[name], payload)


@pytest.mark.parametrize(("name", "payload"), ENUM_AND_BOUND)
def test_enum_type_and_bound_violations_are_rejected(name: str, payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_schema(SCHEMAS[name], payload)
