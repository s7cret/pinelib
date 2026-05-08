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
    runtime = _runtime()
    close = runtime.series("close", "float")
    base = runtime.series("base", "float")

    runtime.begin_bar(_bar(0, 105, 95, 100))
    close.set_current(100.0)
    base.set_current(100.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 115, 100, 105))
    close.set_current(105.0)
    base.set_current(110.0)
    runtime.end_bar()

    runtime.begin_bar(_bar(2, 130, 115, 125))
    close.set_current(125.0)
    base.set_current(120.0)

    assert ta.crossover(close, shifted_series(base, 1)) is False
    runtime.end_bar()


def test_crossover_shifted_series_positive_case_is_true():
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

    assert ta.crossover(close, shifted_series(base, 1)) is True
    runtime.end_bar()


def test_crossunder_shifted_series_uses_previous_shifted_rhs():
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
