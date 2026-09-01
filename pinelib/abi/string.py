from __future__ import annotations

from pinelib.builtins import string as _string
from pinelib.reference import ReferenceHandle, array_new, array_push
from pinelib.runtime.session import RuntimeTransaction


def contains_v1(source: str, substring: str) -> bool:
    return _string.contains(source, substring)


def startswith_v1(source: str, prefix: str) -> bool:
    return _string.startswith(source, prefix)


def endswith_v1(source: str, suffix: str) -> bool:
    return _string.endswith(source, suffix)


def length_v1(source: str) -> int:
    return _string.length(source)


def lower_v1(source: str) -> str:
    return _string.lower(source)


def upper_v1(source: str) -> str:
    return _string.upper(source)


def trim_v1(source: str) -> str:
    return _string.trim(source)


def pos_v1(source: str, substring: str) -> int:
    return _string.pos(source, substring)


def substring_v1(source: str, begin: int, end: int | None = None) -> str:
    return _string.substring(source, begin, end)


def replace_v1(source: str, target: str, replacement: str, occurrence: int = 0) -> str:
    return _string.replace(source, target, replacement, occurrence)


def replace_all_v1(source: str, target: str, replacement: str) -> str:
    return _string.replace_all(source, target, replacement)


def split_v1(
    tx: RuntimeTransaction,
    object_id: str,
    source: str,
    separator: str,
) -> ReferenceHandle:
    handle = array_new(tx.references, object_id, "array<string>")
    for value in _string.split(source, separator):
        array_push(tx.references, handle, value)
    return handle


def tonumber_v1(source: str) -> object:
    return _string.tonumber(source)


def tostring_v1(
    value: object, pattern: str | None = None, mintick: float | None = None
) -> str:
    return _string.tostring(value, pattern, mintick=mintick)


def format_v1(
    template: str,
    *arguments: object,
    timezone_name: str = "UTC",
    mintick: float | None = None,
) -> str:
    return _string.format_template(
        template, *arguments, timezone_name=timezone_name, mintick=mintick
    )


def format_time_v1(timestamp_ms: int, pattern: str, timezone_name: str) -> str:
    return _string.format_time(timestamp_ms, pattern, timezone_name)
