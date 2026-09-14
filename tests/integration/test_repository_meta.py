"""Phase 06：metadata 實體讀寫、Decimal codec 與條件寫入。

跑在 moto 的本機表上：證明 item 形狀與條件寫入邏輯，**不**證明真實 DynamoDB 行為。
`TutorialStep` 沒有 metadata item（它的 SK 是 `REFERENCES#<FEATURE PK>`），所以 `put_meta`
必須明確拒絕它，而不是寫出一筆 `SK=META` 的假步驟。
"""

from datetime import UTC, datetime

import pytest

from training_kb.errors import CoordinationError, PermanentError
from training_kb.models import Feature, Ticket, TutorialStep
from training_kb.repository import RESERVED_ATTRS


def feature(name: str = "Prepare") -> Feature:
    return Feature(feature_id="Prepare", name=name, aliases=[],
                   first_seen=datetime(2026, 8, 1, tzinfo=UTC))


def test_feature_round_trip_and_item_shape(repository, table) -> None:
    repository.put_meta(feature())
    assert repository.get_feature("Prepare") == feature()
    assert repository.get_feature("Missing") is None
    item = table.get_item(Key={"PK": "FEATURE#Prepare", "SK": "META"},
                          ConsistentRead=True)["Item"]
    assert item["entity"] == "FEATURE"
    assert int(item["_revision"]) == 1
    assert set(item) - RESERVED_ATTRS == {"feature_id", "name", "aliases", "first_seen"}


def test_embedding_survives_the_decimal_codec(repository) -> None:
    ticket = Ticket(id="t_881", source="email", text="找不到按鈕", author="u_01",
                    ts=datetime(2026, 8, 3, 10, tzinfo=UTC), project_id="demo",
                    feature_ids=[], embedding=[0.1, -0.25] + [0.0] * 1022)
    repository.put_meta(ticket)
    assert repository.get_meta("TICKET#t_881", Ticket) == ticket


def test_tutorial_step_has_no_metadata_item(repository) -> None:
    step = TutorialStep(tutorial_version="prepare-meeting@v2", number=3,
                        type="click_ui", text="按下開始", feature_id="Prepare")
    with pytest.raises(PermanentError, match="put_edge"):
        repository.put_meta(step)


def test_create_conflict_does_not_overwrite(repository) -> None:
    repository.put_meta(feature())
    with pytest.raises(CoordinationError, match="already exists"):
        repository.put_meta(feature("Meeting Summary"))
    assert repository.get_feature("Prepare") == feature()


def test_revision_of_drives_update_and_rejects_stale_writes(repository) -> None:
    repository.put_meta(feature())
    assert repository.revision_of("FEATURE#Prepare") == 1
    assert repository.update_meta(
        "FEATURE#Prepare", {"name": "Meeting Summary"},
        expected_revision=repository.revision_of("FEATURE#Prepare")) == 2
    assert repository.revision_of("FEATURE#Prepare") == 2
    with pytest.raises(CoordinationError, match="stale revision"):
        repository.update_meta("FEATURE#Prepare", {"name": "Prepare Again"},
                               expected_revision=1)
    assert repository.get_feature("Prepare").name == "Meeting Summary"
    with pytest.raises(CoordinationError, match="metadata not found"):
        repository.revision_of("FEATURE#Missing")


def test_reserved_attributes_and_empty_changes_are_rejected(repository) -> None:
    repository.put_meta(feature())
    for attribute in ("PK", "SK", "target", "entity", "_revision"):
        with pytest.raises(PermanentError, match="reserved"):
            repository.update_meta("FEATURE#Prepare", {attribute: "x"},
                                   expected_revision=1)
    with pytest.raises(PermanentError, match="at least one change"):
        repository.update_meta("FEATURE#Prepare", {}, expected_revision=1)


def test_controlled_overwrite_keeps_revision_monotonic(repository) -> None:
    repository.put_meta(feature())
    repository.put_meta(feature("Meeting Summary"), create_only=False)
    assert repository.revision_of("FEATURE#Prepare") == 2
    assert repository.get_feature("Prepare").name == "Meeting Summary"
