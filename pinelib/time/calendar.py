from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from zoneinfo import ZoneInfo

from pinelib.errors import PL_TIMEZONE_INVALID, PineRuntimeError

PINNED_TZDATA_VERSION = "2026.2"


def _verify_tzdata() -> None:
    try:
        installed = version("tzdata")
    except PackageNotFoundError as error:
        raise PineRuntimeError(
            "the pinned tzdata package is not installed",
            code=PL_TIMEZONE_INVALID,
            details={"required": PINNED_TZDATA_VERSION},
        ) from error
    if installed != PINNED_TZDATA_VERSION:
        raise PineRuntimeError(
            "the installed tzdata package does not match the runtime policy",
            code=PL_TIMEZONE_INVALID,
            details={"required": PINNED_TZDATA_VERSION, "installed": installed},
        )


@lru_cache(maxsize=256)
def get_timezone(name: str) -> ZoneInfo:
    if not name or name.startswith("/") or ".." in name.split("/"):
        raise PineRuntimeError("timezone is required", code=PL_TIMEZONE_INVALID)
    _verify_tzdata()
    resource = files("tzdata.zoneinfo").joinpath(*name.split("/"))
    if not resource.is_file():
        raise PineRuntimeError(
            f"unknown IANA timezone: {name}", code=PL_TIMEZONE_INVALID
        )
    try:
        with resource.open("rb") as stream:
            # Loading directly from the exact tzdata wheel avoids host OS
            # timezone-database drift.
            return ZoneInfo.from_file(stream, key=name)
    except (OSError, ValueError) as error:
        raise PineRuntimeError(
            f"invalid IANA timezone resource: {name}", code=PL_TIMEZONE_INVALID
        ) from error


def from_unix_ms(timestamp_ms: int, timezone_name: str) -> datetime:
    if type(timestamp_ms) is not int:
        raise PineRuntimeError("timestamp must be integer milliseconds")
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=UTC).astimezone(
        get_timezone(timezone_name)
    )


def timestamp_ms(
    timezone_name: str,
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> int:
    zone = get_timezone(timezone_name)
    try:
        value = datetime(year, month, day, hour, minute, second, tzinfo=zone)
    except ValueError as error:
        raise PineRuntimeError(f"invalid calendar value: {error}") from error
    return int(value.timestamp() * 1000)


def year(timestamp: int, timezone_name: str) -> int:
    return from_unix_ms(timestamp, timezone_name).year


def month(timestamp: int, timezone_name: str) -> int:
    return from_unix_ms(timestamp, timezone_name).month


def dayofmonth(timestamp: int, timezone_name: str) -> int:
    return from_unix_ms(timestamp, timezone_name).day


def dayofweek(timestamp: int, timezone_name: str) -> int:
    # Pine: Sunday=1 ... Saturday=7; datetime: Monday=0 ... Sunday=6.
    return ((from_unix_ms(timestamp, timezone_name).weekday() + 1) % 7) + 1


def hour(timestamp: int, timezone_name: str) -> int:
    return from_unix_ms(timestamp, timezone_name).hour


def minute(timestamp: int, timezone_name: str) -> int:
    return from_unix_ms(timestamp, timezone_name).minute


def second(timestamp: int, timezone_name: str) -> int:
    return from_unix_ms(timestamp, timezone_name).second
