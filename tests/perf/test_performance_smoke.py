from __future__ import annotations

from time import perf_counter

from pinelib import Bar, PineRuntime, StrategyContext, SymbolInfo, TimeframeInfo, ta


def test_runtime_ta_smoke_benchmark() -> None:
    runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("1"))
    start = perf_counter()
    for index in range(2_000):
        price = 100.0 + (index % 17)
        runtime.begin_bar(
            Bar(
                time=1_700_000_000_000 + index * 60_000,
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
            )
        )
        ta.sma(runtime.close, 20, runtime=runtime, state_id="bench:sma")
        ta.ema(runtime.close, 20, runtime=runtime, state_id="bench:ema")
        ta.rsi(runtime.close, 14, runtime=runtime, state_id="bench:rsi")
        runtime.end_bar()
    elapsed = perf_counter() - start
    assert elapsed < 5.0


def test_strategy_intent_smoke_benchmark() -> None:
    runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("1"))
    strategy = StrategyContext(pyramiding=1)
    strategy.attach_runtime(runtime)
    start = perf_counter()
    for index in range(1_000):
        price = 100.0 + (index % 5)
        bar = Bar(
            time=1_700_000_000_000 + index * 60_000,
            time_close=1_700_000_000_000 + index * 60_000 + 59_999,
            open=price,
            high=price + 2,
            low=price - 2,
            close=price,
        )
        runtime.begin_bar(bar)
        if index % 100 == 0:
            strategy.entry(f"L{index}", "long", qty=1)
        elif index % 100 == 50:
            strategy.close_all()
        runtime.end_bar()
    elapsed = perf_counter() - start
    assert elapsed < 5.0
