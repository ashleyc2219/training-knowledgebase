"""十個邏輯實體跨欄位不變條件的單元測試（Phase 04）。

PRP Rule 6 由 `test_tutorial_and_feature_ids_have_no_tenant_dimension` 直接斷言；
TIC Rule 6 由 `test_ticket_has_at_most_one_feature` 直接斷言（零與一在 test_entities.py）。
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from training_kb.keys import view_pk
from training_kb.models import (
    AuthoringRule,
    Feature,
    Feedback,
    ProvenWorkflow,
    Release,
    StepType,
    Ticket,
    Tutorial,
    TutorialStep,
    TutorialVersion,
    TutorialView,
)

NOW = datetime(2026, 8, 3, 10, tzinfo=UTC)
NAIVE = datetime(2026, 8, 3, 10)
TAIPEI = timezone(timedelta(hours=8))
SUB_SECOND = datetime(2026, 8, 3, 10, 0, 0, 123456, tzinfo=UTC)
SAME_MOMENT_IN_TAIPEI = datetime(2026, 8, 3, 18, tzinfo=TAIPEI)
EVIDENCE = ["f_12", "f_15", "f_19", "f_23", "f_27"]


def proc(**overrides: Any) -> ProvenWorkflow:
    values: dict[str, Any] = dict(
        signature="d1ad3cfd19a24c4d", domain="github.com", adapter="github_issue",
        steps=[], keys=["action", "issue"], success_count=3, fail_count=0,
        status="active", last_used=NOW,
    )
    values.update(overrides)
    return ProvenWorkflow(**values)


def test_rating_rejects_bool_and_out_of_range() -> None:
    for bad in (True, 0, 6, 3.5, "4"):
        with pytest.raises(ValidationError, match="integer from 1 to 5"):
            Feedback(id="f_1", tutorial_version="prepare-meeting@v1", rating=bad, user="u_01")
    kept = Feedback(id="f_2", tutorial_version="prepare-meeting@v1", rating=None,
                    comment="第三步沒有指出按鈕在哪一頁", user="u_01")
    assert kept.rating is None and kept.ts is None


def test_ticket_has_at_most_one_feature() -> None:
    with pytest.raises(ValidationError, match=r"0\.\.1"):
        Ticket(id="t_883", source="email", text="Button not found", author="u_01",
               ts="2026-08-03T10:00:00Z", project_id="demo",
               feature_ids=["Prepare", "Share Summary"])


def test_renamed_release_requires_both_names() -> None:
    with pytest.raises(ValidationError, match="old_name and new_name"):
        Release(
            id="r_42", source="github_pr", feature="Prepare", kind="renamed",
            evidence="PR diff hunk", ts="2026-08-04T00:00:00Z",
        )


def test_rule_applies_when_is_a_single_step_type() -> None:
    rule = AuthoringRule(rule_id="R-007", rule="點 UI 時寫出頁面與按鈕位置",
                         applies_when="click_ui", status="candidate",
                         evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
                         applied_to=[], derived_from="prepare-meeting@v1")
    assert rule.applies_when is StepType.CLICK_UI
    with pytest.raises(ValidationError):
        AuthoringRule(rule_id="R-008", rule="x", applies_when="step.type == click_ui",
                      status="candidate",
                      evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
                      applied_to=[], derived_from="prepare-meeting@v1")


def test_tutorial_and_feature_ids_have_no_tenant_dimension() -> None:
    assert "project_id" not in Tutorial.model_fields
    assert "project_id" not in Feature.model_fields


def test_changed_and_removed_releases_allow_empty_names() -> None:
    for kind in ("changed", "removed"):
        release = Release(id="r_43", source="changelog", feature="Prepare", kind=kind,
                          evidence="changelog entry", ts=NOW)
        assert release.old_name is None and release.new_name is None
    renamed = Release(id="r_44", source="github_pr", feature="Prepare", kind="renamed",
                      old_name="Meeting Summary", new_name="Prepare",
                      evidence="PR #42 diff excerpt", ts=NOW)
    assert (renamed.old_name, renamed.new_name) == ("Meeting Summary", "Prepare")
    with pytest.raises(ValidationError, match="old_name and new_name"):
        Release(id="r_45", source="github_pr", feature="Prepare", kind="renamed",
                old_name="Meeting Summary", new_name="   ",
                evidence="PR #42 diff excerpt", ts=NOW)


def test_feedback_must_carry_rating_category_or_comment() -> None:
    for blank in (None, "   "):
        with pytest.raises(ValidationError, match="rating, a category or a comment"):
            Feedback(id="f_3", tutorial_version="prepare-meeting@v1", user="u_01",
                     comment=blank)
    only_rating = Feedback(id="f_4", tutorial_version="prepare-meeting@v1", rating=1,
                           user="u_01")
    assert only_rating.rating == 1
    assert Feedback(id="f_5", tutorial_version="prepare-meeting@v1", rating=5,
                    user="u_01").rating == 5
    only_category = Feedback(id="f_6", tutorial_version="prepare-meeting@v1",
                             category="Missing information", user="u_01")
    assert only_category.rating is None


def test_step_number_starts_at_one_and_names_one_bare_feature() -> None:
    with pytest.raises(ValidationError, match="1 or greater"):
        TutorialStep(tutorial_version="prepare-meeting@v2", number=0, type="read",
                     text="閱讀摘要", feature_id="Prepare")
    with pytest.raises(ValidationError, match="bare identifier"):
        TutorialStep(tutorial_version="prepare-meeting@v2", number=1, type="read",
                     text="閱讀摘要", feature_id="FEATURE#Prepare")
    with pytest.raises(ValidationError, match="bare identifier"):
        TutorialStep(tutorial_version="prepare-meeting@v2", number=1, type="read",
                     text="閱讀摘要", feature_id="")


def test_feature_aliases_are_distinct_and_exclude_the_current_name() -> None:
    with pytest.raises(ValidationError, match="aliases must not repeat"):
        Feature(feature_id="Prepare", name="Prepare",
                aliases=["Meeting Summary", "Meeting Summary"], first_seen=NOW)
    with pytest.raises(ValidationError, match="aliases must not repeat"):
        Feature(feature_id="Prepare", name="Prepare", aliases=["Prepare"], first_seen=NOW)
    kept = Feature(feature_id="Prepare", name="Prepare", aliases=["Meeting Summary"],
                   first_seen=NOW)
    assert kept.aliases == ["Meeting Summary"]


def test_rule_evidence_needs_five_distinct_feedback_ids() -> None:
    for bad in (["f_12", "f_15", "f_19", "f_23"], ["f_12"] * 5, []):
        with pytest.raises(ValidationError, match="5 distinct"):
            AuthoringRule(rule_id="R-009", rule="輸入時寫出欄位名稱", applies_when="input",
                          status="candidate", evidence=bad, applied_to=[],
                          derived_from="prepare-meeting@v1")
    rule = AuthoringRule(rule_id="R-010", rule="輸入時寫出欄位名稱", applies_when="input",
                         status="active", evidence=EVIDENCE, applied_to=[],
                         derived_from="prepare-meeting@v1")
    assert rule.evidence == EVIDENCE and rule.derived_from == "prepare-meeting@v1"


def test_proc_signature_scope_and_counters() -> None:
    for bad in ("D1AD3CFD19A24C4D", "d1ad3cfd", "d1ad3cfd19a24c4dd", "g1ad3cfd19a24c4d"):
        with pytest.raises(ValidationError, match="16 lowercase hex"):
            proc(signature=bad)
    for blank in ("", "  "):
        with pytest.raises(ValidationError, match="must not be blank"):
            proc(domain=blank)
        with pytest.raises(ValidationError, match="must not be blank"):
            proc(adapter=blank)
    for field in ("success_count", "fail_count"):
        with pytest.raises(ValidationError, match="must not be negative"):
            proc(**{field: -1})
    assert proc(success_count=0, fail_count=0).status.value == "active"


def test_every_datetime_field_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="aware"):
        Feature(feature_id="Prepare", name="Prepare", aliases=[], first_seen=NAIVE)
    with pytest.raises(ValidationError, match="aware"):
        TutorialView(tutorial_version="prepare-meeting@v1", user="u_01", ts=NAIVE)
    with pytest.raises(ValidationError, match="aware"):
        Release(id="r_46", source="changelog", feature="Prepare", kind="changed",
                evidence="changelog entry", ts=NAIVE)
    with pytest.raises(ValidationError, match="aware"):
        Feedback(id="f_7", tutorial_version="prepare-meeting@v1", rating=3, user="u_01",
                 ts=NAIVE)
    with pytest.raises(ValidationError, match="aware"):
        TutorialVersion(version_id="prepare-meeting@v1", slug="prepare-meeting",
                        supersedes=None, reason="gap:c12", rules_applied=[],
                        s3_key="tutorials/prepare-meeting/v1.md", published_at=NAIVE)
    with pytest.raises(ValidationError, match="aware"):
        proc(last_used=NAIVE)


def test_relation_fields_store_bare_identifiers() -> None:
    with pytest.raises(ValidationError, match="bare identifier"):
        Tutorial(slug="prepare-meeting", current_version="VERSION#prepare-meeting@v1",
                 topic="準備會議", feature_ids=[], status="active", successor=None,
                 cluster_id=None)
    with pytest.raises(ValidationError, match="bare identifier"):
        Feedback(id="f_8", tutorial_version="VERSION#prepare-meeting@v1", rating=3,
                 user="u_01")
    with pytest.raises(ValidationError, match="bare identifier"):
        AuthoringRule(rule_id="R-011", rule="x", applies_when="read", status="candidate",
                      evidence=EVIDENCE, applied_to=["VERSION#prepare-meeting@v1"],
                      derived_from="prepare-meeting@v1")


def test_every_datetime_field_rejects_sub_second_precision() -> None:
    """00A §3.5：時間只到整秒。`clock.to_iso` 已經拒絕微秒，實體落地時也必須同一套規則，
    否則 `model_dump(mode="json")` 會寫出 `.123456Z` 這種 `parse_iso` 讀得回來、
    `to_iso` 卻吐不出來的字串。"""
    with pytest.raises(ValidationError, match="whole seconds"):
        Feature(feature_id="Prepare", name="Prepare", aliases=[], first_seen=SUB_SECOND)
    with pytest.raises(ValidationError, match="whole seconds"):
        TutorialView(tutorial_version="prepare-meeting@v1", user="u_01", ts=SUB_SECOND)
    with pytest.raises(ValidationError, match="whole seconds"):
        Ticket(id="t_884", source="email", text="Button not found", author="u_01",
               ts=SUB_SECOND, project_id="demo")
    with pytest.raises(ValidationError, match="whole seconds"):
        Release(id="r_47", source="changelog", feature="Prepare", kind="changed",
                evidence="changelog entry", ts=SUB_SECOND)
    with pytest.raises(ValidationError, match="whole seconds"):
        Feedback(id="f_9", tutorial_version="prepare-meeting@v1", rating=3, user="u_01",
                 ts=SUB_SECOND)
    with pytest.raises(ValidationError, match="whole seconds"):
        TutorialVersion(version_id="prepare-meeting@v1", slug="prepare-meeting",
                        supersedes=None, reason="gap:c12", rules_applied=[],
                        s3_key="tutorials/prepare-meeting/v1.md", published_at=SUB_SECOND)
    with pytest.raises(ValidationError, match="whole seconds"):
        proc(last_used=SUB_SECOND)


def test_datetime_fields_normalise_to_utc_on_the_way_in() -> None:
    """`+08:00` 建模後序列化成 `Z`：`put_meta` 走的是 `model_dump(mode="json")`，
    不正規化就會把偏移量原樣寫進表，同一時刻在表裡出現兩種字串。"""
    ticket = Ticket(id="t_885", source="email", text="Button not found", author="u_01",
                    ts=SAME_MOMENT_IN_TAIPEI, project_id="demo")
    assert ticket.ts.utcoffset() == timedelta(0)
    assert ticket.model_dump(mode="json")["ts"] == "2026-08-03T10:00:00Z"
    feature = Feature(feature_id="Prepare", name="Prepare", aliases=[],
                      first_seen=SAME_MOMENT_IN_TAIPEI)
    assert feature.model_dump(mode="json")["first_seen"] == "2026-08-03T10:00:00Z"


def test_tutorial_view_key_and_ts_agree_across_offsets() -> None:
    """`view_pk` 走 `clock.to_iso`（一律 UTC），`ts` 走 pydantic 序列化；兩者對同一瞬間
    必須得到同一個字串，否則同一次瀏覽會有兩個去重鍵。"""
    offset = TutorialView(tutorial_version="prepare-meeting@v1", user="u_01",
                          ts=SAME_MOMENT_IN_TAIPEI)
    utc = TutorialView(tutorial_version="prepare-meeting@v1", user="u_01", ts=NOW)
    assert view_pk(offset.tutorial_version, offset.user, offset.ts) == view_pk(
        utc.tutorial_version, utc.user, utc.ts)
    assert offset.model_dump(mode="json")["ts"] == utc.model_dump(mode="json")["ts"]
    assert offset.model_dump(mode="json")["ts"] == "2026-08-03T10:00:00Z"
