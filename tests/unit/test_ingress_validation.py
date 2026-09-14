"""Phase 31：Ticket 與 Release 正規化的必填、列舉、時間與分析欄位邊界。

這裡的每個案例都只呼叫純函式，不碰 AWS、不寫任何 item，所以不標 `aws` marker。
"""

from datetime import UTC, datetime

import pytest

from training_kb.errors import IngressError
from training_kb.ingress import TICKET_REQUIRED, validate_ticket
from training_kb.models import TicketSource


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
