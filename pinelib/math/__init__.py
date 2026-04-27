from __future__ import annotations

import builtins
from collections.abc import Iterable
from typing import Any

from pinelib.core.na import is_na, na
from pinelib.errors import PineTypeError


def _reject_bool(value: Any, name: str) -> None:
    if isinstance(value, bool):
        raise PineTypeError(f"math.{name}() does not accept bool arguments in Pine v6")


def pine_abs(value: Any) -> Any:
    _reject_bool(value, "abs")
    return na if is_na(value) else abs(value)


def pine_round(value: Any, precision: int | None = None) -> Any:
    _reject_bool(value, "round")
    if is_na(value):
        return na
    return round(value) if precision is None else round(value, precision)


def pine_min(*values: Any) -> Any:
    if not values:
        raise ValueError("math.min() requires at least one argument")
    for value in values:
        _reject_bool(value, "min")
        if is_na(value):
            return na
    return builtins.min(values)


def pine_max(*values: Any) -> Any:
    if not values:
        raise ValueError("math.max() requires at least one argument")
    for value in values:
        _reject_bool(value, "max")
        if is_na(value):
            return na
    return builtins.max(values)


def pine_sum(values: Iterable[Any]) -> Any:
    total = 0.0
    saw_value = False
    for value in values:
        _reject_bool(value, "sum")
        if is_na(value):
            continue
        total += float(value)
        saw_value = True
    return total if saw_value else na


__all__ = ["pine_abs", "pine_round", "pine_min", "pine_max", "pine_sum"]
