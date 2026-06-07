from __future__ import annotations

from typing import Any

from pinelib.core.na import is_na, na


def tostring(value: Any, format: str | None = None) -> Any:
    if is_na(value):
        return "NaN"
    if format is None:
        return str(value)
    if format in ("#.##", "#.00") and isinstance(value, (int, float)):
        return f"{float(value):.2f}"
    return str(value)


def tonumber(value: Any) -> Any:
    if is_na(value):
        return na
    try:
        return float(str(value))
    except ValueError:
        return na


def contains(source: str, str_: str) -> bool:
    return str_ in source


def startswith(source: str, str_: str) -> bool:
    return source.startswith(str_)


def endswith(source: str, str_: str) -> bool:
    return source.endswith(str_)


def lower(source: str) -> str:
    return source.lower()


def upper(source: str) -> str:
    return source.upper()


def length(source: str) -> int:
    return len(source)


def substring(source: str, begin_pos: int, end_pos: int | None = None) -> str:
    return source[begin_pos:end_pos]


def replace(source: str, target: str, replacement: str, occurrence: int | None = None) -> str:
    if occurrence is None:
        return source.replace(target, replacement)
    parts = source.split(target)
    if occurrence < 0 or occurrence >= len(parts) - 1:
        return source
    return target.join(parts[: occurrence + 1]) + replacement + target.join(parts[occurrence + 1 :])


def pos(source: str, substr: str, from_pos: int = 0) -> int | float:
    if is_na(source) or is_na(substr):
        return na
    if not substr:
        if from_pos < 0:
            return 0
        if from_pos > len(source):
            return len(source)
        return from_pos
    idx = source.find(substr, max(0, from_pos))
    if idx == -1:
        return na
    return idx


def repeat(source: str, count: int) -> str:
    if is_na(source) or is_na(count):
        return na
    return source * int(count)


def trim(source: str) -> str:
    if is_na(source):
        return na
    return source.strip()


def format_time(time_ms: int, format: str = "%Y-%m-%dT%H:%M:%S", timezone: str = "UTC") -> str:
    import datetime
    if is_na(time_ms):
        return na
    try:
        dt = datetime.datetime.fromtimestamp(time_ms / 1000, tz=datetime.timezone.utc)
        if timezone != "UTC":
            import zoneinfo
            try:
                tz = zoneinfo.ZoneInfo(timezone)
                dt = dt.astimezone(tz)
            except Exception:
                pass
        return dt.strftime(format)
    except Exception:
        return na


def match(source: str, regex: str) -> str:
    import re
    if is_na(source) or is_na(regex):
        return na
    try:
        m = re.search(regex, source)
        return m.group(0) if m else na
    except Exception:
        return na


__all__ = [
    "tostring",
    "tonumber",
    "contains",
    "startswith",
    "endswith",
    "lower",
    "upper",
    "length",
    "substring",
    "replace",
    "pos",
    "repeat",
    "trim",
    "format_time",
    "match",
]
