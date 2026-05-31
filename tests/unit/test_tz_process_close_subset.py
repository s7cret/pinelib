import pytest

from pinelib import Bar, PineRuntime, RuntimeConfig, StrategyContext, SymbolInfo, TimeframeInfo

pytestmark = pytest.mark.skip(
    reason="legacy PineLib process-orders-on-close tests; order execution now belongs to BacktestEngine"
)


def _runtime(strategy: StrategyContext) -> PineRuntime:
    runtime = PineRuntime(
        SymbolInfo("TEST:AAA", mintick=0.01),
        TimeframeInfo.from_string("60"),
        config=RuntimeConfig(),
    )
    strategy.attach_runtime(runtime)
    return runtime


def _bar(i: int, o: float, h: float, low: float, c: float) -> Bar:
    t = 1704067200000 + i * 3_600_000
    return Bar(time=t, time_close=t + 3_599_999, open=o, high=h, low=low, close=c)


def test_process_orders_on_close_current_bar_limit_ignores_intrabar_path_until_close() -> None:
    strategy = StrategyContext(process_orders_on_close=True)
    runtime = _runtime(strategy)

    runtime.begin_bar(_bar(0, 10, 12, 8, 11))
    strategy.order("L", "long", qty=1, limit=9)
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)
    runtime.end_bar()

    assert strategy.position_size == 0
    assert strategy.fills == []


def test_process_orders_on_close_current_bar_limit_can_fill_at_close_only() -> None:
    strategy = StrategyContext(process_orders_on_close=True)
    runtime = _runtime(strategy)

    runtime.begin_bar(_bar(0, 10, 12, 8, 8.5))
    strategy.order("L", "long", qty=1, limit=9)
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)
    runtime.end_bar()

    assert strategy.position_size == 1
    assert strategy.fills[0].order_id == "L"
    assert strategy.fills[0].price == 8.5


def test_process_orders_on_close_stop_limit_does_not_use_current_bar_intrabar_stop() -> None:
    strategy = StrategyContext(process_orders_on_close=True)
    runtime = _runtime(strategy)

    runtime.begin_bar(_bar(0, 10, 15, 9, 10))
    strategy.order("SL", "long", qty=1, stop=14, limit=14)
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)
    runtime.end_bar()

    assert strategy.position_size == 0
    assert strategy.fills == []
