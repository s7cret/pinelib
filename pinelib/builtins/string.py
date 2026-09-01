from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

from pinelib.core.values import is_na, na, require_number
from pinelib.errors import PL_STRING_FORMAT, PL_VALUE_TYPE, PineRuntimeError
from pinelib.time.calendar import from_unix_ms

_PLACEHOLDER_RE = re.compile(
    r"\{(?P<index>[0-9]+)(?:,(?P<kind>number|date),(?P<pattern>[^{}]+))?\}"
)


def contains(source: str, substring: str) -> bool:
    return _string(source, "source").find(_string(substring, "substring")) >= 0


def startswith(source: str, prefix: str) -> bool:
    return _string(source, "source").startswith(_string(prefix, "prefix"))


def endswith(source: str, suffix: str) -> bool:
    return _string(source, "source").endswith(_string(suffix, "suffix"))


def length(source: str) -> int:
    return len(_string(source, "source"))


def lower(source: str) -> str:
    return _string(source, "source").lower()


def upper(source: str) -> str:
    return _string(source, "source").upper()


def trim(source: str) -> str:
    return _string(source, "source").strip()


def pos(source: str, substring: str) -> int:
    return _string(source, "source").find(_string(substring, "substring"))


def substring(source: str, begin: int, end: int | None = None) -> str:
    text = _string(source, "source")
    if type(begin) is not int or (end is not None and type(end) is not int):
        raise PineRuntimeError("substring bounds must be ints", code=PL_VALUE_TYPE)
    effective_end = len(text) if end is None else end
    if begin < 0 or effective_end < begin or effective_end > len(text):
        raise PineRuntimeError("substring bounds are invalid", code=PL_VALUE_TYPE)
    return text[begin:effective_end]


def replace(source: str, target: str, replacement: str, occurrence: int = 0) -> str:
    text = _string(source, "source")
    needle = _string(target, "target")
    new_value = _string(replacement, "replacement")
    if type(occurrence) is not int or occurrence < 0:
        raise PineRuntimeError("replace occurrence must be nonnegative int")
    if needle == "":
        return text
    start = 0
    found = -1
    for _ in range(occurrence + 1):
        found = text.find(needle, start)
        if found < 0:
            return text
        start = found + len(needle)
    return text[:found] + new_value + text[found + len(needle) :]


def replace_all(source: str, target: str, replacement: str) -> str:
    text = _string(source, "source")
    needle = _string(target, "target")
    return (
        text
        if needle == ""
        else text.replace(needle, _string(replacement, "replacement"))
    )


def split(source: str, separator: str) -> tuple[str, ...]:
    text = _string(source, "source")
    delimiter = _string(separator, "separator")
    if delimiter == "":
        return tuple(text)
    return tuple(text.split(delimiter))


def tonumber(source: str) -> object:
    text = _string(source, "source").strip()
    if not text:
        return na
    try:
        value = float(text)
    except ValueError:
        return na
    if value == float("inf") or value == float("-inf") or math.isnan(value):
        return na
    return value


def tostring(
    value: object, pattern: str | None = None, *, mintick: float | None = None
) -> str:
    if is_na(value):
        return "NaN"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return (
            str(value)
            if pattern is None
            else _format_number(float(value), pattern, mintick)
        )
    if type(value) is float:
        if pattern is None:
            return repr(value)
        return _format_number(value, pattern, mintick)
    if isinstance(value, str):
        return value
    raise PineRuntimeError(
        "str.tostring received unsupported value type", code=PL_VALUE_TYPE
    )


def format_template(
    template: str,
    *arguments: object,
    timezone_name: str = "UTC",
    mintick: float | None = None,
) -> str:
    source = _string(template, "template")
    sentinel_open = "\u0000OPEN\u0000"
    sentinel_close = "\u0000CLOSE\u0000"
    protected = source.replace("{{", sentinel_open).replace("}}", sentinel_close)

    def render(match: re.Match[str]) -> str:
        index = int(match.group("index"))
        if index >= len(arguments):
            raise PineRuntimeError(
                "str.format argument index is out of range", code=PL_STRING_FORMAT
            )
        value = arguments[index]
        kind = match.group("kind")
        pattern = match.group("pattern")
        if kind is None:
            return tostring(value, mintick=mintick)
        if kind == "number":
            return tostring(value, pattern, mintick=mintick)
        if kind == "date":
            if type(value) is not int:
                raise PineRuntimeError(
                    "date placeholder requires integer timestamp", code=PL_STRING_FORMAT
                )
            return format_time(value, pattern or "yyyy-MM-dd HH:mm:ss", timezone_name)
        raise PineRuntimeError(
            "unsupported str.format placeholder", code=PL_STRING_FORMAT
        )

    result = _PLACEHOLDER_RE.sub(render, protected)
    if "{" in result or "}" in result:
        raise PineRuntimeError("malformed str.format template", code=PL_STRING_FORMAT)
    return result.replace(sentinel_open, "{").replace(sentinel_close, "}")


def format_time(timestamp_ms: int, pattern: str, timezone_name: str) -> str:
    if type(timestamp_ms) is not int:
        raise PineRuntimeError("format_time timestamp must be int", code=PL_VALUE_TYPE)
    value = from_unix_ms(timestamp_ms, timezone_name)
    tokens = (
        ("yyyy", f"{value.year:04d}"),
        ("MMM", value.strftime("%b")),
        ("MM", f"{value.month:02d}"),
        ("dd", f"{value.day:02d}"),
        ("EEE", value.strftime("%a")),
        ("HH", f"{value.hour:02d}"),
        ("mm", f"{value.minute:02d}"),
        ("ss", f"{value.second:02d}"),
    )
    result = _string(pattern, "pattern")
    for token, replacement in tokens:
        result = result.replace(token, replacement)
    return result


def _format_number(value: float, pattern: str, mintick: float | None) -> str:
    normalized = pattern.strip()
    if normalized in {"mintick", "format.mintick"}:
        if mintick is None:
            raise PineRuntimeError(
                "mintick format requires instrument mintick", code=PL_STRING_FORMAT
            )
        tick = float(require_number(mintick, name="mintick"))
        if tick <= 0:
            raise PineRuntimeError("mintick must be positive", code=PL_STRING_FORMAT)
        exponent = Decimal(str(tick)).as_tuple().exponent
        if not isinstance(exponent, int):
            raise PineRuntimeError("mintick must be finite", code=PL_STRING_FORMAT)
        decimals = max(0, -exponent)
        units = (Decimal(str(value)) / Decimal(str(tick))).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
        rounded = units * Decimal(str(tick))
        return f"{rounded:.{decimals}f}"
    percent = normalized.endswith("%")
    if percent:
        normalized = normalized[:-1]
        value *= 100.0
    scientific = "E" in normalized or "e" in normalized
    if scientific:
        decimal_part = normalized.split("E", 1)[0].split("e", 1)[0]
        digits = len(decimal_part.split(".", 1)[1]) if "." in decimal_part else 0
        text = f"{value:.{digits}E}"
        return text + ("%" if percent else "")
    integer_pattern, _, fraction_pattern = normalized.partition(".")
    if any(character not in "0#," for character in integer_pattern) or any(
        character not in "0#" for character in fraction_pattern
    ):
        raise PineRuntimeError(
            f"unsupported number format pattern: {pattern}", code=PL_STRING_FORMAT
        )
    maximum_digits = len(fraction_pattern)
    minimum_digits = fraction_pattern.count("0")
    grouping = "," in integer_pattern
    quantum = Decimal(1).scaleb(-maximum_digits)
    rounded = (
        Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
        if maximum_digits
        else Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
    text = (
        f"{rounded:,.{maximum_digits}f}"
        if grouping
        else f"{rounded:.{maximum_digits}f}"
    )
    if maximum_digits > minimum_digits and "." in text:
        whole, fraction = text.split(".", 1)
        fraction = fraction.rstrip("0")
        if len(fraction) < minimum_digits:
            fraction += "0" * (minimum_digits - len(fraction))
        text = whole if not fraction else whole + "." + fraction
    return text + ("%" if percent else "")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise PineRuntimeError(f"{name} must be string", code=PL_VALUE_TYPE)
    return value
