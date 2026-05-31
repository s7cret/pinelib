"""Test Series.__getitem__ offset behavior after end_bar."""

from __future__ import annotations

from pinelib import Bar, PineRuntime, RuntimeConfig, SymbolInfo, TimeframeInfo


def _runtime() -> PineRuntime:
    return PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
        timeframe=TimeframeInfo.from_string("60"),
        config=RuntimeConfig(),
    )


def test_series_getitem_offset_one_returns_previous_bar_after_end_bar() -> None:
    """After end_bar, series[1] must return the previous committed bar, not current.

    Pine semantics:
      - series[0] = current bar's value
      - series[1] = previous bar's value (one bar ago)
      - series[2] = two bars ago

    After end_bar(n), the bar n is committed to history.
    At that point (bar_index = n), series[1] should return bar n-1's value.
    """
    rt = _runtime()

    # Bar 0: close=100
    rt.begin_bar(Bar(time=0, open=100, high=100, low=100, close=100, volume=1))
    rt.end_bar()

    # Bar 1: close=110
    rt.begin_bar(Bar(time=1, open=110, high=110, low=110, close=110, volume=1))
    rt.end_bar()

    # Bar 2: close=120
    rt.begin_bar(Bar(time=2, open=120, high=120, low=120, close=120, volume=1))

    # At bar 2 (before end_bar):
    #   series[0] = 120 (current)
    #   series[1] = 110 (bar 1)
    #   series[2] = 100 (bar 0)
    assert rt.close[0] == 120.0, "series[0] must be current bar"
    assert rt.close[1] == 110.0, "series[1] must be previous bar"
    assert rt.close[2] == 100.0, "series[2] must be two bars ago"

    rt.end_bar()

    # After end_bar(2), bar_index = 2
    # series[1] should still return bar 1's close = 110
    assert rt.close[1] == 110.0, "series[1] after end_bar must return previous bar"


def test_series_getitem_zero_returns_current() -> None:
    """series[0] always returns the current (uncommitted) bar value."""
    rt = _runtime()

    rt.begin_bar(Bar(time=0, open=100, high=100, low=100, close=100, volume=1))
    assert rt.close[0] == 100.0
    rt.end_bar()

    rt.begin_bar(Bar(time=1, open=200, high=200, low=200, close=200, volume=1))
    assert rt.close[0] == 200.0, "series[0] must update to new current bar"
    rt.end_bar()


def test_series_getitem_out_of_range_returns_na() -> None:
    """series[n] where n >= len(history) returns na."""
    rt = _runtime()

    rt.begin_bar(Bar(time=0, open=100, high=100, low=100, close=100, volume=1))
    rt.end_bar()

    # After only 1 bar, series[1] should be na
    from pinelib import na

    assert rt.close[1] is na


def test_series_getitem_consistency_before_and_after_end_bar() -> None:
    """series[1] value must be stable across end_bar boundary."""
    rt = _runtime()

    # Bar 0: 100, Bar 1: 111, Bar 2: 122, Bar 3: 133
    for i, close_val in enumerate([100.0, 111.0, 122.0, 133.0]):
        rt.begin_bar(
            Bar(time=i, open=close_val, high=close_val, low=close_val, close=close_val, volume=1)
        )
        rt.end_bar()

    # Bar 4: 144
    rt.begin_bar(Bar(time=4, open=144, high=144, low=144, close=144, volume=1))

    # During bar 4, before end_bar:
    assert rt.close[1] == 133.0, "during bar 4: series[1] = bar 3 close"

    rt.end_bar()

    # After end_bar(4):
    assert rt.close[1] == 133.0, "after end_bar(4): series[1] = bar 3 close"
    assert rt.close[2] == 122.0, "after end_bar(4): series[2] = bar 2 close"
    assert rt.close[3] == 111.0, "after end_bar(4): series[3] = bar 1 close"
