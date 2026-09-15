"""Phase 45：弱教學診斷（`diagnose_weak`）的單元測試。

每個測試的 docstring 寫 Given／When／Then。O5 BLOCKED，全部用假 Writer，不連 Bedrock；
本檔的綠燈只代表程式邏輯正確，**不代表** Bedrock／AWS 已通過。

替身命名（本計畫選擇 2026-09-14）：`tests/unit/conftest.py` 已經有一個 `fake_writer`
fixture（回 Phase 15 的 `RecordingWriter`）。在本檔再定義同名 fixture 會**無聲覆蓋**它
（`tests/unit/pipelines/conftest.py` 檔頭已為同一個陷阱留警語），所以本檔的工廠另取名
`diagnosis_writer`，它直接沿用 conftest 的 `RecordingWriter`——`calls` 存的是 **dict**
（`call["user"]`／`call["node"]`），不是屬性存取。
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest

from training_kb.models import Feedback, StepType, TutorialStep
from training_kb.pipelines.feedback import DiagnosisResult, WeakTarget, diagnose_weak

VERSION_ID = "prepare-meeting@v1"
OTHER_VERSION_ID = "prepare-meeting@v2"
CATEGORY = "找不到按鈕"
OTHER_CATEGORY = "缺少資訊"
TARGET_FEEDBACK_IDS = ("f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40")
HIT: dict[str, Any] = {"number": 3, "reason": "沒有指出按鈕所在頁面與位置"}


class FakeRepo:
    """只實作 `diagnose_weak` 會用到的兩個讀取，行為與 `Repository` 一致（依版本過濾並排序）。"""

    def __init__(self, *, steps: Sequence[TutorialStep] = (),
                 feedback: Sequence[Feedback] = ()) -> None:
        self.steps = list(steps)
        self.feedback = list(feedback)

    def get_steps(self, version_id: str) -> list[TutorialStep]:
        rows = [row for row in self.steps if row.tutorial_version == version_id]
        return sorted(rows, key=lambda row: row.number)

    def list_feedback_of_version(self, version_id: str) -> list[Feedback]:
        rows = [row for row in self.feedback if row.tutorial_version == version_id]
        return sorted(rows, key=lambda row: row.id)


def step(number: int, *, version_id: str = VERSION_ID) -> TutorialStep:
    return TutorialStep(tutorial_version=version_id, number=number, type=StepType.CLICK_UI,
                        text=f"第 {number} 步", feature_id="Prepare")


def feedback(feedback_id: str, *, version_id: str = VERSION_ID, category: str = CATEGORY,
             comment: str = "找不到那顆按鈕") -> Feedback:
    return Feedback(id=feedback_id, tutorial_version=version_id, rating=2, category=category,
                    comment=comment, user="user-1")


@pytest.fixture
def weak_target() -> WeakTarget:
    """P44 選出的目標：`prepare-meeting@v1`、類別「找不到按鈕」、八筆同類證據。"""
    return WeakTarget(tutorial_id="prepare-meeting", version_id=VERSION_ID,
                      category=CATEGORY, feedback_ids=TARGET_FEEDBACK_IDS)


@pytest.fixture
def fake_repo() -> FakeRepo:
    return FakeRepo(steps=[step(1), step(2), step(3), step(4)],
                    feedback=[feedback(row_id) for row_id in TARGET_FEEDBACK_IDS])


@pytest.fixture
def diagnosis_writer(fake_writer: Any) -> Callable[[Sequence[Mapping[str, Any]]], Any]:
    """本檔專用的 Writer 工廠：把一次 `WeakDiagnosis` 回應排進 conftest 的 `RecordingWriter`。"""

    def queue(items: Sequence[Mapping[str, Any]]) -> Any:
        fake_writer.replies.append({"items": [dict(item) for item in items]})
        return fake_writer

    return queue


def test_diagnose_weak_keeps_only_existing_steps(
    fake_repo: FakeRepo, diagnosis_writer: Callable[..., Any], weak_target: WeakTarget,
) -> None:
    """Given 模型同時回傳既有步驟 3 與不存在的步驟 99，When 診斷，Then 只留下步驟 3 與它的原因。"""
    writer = diagnosis_writer([HIT, {"number": 99, "reason": "不存在"}])
    result = diagnose_weak(weak_target, repo=fake_repo, writer=writer,
                           operation_id="op-review-1")
    assert isinstance(result, DiagnosisResult)
    assert result.step_indexes == (3,)
    assert result.reasons == {3: "沒有指出按鈕所在頁面與位置"}
    assert result.version_id == VERSION_ID
    assert result.feedback_ids == weak_target.feedback_ids
