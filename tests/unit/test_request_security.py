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
    return [Bar(time=t, time_close=t + tf_ms - 1, open=v, high=v, low=v, close=v) for t, v in zip(times, values, strict=True)]


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

    gaps_on = merge_requested_series_to_chart_bars(values, requested_bars=requested, chart_bars=chart, gaps="barmerge.gaps_on")
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
