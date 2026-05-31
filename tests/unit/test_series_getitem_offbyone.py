"""Targeted test for Series.__getitem__ off-by-one after end_bar()."""

from typing import cast

from pinelib import Bar, PineRuntime, RuntimeConfig, SymbolInfo, TimeframeInfo


def _runtime() -> PineRuntime:
    return PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
        timeframe=TimeframeInfo.from_string("60"),
        config=RuntimeConfig(),
    )


def test_series_getitem_after_end_bar_returns_previous_not_current():
    """
    At bar N (during execution): series[1] must return bar N-1's committed value.
    After end_bar(N): series[1] must STILL return bar N-1's committed value.

    Bug: if _between_bars is True after end_bar, series[1] incorrectly returns
    the value from 2 bars ago (index = len-1-1 instead of len-1).
    """
    rt = _runtime()

    # Bar 0
    bar0 = Bar(time=1_700_000_000_000, open=1.0, high=2.0, low=0.5, close=1.5, volume=3.0)
    rt.begin_bar(bar0)
    rt.end_bar()

    # Bar 1 (current)
    bar1 = Bar(time=1_700_000_060_000, open=1.5, high=3.0, low=1.0, close=2.5, volume=5.0)
    rt.begin_bar(bar1)

    # DURING bar 1: series[1] should be bar 0's close = 1.5
    assert cast(float, rt.close[1]) == 1.5, f"during bar: close[1]={rt.close[1]}, expected 1.5"
    assert rt.close._between_bars is False, "during bar: _between_bars should be False"
    assert len(rt.close._history) == 1, (
        f"during bar: history len={len(rt.close._history)}, expected 1"
    )

    # NOW end bar 1
    rt.end_bar()

    # BETWEEN bars: we're done with bar 1, next begin_bar will be bar 2
    # series[1] should STILL be bar 0's close = 1.5
    # (series[0] is now the current/uncommitted state, series[1] is bar 0)
    assert rt.close._between_bars is True, "after end_bar: _between_bars should be True"
    assert len(rt.close._history) == 2, (
        f"after end_bar: history len={len(rt.close._history)}, expected 2"
    )

    # This is the critical assertion - should be 1.5 (bar 0), not bar 1's value
    result = rt.close[1]
    assert cast(float, result) == 1.5, (
        f"AFTER end_bar: close[1]={result}, expected 1.5 (bar 0 close). "
        f"Bug: if _between_bars True causes index=len-offset-1, then "
        f"index=2-1-1=0 gives history[0]=bar0 (WRONG, should be bar0=1.5 actually)... "
        f"let me recalculate: with _between_bars True, index = 2-1-1 = 0, "
        f"history[0] = bar0 close = 1.5. So this might actually be CORRECT in this case."
    )


def test_series_getitem_offset_2_after_end_bar():
    """Test offset 2 after end_bar - this is where off-by-one should show more clearly."""
    rt = _runtime()

    # Bar 0
    bar0 = Bar(time=1_700_000_000_000, open=1.0, high=2.0, low=0.5, close=1.5, volume=3.0)
    rt.begin_bar(bar0)
    rt.end_bar()

    # Bar 1
    bar1 = Bar(time=1_700_000_060_000, open=1.5, high=3.0, low=1.0, close=2.5, volume=5.0)
    rt.begin_bar(bar1)
    rt.end_bar()

    # Bar 2 (current)
    bar2 = Bar(time=1_700_000_120_000, open=2.0, high=4.0, low=1.5, close=3.5, volume=7.0)
    rt.begin_bar(bar2)

    # DURING bar 2: close[1]=bar1=2.5, close[2]=bar0=1.5
    assert cast(float, rt.close[1]) == 2.5, f"during bar2: close[1]={rt.close[1]}"
    assert cast(float, rt.close[2]) == 1.5, f"during bar2: close[2]={rt.close[2]}"
    assert rt.close._between_bars is False

    rt.end_bar()

    # BETWEEN bars after bar 2:
    # close[1] should be bar1=2.5, close[2] should be bar0=1.5
    assert rt.close._between_bars is True
    assert len(rt.close._history) == 3  # bar0, bar1, bar2

    r1 = cast(float, rt.close[1])
    r2 = cast(float, rt.close[2])
    assert r1 == 2.5, (
        f"AFTER end_bar: close[1]={r1}, expected 2.5 (bar1). "
        f"_between_bars={rt.close._between_bars}, len={len(rt.close._history)}"
    )
    assert r2 == 1.5, f"AFTER end_bar: close[2]={r2}, expected 1.5 (bar0)"


def test_series_getitem_zero_returns_current_during_bar():
    """s[0] always returns current bar's value (committed or set)."""
    rt = _runtime()

    bar0 = Bar(time=1_700_000_000_000, open=1.0, high=2.0, low=0.5, close=1.5, volume=3.0)
    rt.begin_bar(bar0)
    assert cast(float, rt.close[0]) == 1.5
    rt.end_bar()

    bar1 = Bar(time=1_700_000_060_000, open=1.5, high=3.0, low=1.0, close=2.5, volume=5.0)
    rt.begin_bar(bar1)
    assert cast(float, rt.close[0]) == 2.5
    rt.end_bar()

    # Between bars: s[0] should return last committed value
    assert cast(float, rt.close[0]) == 2.5
