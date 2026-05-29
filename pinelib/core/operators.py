from __future__ import annotations

from typing import Any

from pinelib.core.na import is_na, na
from pinelib.errors import PineNAError


def pine_bool(value: Any) -> bool:
    # Fast path: pointer comparison for na singleton (O(1))
    if value is na:
        raise PineNAError("Boolean context for na is not allowed")
    # type() is faster than isinstance for exact type match
    t = type(value)
    if t is bool:
        return value
    if t is int:
        return bool(value)
    if t is float:
        # NaN floats are NOT na — they are valid True values in Pine
        return bool(value)
    if value is None:
        raise PineNAError("Boolean context for na is not allowed")
    # Series objects, etc. — use default bool conversion
    return bool(value)


def pine_int(value: Any) -> int | type(na):
    if value is na or value is None:
        return na
    return int(value)


def pine_float(value: Any) -> float | type(na):
    if value is na or value is None:
        return na
    return float(value)


def pine_str(value: Any) -> str | type(na):
    if value is na or value is None:
        return na
    return str(value)


def pine_add(left: Any, right: Any) -> Any:
    if left is na or left is None:
        return left
    if right is na or right is None:
        return right
    return left + right


def pine_sub(left: Any, right: Any) -> Any:
    if left is na or left is None:
        return left
    if right is na or right is None:
        return right
    return left - right


def pine_mul(left: Any, right: Any) -> Any:
    if left is na or left is None:
        return left
    if right is na or right is None:
        return right
    return left * right


def pine_div(left: Any, right: Any) -> Any:
    if left is na or left is None:
        return left
    if right is na or right is None:
        return right
    return left / right


def pine_range(start: int, end: int, step: int | None = None) -> range:
    if step is None:
        step = 1 if end >= start else -1
    if step == 0:
        raise ValueError("Pine for-loop step cannot be zero")
    stop = end + (1 if step > 0 else -1)
    return range(int(start), int(stop), int(step))
