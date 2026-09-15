"""單元測試共用設定：一個不連 Bedrock 的假 Writer。"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.analytics import validation
from training_kb.analytics.reopen import ReopenStats
from training_kb.analytics.validation import SeedBatch
from training_kb.analytics.version import VersionMetrics
from training_kb.errors import CoordinationError, PermanentError
from training_kb.models import AuthoringRule, Feedback, RuleStatus, StepType, TutorialVersion

FIXED_EMBEDDING = [0.001] * 1024


class RecordingWriter:
    """實作 Phase 15 的 Writer：回應由測試先排好，呼叫全部記下來。"""

    def __init__(self, *, replies: Sequence[Mapping[str, Any]] = (),
                 tool_plans: Sequence[Mapping[str, Any]] = (),
                 embedding: Sequence[float] = FIXED_EMBEDDING) -> None:
        self.replies = [dict(reply) for reply in replies]
        self.tool_plans = [dict(plan) for plan in tool_plans]
        self.embedding = list(embedding)
        self.calls: list[dict[str, Any]] = []
        self.request_attempts = 0

    def _record(self, kind: str, *, operation_id: str, node: str, **extra: Any) -> None:
        self.request_attempts += 1
        self.calls.append({"kind": kind, "operation_id": operation_id, "node": node, **extra})

    def _next(self, queue: list[dict[str, Any]], name: str) -> dict[str, Any]:
        if not queue:
            raise PermanentError(f"RecordingWriter 沒有排好下一個 {name} 回應")
        return queue.pop(0)

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        self._record("embedding", operation_id=operation_id, node=node, text=text)
        return list(self.embedding)

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self._record("generation", operation_id=operation_id, node=node,
                     system=system, user=user, schema=dict(schema))
        return self._next(self.replies, "generate_json")

    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        self._record("tool_use", operation_id=operation_id, node=node,
                     messages=[dict(message) for message in messages],
                     tools=[dict(tool) for tool in tools])
        return self._next(self.tool_plans, "converse_with_tools")


@pytest.fixture
def fake_writer() -> RecordingWriter:
    return RecordingWriter()


# ---- Phase 55 ----
#
# 規則驗證與狀態轉移的自含合成 fixture（`fake_repo`／`batch`／`rules`）。
#
# 三者都是**明示的合成資料**：`approved_by="fixture-only-not-o7"` 只是一個欄位值，
# 不代表維護者核定，測試綠燈也**不代表** `R-007` 已成為 active 或 O7 已通過
# （O7 由 Phase 56 的真實種子與維護者核定紀錄關閉）。
#
# `fake_repo` 只實作 `analytics.validation`／`analytics.status_writer` 真正會用到的
# Repository 方法；`version_metrics` 換成查表版本，因為「由原始回饋重算出 2.875／4.4」
# 是 Phase 53／54 的測試責任，這裡要驗的是**比較與狀態轉移**。

EVIDENCE_IDS = ["fx_1", "fx_2", "fx_3", "fx_4", "fx_5"]
"""`AuthoringRule.evidence` 的下限是五個不重複 ID（Phase 04），少一個 fixture 就建不起來。"""

FIXTURE_SLUG = "prepare-meeting"
BEFORE_VERSION = f"{FIXTURE_SLUG}@v1"
AFTER_VERSION = f"{FIXTURE_SLUG}@v2"
FIXTURE_NOW = datetime(2026, 9, 1, tzinfo=UTC)
DEFAULT_METRICS = (2.875, 4.4, 0.7, 0.2)
"""前平均／後平均／前 rate／後 rate：唯一一組預設值，四個都改得動。"""


def _fixture_rule(rule_id: str, status: RuleStatus, applies_when: StepType) -> AuthoringRule:
    return AuthoringRule(rule_id=rule_id, rule=f"合成規則 {rule_id}：步驟要寫出可見的按鈕名稱",
                         applies_when=applies_when, evidence=list(EVIDENCE_IDS), status=status,
                         applied_to=[], derived_from="fx_1")


def _fixture_version(version_id: str, *, slug: str = FIXTURE_SLUG,
                     published: bool = True) -> TutorialVersion:
    return TutorialVersion(version_id=version_id, slug=slug, reason="合成 fixture",
                           rules_applied=[], s3_key=f"tutorials/{version_id}.md",
                           published_at=FIXTURE_NOW if published else None)


class FakeRuleRepository:
    """假的 Repository：所有寫入都落在 `updated`／`objects` 兩個 dict，不碰 AWS。"""

    def __init__(self) -> None:
        self.rules: dict[str, AuthoringRule] = {
            "R-006": _fixture_rule("R-006", RuleStatus.ACTIVE, StepType.CLICK_UI),
            "R-007": _fixture_rule("R-007", RuleStatus.CANDIDATE, StepType.CLICK_UI),
            "R-013": _fixture_rule("R-013", RuleStatus.ACTIVE, StepType.READ)}
        self.versions: dict[str, TutorialVersion] = {
            BEFORE_VERSION: _fixture_version(BEFORE_VERSION),
            AFTER_VERSION: _fixture_version(AFTER_VERSION)}
        self.metrics: dict[str, tuple[float | None, float | None]] = {}
        self.updated: dict[str, dict[str, Any]] = {}
        self.objects: dict[str, bytes] = {}
        self.revisions: dict[str, int] = {}
        self.seed_metrics(*DEFAULT_METRICS)

    # --- 測試捷徑 ---

    def set_version(self, version_id: str, *, slug: str | None = None,
                    published: bool | None = None) -> None:
        """只改 `slug` 或 `published_at`，其餘保持原樣。"""
        current = self.versions[version_id]
        self.versions[version_id] = _fixture_version(
            version_id, slug=current.slug if slug is None else slug,
            published=(current.published_at is not None) if published is None else published)

    def seed_metrics(self, before_average: float | None, after_average: float | None,
                     before_rate: float | None, after_rate: float | None) -> None:
        self.metrics = {BEFORE_VERSION: (before_average, before_rate),
                        AFTER_VERSION: (after_average, after_rate)}

    def seed_rule(self, rule_id: str, status: str,
                  applies_when: StepType = StepType.CLICK_UI) -> AuthoringRule:
        self.rules[rule_id] = _fixture_rule(rule_id, RuleStatus(status), applies_when)
        return self.rules[rule_id]

    def version_metrics(self, version_id: str, *, repository: Any,
                        approved: frozenset[str], project_id: str) -> VersionMetrics:
        """換掉 `validation.version_metrics` 的查表版；`rate is None` 時分母是 0。"""
        if version_id not in self.metrics:
            raise PermanentError(f"找不到版本 {version_id!r}")
        average, rate = self.metrics[version_id]
        item = self.versions[version_id]
        return VersionMetrics(version_id, item.published_at, average, 0, frozenset(),
                              ReopenStats(0, 0, 0 if rate is None else 10, rate))

    # --- Repository 介面 ---

    def get_version(self, version_id: str) -> TutorialVersion | None:
        return self.versions.get(version_id)

    def get_meta(self, pk: str, model: type[Any], *, consistent: bool = True) -> Any:
        """依 PK 前綴分派；`FEEDBACK#` 只回答「這個 ID 在不在證據清單裡」。"""
        kind, _, bare = pk.partition("#")
        if kind == "RULE":
            return self.rules.get(bare)
        if kind == "FEEDBACK" and bare in EVIDENCE_IDS:
            return Feedback(id=bare, tutorial_version=AFTER_VERSION, rating=1,
                            user="fixture-user")
        return None

    def revision_of(self, pk: str) -> int:
        """與真實 Repository 一致：item 不存在丟 `CoordinationError`，不是 `PermanentError`。"""
        _, _, bare = pk.partition("#")
        if bare not in self.rules:
            raise CoordinationError(f"metadata not found: {pk}")
        return self.revisions.get(pk, 1)

    def update_meta(self, pk: str, changes: Mapping[str, Any], *,
                    expected_revision: int) -> int:
        _, _, bare = pk.partition("#")
        rule = self.rules[bare]
        self.rules[bare] = AuthoringRule(**{**rule.model_dump(), **dict(changes)})
        self.updated.setdefault(pk, {}).update(dict(changes))
        self.revisions[pk] = expected_revision + 1
        return self.revisions[pk]

    def get_object(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def put_object(self, key: str, body: bytes, content_type: str, *,
                   if_none_match: bool) -> None:
        self.objects[key] = body


@pytest.fixture
def fake_repo(monkeypatch: pytest.MonkeyPatch) -> FakeRuleRepository:
    """假 Repository ＋ 查表版 `version_metrics`（模組層名稱綁定才換得掉）。"""
    repository = FakeRuleRepository()
    monkeypatch.setattr(validation, "version_metrics", repository.version_metrics)
    return repository


@pytest.fixture
def batch() -> SeedBatch:
    """`prepare-meeting@v1 -> @v2` 的合成批次；`approved_by` 不是 O7 核定。"""
    return SeedBatch(batch_id="fixture-b1", rule_id="R-007", slug=FIXTURE_SLUG,
                     before_version_id=BEFORE_VERSION, after_version_id=AFTER_VERSION,
                     cluster_id="c12", project_id="fixture", synthetic=True,
                     approved_by="fixture-only-not-o7", approved_at=FIXTURE_NOW)


@pytest.fixture
def rules(fake_repo: FakeRuleRepository) -> list[AuthoringRule]:
    """`fake_repo` 的三條，再加一條 retired 的 `read` 規則（curation 不得收它）。"""
    return [*fake_repo.rules.values(),
            _fixture_rule("R-020", RuleStatus.RETIRED, StepType.READ)]
