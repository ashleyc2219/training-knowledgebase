"""Phase 40 Task 2／3：slug 由程式決定、教學身分、未發布的第一版。

共用器材（`FakeRepository`／`FakeOperations`／`FakeWriter`／`GAP`／`dt`）定義在
`test_ticket_decide.py`，這裡只 import 類別再各自宣告 fixture——fixture 靠 import 傳遞
會被 ruff 判成未使用的 import。`tests/` 沒有 `__init__.py`，pytest 預設的 prepend import
mode 會把 `tests/unit/pipelines` 放進 `sys.path`，整包跑與單檔跑都成立。
"""

from dataclasses import replace
from typing import Any

import pytest
from test_ticket_decide import GAP, FakeOperations, FakeRepository, FakeWriter, dt

from training_kb.analytics.status_writer import VALIDATED_AT_KEY, load_validated_at
from training_kb.errors import ContentError, PermanentError
from training_kb.keys import META, feature_pk, ticket_pk, tutorial_pk
from training_kb.models import Tutorial
from training_kb.pipelines.ticket import (
    create_first_version,
    create_tutorial_identity,
    decide_ticket_action,
    tutorial_slug,
)
from training_kb.repository import RESERVED_ATTRS


@pytest.fixture
def fake_repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def fake_ops() -> FakeOperations:
    return FakeOperations()


@pytest.fixture
def fake_writer() -> FakeWriter:
    return FakeWriter()


def four_step_draft(*, feature_id: str, title: str = "Prepare Meeting",
                    steps: int = 4) -> dict[str, Any]:
    """符合 `TutorialDraft` schema 的 dict（**不是** pydantic 模型，00A D-02）。

    `title` 固定是 ASCII 的 `Prepare Meeting`，slug 才會是 `prepare-meeting`；四步的型態是
    `read`／`click_ui`／`click_ui`／`read`，`feature_id` 全部是傳入值。
    """
    types = ["read", "click_ui", "click_ui", "read"]
    return {
        "title": title,
        "problem": "找不到會前摘要入口",
        "prerequisites": ["已登入工作區"],
        "expected_outcome": "看得到會前摘要",
        "steps": [{"number": index + 1, "type": types[index % len(types)],
                   "text": f"第 {index + 1} 步", "feature_id": feature_id}
                  for index in range(steps)],
    }


# --- Task 2 Step 1：slug ----------------------------------------------------


def test_slug_is_kebab_case_and_stable_across_retries(fake_repo: FakeRepository) -> None:
    assert tutorial_slug(GAP, "Prepare Meeting", repository=fake_repo) == "prepare-meeting"
    assert tutorial_slug(GAP, "  Prepare--Meeting  ", repository=fake_repo) == "prepare-meeting"
    assert tutorial_slug(GAP, "準備會議", repository=fake_repo) == "prepare"   # 退回 feature_id
    fake_repo.save_tutorial("prepare-meeting", feature_id="Other", cluster_id="c99")
    assert tutorial_slug(GAP, "Prepare Meeting", repository=fake_repo) == "prepare-meeting-c12"
    # 同一個 operation 重試會走同一條退讓，不會像「遞增 -2、-3」那樣每次換一個。
    assert tutorial_slug(GAP, "Prepare Meeting", repository=fake_repo) == "prepare-meeting-c12"


def test_slug_falls_back_to_cluster_id_when_nothing_is_ascii(fake_repo: FakeRepository) -> None:
    gap = replace(GAP, feature_id=None)
    assert tutorial_slug(gap, "準備會議", repository=fake_repo) == "gap-c12"


def test_slug_refuses_when_both_candidates_belong_to_other_clusters(
        fake_repo: FakeRepository) -> None:
    fake_repo.save_tutorial("prepare-meeting", feature_id="Other", cluster_id="c99")
    fake_repo.save_tutorial("prepare-meeting-c12", feature_id="Other", cluster_id="c98")
    with pytest.raises(ContentError):
        tutorial_slug(GAP, "Prepare Meeting", repository=fake_repo)


# --- Task 2 Step 4：教學身分 -------------------------------------------------


def test_create_tutorial_identity_is_reused_on_retry(fake_repo: FakeRepository) -> None:
    fake_repo.save_feature("Prepare")

    first = create_tutorial_identity(GAP, slug="prepare-meeting", topic="Prepare Meeting",
                                     repository=fake_repo)
    writes_after_first = list(fake_repo.writes)
    second = create_tutorial_identity(GAP, slug="prepare-meeting", topic="改過的標題",
                                      repository=fake_repo)

    assert first == second
    assert fake_repo.writes == writes_after_first          # 重試沒有第二次寫入
    assert first.feature_ids == ["Prepare"]
    assert first.current_version is None
    assert first.cluster_id == "c12"
    assert first.successor is None
    # 寫進 feature_ids 了，所以下一輪同群工單會走 KEEP（Phase 27 用 feature_id in feature_ids）
    assert decide_ticket_action(GAP, repository=fake_repo) == "KEEP"
    active = fake_repo.find_active_tutorial_for_feature("Prepare")
    assert active is not None and active.slug == "prepare-meeting"


def test_create_tutorial_identity_refuses_a_slug_owned_by_another_cluster(
        fake_repo: FakeRepository) -> None:
    fake_repo.save_tutorial("prepare-meeting", feature_id="Other", cluster_id="c99")
    with pytest.raises(ContentError):
        create_tutorial_identity(GAP, slug="prepare-meeting", topic="Prepare Meeting",
                                 repository=fake_repo)


def test_tutorial_item_has_no_attributes_beyond_the_model(fake_repo: FakeRepository) -> None:
    create_tutorial_identity(GAP, slug="prepare-meeting", topic="Prepare Meeting",
                             repository=fake_repo)
    item = fake_repo.table[(tutorial_pk("prepare-meeting"), META)]
    assert set(Tutorial.model_fields) <= set(item)
    assert set(item) - set(Tutorial.model_fields) <= RESERVED_ATTRS


def test_no_feature_gap_never_creates_an_identity(fake_repo: FakeRepository) -> None:
    with pytest.raises(ContentError):
        create_tutorial_identity(replace(GAP, feature_id=None), slug="prepare-meeting",
                                 topic="Prepare Meeting", repository=fake_repo)
    assert fake_repo.written("TUTORIAL#") == []


# --- Task 3：未發布的第一版 --------------------------------------------------


def test_create_first_version_writes_unpublished_v1(fake_repo: FakeRepository,
                                                    fake_writer: FakeWriter,
                                                    fake_ops: FakeOperations) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    fake_repo.save_rule("R-007", status="active", applies_when="click_ui")
    fake_repo.save_validated_at_file({"R-007": "2026-09-01T00:00:00Z"})  # Phase 55 寫的那個檔
    fake_writer.reply = four_step_draft(feature_id="Prepare")

    plan = create_first_version(GAP, repository=fake_repo, writer=fake_writer,
                                operations=fake_ops, operation_id="op-1",
                                now=dt("2026-09-13T02:05:00Z"))

    assert plan.version_id == "prepare-meeting@v1"
    assert plan.reason == "gap:c12"
    assert plan.rules_applied == ("R-007",)
    version = fake_repo.get_version("prepare-meeting@v1")
    assert version is not None and version.published_at is None
    tutorial = fake_repo.get_tutorial("prepare-meeting")
    assert tutorial is not None
    assert tutorial.current_version is None
    assert tutorial.feature_ids == ["Prepare"]
    assert fake_repo.objects["tutorials/prepare-meeting/v1.md"]
    assert not [key for key in fake_repo.objects if key.startswith("site/")]


def test_create_first_version_records_the_decision_and_links_tickets(
        fake_repo: FakeRepository, fake_writer: FakeWriter, fake_ops: FakeOperations) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    fake_writer.reply = four_step_draft(feature_id="Prepare")

    create_first_version(GAP, repository=fake_repo, writer=fake_writer, operations=fake_ops,
                         operation_id="op-1", now=dt("2026-09-13T02:05:00Z"))

    assert "operations/op-1/ticket-decision.json" in fake_repo.objects
    assert fake_repo.edges(ticket_pk("t_881"), "ASKS_ABOUT") == [feature_pk("Prepare")]


def test_prompt_carries_the_gap_the_rules_and_only_this_cluster(
        fake_repo: FakeRepository, fake_writer: FakeWriter, fake_ops: FakeOperations) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    fake_repo.save_ticket("t_999", cluster="c99")
    fake_repo.save_rule("R-007", status="active", applies_when="click_ui")
    fake_repo.save_rule("R-800", status="candidate", applies_when="read")
    fake_repo.save_validated_at_file({"R-007": "2026-09-01T00:00:00Z"})
    fake_writer.reply = four_step_draft(feature_id="Prepare")

    create_first_version(GAP, repository=fake_repo, writer=fake_writer, operations=fake_ops,
                         operation_id="op-1", now=dt("2026-09-13T02:05:00Z"))

    assert len(fake_writer.calls) == 1
    call = fake_writer.calls[0]
    assert call["node"] == "create_v1"
    assert GAP.gap in call["user"]
    assert "t_881 的原始提問" in call["user"]
    assert "t_999" not in call["user"]        # 別群的工單文字不進 prompt
    assert "R-007" in call["user"]
    assert "R-800" not in call["user"]        # candidate 規則永不入選
    assert "<source_data>" in call["user"]    # D-67 的資料分區


def test_active_rule_without_validated_at_is_a_permanent_error(
        fake_repo: FakeRepository, fake_writer: FakeWriter, fake_ops: FakeOperations) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    fake_repo.save_rule("R-007", status="active", applies_when="click_ui")
    fake_writer.reply = four_step_draft(feature_id="Prepare")

    with pytest.raises(PermanentError):
        create_first_version(GAP, repository=fake_repo, writer=fake_writer, operations=fake_ops,
                            operation_id="op-1", now=dt("2026-09-13T02:05:00Z"))
    assert fake_writer.calls == []            # 擋在模型呼叫之前


@pytest.mark.parametrize("broken", ["missing_section", "unknown_feature", "bad_step_type"])
def test_invalid_draft_leaves_no_tutorial_behind(fake_repo: FakeRepository,
                                                 fake_writer: FakeWriter,
                                                 fake_ops: FakeOperations,
                                                 broken: str) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    draft = four_step_draft(feature_id="Prepare")
    if broken == "missing_section":
        draft["prerequisites"] = ["   "]
    elif broken == "unknown_feature":
        draft = four_step_draft(feature_id="Nope")
    else:
        draft["steps"][0]["type"] = "scroll"
    fake_writer.reply = draft

    with pytest.raises(PermanentError):
        create_first_version(GAP, repository=fake_repo, writer=fake_writer, operations=fake_ops,
                            operation_id="op-1", now=dt("2026-09-13T02:05:00Z"))

    assert fake_repo.written("TUTORIAL#") == []
    assert fake_repo.written("VERSION#") == []
    assert fake_repo.get_tutorial("prepare-meeting") is None


def test_rerun_with_the_same_operation_id_reuses_version_and_tutorial(
        fake_repo: FakeRepository, fake_writer: FakeWriter, fake_ops: FakeOperations) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    fake_writer.reply = four_step_draft(feature_id="Prepare")

    first = create_first_version(GAP, repository=fake_repo, writer=fake_writer,
                                 operations=fake_ops, operation_id="op-1",
                                 now=dt("2026-09-13T02:05:00Z"))
    second = create_first_version(GAP, repository=fake_repo, writer=fake_writer,
                                  operations=fake_ops, operation_id="op-1",
                                  now=dt("2026-09-13T02:06:00Z"))

    assert first.version_id == second.version_id == "prepare-meeting@v1"
    assert fake_repo.written("TUTORIAL#").count(tutorial_pk("prepare-meeting")) == 1
    assert len([key for key in fake_repo.table if key[0].startswith("VERSION#")]) == 1


def test_create_first_version_refuses_when_the_action_is_not_create(
        fake_repo: FakeRepository, fake_writer: FakeWriter, fake_ops: FakeOperations) -> None:
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    # 別群（或 Demo 直接寫入的種子教學）佔住 Feature，這才是真正的 KEEP。
    fake_repo.save_tutorial("prepare-meeting", feature_id="Prepare", cluster_id="c99")
    fake_writer.reply = four_step_draft(feature_id="Prepare")

    with pytest.raises(PermanentError):
        create_first_version(GAP, repository=fake_repo, writer=fake_writer, operations=fake_ops,
                            operation_id="op-1", now=dt("2026-09-13T02:05:00Z"))
    assert fake_writer.calls == []
    assert fake_repo.written("VERSION#") == []


# --- analytics/status_writer.py 的讀取端（00A D-28，本 Phase 首建） -----------


def test_load_validated_at_returns_empty_before_phase_55(fake_repo: FakeRepository) -> None:
    assert load_validated_at(fake_repo) == {}


def test_load_validated_at_parses_iso_and_refuses_broken_files(
        fake_repo: FakeRepository) -> None:
    fake_repo.save_validated_at_file({"R-007": "2026-09-01T00:00:00Z"})
    assert load_validated_at(fake_repo) == {"R-007": dt("2026-09-01T00:00:00Z")}
    fake_repo.objects[VALIDATED_AT_KEY] = b'{"R-007": "not-a-time"}'
    with pytest.raises(PermanentError):
        load_validated_at(fake_repo)
    fake_repo.objects[VALIDATED_AT_KEY] = b'["R-007"]'
    with pytest.raises(PermanentError):
        load_validated_at(fake_repo)


def test_no_active_rule_means_empty_rules_applied(fake_repo: FakeRepository,
                                                  fake_writer: FakeWriter,
                                                  fake_ops: FakeOperations) -> None:
    """Phase 55 之前沒有 active 規則，`rules_applied` 是 `[]`，這是正常狀態。"""
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    fake_writer.reply = four_step_draft(feature_id="Prepare")

    plan = create_first_version(GAP, repository=fake_repo, writer=fake_writer,
                                operations=fake_ops, operation_id="op-1",
                                now=dt("2026-09-13T02:05:00Z"))

    assert plan.rules_applied == ()
    assert "<active_rules></active_rules>" in fake_writer.calls[0]["user"]
