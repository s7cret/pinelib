from __future__ import annotations

from pinelib.builtins import math as _math


def abs_v1(value: object) -> object:
    return _math.abs_value(value)


def acos_v1(value: object) -> object:
    return _math.acos(value)


def asin_v1(value: object) -> object:
    return _math.asin(value)


def atan_v1(value: object) -> object:
    return _math.atan(value)


def avg_v1(*values: object) -> object:
    return _math.avg(*values)


def ceil_v1(value: object) -> object:
    return _math.ceil(value)


def cos_v1(value: object) -> object:
    return _math.cos(value)


def exp_v1(value: object) -> object:
    return _math.exp(value)


def floor_v1(value: object) -> object:
    return _math.floor(value)


def log_v1(value: object) -> object:
    return _math.log(value)


def log10_v1(value: object) -> object:
    return _math.log10(value)


def max_v1(*values: object) -> object:
    return _math.maximum(*values)


def min_v1(*values: object) -> object:
    return _math.minimum(*values)


def pow_v1(base: object, exponent: object) -> object:
    return _math.power(base, exponent)


def round_v1(value: object, precision: int = 0) -> object:
    return _math.round_value(value, precision)


def round_to_mintick_v1(value: object, mintick: float) -> object:
    return _math.round_to_mintick(value, mintick)


def sign_v1(value: object) -> object:
    return _math.sign(value)


def sin_v1(value: object) -> object:
    return _math.sin(value)


def sqrt_v1(value: object) -> object:
    return _math.sqrt(value)


def sum_v1(left: object, right: object) -> object:
    return _math.sum_pair(left, right)


def tan_v1(value: object) -> object:
    return _math.tan(value)


def todegrees_v1(value: object) -> object:
    return _math.todegrees(value)


def toradians_v1(value: object) -> object:
    return _math.toradians(value)
