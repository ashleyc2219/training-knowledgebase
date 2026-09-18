"""Phase 06：metadata 實體讀寫、Decimal codec 與條件寫入。

跑在 moto 的本機表上：證明 item 形狀與條件寫入邏輯，**不**證明真實 DynamoDB 行為。
`TutorialStep` 沒有 metadata item（它的 SK 是 `REFERENCES#<FEATURE PK>`），所以 `put_meta`
必須明確拒絕它，而不是寫出一筆 `SK=META` 的假步驟。
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from training_kb.errors import CoordinationError, PermanentError
from training_kb.keys import (
    META,
    feature_pk,
    feedback_pk,
    proc_pk,
    release_pk,
    rule_pk,
    ticket_pk,
    tutorial_pk,
    version_pk,
    view_pk,
)
from training_kb.models import (
    AuthoringRule,
    Entity,
    Feature,
    Feedback,
    ProcStep,
    ProvenWorkflow,
    Release,
    Ticket,
    Tutorial,
    TutorialStep,
    TutorialVersion,
    TutorialView,
)
from training_kb.repository import RESERVED_ATTRS, item_to_model


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
    ticket = Ticket(id="t_881", source="email", text="Button not found", author="u_01",
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


def test_raw_item_needs_item_to_model(repository, table) -> None:
    repository.put_meta(feature())
    item = table.get_item(Key={"PK": "FEATURE#Prepare", "SK": "META"},
                          ConsistentRead=True)["Item"]
    with pytest.raises(ValidationError):
        Feature.model_validate(item)
    assert item_to_model(item, Feature) == feature()


def test_meta_item_primitives_serve_non_model_prefixes(repository) -> None:
    assert repository.get_meta_item("OPS#op-1") is None
    assert repository.put_meta_item("OPS#op-1", {"status": "accepted", "counter": 0}) is True
    assert repository.put_meta_item("OPS#op-1", {"status": "done", "counter": 9}) is False
    item = repository.get_meta_item("OPS#op-1")
    assert item["PK"] == "OPS#op-1" and item["SK"] == "META"
    assert item["entity"] == "OPS" and item["_revision"] == 1
    assert item["status"] == "accepted" and item["counter"] == 0
    assert repository.update_meta("OPS#op-1", {"counter": 1},
                                  expected_revision=item["_revision"]) == 2
    assert repository.get_meta_item("OPS#op-1")["counter"] == 1
    with pytest.raises(PermanentError, match="reserved"):
        repository.put_meta_item("OPS#op-2", {"_revision": 7})


TS = datetime(2026, 8, 3, 10, tzinfo=UTC)
VIEW = TutorialView(tutorial_version="prepare-meeting@v2", user="u_01", ts=TS)

NINE_METADATA_ENTITIES: list[tuple[str, Entity]] = [
    (tutorial_pk("prepare-meeting"),
     Tutorial(slug="prepare-meeting", topic="會前準備", feature_ids=["Prepare"],
              status="active")),
    (version_pk("prepare-meeting@v2"),
     TutorialVersion(version_id="prepare-meeting@v2", slug="prepare-meeting",
                     supersedes="prepare-meeting@v1", reason="gap:c12",
                     rules_applied=["R-001"], s3_key="tutorials/prepare-meeting/v2.md",
                     published_at=TS)),
    (feature_pk("Prepare"), feature()),
    (ticket_pk("t_881"),
     Ticket(id="t_881", source="github_issue", text="Button not found", author="u_01", ts=TS,
            project_id="demo", feature_ids=["Prepare"], embedding=[0.5] * 1024)),
    (release_pk("R-007"),
     Release(id="R-007", source="changelog", feature="Prepare", kind="renamed",
             old_name="Prepare", new_name="Meeting Summary", evidence="改名公告", ts=TS)),
    (feedback_pk("f_12"),
     Feedback(id="f_12", tutorial_version="prepare-meeting@v2", rating=2,
              category="步驟不清楚", comment="第三步找不到", user="u_01", ts=TS)),
    (view_pk("prepare-meeting@v2", "u_01", TS), VIEW),
    (rule_pk("R-001"),
     AuthoringRule(rule_id="R-001", rule="每步只提一個功能", applies_when="click_ui",
                   evidence=["f_1", "f_2", "f_3", "f_4", "f_5"], status="active",
                   applied_to=["prepare-meeting@v2"], derived_from="feedback-review")),
    (proc_pk("0123456789abcdef"),
     ProvenWorkflow(signature="0123456789abcdef", domain="github.com", adapter="issues",
                    steps=[ProcStep(tool="http_get", args={"path": "/issues"})],
                    keys=["action", "issue"], success_count=3, fail_count=0,
                    status="active", last_used=TS)),
]


def test_all_nine_metadata_entities_round_trip(repository, table) -> None:
    for pk, entity in NINE_METADATA_ENTITIES:
        repository.put_meta(entity)
        assert repository.get_meta(pk, type(entity)) == entity, pk
        item = table.get_item(Key={"PK": pk, "SK": "META"}, ConsistentRead=True)["Item"]
        assert item["entity"] == pk.split("#", 1)[0]
        assert set(item) - RESERVED_ATTRS == set(entity.model_dump())


def test_native_list_and_map_are_not_json_strings(repository, table) -> None:
    pk, proc = NINE_METADATA_ENTITIES[-1]
    repository.put_meta(proc)
    item = table.get_item(Key={"PK": pk, "SK": "META"}, ConsistentRead=True)["Item"]
    assert item["keys"] == ["action", "issue"]
    assert item["steps"] == [{"tool": "http_get", "args": {"path": "/issues"}}]
    assert item["last_used"] == "2026-08-03T10:00:00Z"


def test_named_getters_use_their_own_key_builder(repository) -> None:
    for _, entity in NINE_METADATA_ENTITIES:
        repository.put_meta(entity)
    assert repository.get_tutorial("prepare-meeting").topic == "會前準備"
    assert repository.get_version("prepare-meeting@v2").s3_key.endswith("v2.md")
    assert repository.get_feature("Prepare") == feature()
    assert repository.get_proc("0123456789abcdef").domain == "github.com"
    assert repository.get_tutorial("missing") is None


# --- Phase 06 review 代修項目（由 Phase 07 一併處理；測試放在 Phase 06 的行為所屬檔案）---


def test_controlled_overwrite_reports_that_it_did_not_create(repository) -> None:
    """`put_meta_item` 的回傳值是「**本次是否由我建立**」（00A §6.3）：受控覆寫成功是 `False`。

    回 `True` 會讓 `OPS#`／`SEQ#`／`LEASE#` 的呼叫端誤以為自己是第一個建立者，
    永久去重的判斷點就失效了。
    """
    assert repository.put_meta_item("OPS#op-9", {"status": "accepted"}) is True
    assert repository.put_meta_item("OPS#op-9", {"status": "done"}, create_only=False) is False
    item = repository.get_meta_item("OPS#op-9")
    assert item["_revision"] == 2
    assert item["status"] == "done"


def test_tuple_values_survive_the_decimal_codec(repository) -> None:
    """Phase 10 的 `OperationRecord.model_output_refs` 是 `tuple`；
    tuple 內的 float 也要轉 Decimal。"""
    repository.put_meta_item("OPS#op-10", {"refs": ("a", "b"), "scores": (0.5, 1)})
    item = repository.get_meta_item("OPS#op-10")
    assert item["refs"] == ["a", "b"]
    assert item["scores"] == [0.5, 1]


def test_transact_write_values_survive_the_decimal_codec(repository) -> None:
    """交易 item 的值與 `put_meta`／`update_meta` 走**同一套** Decimal codec。

    boto3 的 resource client 不收 Python `float`（`Float types are not supported`），
    所以沒有 codec 的話帶 float 欄位的交易會在寫入端直接炸掉——呼叫端得各自先轉一次
    Decimal，遲早有人漏掉（Phase 24 review 便宜修正 A-minor 2）。
    """
    repository.put_meta_item("OPS#op-11", {"status": "accepted"})
    action = {"Update": {
        "TableName": repository.table_name,
        "Key": {"PK": "OPS#op-11", "SK": META},
        "UpdateExpression": "SET #score = :score, #tags = :tags",
        "ConditionExpression": "attribute_exists(PK)",
        "ExpressionAttributeNames": {"#score": "score", "#tags": "tags"},
        "ExpressionAttributeValues": {":score": 0.5, ":tags": [0.25, 1]},
    }}
    assert repository.transact_write([action]) is None
    item = repository.get_meta_item("OPS#op-11")
    assert item["score"] == 0.5
    assert item["tags"] == [0.25, 1]


def test_malformed_primary_key_is_a_permanent_error(repository) -> None:
    """`parse_pk` 的 `ValueError` 不在 00A §4.1 的分類裡，要包成 `PermanentError`。"""
    with pytest.raises(PermanentError, match="primary key"):
        repository.put_meta_item("no-prefix", {"status": "accepted"})
