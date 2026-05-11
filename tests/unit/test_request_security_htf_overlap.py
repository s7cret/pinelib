"""Tests for request.security HTF overlap-aware filtering.

Bug: When chart starts mid-period (e.g., May 5 20:00), the HTF bar that
opened before chart_start (e.g., May 5 00:00) was excluded by the filter
`bar.time >= chart_start`, even though that HTF bar's period covers part
of the chart.

Fix: Use start=None in get_bars() to include HTF bars from before chart_start.
The merge logic (lookahead_off + effective_close) determines which bar's
value to return based on finalization status.
"""

import pytest

from pinelib import (
    Bar,
    InMemoryDataProvider,
    PineRuntime,
    RuntimeConfig,
    SymbolInfo,
    TimeframeInfo,
    is_na,
    security,
)


def _bars(times: list[int], tf_ms: int, closes: list[float] | None = None) -> list[Bar]:
    values = closes or [float(i + 1) for i in range(len(times))]
    return [
        Bar(time=t, time_close=t + tf_ms - 1, open=v, high=v, low=v, close=v)
        for t, v in zip(times, values, strict=True)
    ]


def _runtime_15(provider: InMemoryDataProvider) -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC"),
        TimeframeInfo.from_string("15"),
        data_provider=provider,
        config=RuntimeConfig(),
    )


def test_htf_bar_opens_before_chart_start_with_previous_bar() -> None:
    """HTF bar opened before chart_start but previous bar is needed for lookahead_off.

    Scenario: Chart starts at May 5 20:00 (mid-period).
    D bars: May 4 (closed) and May 5 (open).
    At May 5 20:00: May 5 D is not finalized, so should return May 4 D close.
    """
    # D bars: May 4 and May 5
    d_bars = _bars([1777852800000, 1777939200000], 86400000, [79861.01, 80905.52])

    # Chart: 15m bar at May 5 20:00
    chart = _bars([1778011200000], 900000, [81606.35])

    provider = InMemoryDataProvider({("TEST:AAA", "15"): chart, ("TEST:AAA", "D"): d_bars})
    rt = _runtime_15(provider)

    rt.begin_bar(chart[0])
    # With fix: May 4 D bar is included (starts before chart but closed)
    # May 5 D bar is included (overlaps chart)
    # At 20:00: May 5 D not finalized -> returns May 4 D close = 79861.01
    result = security("TEST:AAA", "D", [b.close for b in d_bars], runtime=rt, state_id="test1")
    assert not is_na(result), f"Expected May 4 D close (79861.01), got NA"
    assert float(result) == pytest.approx(79861.01)


def test_htf_bar_at_last_child_returns_current_close() -> None:
    """At last child bar (23:45), should return current D close (finalized)."""
    # D bars: May 4 and May 5
    d_bars = _bars([1777852800000, 1777939200000], 86400000, [79861.01, 80905.52])

    # Chart: 15m bar at May 5 23:45 (last child of May 5 D)
    chart = _bars([1778024700000], 900000, [80905.52])  # 23:45

    provider = InMemoryDataProvider({("TEST:AAA", "15"): chart, ("TEST:AAA", "D"): d_bars})
    rt = _runtime_15(provider)

    rt.begin_bar(chart[0])
    # At 23:45: May 5 D is finalized -> returns May 5 D close = 80905.52
    result = security("TEST:AAA", "D", [b.close for b in d_bars], runtime=rt, state_id="test2")
    assert not is_na(result), f"Expected May 5 D close (80905.52), got NA"
    assert float(result) == pytest.approx(80905.52)


def test_only_current_htf_bar_not_finalized_returns_na() -> None:
    """If only current (unfinalized) HTF bar exists, returns NA for early chart bars.

    Scenario: Only May 5 D bar available (no May 4).
    At May 5 20:00: May 5 D not finalized, no previous bar -> returns NA.
    """
    # Only May 5 D bar
    d_bars = _bars([1777939200000], 86400000, [80905.52])

    # Chart: 15m bar at May 5 20:00
    chart = _bars([1778011200000], 900000, [81606.35])

    provider = InMemoryDataProvider({("TEST:AAA", "15"): chart, ("TEST:AAA", "D"): d_bars})
    rt = _runtime_15(provider)

    rt.begin_bar(chart[0])
    # May 5 D bar exists but not finalized at 20:00, no previous bar -> NA
    result = security("TEST:AAA", "D", [b.close for b in d_bars], runtime=rt, state_id="test3")
    assert is_na(result), f"Expected NA (May 5 D not finalized), got {result}"


def test_p4_mtf_overlap_scenario() -> None:
    """Simulate the P4 bug scenario: 15m chart starting May 5 20:00, D bars May 4-5.

    This reproduces the actual P4 bug where:
    - Chart: 300 x 15m bars from May 5 20:00
    - D bars: May 4 (close=79861.01) and May 5 (close=80905.52)
    - Bug was: May 4 D bar excluded because time < chart_start
    - Fix: include both D bars, merge logic handles finalization
    """
    # D bars: May 4 and May 5
    d_bars = _bars([1777852800000, 1777939200000], 86400000, [79861.01, 80905.52])

    # Chart: 15m bar at May 5 20:00
    chart = _bars([1778011200000], 900000, [81606.35])

    provider = InMemoryDataProvider({("BINANCE:BTCUSDT", "15"): chart, ("BINANCE:BTCUSDT", "D"): d_bars})
    rt = PineRuntime(
        SymbolInfo("BINANCE:BTCUSDT", timezone="UTC"),
        TimeframeInfo.from_string("15"),
        data_provider=provider,
        config=RuntimeConfig(),
    )

    rt.begin_bar(chart[0])
    # At bar 0 (20:00): May 5 D not finalized -> returns May 4 D close
    result = security("BINANCE:BTCUSDT", "D", [b.close for b in d_bars], runtime=rt, state_id="p4_test")
    assert not is_na(result), f"P4 scenario: Expected 79861.01, got NA"
    assert float(result) == pytest.approx(79861.01)
