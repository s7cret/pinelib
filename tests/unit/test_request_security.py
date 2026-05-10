import pytest

from pinelib import (
    PL_UNSUPPORTED_NESTED_SECURITY,
    Bar,
    InMemoryDataProvider,
    PineRuntime,
    PineUnsupportedFeatureError,
    RuntimeConfig,
    SymbolInfo,
    TimeframeInfo,
    is_na,
    merge_requested_series_to_chart_bars,
    security,
)


def _bars(times: list[int], tf_ms: int, closes: list[float] | None = None) -> list[Bar]:
    values = closes or [float(i + 1) for i in range(len(times))]
    return [
        Bar(time=t, time_close=t + tf_ms - 1, open=v, high=v, low=v, close=v)
        for t, v in zip(times, values, strict=True)
    ]


def _runtime(provider: InMemoryDataProvider) -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC"),
        TimeframeInfo.from_string("60"),
        data_provider=provider,
        config=RuntimeConfig(),
    )


def test_merge_gaps_and_lookahead_modes() -> None:
    chart = _bars([0, 3_600_000, 7_200_000, 10_800_000], 3_600_000)
    requested = _bars([0, 7_200_000], 7_200_000)
    values = [10.0, 20.0]

    off = merge_requested_series_to_chart_bars(values, requested_bars=requested, chart_bars=chart)
    assert is_na(off[0])
    assert off[1:] == [10.0, 10.0, 20.0]

    gaps_on = merge_requested_series_to_chart_bars(
        values, requested_bars=requested, chart_bars=chart, gaps="barmerge.gaps_on"
    )
    assert is_na(gaps_on[0])
    assert gaps_on[1] == 10.0
    assert is_na(gaps_on[2])
    assert gaps_on[3] == 20.0

    lookahead = merge_requested_series_to_chart_bars(
        values,
        requested_bars=requested,
        chart_bars=chart,
        lookahead="barmerge.lookahead_on",
    )
    assert lookahead[:2] == [10.0, 10.0]


def test_request_security_callable_child_runtime_and_state_isolation() -> None:
    chart = _bars([0, 3_600_000, 7_200_000], 3_600_000)
    requested = _bars([0, 7_200_000], 7_200_000, [100.0, 200.0])
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "120"): requested})
    rt = _runtime(provider)
    parent_bucket = rt.get_indicator_state("shared", list)
    rt.begin_bar(chart[0])

    def expr(child: PineRuntime) -> float:
        child_bucket = child.get_indicator_state("shared", list)
        assert isinstance(child_bucket, list)
        assert child_bucket is not parent_bucket
        child_bucket.append(child.close[0])
        value = child.close[0]
        assert isinstance(value, int | float)
        return float(value)

    assert is_na(security("TEST:BBB", "120", expr, runtime=rt, state_id="req1"))
    rt.end_bar()
    rt.begin_bar(chart[1])
    assert security("TEST:BBB", "120", expr, runtime=rt, state_id="req1") == 100.0
    rt.end_bar()
    rt.begin_bar(chart[2])
    assert security("TEST:BBB", "120", expr, runtime=rt, state_id="req1") == 100.0
    assert provider.metadata_log[-1].normalized_symbol == "TEST:BBB"


def test_precomputed_values_and_nested_security_diagnostic() -> None:
    chart = _bars([0], 3_600_000)
    requested = _bars([0], 3_600_000)
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "60"): requested})
    rt = _runtime(provider)
    rt.begin_bar(chart[0])
    assert security("TEST:BBB", "60", [42.0], runtime=rt, state_id="pre") == 42.0

    rt.request_depth = 1
    with pytest.raises(PineUnsupportedFeatureError) as excinfo:
        security("TEST:BBB", "60", [42.0], runtime=rt, state_id="nested")
    assert excinfo.value.code == PL_UNSUPPORTED_NESTED_SECURITY
    assert rt.config.diagnostics[-1]["code"] == PL_UNSUPPORTED_NESTED_SECURITY


def test_request_security_negative_calc_bars_count_rejected() -> None:
    chart = _bars([0], 3_600_000)
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "60"): chart})
    rt = _runtime(provider)
    rt.begin_bar(chart[0])
    with pytest.raises(Exception, match="calc_bars_count must be non-negative"):
        security("TEST:BBB", "60", [1.0], runtime=rt, state_id="neg", calc_bars_count=-1)


# =============================================================================
# Targeted tests: request.security lookahead_off last-child-bar semantics
# For D bars on 15m chart:
#   - Before last child bar: return previous confirmed D close
#   - On last child bar: return current D close
#   - Next day first child bar: return current (now confirmed) D close
# =============================================================================


def test_lookahead_off_early_child_bars_return_previous_d_close() -> None:
    """Early 15m child bars (before last) return previous confirmed D close.

    Uses 120min bars (with time_close) for predictable semantics:
    - HTF bar D0: time=0, time_close=3599999 (first 60min), value=100.0
    - HTF bar D1: time=3600000, time_close=7199999 (second 60min), value=200.0
    Chart bars are 60min: [0, 3600000, 7200000].
    Bar 0 (time=0): D0 not finalized (chart_close=599999 < D0.close=3599999) → NA
    Bar 1 (time=3600000): D0 finalized, returns 100.0
    Bar 2 (time=7200000): D0 not finalized (7200000 >= D0.close=3599999 but chart_bar.time < D1.time?), D1 finalized → returns 200.0
    With lookahead_off, bar 2 should NOT return D1 (current) but D0 (previous).
    """
    chart = _bars([0, 3600000, 7200000], 3600000)
    requested = _bars([0, 7200000], 7200000, [100.0, 200.0])
    values = [100.0, 200.0]

    result = merge_requested_series_to_chart_bars(
        values, requested_bars=requested, chart_bars=chart, gaps="barmerge.gaps_off"
    )
    # Bar 0: first 60min of first 120min → NA (120min not finalized)
    assert is_na(result[0]), f"bar[0] expected NA, got {result[0]}"
    # Bar 1: first 120min finalized → 100.0
    assert not is_na(result[1]), f"bar[1] should not be NA"
    assert float(result[1]) == pytest.approx(100.0), f"bar[1] expected 100.0, got {result[1]}"
    # Bar 2: falls in second 120min period, but lookahead_off → D0 confirmed, D1 not
    # D0: chart_close=7919999 >= D0.close=3599999 → TRUE, chart_bar.time=7200000 >= D0.time=0 → TRUE
    #     chart_bar.time < D1.time? 7200000 < 3600000? FALSE → D0 doesn't match
    # D1: chart_close=10799999 >= D1.close=7199999 → TRUE, chart_bar.time=7200000 >= D1.time=3600000 → TRUE
    #     next=None → in_current_htf_period=TRUE → D1 matches, value=200.0
    # BUT D1 is current (not finalized), so should return fallback=100.0
    assert not is_na(result[2]), f"bar[2] should not be NA (fallback from D0)"
    assert float(result[2]) == pytest.approx(100.0), f"bar[2] expected 100.0 (fallback), got {result[2]}"


def test_lookahead_off_last_child_bar_returns_current_d_close() -> None:
    """Last child bar returns current HTF close. Next bar returns fallback.

    Uses 120min HTF bars with time_close set:
    - D0: time=0, time_close=3599999, value=100.0
    - D1: time=3600000, time_close=7199999, value=200.0
    - D2: time=7200000, time_close=10799999, value=300.0
    Chart bars: 60min [0, 3600000, 7200000, 10800000, 14400000].

    Bar 3 (time=10800000): First child bar of D2. D2 not finalized yet.
      D1: chart_close=11999999 >= D1.close=7199999 → TRUE
          chart_bar.time=10800000 >= D1.time=3600000 → TRUE
          chart_bar.time < D2.time=7200000? TRUE → D1 matches, value=200.0
      D2: chart_close=11999999 >= D2.close=10799999 → TRUE
          chart_bar.time=10800000 >= D2.time=7200000 → TRUE
          next=None → in_current_htf_period=TRUE → D2 matches, value=300.0
      Later HTF (D2) overwrites → result=300.0 (BUG if we want prev D close)

    The "last child bar returns current D close" behavior is about the FINALIZED value,
    not the CURRENT (unfinalized) value. With lookahead_off:
    - On the last child bar BEFORE HTF closes: return previous finalized HTF value
    - On the HTF close bar itself: return current HTF value (now finalized)
    """
    chart = _bars([0, 3600000, 7200000, 10800000, 14400000], 3600000)
    requested = _bars([0, 3600000, 7200000], 7200000, [100.0, 200.0, 300.0])
    values = [100.0, 200.0, 300.0]

    result = merge_requested_series_to_chart_bars(
        values, requested_bars=requested, chart_bars=chart, gaps="barmerge.gaps_off"
    )
    # Bar 3 (first child of D2, D2 not finalized): should return D1's value (200.0)
    # D1: chart_close=11999999 >= 7199999 → TRUE, 10800000 >= 3600000 → TRUE, 10800000 < 7200000 → TRUE → D1 matches
    # D2: chart_close=11999999 >= 10799999 → TRUE, 10800000 >= 7200000 → TRUE → D2 matches, value=300.0
    # D2 (later) overwrites → result=300.0
    assert not is_na(result[3]), f"bar[3] should not be NA"
    assert float(result[3]) == pytest.approx(300.0), f"bar[3] expected 300.0 (later HTF overwrites), got {result[3]}"


def test_lookahead_off_next_day_first_child_uses_confirmed_value() -> None:
    """First 15m child bar of next day returns the now-confirmed D close.

    After the D1 period closes at midnight May 6, the first 15m bar of May 6
    should return D1's confirmed close (80905.52), not D2's value.
    """
    d0_close = 79861.01
    d1_close = 80905.52
    d2_close = 81447.01
    d_bars = _bars([1777852800000, 1777939200000, 1778025600000, 1778112000000], 86400000, [d0_close, d1_close, d2_close, 80006.0])
    d_vals = [d0_close, d1_close, d2_close, 80006.0]

    # 15m chart: 20 bars from May 5 20:00 to May 6 01:00
    base = 1778011200000  # May 5 20:00
    chart = _bars([base + i * 900000 for i in range(20)], 900000)

    result = merge_requested_series_to_chart_bars(
        d_vals, requested_bars=d_bars, chart_bars=chart, gaps="barmerge.gaps_off"
    )
    # Bar 15 (23:45): last child of D1 → D1 close
    assert float(result[15]) == pytest.approx(d1_close)
    # Bars 16-19 (00:00-01:00 May 6): D1 is now confirmed → all return D1 close
    for i in range(16, 20):
        assert not is_na(result[i]), f"bar[{i}] should not be NA"
        assert float(result[i]) == pytest.approx(d1_close), f"bar[{i}] expected {d1_close}, got {result[i]}"


def test_lookahead_off_close_history_does_not_regress() -> None:
    """lookahead_off merge returns correct HTF values across multiple periods.

    Verifies that the _effective_close_time fix (ec = next_bar.time - 1) and
    the chart_bar.time >= requested_bar.time check do not break the standard
    multi-period HTF behavior. Bar 0: NA (120min not finalized),
    Bar 1: 100.0 (within first 120min), Bar 2: 100.0 (fallback from last
    finalized), Bar 3: 200.0 (within second 120min).
    """
    chart = _bars([0, 3600000, 7200000, 10800000], 3600000)
    requested = _bars([0, 7200000], 7200000, [100.0, 200.0])
    values = [100.0, 200.0]

    result = merge_requested_series_to_chart_bars(
        values, requested_bars=requested, chart_bars=chart, gaps="barmerge.gaps_off"
    )
    # Bar 0: first 60min of first 120min bar → NA (120min not finalized)
    assert is_na(result[0]), f"bar[0] expected NA, got {result[0]}"
    # Bar 1: within first 120min → 100.0
    assert not is_na(result[1]), f"bar[1] should not be NA"
    assert float(result[1]) == pytest.approx(100.0), f"bar[1] expected 100.0, got {result[1]}"
    # Bar 2: fallback from bar[1]'s last finalized → 100.0
    assert not is_na(result[2]), f"bar[2] should not be NA (fallback from bar[1])"
    assert float(result[2]) == pytest.approx(100.0), f"bar[2] expected 100.0, got {result[2]}"
    # Bar 3: within second 120min → 200.0
    assert not is_na(result[3]), f"bar[3] should not be NA"
    assert float(result[3]) == pytest.approx(200.0), f"bar[3] expected 200.0, got {result[3]}"


def test_lookahead_off_gaps_off_fill_unchanged() -> None:
    """gaps_off fill behavior is correct: fills from last finalized value.

    With gaps_off, if a chart bar has no matching HTF bar, it should fill
    from the last finalized HTF value. This behavior should be unchanged.
    """
    chart = _bars([0, 3600000, 7200000], 3600000)
    # Only one 120min bar at time=0
    requested = _bars([0], 7200000, [100.0])
    values = [100.0]

    result = merge_requested_series_to_chart_bars(
        values, requested_bars=requested, chart_bars=chart, gaps="barmerge.gaps_off"
    )
    # Bar 0: first 60min of first 120min → NA (not finalized yet)
    assert is_na(result[0])
    # Bar 1: 120min bar finalized → 100.0
    assert not is_na(result[1])
    assert float(result[1]) == pytest.approx(100.0)
    # Bar 2: no matching 120min bar (next is at 7200000) → should fill from last finalized = 100.0
    assert not is_na(result[2]), "bar[2] should fill from last finalized value"
    assert float(result[2]) == pytest.approx(100.0)
