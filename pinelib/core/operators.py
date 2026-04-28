from __future__ import annotations

from typing import Any

from pinelib.core.na import is_na
from pinelib.errors import PineNAError


def pine_bool(value: Any) -> bool:
    if is_na(value):
        raise PineNAError("Boolean context for na is not allowed")
    return bool(value)


def pine_add(left: Any, right: Any) -> Any:
    if is_na(left) or is_na(right):
        return left if is_na(left) else right
    return left + right


def pine_sub(left: Any, right: Any) -> Any:
    if is_na(left) or is_na(right):
        return left if is_na(left) else right
    return left - right


def pine_mul(left: Any, right: Any) -> Any:
    if is_na(left) or is_na(right):
        return left if is_na(left) else right
    return left * right


def pine_div(left: Any, right: Any) -> Any:
    if is_na(left) or is_na(right):
        return left if is_na(left) else right
    return left / right


def pine_range(start: int, end: int, step: int | None = None) -> range:
    if step is None:
        step = 1 if end >= start else -1
    if step == 0:
        raise ValueError("Pine for-loop step cannot be zero")
    stop = end + (1 if step > 0 else -1)
    return range(int(start), int(stop), int(step))
