from __future__ import annotations

import pytest
from typing import cast

from pinelib import (
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


def _bar(i: int, o: float = 10, h: float = 10, l: float = 10, c: float = 10) -> Bar:
    return Bar(time=i * 60_000, open=o, high=h, low=l, close=c, time_close=(i + 1) * 60_000 - 1)


def _rt(config: RuntimeConfig | None = None) -> PineRuntime:
    return PineRuntime(SymbolInfo("TEST:D"), TimeframeInfo.from_string("1"), config=config or RuntimeConfig())


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
    assert rt.volume.current == 7
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
