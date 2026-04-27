import pytest

from pinelib import Bar, PineRuntime, RuntimeConfig, SymbolInfo, TimeframeInfo, na


def _runtime() -> PineRuntime:
    return PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
        timeframe=TimeframeInfo.from_string("60"),
        config=RuntimeConfig(),
    )


def test_runtime_begin_end_bar_commits_after_processing() -> None:
    runtime = _runtime()
    user_series = runtime.series("my_value", "float")
    first_bar = Bar(time=1_700_000_000_000, open=1.0, high=2.0, low=0.5, close=1.5, volume=3.0)

    runtime.begin_bar(first_bar)
    assert runtime.bar_index == -1
    assert runtime.open[0] == 1.0
    assert runtime.close[1] is na
    user_series.set_current(11.0)
    assert user_series[1] is na
    runtime.end_bar()

    second_bar = Bar(time=1_700_000_060_000, open=1.5, high=3.0, low=1.0, close=2.5, volume=5.0)
    runtime.begin_bar(second_bar)
    assert runtime.bar_index == 0
    assert runtime.close[1] == 1.5
    assert runtime.time_close[0] == second_bar.time + 3_600_000 - 1
    assert runtime.bar_index_series[0] == 1
    assert user_series[1] == 11.0


def test_runtime_indicator_state_is_stable_and_child_context_isolated() -> None:
    runtime = _runtime()
    bucket = runtime.get_indicator_state("L1_C1_ema_1", list)
    same_bucket = runtime.get_indicator_state("L1_C1_ema_1", dict)
    assert bucket is same_bucket

    child = runtime.spawn_child_context(symbol="TEST:BBB", timeframe="5", namespace="req")
    assert child.contract_version == "1.4"
    assert child.request_namespace == "req"
    assert child.syminfo.tickerid == "TEST:BBB"
    assert str(child.timeframe.value) == "5"
    assert child.series_registry is not runtime.series_registry


def test_series_history_allowed_metadata_is_enforced() -> None:
    from pinelib import TypeInfo
    from pinelib.errors import PL_HISTORY_NOT_ALLOWED, PL_REFERENCE_HISTORY_UNSUPPORTED, PineHistoryError

    runtime = _runtime()
    normal = runtime.series("normal", "float")
    normal.set_current(1.0)
    runtime.end_bar() if runtime.current_bar is not None else None
    forbidden = runtime.series("forbidden", "float", type_info=TypeInfo("float", "simple", is_history_allowed=False))
    with pytest.raises(PineHistoryError) as exc:
        _ = forbidden[1]
    assert exc.value.code == PL_HISTORY_NOT_ALLOWED

    ref = runtime.series("ref", "object", type_info=TypeInfo("array", "series", is_reference_type=True))
    with pytest.raises(PineHistoryError) as ref_exc:
        _ = ref[1]
    assert ref_exc.value.code == PL_REFERENCE_HISTORY_UNSUPPORTED

    allowed_bool = runtime.series("flag", "bool", type_info=TypeInfo("bool", "series", is_history_allowed=True))
    assert allowed_bool[1] is False
