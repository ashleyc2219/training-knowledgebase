"""共用領域模型：七個 StrEnum、嚴格模型基底、裸識別碼檢查、內容草稿模型與十個邏輯實體。

Phase 03 放不依賴實體的 primitive，Phase 04 在其後追加十個邏輯實體與 `Entity` union。
領域模型不帶 DynamoDB 的 `PK`／`SK`／`entity`／`_revision`，只保存裸識別碼與原生型別。
"""

from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Any

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


def aware(value: datetime) -> datetime:
    """確認時間帶時區，並收斂成 **UTC 整秒**（00A §3.5）。

    模型內不補 `now`，時間一律由呼叫端傳入（Phase 02 的規則）。三步固定：

    1. naive 直接拒絕——沒有偏移量就無從換算。
    2. 微秒非零直接拒絕，與 `clock.to_iso` 同一句話。**不靜默截斷**：截掉的那一段
       會讓 `view_pk` 這種以時間入鍵的計算靜靜地改變答案。
    3. 換算成 UTC。`put_meta` 走 `model_dump(mode="json")`，不在這裡換算，`+08:00`
       就會原樣寫進表，同一時刻在表裡出現兩種字串，也與 `to_iso` 只吐 `Z` 分岔。
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("datetime must be timezone aware")
    if value.microsecond:
        raise ValueError("datetime must be whole seconds")
    return value.astimezone(UTC)


class Tutorial(StrictModel):
    slug: str
    current_version: str | None = None
    topic: str
    feature_ids: list[str]
    status: TutorialStatus
    successor: str | None = None
    cluster_id: str | None = None

    @field_validator("slug")
    @classmethod
    def slug_is_bare(cls, value: str) -> str:
        return bare_id(value)

    @field_validator("topic")
    @classmethod
    def topic_is_filled(cls, value: str) -> str:
        return filled(value)

    @field_validator("current_version", "successor", "cluster_id")
    @classmethod
    def optional_ids_are_bare(cls, value: str | None) -> str | None:
        return None if value is None else bare_id(value)

    @field_validator("feature_ids")
    @classmethod
    def features_are_bare(cls, value: list[str]) -> list[str]:
        return [bare_id(item) for item in value]


class TutorialVersion(StrictModel):
    version_id: str
    slug: str
    supersedes: str | None = None
    reason: str
    rules_applied: list[str]
    s3_key: str
    published_at: datetime | None = None

    @field_validator("version_id", "slug")
    @classmethod
    def ids_are_bare(cls, value: str) -> str:
        return bare_id(value)

    @field_validator("supersedes")
    @classmethod
    def supersedes_is_bare(cls, value: str | None) -> str | None:
        return None if value is None else bare_id(value)

    @field_validator("rules_applied")
    @classmethod
    def rules_are_bare(cls, value: list[str]) -> list[str]:
        return [bare_id(item) for item in value]

    @field_validator("reason", "s3_key")
    @classmethod
    def text_is_filled(cls, value: str) -> str:
        return filled(value)

    @field_validator("published_at")
    @classmethod
    def published_at_is_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else aware(value)


class TutorialStep(StrictModel):
    tutorial_version: str
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

    @field_validator("tutorial_version", "feature_id")
    @classmethod
    def ids_are_bare(cls, value: str) -> str:
        return bare_id(value)

    @field_validator("text")
    @classmethod
    def text_is_filled(cls, value: str) -> str:
        return filled(value)


class Feature(StrictModel):
    feature_id: str
    name: str
    aliases: list[str]
    first_seen: datetime

    @field_validator("feature_id", "name")
    @classmethod
    def names_are_bare(cls, value: str) -> str:
        return bare_id(value)

    @field_validator("aliases")
    @classmethod
    def aliases_are_bare(cls, value: list[str]) -> list[str]:
        return [bare_id(item) for item in value]

    @field_validator("first_seen")
    @classmethod
    def first_seen_is_aware(cls, value: datetime) -> datetime:
        return aware(value)

    @model_validator(mode="after")
    def aliases_are_distinct(self) -> "Feature":
        if len(set(self.aliases)) != len(self.aliases) or self.name in self.aliases:
            raise ValueError("aliases must not repeat themselves or the current name")
        return self


class Ticket(StrictModel):
    id: str
    source: TicketSource
    text: str
    author: str
    ts: datetime
    project_id: str
    cluster_id: str | None = None
    feature_ids: list[str] = []
    embedding: list[float] | None = None

    @field_validator("id", "author", "project_id")
    @classmethod
    def ids_are_bare(cls, value: str) -> str:
        return bare_id(value)

    @field_validator("cluster_id")
    @classmethod
    def cluster_is_bare(cls, value: str | None) -> str | None:
        return None if value is None else bare_id(value)

    @field_validator("text")
    @classmethod
    def text_is_filled(cls, value: str) -> str:
        return filled(value)

    @field_validator("ts")
    @classmethod
    def ts_is_aware(cls, value: datetime) -> datetime:
        return aware(value)

    @field_validator("feature_ids")
    @classmethod
    def one_feature_at_most(cls, value: list[str]) -> list[str]:
        if len(value) > 1:
            raise ValueError("Ticket feature_ids length must be 0..1")
        return [bare_id(item) for item in value]

    @field_validator("embedding")
    @classmethod
    def valid_embedding(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and (len(value) != 1024 or not all(isfinite(x) for x in value)):
            raise ValueError("embedding must contain 1024 finite numbers")
        return value


class Release(StrictModel):
    id: str
    source_event_id: str | None = None
    source: ReleaseSource
    feature: str
    kind: ReleaseKind
    old_name: str | None = None
    new_name: str | None = None
    evidence: str
    ts: datetime

    @field_validator("id", "feature")
    @classmethod
    def ids_are_bare(cls, value: str) -> str:
        return bare_id(value)

    @field_validator("source_event_id")
    @classmethod
    def source_event_is_bare(cls, value: str | None) -> str | None:
        return None if value is None else bare_id(value)

    @field_validator("evidence")
    @classmethod
    def evidence_is_filled(cls, value: str) -> str:
        return filled(value)

    @field_validator("ts")
    @classmethod
    def ts_is_aware(cls, value: datetime) -> datetime:
        return aware(value)

    @model_validator(mode="after")
    def renamed_carries_both_names(self) -> "Release":
        if self.kind is ReleaseKind.RENAMED and not (
            (self.old_name or "").strip() and (self.new_name or "").strip()
        ):
            raise ValueError("renamed release requires old_name and new_name")
        return self


class Feedback(StrictModel):
    id: str
    tutorial_version: str
    rating: int | None = None
    category: str | None = None
    comment: str | None = None
    user: str
    ts: datetime | None = None

    @field_validator("id", "tutorial_version", "user")
    @classmethod
    def ids_are_bare(cls, value: str) -> str:
        return bare_id(value)

    @field_validator("rating", mode="before")
    @classmethod
    def rating_is_strict_int(cls, value: Any) -> Any:
        """`mode="before"` 才看得到轉型前的原值，否則 `True` 會先被轉成 `1`。"""
        if value is not None and (type(value) is not int or not 1 <= value <= 5):
            raise ValueError("rating must be an integer from 1 to 5")
        return value

    @field_validator("ts")
    @classmethod
    def ts_is_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else aware(value)

    @model_validator(mode="after")
    def carries_signal(self) -> "Feedback":
        if self.rating is None and self.category is None and not (self.comment or "").strip():
            raise ValueError("feedback must carry a rating, a category or a comment")
        return self


class TutorialView(StrictModel):
    tutorial_version: str
    user: str
    ts: datetime

    @field_validator("tutorial_version", "user")
    @classmethod
    def ids_are_bare(cls, value: str) -> str:
        return bare_id(value)

    @field_validator("ts")
    @classmethod
    def ts_is_aware(cls, value: datetime) -> datetime:
        return aware(value)


class AuthoringRule(StrictModel):
    rule_id: str
    rule: str
    applies_when: StepType
    evidence: list[str]
    status: RuleStatus
    applied_to: list[str]
    derived_from: str

    @field_validator("rule_id", "derived_from")
    @classmethod
    def ids_are_bare(cls, value: str) -> str:
        return bare_id(value)

    @field_validator("rule")
    @classmethod
    def rule_is_filled(cls, value: str) -> str:
        return filled(value)

    @field_validator("applied_to")
    @classmethod
    def applied_to_is_bare(cls, value: list[str]) -> list[str]:
        return [bare_id(item) for item in value]

    @field_validator("evidence")
    @classmethod
    def evidence_has_five_distinct_ids(cls, value: list[str]) -> list[str]:
        ids = [bare_id(item) for item in value]
        if len(set(ids)) < 5:
            raise ValueError("evidence must contain at least 5 distinct feedback ids")
        return ids


class ProvenWorkflow(StrictModel):
    signature: str
    domain: str
    adapter: str
    steps: list[ProcStep]
    keys: list[str]
    success_count: int
    fail_count: int
    status: ProcStatus
    last_used: datetime

    @field_validator("signature")
    @classmethod
    def signature_is_hex16(cls, value: str) -> str:
        if len(value) != 16 or not set(value) <= set("0123456789abcdef"):
            raise ValueError("signature must be 16 lowercase hex characters")
        return value

    @field_validator("domain", "adapter")
    @classmethod
    def scope_is_filled(cls, value: str) -> str:
        return filled(value)

    @field_validator("success_count", "fail_count")
    @classmethod
    def counts_are_not_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("count must not be negative")
        return value

    @field_validator("last_used")
    @classmethod
    def last_used_is_aware(cls, value: datetime) -> datetime:
        return aware(value)


Entity = (Tutorial | TutorialVersion | TutorialStep | Feature | Ticket
          | Release | Feedback | TutorialView | AuthoringRule | ProvenWorkflow)
