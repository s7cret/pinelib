from __future__ import annotations

from typing import Any

from pinelib.core.na import is_na

DEFAULT_EPSILON = 1e-10


def _to_scalar(value: Any) -> Any:
    """Extract scalar value from Series (or other wrapped objects)."""
    return getattr(value, "_current", value)


def pine_isclose(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    l = _to_scalar(left)
    r = _to_scalar(right)
    return abs(float(l) - float(r)) <= epsilon


def pine_eq(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    return pine_isclose(left, right, epsilon=epsilon)


def pine_ne(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    return not pine_isclose(left, right, epsilon=epsilon)


def pine_gt(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    l = _to_scalar(left)
    r = _to_scalar(right)
    return float(l) > float(r) + epsilon


def pine_gte(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    l = _to_scalar(left)
    r = _to_scalar(right)
    return float(l) >= float(r) - epsilon


def pine_lt(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    l = _to_scalar(left)
    r = _to_scalar(right)
    return float(l) < float(r) - epsilon


def pine_lte(left: Any, right: Any, *, epsilon: float = DEFAULT_EPSILON) -> bool:
    if is_na(left) or is_na(right):
        return False
    l = _to_scalar(left)
    r = _to_scalar(right)
    return float(l) <= float(r) + epsilon
