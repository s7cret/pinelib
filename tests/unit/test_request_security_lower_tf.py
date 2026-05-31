import pytest

from pinelib import (
    PL_UNSUPPORTED_NESTED_SECURITY,
    Bar,
    InMemoryDataProvider,
    PineDataFormatError,
    PineRequestError,
    PineRuntime,
    PineUnsupportedFeatureError,
    RuntimeConfig,
    SymbolInfo,
    TimeframeInfo,
    security_lower_tf,
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


def test_security_lower_tf_returns_ordered_array_for_current_chart_bar() -> None:
    chart = _bars([0, 3_600_000], 3_600_000)
    ltf = _bars([0, 60_000, 120_000, 3_600_000, 3_660_000], 60_000, [10.0, 11.0, 12.0, 20.0, 21.0])
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "1"): ltf})
    rt = _runtime(provider)

    rt.begin_bar(chart[0])
    arr = security_lower_tf(
        "TEST:BBB", "1", lambda child: child.close[0], runtime=rt, state_id="ltf"
    )
    assert list(arr) == [10.0, 11.0, 12.0]
    rt.end_bar()

    rt.begin_bar(chart[1])
    arr = security_lower_tf(
        "TEST:BBB", "1", lambda child: child.close[0], runtime=rt, state_id="ltf"
    )
    assert list(arr) == [20.0, 21.0]


def test_security_lower_tf_reuses_data_provider_window_cache() -> None:
    chart = _bars([0, 3_600_000], 3_600_000)
    ltf = _bars([0, 60_000, 120_000, 3_600_000, 3_660_000], 60_000, [10.0, 11.0, 12.0, 20.0, 21.0])
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "1"): ltf})
    rt = _runtime(provider)
    rt.request_data_end_ms = chart[-1].time_close

    for bar in chart:
        rt.begin_bar(bar)
        security_lower_tf("TEST:BBB", "1", lambda child: child.close[0], runtime=rt, state_id="ltf")
        rt.end_bar()

    lower_tf_queries = [m for m in provider.metadata_log if m.normalized_symbol == "TEST:BBB"]
    assert len(lower_tf_queries) == 1


def test_security_lower_tf_expression_hint_reads_bar_fields_without_child_runtime() -> None:
    chart = _bars([0], 3_600_000)
    ltf = [
        Bar(time=0, time_close=59_999, open=10.0, high=11.0, low=9.0, close=10.5, volume=100.0),
        Bar(
            time=60_000,
            time_close=119_999,
            open=20.0,
            high=21.0,
            low=19.0,
            close=20.5,
            volume=200.0,
        ),
    ]
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "1"): ltf})
    rt = _runtime(provider)

    def fail_if_called(child: object) -> float:
        raise AssertionError("expression callable should not be evaluated for direct bar hints")

    rt.begin_bar(chart[0])
    assert list(
        security_lower_tf(
            "TEST:BBB",
            "1",
            fail_if_called,
            runtime=rt,
            state_id="ltf-open",
            expression_hint="open",
        )
    ) == [10.0, 20.0]
    assert list(
        security_lower_tf(
            "TEST:BBB",
            "1",
            fail_if_called,
            runtime=rt,
            state_id="ltf-volume",
            expression_hint="volume",
        )
    ) == [100.0, 200.0]


def test_security_lower_tf_empty_and_calc_bars_count_cap() -> None:
    chart = _bars([0, 3_600_000], 3_600_000)
    ltf = _bars([0, 60_000, 120_000, 3_600_000], 60_000, [10.0, 11.0, 12.0, 20.0])
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "1"): ltf})
    rt = _runtime(provider)

    rt.begin_bar(chart[0])
    arr = security_lower_tf(
        "TEST:BBB", "1", lambda child: child.close[0], runtime=rt, state_id="ltf", calc_bars_count=2
    )
    assert list(arr) == [10.0, 11.0]
    rt.end_bar()

    rt.begin_bar(chart[1])
    assert (
        list(
            security_lower_tf(
                "TEST:BBB",
                "1",
                lambda child: child.close[0],
                runtime=rt,
                state_id="ltf",
                calc_bars_count=2,
            )
        )
        == []
    )
    assert rt.lower_tf_metadata_log[-1].provider_source == "data_provider"
    assert rt.lower_tf_metadata_log[-1].requested_bars == 2
    assert rt.lower_tf_metadata_log[-1].selected_bars == 0
    assert provider.metadata_log[-1].max_bars == 2


def test_security_lower_tf_precomputed_length_and_nested_fail_closed() -> None:
    chart = _bars([0], 3_600_000)
    ltf = _bars([0, 60_000], 60_000, [10.0, 11.0])
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "1"): ltf})
    rt = _runtime(provider)
    rt.begin_bar(chart[0])

    assert list(security_lower_tf("TEST:BBB", "1", [1.0, 2.0], runtime=rt, state_id="pre")) == [
        1.0,
        2.0,
    ]
    with pytest.raises(PineRequestError):
        security_lower_tf("TEST:BBB", "1", [1.0], runtime=rt, state_id="bad-pre")

    rt.request_depth = 1
    with pytest.raises(PineUnsupportedFeatureError) as excinfo:
        security_lower_tf(
            "TEST:BBB", "1", lambda child: child.close[0], runtime=rt, state_id="nested"
        )
    assert excinfo.value.code == PL_UNSUPPORTED_NESTED_SECURITY
    assert rt.config.diagnostics[-1]["code"] == PL_UNSUPPORTED_NESTED_SECURITY


def test_security_lower_tf_metadata_records_intrabar_provider_source() -> None:
    class Intrabars:
        def __init__(self, bars: list[Bar]) -> None:
            self.max_bars: int | None = None
            self.bars = bars

        def get_intrabar_bars(
            self,
            symbol: str,
            chart_bar: Bar,
            lower_timeframe: str | None = None,
            *,
            max_bars: int | None = None,
        ) -> list[Bar]:
            del symbol, chart_bar, lower_timeframe
            self.max_bars = max_bars
            return self.bars[:max_bars] if max_bars is not None else self.bars

    chart = _bars([0], 3_600_000)
    intrabars = Intrabars(_bars([0, 60_000, 120_000], 60_000, [10.0, 11.0, 12.0]))
    rt = PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC"),
        TimeframeInfo.from_string("60"),
        intrabar_provider=intrabars,
        config=RuntimeConfig(),
    )
    rt.begin_bar(chart[0])

    arr = security_lower_tf(
        "TEST:BBB", "1", lambda child: child.close[0], runtime=rt, state_id="ltf", calc_bars_count=2
    )

    assert list(arr) == [10.0, 11.0]
    assert intrabars.max_bars == 2
    metadata = rt.lower_tf_metadata_log[-1]
    assert metadata.provider_source == "intrabar_provider"
    assert metadata.selected_bar_times == (0, 60_000)


def test_security_lower_tf_intrabar_provider_missing_preload_fails_closed() -> None:
    chart = _bars([0], 3_600_000)
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart})
    rt = PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC"),
        TimeframeInfo.from_string("60"),
        intrabar_provider=provider,
        config=RuntimeConfig(),
    )
    rt.begin_bar(chart[0])

    with pytest.raises(PineDataFormatError, match="Intrabar bars are not loaded"):
        security_lower_tf("TEST:BBB", "1", lambda child: child.close[0], runtime=rt, state_id="ltf")


def test_security_lower_tf_intrabar_provider_explicit_empty_preload_returns_empty_array() -> None:
    chart = _bars([0], 3_600_000)
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "1"): []})
    rt = PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC"),
        TimeframeInfo.from_string("60"),
        intrabar_provider=provider,
        config=RuntimeConfig(),
    )
    rt.begin_bar(chart[0])

    arr = security_lower_tf(
        "TEST:BBB", "1", lambda child: child.close[0], runtime=rt, state_id="ltf"
    )

    assert list(arr) == []
