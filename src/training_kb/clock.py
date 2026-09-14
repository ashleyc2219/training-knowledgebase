from datetime import UTC, date, datetime

from training_kb.errors import PermanentError


def now_utc() -> datetime:
    """現在的 UTC 時間；先去掉微秒，全套時間字串只有整秒一種形狀。"""
    return datetime.now(UTC).replace(microsecond=0)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("datetime must include timezone")
    return dt.astimezone(UTC)


def to_iso(dt: datetime) -> str:
    value = _aware(dt)
    if value.microsecond:
        raise PermanentError(f"datetime must be whole seconds: {value.isoformat()}")
    return value.isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    # Python 3.11 起 fromisoformat 直接支援結尾的 Z，不需要先做字串置換。
    return _aware(datetime.fromisoformat(value))


def utc_date(dt: datetime) -> date:
    return _aware(dt).date()
