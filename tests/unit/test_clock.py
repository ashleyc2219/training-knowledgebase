from datetime import UTC, datetime, timedelta, timezone

import pytest

from training_kb.clock import now_utc, parse_iso, to_iso, utc_date
from training_kb.errors import PermanentError

TAIPEI = timezone(timedelta(hours=8))


def test_iso_round_trip_and_offset_conversion() -> None:
    value = datetime(2026, 8, 20, tzinfo=UTC)
    assert to_iso(value) == "2026-08-20T00:00:00Z"
    assert parse_iso("2026-08-20T00:00:00Z") == value
    assert utc_date(value).isoformat() == "2026-08-20"
    assert to_iso(datetime(2026, 8, 20, 8, 0, tzinfo=TAIPEI)) == "2026-08-20T00:00:00Z"
    assert utc_date(datetime(2026, 8, 20, 7, 0, tzinfo=TAIPEI)).isoformat() == "2026-08-19"
    assert now_utc().tzinfo is not None


def test_naive_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        to_iso(datetime(2026, 8, 20))
    with pytest.raises(ValueError, match="timezone"):
        parse_iso("2026-08-20T00:00:00")


def test_time_strings_are_whole_seconds() -> None:
    assert now_utc().microsecond == 0
    with pytest.raises(PermanentError, match="whole seconds"):
        to_iso(datetime(2026, 8, 20, 6, 25, 58, 635733, tzinfo=UTC))
