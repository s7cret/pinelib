import pytest

from pinelib import PineNAError, na, pine_add, pine_bool, pine_div, pine_mul, pine_range, pine_sub


def test_pine_range_is_inclusive_in_both_directions() -> None:
    assert list(pine_range(1, 3)) == [1, 2, 3]
    assert list(pine_range(3, 1)) == [3, 2, 1]
    assert list(pine_range(1, 5, 2)) == [1, 3, 5]


def test_pine_range_rejects_zero_step() -> None:
    with pytest.raises(ValueError):
        pine_range(1, 2, 0)


def test_basic_numeric_helpers_propagate_na() -> None:
    assert pine_add(2, 3) == 5
    assert pine_sub(5, 2) == 3
    assert pine_mul(2, 4) == 8
    assert pine_div(8, 2) == 4
    assert pine_add(na, 1) is na


def test_pine_bool_rejects_na() -> None:
    with pytest.raises(PineNAError):
        pine_bool(na)

