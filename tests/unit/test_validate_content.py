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


@pytest.mark.parametrize("numbers", [[1, 2, 4, 5], [1, 1, 2, 3]])
def test_non_contiguous_step_numbers_are_rejected(numbers: list[int],
                                                  known_feature_ids: frozenset[str]) -> None:
    """跳號與重複都會讓兩步共用同一個 `STEP#<version_id>#<i>` 鍵（Phase 05）。"""
    content = four_step_content(numbers=numbers)
    with pytest.raises(ContentError, match="連續整數"):
        validate_content(content, known_feature_ids)


def test_empty_steps_is_rejected(known_feature_ids: frozenset[str]) -> None:
    content = four_step_content(numbers=())
    with pytest.raises(ContentError, match="缺少 Steps"):
        validate_content(content, known_feature_ids)


@pytest.mark.parametrize(
    ("feature_id", "signal"),
    [("", "沒有引用 Feature"), ("   ", "沒有引用 Feature"),
     ("Prepare, Share Summary", "引用了多個 Feature"),
     ("Prepare、Share Summary", "引用了多個 Feature"),
     ("Calendar", "引用的 Feature 不存在")],
)
def test_step_feature_reference_is_strict(feature_id: str, signal: str,
                                          known_feature_ids: frozenset[str]) -> None:
    """零個、多個、不存在一律拒絕；不得自動挑第一個或留空待補（D05）。"""
    content = four_step_content(step3_feature=feature_id)
    with pytest.raises(ContentError, match=signal):
        validate_content(content, known_feature_ids)


def test_known_feature_name_with_separator_passes(known_feature_ids: frozenset[str]) -> None:
    """清單命中優先於分隔符號：`Import/Export` 真的存在時不算「多個 Feature」。"""
    known = known_feature_ids | {"Import/Export"}
    validate_content(four_step_content(step3_feature="Import/Export"), known)


def test_illegal_step_type_is_rejected(known_feature_ids: frozenset[str]) -> None:
    content = four_step_content(step3_type="scroll")
    with pytest.raises(ContentError, match="type 不合法"):
        validate_content(content, known_feature_ids)


def test_all_problems_are_reported_in_one_error(known_feature_ids: frozenset[str]) -> None:
    """Phase 18 只允許一次修正（設計 §14.3）：一次沒列完，那次機會就被浪費掉了。"""
    content = four_step_content(
        problem="  ", step2_feature="", step3_feature="Prepare, Share Summary",
        step4_feature="Calendar",
    )
    with pytest.raises(ContentError) as caught:
        validate_content(content, known_feature_ids)
    message = str(caught.value)
    for signal in ("缺少 Problem", "第 2 步沒有引用", "第 3 步引用了多個",
                   "第 4 步引用的 Feature 不存在"):
        assert signal in message


def test_error_message_does_not_leak_step_text(known_feature_ids: frozenset[str]) -> None:
    """訊息只含段落名稱、步驟編號與 `feature_id`：它會被原樣送回模型並落進操作紀錄。"""
    secret = "使用者 u_7788 回報：找不到右上角的分享鍵。"
    content = four_step_content(step3_feature="Calendar", step3_text=secret)
    with pytest.raises(ContentError) as caught:
        validate_content(content, known_feature_ids)
    message = str(caught.value)
    assert "第 3 步引用的 Feature 不存在：Calendar" in message
    assert secret not in message
    assert "u_7788" not in message
