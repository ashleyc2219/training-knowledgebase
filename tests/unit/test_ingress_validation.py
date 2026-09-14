"""Phase 31：Ticket 與 Release 正規化的必填、列舉、時間與分析欄位邊界。

這裡的每個案例都只呼叫純函式，不碰 AWS、不寫任何 item，所以不標 `aws` marker。
"""

from datetime import UTC, datetime

import pytest

from training_kb.errors import IngressError
from training_kb.ingress import (
    RELEASE_REQUIRED,
    TICKET_REQUIRED,
    validate_release,
    validate_ticket,
)
from training_kb.models import ReleaseKind, ReleaseSource, TicketSource


@pytest.fixture
def valid_ticket() -> dict[str, object]:
    return {
        "id": "t_gh-acme-app-881", "source": "github_issue",
        "text": "會前摘要在哪裡開啟？", "author": "u_gh-4821",
        "ts": "2026-08-03T10:00:00Z", "project_id": "demo",
    }


@pytest.mark.parametrize("missing", ["id", "source", "text", "author", "ts", "project_id"])
def test_ticket_requires_all_ingress_fields(valid_ticket: dict[str, object], missing: str) -> None:
    valid_ticket.pop(missing)
    with pytest.raises(IngressError) as error:
        validate_ticket(valid_ticket)
    assert missing in error.value.fields


def test_ticket_has_no_analysis_output_at_ingress(valid_ticket: dict[str, object]) -> None:
    ticket = validate_ticket(valid_ticket)
    assert ticket.source is TicketSource.GITHUB_ISSUE
    assert ticket.embedding is None
    assert ticket.cluster_id is None
    assert ticket.feature_ids == []


@pytest.mark.parametrize(("patch", "expected"), [
    ({"cluster_id": "c12"}, ("cluster_id",)),
    ({"feature_ids": []}, ("feature_ids",)),
    ({"embedding": [0.1]}, ("embedding",)),
    ({"author": "   "}, ("author",)),
    ({"ts": "2026-08-03T10:00:00"}, ("ts",)),
    ({"source": "slack"}, ("source",)),
])
def test_ticket_boundaries_report_exact_fields(
    valid_ticket: dict[str, object], patch: dict[str, object], expected: tuple[str, ...]
) -> None:
    with pytest.raises(IngressError) as error:
        validate_ticket(valid_ticket | patch)
    assert error.value.fields == expected


def test_manual_import_without_author_is_rejected(valid_ticket: dict[str, object]) -> None:
    """ING Rule 22：缺 `author` 的匯入檔直接拒絕，`fields` 逐字是 `("author",)`。"""
    del valid_ticket["author"]
    with pytest.raises(IngressError) as error:
        validate_ticket(valid_ticket)
    assert error.value.fields == ("author",)
    assert isinstance(error.value.fields, tuple)


def test_all_missing_ticket_fields_are_reported_at_once() -> None:
    """ING Rule 21：一次回報所有缺欄位，排序去重後的 tuple 就是六個必填欄位名。"""
    with pytest.raises(IngressError) as error:
        validate_ticket({})
    assert error.value.fields == tuple(sorted(TICKET_REQUIRED))


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_blank_ticket_text_counts_as_missing(valid_ticket: dict[str, object], bad: str) -> None:
    with pytest.raises(IngressError) as error:
        validate_ticket(valid_ticket | {"text": bad})
    assert error.value.fields == ("text",)


@pytest.mark.parametrize("bad", [None, 881, ["t_881"], {"id": "t_881"}])
def test_non_string_ticket_id_counts_as_missing(
    valid_ticket: dict[str, object], bad: object
) -> None:
    with pytest.raises(IngressError) as error:
        validate_ticket(valid_ticket | {"id": bad})
    assert error.value.fields == ("id",)


def test_subsecond_ts_is_rejected_instead_of_silently_truncated(
    valid_ticket: dict[str, object],
) -> None:
    """00A §3.5：datetime 一律 UTC 整秒，微秒不得靜默截斷。"""
    with pytest.raises(IngressError) as error:
        validate_ticket(valid_ticket | {"ts": "2026-08-03T10:00:00.250Z"})
    assert error.value.fields == ("ts",)


def test_offset_ts_is_normalized_to_utc(valid_ticket: dict[str, object]) -> None:
    ticket = validate_ticket(valid_ticket | {"ts": "2026-08-03T18:00:00+08:00"})
    assert ticket.ts == datetime(2026, 8, 3, 10, 0, tzinfo=UTC)


def test_prefixed_id_is_an_ingress_error_not_a_validation_error(
    valid_ticket: dict[str, object],
) -> None:
    """模型層的拒絕也要收斂成 `IngressError`，否則 webhook handler 會變成 500。"""
    with pytest.raises(IngressError) as error:
        validate_ticket(valid_ticket | {"id": "TICKET#t_881"})
    assert error.value.fields == ("id",)


def test_ticket_source_values_are_all_accepted(valid_ticket: dict[str, object]) -> None:
    """ING Rule 25：三個合法 StrEnum 值都通過，`set(TicketSource)` 就是唯一清單。"""
    for source in TicketSource:
        assert validate_ticket(valid_ticket | {"source": source.value}).source is source


# --- Task 2：Release 與 renamed 條件 ------------------------------------------


@pytest.fixture
def valid_release() -> dict[str, object]:
    return {
        "id": "r_gh-acme-app-pr42-1", "source_event_id": "gh-acme-app-pr42",
        "source": "github_pr", "feature": "Prepare", "kind": "removed",
        "evidence": "PR diff hunk: remove Meeting Summary entry point",
        "ts": "2026-08-04T00:00:00Z",
    }


def test_renamed_requires_old_and_new_name(valid_release: dict[str, object]) -> None:
    payload = valid_release | {"kind": "renamed", "old_name": "Meeting Summary"}
    with pytest.raises(IngressError) as error:
        validate_release(payload)
    assert error.value.fields == ("new_name",)


def test_changed_does_not_invent_names(valid_release: dict[str, object]) -> None:
    release = validate_release(valid_release | {"kind": "changed"})
    assert release.kind is ReleaseKind.CHANGED
    assert release.source is ReleaseSource.GITHUB_PR
    assert release.old_name is None
    assert release.new_name is None


def test_sub_releases_share_source_event_id(valid_release: dict[str, object]) -> None:
    first = validate_release(valid_release)
    second = validate_release(
        valid_release | {"id": "r_gh-acme-app-pr42-2", "feature": "Share Summary"}
    )
    assert first.id != second.id
    assert first.source_event_id == second.source_event_id == "gh-acme-app-pr42"
    assert "42" not in {first.id, second.id}
    with pytest.raises(IngressError) as error:
        validate_release(valid_release | {"id": ""})
    assert error.value.fields == ("id",)


@pytest.mark.parametrize("missing", ["id", "source", "feature", "kind", "evidence", "ts"])
def test_release_requires_all_ingress_fields(
    valid_release: dict[str, object], missing: str
) -> None:
    valid_release.pop(missing)
    with pytest.raises(IngressError) as error:
        validate_release(valid_release)
    assert error.value.fields == (missing,)


def test_all_missing_release_fields_are_reported_at_once() -> None:
    """ING Rule 21：六個必填欄位一次回報，`fields` 是排序去重後的 tuple。"""
    with pytest.raises(IngressError) as error:
        validate_release({})
    assert error.value.fields == tuple(sorted(RELEASE_REQUIRED))


def test_renamed_missing_both_names_reports_both(valid_release: dict[str, object]) -> None:
    with pytest.raises(IngressError) as error:
        validate_release(valid_release | {"kind": "renamed"})
    assert error.value.fields == ("new_name", "old_name")  # constructor 已排序去重


def test_renamed_with_both_names_is_accepted(valid_release: dict[str, object]) -> None:
    release = validate_release(valid_release | {
        "kind": "renamed", "old_name": "Meeting Summary", "new_name": "Prepare",
    })
    assert release.kind is ReleaseKind.RENAMED
    assert (release.old_name, release.new_name) == ("Meeting Summary", "Prepare")


@pytest.mark.parametrize(("patch", "expected"), [
    ({"source": "slack"}, ("source",)),
    ({"kind": "deprecated"}, ("kind",)),
    ({"feature": "   "}, ("feature",)),
    ({"ts": "2026-08-04T00:00:00"}, ("ts",)),
    ({"kind": "renamed", "new_name": "Prepare"}, ("old_name",)),
    ({"source_event_id": ["gh-acme-app-pr42"]}, ("source_event_id",)),
])
def test_release_boundaries_report_exact_fields(
    valid_release: dict[str, object], patch: dict[str, object], expected: tuple[str, ...]
) -> None:
    with pytest.raises(IngressError) as error:
        validate_release(valid_release | patch)
    assert error.value.fields == expected


def test_release_carries_feature_and_kind_at_ingress(valid_release: dict[str, object]) -> None:
    """ING Rule 23：接入當下就解析完成，不是等到 pipeline 才判定。"""
    release = validate_release(valid_release)
    assert release.feature == "Prepare"
    assert release.kind is ReleaseKind.REMOVED
    assert isinstance(release.kind, ReleaseKind)


def test_release_source_values_are_all_accepted(valid_release: dict[str, object]) -> None:
    """ING Rule 25：兩個合法 `ReleaseSource` 與三個合法 `ReleaseKind` 都通過。"""
    for source in ReleaseSource:
        assert validate_release(valid_release | {"source": source.value}).source is source
    for kind in (ReleaseKind.CHANGED, ReleaseKind.REMOVED):
        assert validate_release(valid_release | {"kind": kind.value}).kind is kind


def test_validating_twice_produces_the_same_object(valid_release: dict[str, object]) -> None:
    assert (validate_release(valid_release).model_dump_json()
            == validate_release(dict(reversed(list(valid_release.items())))).model_dump_json())
