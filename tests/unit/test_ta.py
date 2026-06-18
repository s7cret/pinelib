import pytest

from pinelib import (
    Bar,
    PineRuntime,
    PineRuntimeError,
    PineTypeError,
    SymbolInfo,
    TimeframeInfo,
    is_na,
    na,
    ta,
)


def _runtime() -> PineRuntime:
    return PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
        timeframe=TimeframeInfo.from_string("60"),
    )


def _bar(index: int, close: float, high: float | None = None, low: float | None = None) -> Bar:
    high_value = close if high is None else high
    low_value = close if low is None else low
    return Bar(
        time=1_700_000_000_000 + index * 3_600_000,
        open=close,
        high=high_value,
        low=low_value,
        close=close,
        volume=1.0,
    )


def test_stateful_sma_runtime_warmup_and_state_id_isolation() -> None:
    runtime = _runtime()
    outputs_a = []
    outputs_b = []
    for index, value in enumerate([1.0, 2.0, 3.0, 4.0]):
        runtime.begin_bar(_bar(index, value))
        outputs_a.append(ta.sma(runtime.close, 3, runtime=runtime, state_id="L1_C1_sma_1"))
        outputs_b.append(ta.sma(runtime.close, 2, runtime=runtime, state_id="L2_C1_sma_1"))
        runtime.end_bar()

    assert outputs_a[:2] == [na, na]
    assert outputs_a[2:] == [2.0, 3.0]
    assert outputs_b == [na, 1.5, 2.5, 3.5]


def test_batch_and_runtime_ema_rma_rsi_macd_consistency() -> None:
    values = [1.0, 2.0, 3.0, 2.0, 5.0, 8.0, 13.0]
    runtime = _runtime()
    ema_runtime = []
    rma_runtime = []
    rsi_runtime = []
    macd_runtime = []
    for index, value in enumerate(values):
        runtime.begin_bar(_bar(index, value))
        ema_runtime.append(ta.ema(runtime.close, 3, runtime=runtime, state_id="L1_C1_ema_1"))
        rma_runtime.append(ta.rma(runtime.close, 3, runtime=runtime, state_id="L1_C1_rma_1"))
        rsi_runtime.append(ta.rsi(runtime.close, 3, runtime=runtime, state_id="L1_C1_rsi_1"))
        macd_runtime.append(
            ta.macd(runtime.close, 2, 4, 3, runtime=runtime, state_id="L1_C1_macd_1")
        )
        runtime.end_bar()

    assert ema_runtime == ta.ema(values, 3)
    assert rma_runtime == ta.rma(values, 3)
    assert rsi_runtime == ta.rsi(values, 3)
    assert tuple([row[index] for row in macd_runtime] for index in range(3)) == ta.macd(
        values, 2, 4, 3
    )


def test_tr_atr_runtime_and_batch_consistency() -> None:
    highs = [10.0, 12.0, 11.0, 14.0]
    lows = [8.0, 9.0, 8.5, 10.0]
    closes = [9.0, 10.0, 10.5, 13.0]
    runtime = _runtime()
    tr_runtime = []
    atr_runtime = []
    for index, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True)):
        runtime.begin_bar(_bar(index, close, high, low))
        tr_runtime.append(ta.tr(runtime=runtime))
        atr_runtime.append(ta.atr(3, runtime=runtime, state_id="L1_C1_atr_1"))
        runtime.end_bar()

    assert tr_runtime == ta.tr_batch(highs, lows, closes)
    assert atr_runtime == ta.atr(3, high=highs, low=lows, close=closes)


def test_highest_lowest_change_cross_helpers() -> None:
    runtime = _runtime()
    observed = []
    for index, value in enumerate([1.0, 3.0, 2.0, 4.0]):
        runtime.begin_bar(_bar(index, value))
        observed.append(
            (ta.highest(runtime.close, 3), ta.lowest(runtime.close, 3), ta.change(runtime.close))
        )
        runtime.end_bar()

    assert observed[0][0] == 1.0
    assert observed[0][1] == 1.0
    assert is_na(observed[0][2])
    assert observed[-1] == (4.0, 2.0, 2.0)

    left = runtime.series("left", "float")
    right = runtime.series("right", "float")
    runtime.begin_bar(_bar(4, 0.0))
    left.set_current(1.0)
    right.set_current(2.0)
    runtime.end_bar()
    runtime.begin_bar(_bar(5, 0.0))
    left.set_current(3.0)
    right.set_current(2.0)
    assert ta.crossover(left, right)
    assert ta.cross(left, right)
    assert not ta.crossunder(left, right)


def test_stateful_highest_lowest_only_advance_when_call_executes() -> None:
    runtime = _runtime()
    observed: list[tuple[float, float]] = []

    for index, (high, low, should_call) in enumerate(
        [
            (10.0, 9.0, False),
            (12.0, 7.0, True),
            (99.0, 1.0, False),
            (15.0, 6.0, True),
        ]
    ):
        runtime.begin_bar(_bar(index, close=low, high=high, low=low))
        if should_call:
            observed.append(
                (
                    ta.highest(runtime.high, 3, runtime=runtime, state_id="cond_high"),
                    ta.lowest(runtime.low, 3, runtime=runtime, state_id="cond_low"),
                )
            )
        runtime.end_bar()

    # Pine's stateful TA call history is per executed call site, not the global
    # chart series. If the call only executes on bars 2 and 4, length=3 still
    # sees only those two values.
    assert observed == [(12.0, 7.0), (15.0, 6.0)]


def test_highest_lowest_tv_lazy_state_uses_branch_local_call_history() -> None:
    runtime = _runtime()
    lazy_observed: list[tuple[float, float]] = []
    rolling_observed: list[tuple[float, float]] = []

    for index, (high, low, should_call) in enumerate(
        [
            (10.0, 9.0, False),
            (12.0, 7.0, True),
            (99.0, 1.0, False),
            (15.0, 6.0, True),
        ]
    ):
        runtime.begin_bar(_bar(index, close=low, high=high, low=low))
        rolling_observed.append(
            (
                ta.highest(runtime.high, 3, runtime=runtime, state_id="mixed_high"),
                ta.lowest(runtime.low, 3, runtime=runtime, state_id="mixed_low"),
            )
        )
        if should_call:
            lazy_observed.append(
                (
                    ta.highest(
                        runtime.high,
                        3,
                        runtime=runtime,
                        state_id="mixed_high",
                        tv_lazy_state=True,
                    ),
                    ta.lowest(
                        runtime.low,
                        3,
                        runtime=runtime,
                        state_id="mixed_low",
                        tv_lazy_state=True,
                    ),
                )
            )
        runtime.end_bar()

    assert rolling_observed == [(10.0, 9.0), (12.0, 7.0), (99.0, 1.0), (99.0, 1.0)]
    # The tv_lazy_state namespace must not share the ordinary rolling state_id:
    # the skipped bar with high=99/low=1 must not leak into lazy branch results.
    assert lazy_observed == [(12.0, 7.0), (15.0, 6.0)]


def test_ta_rejects_bool_sources_and_unstable_state_lengths() -> None:
    with pytest.raises(PineTypeError):
        ta.sma([True], 1)

    runtime = _runtime()
    runtime.begin_bar(_bar(0, 1.0))
    assert is_na(ta.sma(runtime.close, 3, runtime=runtime, state_id="L1_C1_sma_1"))
    with pytest.raises(PineRuntimeError):
        ta.sma(runtime.close, 2, runtime=runtime, state_id="L1_C1_sma_1")
