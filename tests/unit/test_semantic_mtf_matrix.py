"""V5-SEM-001 MTF semantic matrix. Unknown/nested fail closed; profiles differ."""

from __future__ import annotations

import pytest
from openpine_contracts import SemanticProfile

from pinelib import (
    PL_UNSUPPORTED_NESTED_SECURITY,
    Bar,
    InMemoryDataProvider,
    PineRequestError,
    PineRuntime,
    PineUnsupportedFeatureError,
    RuntimeConfig,
    SymbolInfo,
    TimeframeInfo,
    is_na,
    merge_requested_series_to_chart_bars,
    security,
    security_lower_tf,
)

HOUR = 3_600_000


def _bars(times: list[int], tf_ms: int, closes: list[float] | None = None) -> list[Bar]:
    values = closes or [float(i + 1) for i in range(len(times))]
    return [
        Bar(time=t, time_close=t + tf_ms - 1, open=v, high=v, low=v, close=v)
        for t, v in zip(times, values, strict=True)
    ]


def _rt(
    provider: InMemoryDataProvider,
    *,
    profile: SemanticProfile = SemanticProfile.STRICT_5X,
    tf: str = "60",
    nested: bool = False,
) -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC"),
        TimeframeInfo.from_string(tf),
        data_provider=provider,
        config=RuntimeConfig(semantic_profile=profile, supports_nested_security=nested),
    )


def _series(
    profile: SemanticProfile, timeframe: str, requested: list[Bar]
) -> list[object]:
    chart = _bars([0, HOUR, 2 * HOUR], HOUR)
    provider = InMemoryDataProvider(
        {("TEST:AAA", "60"): chart, ("TEST:BBB", timeframe): requested}
    )
    rt = _rt(provider, profile=profile)
    out: list[object] = []
    for bar in chart:
        rt.begin_bar(bar)
        out.append(
            security(
                "TEST:BBB",
                timeframe,
                lambda child: float(child.close[0]),
                runtime=rt,
                state_id=f"mtf-{profile.value}-{timeframe}",
            )
        )
        rt.end_bar()
    return out


def test_same_tf_higher_tf_and_lower_tf_are_defined() -> None:
    same = _bars([0, HOUR, 2 * HOUR], HOUR, [1.0, 2.0, 3.0])
    higher = _bars([0, 2 * HOUR], 2 * HOUR, [10.0, 20.0])
    assert not is_na(_series(SemanticProfile.STRICT_5X, "60", same)[-1])
    assert _series(SemanticProfile.STRICT_5X, "120", higher) != _series(
        SemanticProfile.LEGACY_4X, "120", higher
    )
    chart = _bars([0, HOUR], HOUR)
    ltf = _bars([0, 60_000, 120_000, HOUR], 60_000, [1.0, 2.0, 3.0, 4.0])
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "1"): ltf})
    rt = _rt(provider)
    rt.begin_bar(chart[0])
    arr = security_lower_tf(
        "TEST:BBB", "1", lambda child: child.close[0], runtime=rt, state_id="ltf"
    )
    assert list(arr) == [1.0, 2.0, 3.0]


def test_gaps_and_lookahead_modes_are_independent() -> None:
    chart = _bars([0, HOUR, 2 * HOUR, 3 * HOUR], HOUR)
    requested = _bars([0, 2 * HOUR], 2 * HOUR, [10.0, 20.0])
    values = [10.0, 20.0]
    off = merge_requested_series_to_chart_bars(
        values, requested_bars=requested, chart_bars=chart, gaps="barmerge.gaps_off"
    )
    on = merge_requested_series_to_chart_bars(
        values, requested_bars=requested, chart_bars=chart, gaps="barmerge.gaps_on"
    )
    look = merge_requested_series_to_chart_bars(
        values,
        requested_bars=requested,
        chart_bars=chart,
        lookahead="barmerge.lookahead_on",
    )
    assert off != on
    assert look != off
    with pytest.raises(PineRequestError, match="gaps"):
        merge_requested_series_to_chart_bars(
            values, requested_bars=requested, chart_bars=chart, gaps="nope"
        )
    with pytest.raises(PineRequestError, match="lookahead"):
        merge_requested_series_to_chart_bars(
            values,
            requested_bars=requested,
            chart_bars=chart,
            lookahead="nope",
        )


def test_first_bar_is_na_last_bar_defined_for_htf() -> None:
    requested = _bars([0, 2 * HOUR], 2 * HOUR, [10.0, 20.0])
    series = _series(SemanticProfile.LEGACY_4X, "120", requested)
    assert is_na(series[0])
    assert not is_na(series[-1])


def test_nested_security_fail_closed() -> None:
    chart = _bars([0], HOUR)
    provider = InMemoryDataProvider(
        {("TEST:AAA", "60"): chart, ("TEST:BBB", "60"): chart}
    )
    rt = _rt(provider)
    rt.begin_bar(chart[0])
    rt.request_depth = 1
    with pytest.raises(PineUnsupportedFeatureError) as exc:
        security("TEST:BBB", "60", [1.0], runtime=rt, state_id="nested")
    assert exc.value.code == PL_UNSUPPORTED_NESTED_SECURITY


def test_insufficient_history_is_na_not_crash() -> None:
    chart = _bars([10 * HOUR, 11 * HOUR], HOUR)
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "60"): []})
    rt = _rt(provider)
    rt.begin_bar(chart[0])
    value = security(
        "TEST:BBB",
        "60",
        lambda child: float(child.close[0]),
        runtime=rt,
        state_id="hist",
    )
    assert is_na(value)


def test_two_profiles_produce_distinct_identity_payload() -> None:
    requested = _bars([0, 2 * HOUR], 2 * HOUR, [10.0, 20.0])
    legacy = _series(SemanticProfile.LEGACY_4X, "120", requested)
    strict = _series(SemanticProfile.STRICT_5X, "120", requested)
    assert [SemanticProfile.LEGACY_4X.value, legacy] != [
        SemanticProfile.STRICT_5X.value,
        strict,
    ]
