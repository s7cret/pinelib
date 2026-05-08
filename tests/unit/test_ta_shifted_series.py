from __future__ import annotations

from pinelib import Bar, PineRuntime, SymbolInfo, TimeframeInfo, ta
from pinelib.ta import _history


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
