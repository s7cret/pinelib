import pytest

from pinelib import (
    PineTypeError,
    is_na,
    na,
    pine_abs,
    pine_eq,
    pine_gt,
    pine_isclose,
    pine_lt,
    pine_max,
    pine_min,
    pine_round,
    pine_sum,
)


def test_math_aliases_propagate_na_and_reject_bool() -> None:
    assert pine_abs(-3) == 3
    assert pine_round(1.234, 2) == 1.23
    assert pine_min(3, 2, 5) == 2
    assert pine_max(3, 2, 5) == 5
    assert pine_sum([1, na, 2]) == 3.0
    assert is_na(pine_sum([na]))
    assert pine_abs(na) is na
    with pytest.raises(PineTypeError):
        pine_min(1, True)


def test_pine_round_ties_round_up() -> None:
    assert pine_round(81095.25, 1) == 81095.3
    assert pine_round(2.5) == 3


def test_precision_compare_helpers_are_na_safe() -> None:
    assert pine_isclose(1.0, 1.0 + 1e-11)
    assert pine_eq(1.0, 1.0 + 1e-11)
    assert pine_gt(2.0, 1.0)
    assert pine_lt(1.0, 2.0)
    assert not pine_eq(na, na)
    assert not pine_gt(na, 1.0)
