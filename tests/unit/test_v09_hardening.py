from __future__ import annotations

import pytest

import pinelib
from pinelib import (
    Bar,
    InMemoryDataProvider,
    PineArray,
    PineRuntime,
    PineRuntimeError,
    RuntimeConfig,
    StrategyContext,
    SymbolInfo,
    TimeframeInfo,
    VisualRecorder,
    is_na,
    security,
    ta,
)
from pinelib.errors import PineRequestError, PineSessionError, PineTypeError


def _bar(index: int, close: float = 10.0, *, time: int | None = None) -> Bar:
    start = 1_704_067_200_000 + index * 3_600_000 if time is None else time
    return Bar(
        time=start,
        time_close=start + 3_599_999,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
    )


def _runtime() -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
        TimeframeInfo.from_string("60"),
        config=RuntimeConfig(),
    )


def test_public_api_all_is_stable_sorted_and_exports_version() -> None:
    names = pinelib.__all__
    assert len(names) == len(set(names))
    assert names == sorted(names)
    assert pinelib.__version__ == "2.17.0"
    for name in names:
        assert hasattr(pinelib, name), name


def test_strategy_stop_limit_waits_for_stop_then_fills_at_limit() -> None:
    strategy = StrategyContext()
    runtime = _runtime()
    runtime.begin_bar(_bar(0, 10))
    strategy.attach_runtime(runtime)
    strategy.order("SL", "long", qty=1, stop=12, limit=9)
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()

    runtime.begin_bar(
        Bar(time=_bar(1).time, time_close=_bar(1).time_close, open=10, high=13, low=8, close=11)
    )
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    assert strategy.fills[-1].order_id == "SL"
    assert strategy.fills[-1].price == 9


def test_strategy_any_close_rule_prefers_requested_entry_id() -> None:
    strategy = StrategyContext(close_entries_rule="ANY", pyramiding=2)
    runtime = _runtime()
    strategy.attach_runtime(runtime)
    for idx, entry_id in enumerate(["A", "B"]):
        runtime.begin_bar(_bar(idx, 10 + idx))
        strategy.entry(entry_id, "long", qty=1)
        strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
        runtime.end_bar()
        runtime.begin_bar(_bar(idx + 10, 10 + idx))
        strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
        runtime.end_bar()
    runtime.begin_bar(_bar(20, 12))
    strategy.exit("XB", from_entry="B", qty=1)
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    runtime.begin_bar(_bar(21, 12))
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    assert strategy.closed_trade_log[-1].entry_id == "B"
    assert strategy.position_entry_name == "A"


def test_request_security_invalid_merge_args_and_missing_symbol_ignore() -> None:
    chart = [_bar(0), _bar(1)]
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart})
    runtime = PineRuntime(
        SymbolInfo("TEST:AAA"),
        TimeframeInfo.from_string("60"),
        data_provider=provider,
        config=RuntimeConfig(),
    )
    runtime.chart_bars = chart
    runtime.begin_bar(chart[0])
    assert is_na(
        security(
            "MISSING", "60", [1.0], runtime=runtime, state_id="missing", ignore_invalid_symbol=True
        )
    )
    with pytest.raises(PineRequestError):
        pinelib.merge_requested_series_to_chart_bars([1.0], requested_bars=[], chart_bars=chart)
    with pytest.raises(PineRequestError):
        pinelib.merge_requested_series_to_chart_bars(
            [1.0], requested_bars=[chart[0]], chart_bars=chart, gaps="bad"
        )


def test_session_dst_fall_back_ambiguous_hours_use_timezone_database() -> None:
    runtime = PineRuntime(
        SymbolInfo("TEST:AAA", timezone="America/New_York", session="0000-2359:1234567"),
        TimeframeInfo.from_string("60"),
    )
    # 2024-11-03 05:30Z and 06:30Z are both 01:30 local on different DST folds.
    for timestamp in (1_730_610_600_000, 1_730_614_200_000):
        runtime.begin_bar(
            Bar(time=timestamp, time_close=timestamp + 3_599_999, open=1, high=1, low=1, close=1)
        )
        assert runtime.timefunc.hour(runtime=runtime) == 1
        assert runtime.timefunc.time(runtime=runtime) == timestamp
        runtime.end_bar()
    with pytest.raises(PineSessionError):
        runtime.timefunc.hour(runtime=runtime, timezone="Not/AZone")


def test_input_edge_validation_and_visual_reference_edges() -> None:
    runtime = _runtime()
    with pytest.raises(PineRuntimeError):
        runtime.inputs.float("bad_bool", True)
    with pytest.raises(PineRuntimeError):
        runtime.inputs.int("bad_range", 5, minval=10, maxval=1)
    with pytest.raises(PineRuntimeError):
        runtime.inputs.string("bad_option", "x", options=["y"])

    recorder = VisualRecorder(max_lines_count=1)
    line = recorder.line_new(x1=1, x2=2)
    recorder.delete(line)
    with pytest.raises(PineRuntimeError):
        recorder.set(line, x1=3)

    arr = PineArray([1, 2])
    assert list(arr) == [1, 2]


def test_ta_edge_validation_for_lengths_and_bool_scalars() -> None:
    with pytest.raises(PineRuntimeError):
        ta.sma([1, 2], 0)
    with pytest.raises(PineRuntimeError):
        ta.macd([1, 2, 3], 5, 3, 2)
    with pytest.raises(PineTypeError):
        ta.change(True)
