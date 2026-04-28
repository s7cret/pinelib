from pinelib import Bar, PineRuntime, RuntimeConfig, SymbolInfo, TimeframeInfo, is_na


def _runtime(session: str, timezone: str) -> PineRuntime:
    return PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone=timezone, session=session),
        timeframe=TimeframeInfo.from_string("60"),
        config=RuntimeConfig(),
    )


def test_regular_session_filter_and_calendar_helpers_use_exchange_timezone() -> None:
    runtime = _runtime("0930-1600:23456", "America/New_York")
    bar = Bar(
        time=1_709_303_400_000,
        time_close=1_709_306_999_999,
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
    )

    runtime.begin_bar(bar)
    assert runtime.timefunc.time(runtime=runtime) == bar.time
    assert runtime.timefunc.time_close(runtime=runtime) == bar.time_close
    assert runtime.timefunc.hour(runtime=runtime) == 9
    assert runtime.timefunc.dayofweek(runtime=runtime) == 6


def test_session_filter_returns_na_outside_session() -> None:
    runtime = _runtime("0930-1600:23456", "America/New_York")
    bar = Bar(
        time=1_709_328_600_000,
        time_close=1_709_332_199_999,
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
    )

    runtime.begin_bar(bar)
    assert is_na(runtime.timefunc.time(runtime=runtime))
    assert is_na(runtime.timefunc.time_close(runtime=runtime))


def test_dst_week_uses_iana_timezone_rules() -> None:
    runtime = _runtime("0000-2359:1234567", "America/New_York")
    before_dst = Bar(
        time=1_709_988_000_000, time_close=1_709_991_599_999, open=1, high=1, low=1, close=1
    )
    after_dst = Bar(
        time=1_710_331_200_000, time_close=1_710_334_799_999, open=1, high=1, low=1, close=1
    )

    runtime.begin_bar(before_dst)
    assert runtime.timefunc.hour(runtime=runtime) == 7
    runtime.end_bar()
    runtime.begin_bar(after_dst)
    assert runtime.timefunc.hour(runtime=runtime) == 8


def test_overnight_session_is_supported() -> None:
    runtime = _runtime("1700-1700:23456", "America/New_York")
    bar = Bar(
        time=1_709_066_400_000,
        time_close=1_709_069_999_999,
        open=10.0,
        high=10.5,
        low=9.5,
        close=10.2,
    )

    runtime.begin_bar(bar)
    assert runtime.timefunc.time(runtime=runtime) == bar.time
    assert runtime.timefunc.time_close(runtime=runtime) == bar.time_close


import pytest  # noqa: E402

from pinelib.errors import (  # noqa: E402
    PL_UNSUPPORTED_TIMEFRAME_TIMEFUNC,
    PineUnsupportedFeatureError,
)


def test_time_and_time_close_accept_chart_timeframe() -> None:
    runtime = _runtime("0000-2359:1234567", "UTC")
    bar = Bar(time=1_700_000_000_000, time_close=1_700_003_599_999, open=1, high=1, low=1, close=1)
    runtime.begin_bar(bar)
    assert runtime.timefunc.time("60", runtime=runtime) == bar.time
    assert runtime.timefunc.time_close("1H", runtime=runtime) == bar.time_close


def test_time_and_time_close_non_chart_timeframe_is_explicit_unsupported() -> None:
    runtime = _runtime("0000-2359:1234567", "UTC")
    bar = Bar(time=1_700_000_000_000, time_close=1_700_003_599_999, open=1, high=1, low=1, close=1)
    runtime.begin_bar(bar)
    with pytest.raises(PineUnsupportedFeatureError) as exc:
        runtime.timefunc.time("D", runtime=runtime)
    assert exc.value.code == PL_UNSUPPORTED_TIMEFRAME_TIMEFUNC
    assert runtime.config.diagnostics[-1]["code"] == PL_UNSUPPORTED_TIMEFRAME_TIMEFUNC
    with pytest.raises(PineUnsupportedFeatureError):
        runtime.timefunc.time_close("D", runtime=runtime)
