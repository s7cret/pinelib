from __future__ import annotations

import builtins
import math as _math
from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from pinelib.core.na import is_na, na
from pinelib.errors import PineTypeError

pi = _math.pi
e = _math.e
phi = (1 + 5**0.5) / 2


def _reject_bool(value: Any, name: str) -> None:
    if isinstance(value, bool):
        raise PineTypeError(f"math.{name}() does not accept bool arguments in Pine v6")


def _unary(value: Any, name: str, fn: Any) -> Any:
    _reject_bool(value, name)
    return na if is_na(value) else fn(value)


def pine_abs(value: Any) -> Any:
    return _unary(value, "abs", builtins.abs)


def abs(value: Any) -> Any:
    return pine_abs(value)


def sign(value: Any) -> Any:
    return _unary(value, "sign", lambda x: 1 if x > 0 else -1 if x < 0 else 0)


def sqrt(value: Any) -> Any:
    return _unary(value, "sqrt", _math.sqrt)


def pow(base: Any, exponent: Any) -> Any:
    _reject_bool(base, "pow")
    _reject_bool(exponent, "pow")
    return na if is_na(base) or is_na(exponent) else _math.pow(base, exponent)


def exp(value: Any) -> Any:
    return _unary(value, "exp", _math.exp)


def log(value: Any) -> Any:
    return _unary(value, "log", _math.log)


def log10(value: Any) -> Any:
    return _unary(value, "log10", _math.log10)


def sin(value: Any) -> Any:
    return _unary(value, "sin", _math.sin)


def cos(value: Any) -> Any:
    return _unary(value, "cos", _math.cos)


def tan(value: Any) -> Any:
    return _unary(value, "tan", _math.tan)


def asin(value: Any) -> Any:
    return _unary(value, "asin", _math.asin)


def acos(value: Any) -> Any:
    return _unary(value, "acos", _math.acos)


def atan(value: Any) -> Any:
    return _unary(value, "atan", _math.atan)


def todegrees(value: Any) -> Any:
    return _unary(value, "todegrees", _math.degrees)


def toradians(value: Any) -> Any:
    return _unary(value, "toradians", _math.radians)


def ceil(value: Any) -> Any:
    return _unary(value, "ceil", _math.ceil)


def floor(value: Any) -> Any:
    return _unary(value, "floor", _math.floor)


def trunc(value: Any) -> Any:
    return _unary(value, "trunc", _math.trunc)


def pine_round(value: Any, precision: int | None = None) -> Any:
    _reject_bool(value, "round")
    if is_na(value):
        return na
    quant = Decimal("1") if precision is None else Decimal("1").scaleb(-precision)
    rounded = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    if precision is None:
        return int(rounded)
    return float(rounded)


def round(value: Any, precision: int | None = None) -> Any:
    return pine_round(value, precision)


def pine_min(*values: Any) -> Any:
    if not values:
        raise ValueError("math.min() requires at least one argument")
    for value in values:
        _reject_bool(value, "min")
        if is_na(value):
            return na
    return builtins.min(values)


def min(*values: Any) -> Any:
    return pine_min(*values)


def pine_max(*values: Any) -> Any:
    if not values:
        raise ValueError("math.max() requires at least one argument")
    for value in values:
        _reject_bool(value, "max")
        if is_na(value):
            return na
    return builtins.max(values)


def max(*values: Any) -> Any:
    return pine_max(*values)


def avg(*values: Any) -> Any:
    if not values:
        raise ValueError("math.avg() requires at least one argument")
    for value in values:
        _reject_bool(value, "avg")
        if is_na(value):
            return na
    return builtins.sum(float(v) for v in values) / len(values)


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


def sum(values: Iterable[Any]) -> Any:
    return pine_sum(values)


def random(min: float = 0.0, max: float = 1.0, seed: int | None = None) -> float:
    import random as _random

    rng = _random.Random(seed) if seed is not None else _random
    return rng.uniform(min, max)


__all__ = [
    "pi",
    "e",
    "phi",
    "pine_abs",
    "pine_round",
    "pine_min",
    "pine_max",
    "pine_sum",
    "abs",
    "sign",
    "sqrt",
    "pow",
    "exp",
    "log",
    "log10",
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "todegrees",
    "toradians",
    "ceil",
    "floor",
    "trunc",
    "round",
    "min",
    "max",
    "avg",
    "sum",
    "random",
]
