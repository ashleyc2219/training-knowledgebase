"""教學內容的第二道防線：五段齊全、步驟編號連續、型態合法、每步恰好一個既有 Feature。

整個檔案不碰 AWS、不呼叫模型：`validate_content` 是純函式，`known_feature_ids` 由呼叫端
先查好再傳進來。**不合格的變體一律走 `model_construct`**（見 `_step`／`_content`）：
Phase 03 的 `TutorialContent`／`StepDraft` 已經擋掉空白段落、不連續編號、非法 `type` 與非裸
ID 的 `feature_id`，用一般建構式組這些值只會停在 `ValidationError`，證明不了 schema 之後
還有一道業務驗證（設計 §14.1、F48）。
"""

from collections.abc import Sequence

import pytest

from training_kb.content import validate_content
from training_kb.errors import ContentError
from training_kb.models import StepDraft, StepType, TutorialContent

_TEXTS = ("開啟行事曆。", "點選準備會議。", "開啟摘要。", "確認摘要內容。")
_TYPES = ("read", "click_ui", "click_ui", "read")


def _step(number: int, step_type: str, text: str, feature_id: str) -> StepDraft:
    """組一步；值會被 Phase 03 擋下時改用 `model_construct`。

    pydantic v2 的 `ValidationError` 是 `ValueError` 子類，`StepType("scroll")` 也丟
    `ValueError`，所以一個 `except` 就涵蓋「schema 擋得住」的全部情況。
    """
    try:
        return StepDraft(number=number, type=StepType(step_type), text=text,
                         feature_id=feature_id)
    except ValueError:
        return StepDraft.model_construct(number=number, type=step_type, text=text,
                                         feature_id=feature_id)


def four_step_content(
    *,
    title: str = "準備會議",
    problem: str = "會議前的準備步驟散在多個頁面，新人找不到。",
    prerequisites: Sequence[str] | None = None,
    expected_outcome: str = "會議開始前已備妥議程與摘要。",
    numbers: Sequence[int] = (1, 2, 3, 4),
    step2_feature: str = "Prepare",
    step3_feature: str = "Prepare",
    step4_feature: str = "Prepare",
    step3_type: str = "click_ui",
    step3_text: str = _TEXTS[2],
) -> TutorialContent:
    """預設是合格的四步草稿；`numbers` 決定實際步數（空 tuple 就是沒有步驟）。"""
    features = ("Prepare", step2_feature, step3_feature, step4_feature)
    types = (_TYPES[0], _TYPES[1], step3_type, _TYPES[3])
    texts = (_TEXTS[0], _TEXTS[1], step3_text, _TEXTS[3])
    steps = [_step(number, types[index], texts[index], features[index])
             for index, number in enumerate(numbers)]
    needs = list(prerequisites) if prerequisites is not None else ["已登入工作區"]
    try:
        return TutorialContent(title=title, problem=problem, prerequisites=needs,
                               steps=steps, expected_outcome=expected_outcome)
    except ValueError:
        return TutorialContent.model_construct(title=title, problem=problem, prerequisites=needs,
                                               steps=steps, expected_outcome=expected_outcome)


@pytest.fixture
def known_feature_ids() -> frozenset[str]:
    return frozenset({"Prepare", "Share Summary", "Notification Settings"})


def test_valid_content_passes(known_feature_ids: frozenset[str]) -> None:
    validate_content(four_step_content(), known_feature_ids)


def test_missing_section_is_reported(known_feature_ids: frozenset[str]) -> None:
    content = four_step_content(problem="  ")
    with pytest.raises(ContentError, match="缺少 Problem"):
        validate_content(content, known_feature_ids)


def test_non_contiguous_step_numbers_are_rejected(known_feature_ids: frozenset[str]) -> None:
    content = four_step_content(numbers=[1, 2, 4, 5])
    with pytest.raises(ContentError, match="連續整數"):
        validate_content(content, known_feature_ids)
