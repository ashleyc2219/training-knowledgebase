"""十個邏輯實體、`Entity` union 與基本欄位驗證的單元測試（Phase 04）。"""

from datetime import UTC, datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from training_kb import models

NAMES = ["Tutorial", "TutorialVersion", "TutorialStep", "Feature", "Ticket",
         "Release", "Feedback", "TutorialView", "AuthoringRule", "ProvenWorkflow"]

NOW = datetime(2026, 8, 3, 10, tzinfo=UTC)
EVIDENCE = ["f_12", "f_15", "f_19", "f_23", "f_27"]


def ten_fixtures() -> list[models.StrictModel]:
    """驗收表的十個合法 fixture，順序與 `Entity` union 相同。"""
    return [
        models.Tutorial(slug="prepare-meeting", current_version="prepare-meeting@v2",
                        topic="準備會議", feature_ids=["Prepare"], status="active",
                        successor=None, cluster_id="c12"),
        models.TutorialVersion(version_id="prepare-meeting@v2", slug="prepare-meeting",
                               supersedes="prepare-meeting@v1", reason="gap:c12",
                               rules_applied=["R-007"],
                               s3_key="tutorials/prepare-meeting/v2.md", published_at=NOW),
        models.TutorialStep(tutorial_version="prepare-meeting@v2", number=3, type="click_ui",
                            text="按下開始", feature_id="Prepare"),
        models.Feature(feature_id="Prepare", name="Prepare", aliases=["Meeting Summary"],
                       first_seen=NOW),
        models.Ticket(id="t_881", source="email", text="Button not found", author="u_01", ts=NOW,
                      project_id="demo", cluster_id=None, feature_ids=["Prepare"],
                      embedding=[0.5] * 1024),
        models.Release(id="r_42", source_event_id="42", source="github_pr", feature="Prepare",
                       kind="renamed", old_name="Meeting Summary", new_name="Prepare",
                       evidence="PR #42 diff excerpt", ts=NOW),
        models.Feedback(id="f_12", tutorial_version="prepare-meeting@v2", rating=2,
                        category="Button not found", comment="第三步沒有指出按鈕在哪一頁",
                        user="u_01", ts=NOW),
        models.TutorialView(tutorial_version="prepare-meeting@v2", user="u_01", ts=NOW),
        models.AuthoringRule(rule_id="R-007", rule="點 UI 時寫出頁面與按鈕位置",
                             applies_when="click_ui", evidence=EVIDENCE, status="candidate",
                             applied_to=["prepare-meeting@v2"],
                             derived_from="prepare-meeting@v1"),
        models.ProvenWorkflow(signature="d1ad3cfd19a24c4d", domain="github.com",
                              adapter="github_issue",
                              steps=[models.ProcStep(tool="parse_github_issue",
                                                     args={"title": "$.issue.title"})],
                              keys=["action", "issue", "repository", "sender"],
                              success_count=4, fail_count=0, status="active", last_used=NOW),
    ]


def test_exactly_ten_entity_models_are_public() -> None:
    assert [model.__name__ for model in get_args(models.Entity)] == NAMES
    assert all(issubclass(model, models.StrictModel) for model in get_args(models.Entity))
    for absent in ("User", "Project", "KnowledgeGap"):
        assert not hasattr(models, absent)


def test_ticket_accepts_zero_or_one_feature() -> None:
    ticket = models.Ticket(
        id="t_881", source="email", text="Button not found", author="u_01",
        ts="2026-08-03T10:00:00Z", project_id="demo", feature_ids=[],
    )
    assert ticket.feature_ids == [] and ticket.ts.tzinfo is not None


def test_ticket_requires_author_and_aware_ts() -> None:
    base = dict(id="t_882", source="email", text="Button not found", project_id="demo")
    with pytest.raises(ValidationError, match="author"):
        models.Ticket(**base, ts="2026-08-03T10:00:00Z")
    with pytest.raises(ValidationError, match="aware"):
        models.Ticket(**base, author="u_01", ts="2026-08-03T10:00:00")


def test_ten_valid_fixtures_are_exactly_the_entity_union() -> None:
    built = ten_fixtures()
    assert [type(item).__name__ for item in built] == NAMES
    assert all(isinstance(item, get_args(models.Entity)) for item in built)
    assert len(get_args(models.Entity)) == 10


def test_proven_workflow_keeps_domain_and_adapter_scope() -> None:
    proc = ten_fixtures()[-1]
    assert isinstance(proc, models.ProvenWorkflow)
    assert (proc.domain, proc.adapter) == ("github.com", "github_issue")
    assert proc.status is models.ProcStatus.ACTIVE and proc.steps[0].tool == "parse_github_issue"


@pytest.mark.parametrize("bad", [[0.0] * 1023, [0.0] * 1025,
                                 [float("nan")] + [0.0] * 1023,
                                 [float("inf")] + [0.0] * 1023])
def test_embedding_must_be_1024_finite_numbers(bad: list[float]) -> None:
    with pytest.raises(ValidationError, match="1024 finite"):
        models.Ticket(id="t_884", source="email", text="Button not found", author="u_01", ts=NOW,
                      project_id="demo", feature_ids=[], embedding=bad)


def test_tutorial_view_requires_version_user_and_ts() -> None:
    for missing in ("tutorial_version", "user", "ts"):
        values: dict[str, object] = {"tutorial_version": "prepare-meeting@v2",
                                     "user": "u_01", "ts": NOW}
        del values[missing]
        with pytest.raises(ValidationError, match=missing):
            models.TutorialView(**values)


def test_boundary_shapes_from_the_acceptance_table() -> None:
    fresh = models.Tutorial(slug="prepare-meeting", current_version=None, topic="準備會議",
                            feature_ids=[], status="active", successor=None, cluster_id=None)
    assert fresh.current_version is None and fresh.status is models.TutorialStatus.ACTIVE
    retired = models.Tutorial(slug="meeting-summary", current_version="meeting-summary@v1",
                              topic="舊教學", feature_ids=[], status="retired",
                              successor=None, cluster_id=None)
    assert retired.successor is None and retired.status is models.TutorialStatus.RETIRED
    draft = models.TutorialVersion(version_id="prepare-meeting@v3", slug="prepare-meeting",
                                   supersedes="prepare-meeting@v2", reason="release:r_42",
                                   rules_applied=[], s3_key="tutorials/prepare-meeting/v3.md",
                                   published_at=None)
    assert draft.published_at is None


def test_entities_reject_physical_attributes() -> None:
    for attr in ("PK", "SK", "entity", "_revision"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            models.Feature(**{"feature_id": "Prepare", "name": "Prepare", "aliases": [],
                              "first_seen": NOW, attr: "x"})
