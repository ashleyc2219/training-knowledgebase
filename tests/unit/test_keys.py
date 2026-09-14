"""Phase 05：單表鍵與關係邊契約。

十個 PK builder 只吃裸 ID，三個 parser 是它們的反函式；View 鍵是固定 JSON 三元組的 SHA-256。
測試全部是本機契約，不碰任何 AWS 資源，也不宣稱實表 CRUD 已驗證。
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from training_kb.errors import PermanentError
from training_kb.keys import (
    META,
    RELATIONS,
    edge_sk,
    feature_pk,
    feedback_pk,
    parse_edge_sk,
    parse_pk,
    parse_step_pk,
    proc_pk,
    release_pk,
    rule_pk,
    step_pk,
    ticket_pk,
    tutorial_pk,
    version_pk,
    view_pk,
)

VIEW_TS = datetime(2026, 8, 20, tzinfo=UTC)
DECISION = Path(__file__).resolve().parents[2] / "docs/decisions/O1-metadata-sort-key.md"


def _step_builder(value: str) -> str:
    """把 step_pk 收斂成單一裸 ID 的入口，讓十種 builder 能用同一組參數表。"""
    return step_pk(value, 3)


def _view_builder(value: str) -> str:
    """同上；View 的另外兩個輸入固定，只留 tutorial_version 當受測裸 ID。"""
    return view_pk(value, "u_01", VIEW_TS)


BUILDERS: tuple[tuple[str, Callable[[str], str], str], ...] = (
    ("TUTORIAL", tutorial_pk, "prepare-meeting"),
    ("VERSION", version_pk, "prepare-meeting@v2"),
    ("STEP", _step_builder, "prepare-meeting@v2"),
    ("FEATURE", feature_pk, "Prepare"),
    ("TICKET", ticket_pk, "t_881"),
    ("RELEASE", release_pk, "r_42"),
    ("FEEDBACK", feedback_pk, "f_12"),
    ("VIEW", _view_builder, "prepare-meeting@v2"),
    ("RULE", rule_pk, "R-007"),
    ("PROC", proc_pk, "sig-7f3a"),
)
BUILDER_IDS = [row[0] for row in BUILDERS]


@pytest.mark.parametrize(("kind", "build", "bare"), BUILDERS, ids=BUILDER_IDS)
def test_every_builder_prefixes_its_own_kind(
    kind: str, build: Callable[[str], str], bare: str
) -> None:
    value = build(bare)
    assert value.startswith(f"{kind}#")
    assert parse_pk(value)[0] == kind


@pytest.mark.parametrize(("kind", "build", "bare"), BUILDERS, ids=BUILDER_IDS)
def test_every_builder_rejects_empty_and_already_prefixed_input(
    kind: str, build: Callable[[str], str], bare: str
) -> None:
    with pytest.raises(ValueError, match="bare identifier"):
        build("")
    with pytest.raises(ValueError, match="bare identifier"):
        build(f"{kind}#{bare}")


def test_builders_use_the_prefix_strings_from_the_design_table() -> None:
    assert tutorial_pk("prepare-meeting") == "TUTORIAL#prepare-meeting"
    assert version_pk("prepare-meeting@v2") == "VERSION#prepare-meeting@v2"
    assert feature_pk("Prepare") == "FEATURE#Prepare"
    assert ticket_pk("t_881") == "TICKET#t_881"
    assert release_pk("r_42") == "RELEASE#r_42"
    assert feedback_pk("f_12") == "FEEDBACK#f_12"
    assert rule_pk("R-007") == "RULE#R-007"
    assert proc_pk("sig-7f3a") == "PROC#sig-7f3a"


def test_version_and_edge_round_trip() -> None:
    assert parse_pk(version_pk("prepare-meeting@v2")) == (
        "VERSION", "prepare-meeting@v2"
    )
    value = edge_sk("REFERENCES", feature_pk("Prepare"))
    assert value == "REFERENCES#FEATURE#Prepare"
    assert parse_edge_sk(value) == ("REFERENCES", "FEATURE#Prepare")


def test_view_key_is_deterministic_but_time_sensitive() -> None:
    ts = datetime(2026, 8, 20, tzinfo=UTC)
    first = view_pk("prepare-meeting@v2", "u_01", ts)
    assert first == view_pk("prepare-meeting@v2", "u_01", ts)
    assert first.startswith("VIEW#")
    assert len(first) == len("VIEW#") + 64
    assert first != view_pk("prepare-meeting@v2", "u_01", ts + timedelta(seconds=1))
    assert first != view_pk("prepare-meeting@v2", "u_02", ts)


def test_already_prefixed_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="bare identifier"):
        feature_pk("FEATURE#Prepare")
    with pytest.raises(ValueError, match="bare identifier"):
        step_pk("VERSION#prepare-meeting@v2", 3)


def test_step_pk_round_trip_recovers_the_step_number() -> None:
    value = step_pk("prepare-meeting@v2", 3)
    assert value == "STEP#prepare-meeting@v2#3"
    assert parse_step_pk(value) == ("prepare-meeting@v2", 3)
    with pytest.raises(ValueError, match="invalid step primary key"):
        parse_step_pk(version_pk("prepare-meeting@v2"))


def test_invalid_step_number_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        step_pk("prepare-meeting@v2", 0)
    with pytest.raises(ValueError, match="positive"):
        step_pk("prepare-meeting@v2", True)


def test_unknown_relation_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported edge relation"):
        edge_sk("VIEWED", feature_pk("Prepare"))
    with pytest.raises(ValueError, match="invalid edge sort key"):
        parse_edge_sk("HAS_VERSION#VERSION#prepare-meeting@v1")


def test_edge_sk_covers_exactly_the_five_design_relations() -> None:
    assert len(RELATIONS) == 5
    assert edge_sk("SUPERSEDES", version_pk("prepare-meeting@v2")) == (
        "SUPERSEDES#VERSION#prepare-meeting@v2"
    )
    assert edge_sk("APPLIED_TO", version_pk("prepare-meeting@v2")) == (
        "APPLIED_TO#VERSION#prepare-meeting@v2"
    )
    assert edge_sk("ASKS_ABOUT", feature_pk("Prepare")) == "ASKS_ABOUT#FEATURE#Prepare"
    assert edge_sk("REFERS_TO", version_pk("prepare-meeting@v1")) == (
        "REFERS_TO#VERSION#prepare-meeting@v1"
    )
    for unsupported in ("HAS_VERSION", "VIEWED", "SUCCESSOR", "references", ""):
        with pytest.raises(ValueError, match="unsupported edge relation"):
            edge_sk(unsupported, feature_pk("Prepare"))


def test_edge_sk_requires_a_full_target_primary_key() -> None:
    with pytest.raises(ValueError, match="invalid physical primary key"):
        edge_sk("REFERENCES", "Prepare")
    with pytest.raises(ValueError, match="invalid physical primary key"):
        parse_edge_sk("REFERENCES#Prepare")


def test_parse_pk_rejects_strings_without_a_prefix() -> None:
    for bad in ("", "FEATURE", "FEATURE#", "#Prepare"):
        with pytest.raises(ValueError, match="invalid physical primary key"):
            parse_pk(bad)


MALFORMED_STEP_PKS = (
    "STEP#prepare-meeting@v2",       # 沒有步驟號
    "STEP#prepare-meeting@v2#x",     # 步驟號不是數字
    "VERSION#prepare-meeting@v2#3",  # 前綴不是 STEP
    "STEP##3",                       # 版本 ID 空白
    "STEP#prepare-meeting@v2#",      # 步驟號空白
    "STEP#prepare-meeting@v2#03",    # 前導零，組回去不是原字串
    "STEP#prepare-meeting@v2#\uff13",   # 全形數字，int() 會過但組不回原字串
    "STEP#prepare-meeting@v2#\u00b3",   # 上標數字，isdigit() 會過但 isdecimal() 不過
)


@pytest.mark.parametrize("bad", MALFORMED_STEP_PKS)
def test_parse_step_pk_rejects_shapes_that_are_not_a_step(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid step primary key"):
        parse_step_pk(bad)


@pytest.mark.parametrize("number", [1, 3, 10, 42])
def test_parse_step_pk_round_trip_is_closed(number: int) -> None:
    value = step_pk("prepare-meeting@v2", number)
    assert step_pk(*parse_step_pk(value)) == value


def test_builders_reject_padded_identifiers() -> None:
    with pytest.raises(ValueError, match="bare identifier"):
        feature_pk(" Prepare ")
    with pytest.raises(ValueError, match="bare identifier"):
        version_pk("prepare-meeting@v2\n")
    with pytest.raises(ValueError, match="bare identifier"):
        step_pk(" prepare-meeting@v2", 3)


def test_view_pk_rejects_naive_and_sub_second_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone"):
        view_pk("prepare-meeting@v2", "u_01", datetime(2026, 8, 20))
    with pytest.raises(PermanentError, match="whole seconds"):
        view_pk("prepare-meeting@v2", "u_01", VIEW_TS.replace(microsecond=1))


def test_metadata_sort_key_matches_the_recorded_o1_decision() -> None:
    text = DECISION.read_text(encoding="utf-8")
    status = re.search(r"^Status: (accepted|rejected)$", text, re.M)
    approver = re.search(r"^Approver: \S.*$", text, re.M)
    decided_on = re.search(r"^Date: \d{4}-\d{2}-\d{2}$", text, re.M)
    sort_key = re.search(r"^Sort-Key: (\S+)$", text, re.M)
    assert status is not None, "O1 尚未核定：Status 必須是 accepted 或 rejected"
    assert approver is not None, "O1 決策紀錄缺核定者"
    assert decided_on is not None, "O1 決策紀錄缺決策日期"
    assert sort_key is not None, "O1 決策紀錄缺最終 metadata sort key"
    assert META == sort_key.group(1)


def test_step_items_use_an_edge_sort_key_instead_of_meta() -> None:
    step = step_pk("prepare-meeting@v2", 3)
    sort_key = edge_sk("REFERENCES", feature_pk("Prepare"))
    assert parse_pk(step)[0] == "STEP"
    assert sort_key != META
    assert not sort_key.startswith(META)
    assert parse_edge_sk(sort_key)[1] == feature_pk("Prepare")
    with pytest.raises(ValueError, match="invalid edge sort key"):
        parse_edge_sk(META)
