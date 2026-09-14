"""共用領域模型：七個 StrEnum、嚴格模型基底、裸識別碼檢查與內容草稿模型。

Phase 04 會在本檔案追加十個邏輯實體，因此這裡只放不依賴實體的 primitive。
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


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
