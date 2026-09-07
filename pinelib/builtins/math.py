from __future__ import annotations

import math
from collections.abc import Callable
from decimal import Decimal

from pinelib.core.values import is_na, na, require_number
from pinelib.errors import PL_VALUE_DOMAIN, PineRuntimeError


def _unary(
    value: object,
    function: Callable[[float], float],
    *,
    domain: Callable[[float], bool] | None = None,
) -> object:
    if is_na(value):
        return na
    number = require_number(value)
    numeric = float(number)
    if domain is not None and not domain(numeric):
        return na
    try:
        result = function(numeric)
    except (ValueError, OverflowError):
        return na
    if not math.isfinite(float(result)):
        raise PineRuntimeError("math result is non-finite", code=PL_VALUE_DOMAIN)
    return result


def abs_value(value: object) -> object:
    if is_na(value):
        return na
    number = require_number(value)
    return abs(number)


def acos(value: object) -> object:
    return _unary(value, math.acos, domain=lambda item: -1 <= item <= 1)


def asin(value: object) -> object:
    return _unary(value, math.asin, domain=lambda item: -1 <= item <= 1)


def atan(value: object) -> object:
    return _unary(value, math.atan)


def ceil(value: object) -> object:
    return _unary(value, math.ceil)


def cos(value: object) -> object:
    return _unary(value, math.cos)


def exp(value: object) -> object:
    return _unary(value, math.exp)


def floor(value: object) -> object:
    return _unary(value, math.floor)


def log(value: object) -> object:
    return _unary(value, math.log, domain=lambda item: item > 0)


def log10(value: object) -> object:
    return _unary(value, math.log10, domain=lambda item: item > 0)


def sign(value: object) -> object:
    if is_na(value):
        return na
    number = require_number(value)
    return 1 if number > 0 else -1 if number < 0 else 0


def sin(value: object) -> object:
    return _unary(value, math.sin)


def sqrt(value: object) -> object:
    return _unary(value, math.sqrt, domain=lambda item: item >= 0)


def tan(value: object) -> object:
    return _unary(value, math.tan)


def todegrees(value: object) -> object:
    return _unary(value, math.degrees)


def toradians(value: object) -> object:
    return _unary(value, math.radians)


def avg(*values: object) -> object:
    if not values:
        raise PineRuntimeError(
            "math.avg requires at least one value", code=PL_VALUE_DOMAIN
        )
    if any(is_na(value) for value in values):
        return na
    numbers = [float(require_number(value)) for value in values]
    return math.fsum(numbers) / len(numbers)


def maximum(*values: object) -> object:
    if not values:
        raise PineRuntimeError(
            "math.max requires at least one value", code=PL_VALUE_DOMAIN
        )
    if any(is_na(value) for value in values):
        return na
    numbers = [require_number(value) for value in values]
    return max(numbers)


def minimum(*values: object) -> object:
    if not values:
        raise PineRuntimeError(
            "math.min requires at least one value", code=PL_VALUE_DOMAIN
        )
    if any(is_na(value) for value in values):
        return na
    numbers = [require_number(value) for value in values]
    return min(numbers)


def power(base: object, exponent: object) -> object:
    if is_na(base) or is_na(exponent):
        return na
    base_number = float(require_number(base, name="base"))
    exponent_number = float(require_number(exponent, name="exponent"))
    try:
        result = math.pow(base_number, exponent_number)
    except (ValueError, OverflowError):
        return na
    return result if math.isfinite(result) else na


def _round_ratio_up(numerator: int, denominator: int) -> int:
    """Round an exact ratio to the nearest integer; a tie chooses +infinity."""
    integral, remainder = divmod(numerator, denominator)
    return integral + (2 * remainder >= denominator)


def round_value(value: object, precision: object = None) -> object:
    # None is the ABI's omitted argument marker, distinct from Pine's `na`.
    if is_na(value) or is_na(precision):
        return na
    if precision is not None and type(precision) is not int:
        raise PineRuntimeError("round precision must be int", code=PL_VALUE_DOMAIN)
    number = Decimal(str(require_number(value)))
    digits = 0 if precision is None else precision
    exponent = number.as_tuple().exponent
    assert isinstance(exponent, int)  # require_number has rejected infinities/NaN.
    if not number or digits >= -exponent:
        return int(number) if precision is None else float(number)
    # Avoid enormous powers for precision values that cannot affect the result.
    if digits < -number.adjusted() - 1:
        return 0 if precision is None else 0.0
    numerator, denominator = number.as_integer_ratio()
    scale = 10 ** abs(digits)
    if digits >= 0:
        integral = _round_ratio_up(numerator * scale, denominator)
        rounded = integral / scale if precision is not None else integral
    else:
        rounded = _round_ratio_up(numerator, denominator * scale) * scale
    return int(rounded) if precision is None else float(rounded)


def round_to_mintick(value: object, mintick: float) -> object:
    if is_na(value):
        return na
    tick = float(require_number(mintick, name="mintick"))
    if tick <= 0:
        raise PineRuntimeError("mintick must be positive", code=PL_VALUE_DOMAIN)
    numerator, denominator = Decimal(str(require_number(value))).as_integer_ratio()
    tick_numerator, tick_denominator = Decimal(str(tick)).as_integer_ratio()
    units = _round_ratio_up(numerator * tick_denominator, denominator * tick_numerator)
    return units * tick_numerator / tick_denominator


def sum_pair(left: object, right: object) -> object:
    if is_na(left) or is_na(right):
        return na
    return require_number(left, name="left") + require_number(right, name="right")
