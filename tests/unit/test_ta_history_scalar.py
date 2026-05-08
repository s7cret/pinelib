"""Unit tests for _history() scalar constant preservation fix.

Regression tests for the bug where ta.crossover(series, scalar) and
ta.crossunder(series, scalar) always returned False because _history()
returned na for scalar constants at offset > 0.

Fix: scalar constants (e.g. 50) don't change between bars, so
_history(source=scalar, offset>0) must return the scalar value itself,
not na.

Ref: pine-strategy-parity skill, bug #10.
"""

from __future__ import annotations

from pinelib import PineRuntime, SymbolInfo, TimeframeInfo, Bar, ta


def _runtime() -> PineRuntime:
    return PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
        timeframe=TimeframeInfo.from_string("60"),
    )


def _bar(index: int, close: float) -> Bar:
    return Bar(
        time=1_700_000_000_000 + index * 3_600_000,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
    )


# ---------------------------------------------------------------------------
# _history scalar preservation
# ---------------------------------------------------------------------------

def test_history_scalar_nonzero_offset_returns_scalar() -> None:
    """_history(50, 1) must return 50, not na."""
    from pinelib.ta import _history
    result = _history(50, 1, "test")
    assert result == 50, f"Expected 50, got {result!r}"


def test_history_scalar_zero_offset_returns_scalar() -> None:
    """_history(50, 0) must return 50."""
    from pinelib.ta import _history
    result = _history(50, 0, "test")
    assert result == 50


def test_history_zero_scalar_offset_one() -> None:
    """_history(0, 1) must return 0, not na."""
    from pinelib.ta import _history
    result = _history(0, 1, "test")
    assert result == 0, f"Expected 0, got {result!r}"


def test_history_negative_scalar_offset() -> None:
    """_history(-99, 1) must return -99."""
    from pinelib.ta import _history
    result = _history(-99, 1, "test")
    assert result == -99, f"Expected -99, got {result!r}"


# ---------------------------------------------------------------------------
# crossover/crossunder with scalar threshold (series vs scalar)
# ---------------------------------------------------------------------------

def test_crossover_series_crosses_above_scalar() -> None:
    """crossover([49, 51], 50) -> True at bar 1.

    Before fix: _history(50, 1) returned na → previous_right=na →
    na <= 50 = False → crossover never fired.
    After fix: _history(50, 1) = 50 → 49 <= 50 = True, 51 > 50 = True → True.
    """
    runtime = _runtime()
    s = runtime.series("close", "float")

    runtime.begin_bar(_bar(0, 49.0))
    s.set_current(49.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 51.0))
    s.set_current(51.0)
    result = ta.crossover(s, 50)
    runtime.end_bar()

    assert result is True, f"Expected True, got {result!r}"


def test_crossunder_series_crosses_below_scalar() -> None:
    """crossunder([51, 49], 50) -> True at bar 1."""
    runtime = _runtime()
    s = runtime.series("close", "float")

    runtime.begin_bar(_bar(0, 51.0))
    s.set_current(51.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 49.0))
    s.set_current(49.0)
    result = ta.crossunder(s, 50)
    runtime.end_bar()

    assert result is True, f"Expected True, got {result!r}"


def test_crossunder_1_to_neg1_crosses_zero() -> None:
    """crossunder([1, -1], 0) -> True at bar 1 (1 crosses below 0)."""
    runtime = _runtime()
    s = runtime.series("close", "float")

    runtime.begin_bar(_bar(0, 1.0))
    s.set_current(1.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, -1.0))
    s.set_current(-1.0)
    result = ta.crossunder(s, 0)
    runtime.end_bar()

    assert result is True, f"Expected True, got {result!r}"


def test_crossover_neg1_to_pos1_crosses_zero() -> None:
    """crossover([-1, 1], 0) -> True at bar 1 (-1 crosses above 0)."""
    runtime = _runtime()
    s = runtime.series("close", "float")

    runtime.begin_bar(_bar(0, -1.0))
    s.set_current(-1.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 1.0))
    s.set_current(1.0)
    result = ta.crossover(s, 0)
    runtime.end_bar()

    assert result is True, f"Expected True, got {result!r}"


def test_crossover_scalar_exact_boundary_no_cross() -> None:
    """crossover([49.9, 50.0], 50) -> False (50 is NOT strictly > 50)."""
    runtime = _runtime()
    s = runtime.series("close", "float")

    runtime.begin_bar(_bar(0, 49.9))
    s.set_current(49.9)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 50.0))
    s.set_current(50.0)
    result = ta.crossover(s, 50)
    runtime.end_bar()

    assert result is False  # 50 is not strictly > 50


def test_crossunder_scalar_exact_boundary_no_cross() -> None:
    """crossunder([50.1, 50.0], 50) -> False (50 is NOT strictly < 50)."""
    runtime = _runtime()
    s = runtime.series("close", "float")

    runtime.begin_bar(_bar(0, 50.1))
    s.set_current(50.1)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 50.0))
    s.set_current(50.0)
    result = ta.crossunder(s, 50)
    runtime.end_bar()

    assert result is False  # 50 is not strictly < 50


# ---------------------------------------------------------------------------
# series-vs-series crossover still works (no regression)
# ---------------------------------------------------------------------------

def test_crossover_series_vs_series_still_works() -> None:
    """crossover between two series must still work after the scalar fix."""
    runtime = _runtime()
    a = runtime.series("a", "float")
    b = runtime.series("b", "float")

    runtime.begin_bar(_bar(0, 0.0))
    a.set_current(9.0)
    b.set_current(10.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 0.0))
    a.set_current(11.0)
    b.set_current(10.0)
    result = ta.crossover(a, b)
    runtime.end_bar()

    assert result is True, f"Expected True (11 > 10), got {result!r}"


def test_crossunder_series_vs_series_still_works() -> None:
    """crossunder between two series must still work after the scalar fix."""
    runtime = _runtime()
    c = runtime.series("c", "float")
    d = runtime.series("d", "float")

    runtime.begin_bar(_bar(0, 0.0))
    c.set_current(51.0)
    d.set_current(50.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 0.0))
    c.set_current(49.0)
    d.set_current(50.0)
    result = ta.crossunder(c, d)
    runtime.end_bar()

    assert result is True, f"Expected True (49 < 50), got {result!r}"


def test_history_series_at_offset_still_works() -> None:
    """For a real series, _history at offset>0 must still return previous bar value."""
    from pinelib.ta import _history
    runtime = _runtime()
    s = runtime.series("close", "float")

    runtime.begin_bar(_bar(0, 10.0))
    s.set_current(10.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 20.0))
    s.set_current(20.0)
    # At bar 1: _history(s, 0) = current = 20, _history(s, 1) = previous = 10
    current = _history(s, 0, "test")
    previous = _history(s, 1, "test")
    runtime.end_bar()

    assert current == 20.0, f"Expected current=20.0, got {current!r}"
    assert previous == 10.0, f"Expected previous=10.0, got {previous!r}"
