from __future__ import annotations

from pinelib import Bar, PineRuntime, SymbolInfo, TimeframeInfo, ta
from pinelib.ta import _history, shifted_series


def _runtime() -> PineRuntime:
    return PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
        timeframe=TimeframeInfo.from_string("60"),
    )


def _bar(index: int, high: float, low: float, close: float) -> Bar:
    return Bar(
        time=1_700_000_000_000 + index * 3_600_000,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1_000.0,
    )


def test_history_preserves_scalar_constants():
    assert _history(50, 1, "test") == 50
    assert _history(0, 1, "test") == 0


def test_crossover_with_scalar_threshold():
    runtime = _runtime()
    close = runtime.series("close", "float")

    runtime.begin_bar(_bar(0, 55, 45, 49))
    close.set_current(49.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 55, 45, 51))
    close.set_current(51.0)
    assert ta.crossover(close, 50) is True
    runtime.end_bar()


def test_crossunder_with_scalar_threshold():
    runtime = _runtime()
    close = runtime.series("close", "float")

    runtime.begin_bar(_bar(0, 55, 45, 51))
    close.set_current(51.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 55, 45, 49))
    close.set_current(49.0)
    assert ta.crossunder(close, 50) is True
    runtime.end_bar()


def test_crossover_shifted_series_wrong_case_is_false():
    """
    Regression: ta.crossover(src, shifted_rhs) must NOT fire when
    src caught up to rhs but was never strictly below it from the previous bar.

    Bug scenario (bar 29 from strict Donchian proof):
      src_prev = 80075.99 = shifted_rhs_now  (src caught up to rhs)
      shifted_rhs_prev = 79956.43              (rhs was lower at previous bar)
      80075.99 <= 79956.43 = False -> no crossover

    At bar 3: close[2]=125, close[1]=105, base[1]=110, base[2]=100
    shifted_base[0]=base[1]=110, shifted_base[1]=base[2]=100
    close[1]=105 > shifted_base[1]=100 (close was already above prev rhs)
    crossover: 125>110 AND 105<=100 = True AND False = False
    """
    runtime = _runtime()
    close = runtime.series("close", "float")
    base = runtime.series("base", "float")

    # Bar 0
    runtime.begin_bar(_bar(0, 105, 95, 100))
    close.set_current(100.0)
    base.set_current(100.0)
    runtime.end_bar()

    # Bar 1: close=105, base=110
    runtime.begin_bar(_bar(1, 115, 100, 105))
    close.set_current(105.0)
    base.set_current(110.0)
    runtime.end_bar()

    # Bar 2: close=125, base=120
    runtime.begin_bar(_bar(2, 130, 120, 125))
    close.set_current(125.0)
    base.set_current(120.0)
    runtime.end_bar()

    # Bar 3: begin_bar to advance bar_index to 3, then evaluate crossover
    runtime.begin_bar(_bar(3, 140, 130, 135))
    close.set_current(135.0)
    base.set_current(130.0)
    # At bar_index=3: close[2]=125, close[1]=105, base[1]=110, base[2]=100
    # shifted_base[0]=110, shifted_base[1]=100
    # close[1]=105 > shifted_base[1]=100 -> close was already above prev rhs
    result = ta.crossover(close, shifted_series(base, 1))
    assert result is False
    runtime.end_bar()


def test_crossover_shifted_series_positive_case_is_true():
    """Crossover fires when close crosses above shifted base."""
    runtime = _runtime()
    close = runtime.series("close", "float")
    base = runtime.series("base", "float")

    runtime.begin_bar(_bar(0, 105, 95, 100))
    close.set_current(100.0)
    base.set_current(100.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 115, 90, 95))
    close.set_current(95.0)
    base.set_current(110.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(2, 130, 115, 125))
    close.set_current(125.0)
    base.set_current(120.0)
    # At bar 2: close[0]=125, close[1]=95, shifted_base[0]=base[1]=110
    # close[1] <= shifted_base[1] = 95 <= 100 = True -> crossover fires
    assert ta.crossover(close, shifted_series(base, 1)) is True
    runtime.end_bar()


def test_crossunder_shifted_series_uses_previous_shifted_rhs():
    """crossunder fires when close crosses below shifted base."""
    runtime = _runtime()
    close = runtime.series("close", "float")
    base = runtime.series("base", "float")

    runtime.begin_bar(_bar(0, 130, 115, 120))
    close.set_current(120.0)
    base.set_current(120.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 135, 100, 130))
    close.set_current(130.0)
    base.set_current(110.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(2, 105, 90, 95))
    close.set_current(95.0)
    base.set_current(100.0)
    # close[1]=130 > shifted_base[1]=100 (close was above prev bar's rhs)
    # close[0]=95 < shifted_base[0]=110 -> crossunder fires
    assert ta.crossunder(close, shifted_series(base, 1)) is True
    runtime.end_bar()


def test_shifted_series_composes_offsets():
    runtime = _runtime()
    base = runtime.series("base", "float")

    for index, value in enumerate([10.0, 20.0, 30.0]):
        runtime.begin_bar(_bar(index, value + 1, value - 1, value))
        base.set_current(value)
        runtime.end_bar()

    runtime.begin_bar(_bar(3, 41, 39, 40))
    base.set_current(40.0)

    once = shifted_series(base, 1)
    twice = shifted_series(once, 1)
    assert once[1] == base[2]
    assert twice[0] == base[2]


# NOTE: ta.highest() returns a scalar per bar, not a series.
# Tests for shifted RHS use manual shifted_series() which is the same semantics.
