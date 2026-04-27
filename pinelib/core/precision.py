from __future__ import annotations

from typing import Any

from pinelib.core.na import is_na

DEFAULT_EPSILON = 1e-10


def pine_isclose(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    return abs(float(left) - float(right)) <= epsilon


def pine_eq(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    return pine_isclose(left, right, epsilon=epsilon)


def pine_ne(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    return not pine_isclose(left, right, epsilon=epsilon)


def pine_gt(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    return float(left) > float(right) + epsilon


def pine_gte(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    return float(left) >= float(right) - epsilon


def pine_lt(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    return float(left) < float(right) - epsilon


def pine_lte(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    return float(left) <= float(right) + epsilon
