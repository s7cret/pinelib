from __future__ import annotations

from typing import cast

import pytest

from pinelib import (
    PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK,
    Bar,
    PineRuntime,
    PineStrategyError,
    RuntimeConfig,
    StrategyContext,
    SymbolInfo,
    TickUpdate,
    TimeframeInfo,
    run_generated_strategy,
)


def _bar(i: int, o: float = 10, h: float = 10, low: float = 10, c: float = 10) -> Bar:
    return Bar(time=i * 60_000, open=o, high=h, low=low, close=c, time_close=(i + 1) * 60_000 - 1)


def _rt(config: RuntimeConfig | None = None) -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:D"), TimeframeInfo.from_string("1"), config=config or RuntimeConfig()
    )


def test_realtime_tick_scheduler_updates_barstate_and_builtin_series() -> None:
    rt = _rt()
    rt.begin_realtime_bar(_bar(0, 10, 10, 10, 10))
    first = rt.update_realtime_tick(TickUpdate(price=12, volume=5, time=1_000))
    assert first.high == 12
    assert rt.close.current == 12
    assert rt.volume.current == 5
    assert rt.barstate.isrealtime is True
    assert rt.barstate.isconfirmed is False

    final = rt.update_realtime_tick(TickUpdate(price=9, volume=2, time=2_000, is_final=True))
    assert final.high == 12
    assert final.low == 9
    assert final.close == 9
    assert cast(float, rt.volume.current) == 7
    assert rt.barstate.isconfirmed is True
    rt.end_bar()
    assert rt.bar_index == 0


def test_calc_on_every_tick_runs_each_supplied_tick_and_fills_deterministically() -> None:
    class TickStrategy:
        def __init__(self) -> None:
            self.calls: list[tuple[float, bool]] = []

        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            self.calls.append((cast(float, rt.close.current), rt.barstate.isconfirmed))
            if len(self.calls) == 1:
                strategy.entry("L", "long", qty=1)

    generated = TickStrategy()
    strategy = StrategyContext(calc_on_every_tick=True, process_orders_on_close=True)
    result = run_generated_strategy(
        generated,
        _rt(),
        strategy,
        [_bar(0)],
        realtime_ticks=[[TickUpdate(11, 1), TickUpdate(12, 1, is_final=True)]],
    )

    assert generated.calls == [(11, False), (12, True)]
    assert strategy.position_size == 1
    assert strategy.fills[0].price == 11
    assert result.snapshots[-1].close == 12


def test_runtime_strategy_flag_conflict_fails_closed() -> None:
    rt = _rt(RuntimeConfig(calc_on_every_tick=False))
    with pytest.raises(PineStrategyError):
        StrategyContext(calc_on_every_tick=True).attach_runtime(rt)


def test_fill_orders_on_standard_ohlc_is_captured_but_diagnosed() -> None:
    rt = _rt()
    strategy = StrategyContext(fill_orders_on_standard_ohlc=True)
    strategy.attach_runtime(rt)
    codes = [d["code"] for d in rt.config.diagnostics]
    assert "PL_UNSUPPORTED_STRATEGY_SETTING" in codes


def test_calc_on_every_tick_historical_fallback_emits_once_at_execution() -> None:
    class CountingStrategy:
        def __init__(self) -> None:
            self.calls = 0

        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            del rt, strategy
            self.calls += 1

    generated = CountingStrategy()
    runtime = _rt()
    strategy = StrategyContext(calc_on_every_tick=True)
    strategy.attach_runtime(runtime)
    assert PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK not in [
        d["code"] for d in runtime.config.diagnostics
    ]
    run_generated_strategy(generated, runtime, strategy, [_bar(0), _bar(1)])
    codes = [d["code"] for d in runtime.config.diagnostics]
    assert codes.count(PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK) == 1
    assert generated.calls == 2


def test_calc_on_every_tick_supplied_ticks_do_not_emit_false_fallback() -> None:
    class StateStrategy:
        def __init__(self) -> None:
            self.states: list[tuple[bool, bool, bool]] = []

        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            del strategy
            self.states.append(
                (rt.barstate.ishistory, rt.barstate.isrealtime, rt.barstate.islastconfirmedhistory)
            )

    generated = StateStrategy()
    runtime = _rt()
    strategy = StrategyContext(calc_on_every_tick=True)
    run_generated_strategy(
        generated,
        runtime,
        strategy,
        [_bar(0)],
        realtime_ticks=[[TickUpdate(12, 1), TickUpdate(13, 1, is_final=True)]],
    )
    assert PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK not in [
        d["code"] for d in runtime.config.diagnostics
    ]
    assert generated.states == [(False, True, False), (False, True, False)]


def test_islastconfirmedhistory_marks_historical_bar_before_realtime() -> None:
    class StateStrategy:
        def __init__(self) -> None:
            self.states: list[tuple[bool, bool, bool]] = []

        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            del strategy
            self.states.append(
                (rt.barstate.ishistory, rt.barstate.isrealtime, rt.barstate.islastconfirmedhistory)
            )

    generated = StateStrategy()
    runtime = _rt()
    strategy = StrategyContext(calc_on_every_tick=True)
    run_generated_strategy(
        generated,
        runtime,
        strategy,
        [_bar(0), _bar(1)],
        realtime_ticks=[[], [TickUpdate(12, 1), TickUpdate(13, 1, is_final=True)]],
    )
    assert [d["code"] for d in runtime.config.diagnostics].count(
        PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK
    ) == 1
    assert generated.states == [(True, False, True), (False, True, False), (False, True, False)]
