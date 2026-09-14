"""共用領域模型：七個 StrEnum、嚴格模型基底、裸識別碼檢查與內容草稿模型。

Phase 04 會在本檔案追加十個邏輯實體，因此這裡只放不依賴實體的 primitive。
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class TicketSource(StrEnum):
    GITHUB_ISSUE = "github_issue"
    DISCORD = "discord"
    EMAIL = "email"


class ReleaseSource(StrEnum):
    GITHUB_PR = "github_pr"
    CHANGELOG = "changelog"


class ReleaseKind(StrEnum):
    RENAMED = "renamed"
    CHANGED = "changed"
    REMOVED = "removed"


class StepType(StrEnum):
    CLICK_UI = "click_ui"
    INPUT = "input"
    READ = "read"


class TutorialStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class RuleStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"


class ProcStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class StrictModel(BaseModel):
    """Phase 04 起所有模型的共同基底：多餘欄位直接拒絕，物件建立後不可改。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


def bare_id(value: str) -> str:
    """確認字串是裸 ID（不含型別前綴、非空、沒有前後空白與控制字元）。"""
    if not value or value != value.strip():
        raise ValueError("bare identifier must not be empty or padded")
    if "#" in value or any(char < " " for char in value):
        raise ValueError("bare identifier must not contain '#' or control characters")
    return value


def filled(value: str) -> str:
    """確認顯示用文字不是空字串或全空白。"""
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


class ProcStep(StrictModel):
    tool: str
    args: dict[str, str]


class StepDraft(StrictModel):
    number: int
    type: StepType
    text: str
    feature_id: str

    @field_validator("number")
    @classmethod
    def number_starts_at_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("number must be 1 or greater")
        return value

    @field_validator("text")
    @classmethod
    def text_is_filled(cls, value: str) -> str:
        return filled(value)

    @field_validator("feature_id")
    @classmethod
    def feature_is_bare(cls, value: str) -> str:
        return bare_id(value)


class TutorialContent(StrictModel):
    title: str
    problem: str
    prerequisites: list[str]
    steps: list[StepDraft]
    expected_outcome: str

    @field_validator("title", "problem", "expected_outcome")
    @classmethod
    def section_is_filled(cls, value: str) -> str:
        return filled(value)

    @model_validator(mode="after")
    def contiguous_steps(self) -> "TutorialContent":
        numbers = [step.number for step in self.steps]
        if not numbers or numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("step numbers must be contiguous from 1 and must not be empty")
        return self
