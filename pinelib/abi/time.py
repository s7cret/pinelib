from __future__ import annotations

from pinelib.runtime.context import RuntimeLanguageContext
from pinelib.time import calendar as _calendar
from pinelib.time import parse_session


def timestamp_v1(
    timezone_name: str,
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> int:
    return _calendar.timestamp_ms(timezone_name, year, month, day, hour, minute, second)


def year_v1(timestamp_ms: int, timezone_name: str) -> int:
    return _calendar.year(timestamp_ms, timezone_name)


def month_v1(timestamp_ms: int, timezone_name: str) -> int:
    return _calendar.month(timestamp_ms, timezone_name)


def dayofmonth_v1(timestamp_ms: int, timezone_name: str) -> int:
    return _calendar.dayofmonth(timestamp_ms, timezone_name)


def dayofweek_v1(timestamp_ms: int, timezone_name: str) -> int:
    return _calendar.dayofweek(timestamp_ms, timezone_name)


def hour_v1(timestamp_ms: int, timezone_name: str) -> int:
    return _calendar.hour(timestamp_ms, timezone_name)


def minute_v1(timestamp_ms: int, timezone_name: str) -> int:
    return _calendar.minute(timestamp_ms, timezone_name)


def second_v1(timestamp_ms: int, timezone_name: str) -> int:
    return _calendar.second(timestamp_ms, timezone_name)


def in_session_v1(
    timestamp_ms: int,
    session: str,
    timezone_name: str,
    language: RuntimeLanguageContext,
) -> bool:
    return parse_session(session, language).contains(timestamp_ms, timezone_name)
