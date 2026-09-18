"""Stage 2.9 ABI expected values derived from elementary arithmetic, not runtime dumps."""

from __future__ import annotations

import math

import pytest

from pinelib import is_na, na
from pinelib.builtins import math as pine_math


def test_stage29_abs_sqrt_pow_na_domain():
    assert pine_math.abs_value(-4) == 4
    assert pine_math.abs_value(na) is na or is_na(pine_math.abs_value(na))
    assert pine_math.sqrt(9) == 3
    assert is_na(pine_math.sqrt(-1))
    assert pine_math.power(2, 3) == 8


def test_stage29_round_half_toward_plus_infinity():
    # Documented Stage 2 binding: ties toward +inf. Independent of current dumps.
    assert pine_math.round_value(1.5) == 2
    assert pine_math.round_value(-1.5) == -1


def test_stage29_exp_zero_is_one():
    assert pine_math.exp(0) == pytest.approx(1.0)
    assert pine_math.exp(1) == pytest.approx(math.e)
