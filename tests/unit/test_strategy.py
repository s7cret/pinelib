from pinelib import Bar, PineRuntime, RuntimeConfig, StrategyContext, SymbolInfo, TimeframeInfo
from pinelib.errors import PL_WARNING_EXIT_QTY_REDUCED


def rt(strategy: StrategyContext | None = None) -> PineRuntime:
    runtime = PineRuntime(SymbolInfo("TEST:AAA", mintick=0.01), TimeframeInfo.from_string("60"), config=RuntimeConfig())
    if strategy:
        strategy.attach_runtime(runtime)
    return runtime


def bar(i: int, o: float, h: float, l: float, c: float) -> Bar:
    t = 1704067200000 + i * 3_600_000
    return Bar(time=t, time_close=t + 3_599_999, open=o, high=h, low=l, close=c)


def process(runtime: PineRuntime, strategy: StrategyContext, b: Bar) -> None:
    runtime.begin_bar(b)
    strategy.process_orders_for_bar(runtime=runtime, bar=b)
    runtime.end_bar()


def test_market_entry_fills_next_bar_open() -> None:
    s = StrategyContext(default_qty_value=2)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))
    s.entry("L", "long")
    s.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, s, bar(1, 20, 21, 19, 20))
    assert s.position_size == 2
    assert s.position_avg_price == 20


def test_process_orders_on_close_market_fills_current_close() -> None:
    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))
    s.entry("L", "long")
    s.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    assert s.position_size == 1
    assert s.position_avg_price == 11


def test_limit_stop_ohlc_path_ordering_and_gap_open_fill() -> None:
    s = StrategyContext()
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 15, 8, 12))
    s.order("buy_limit", "long", qty=1, limit=9)
    s.order("buy_stop", "long", qty=1, stop=14)
    s.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, s, bar(1, 20, 25, 18, 22))
    assert [f.order_id for f in s.fills] == ["buy_stop"]
    assert s.fills[0].price == 20


def test_entry_reversal_and_pyramiding() -> None:
    s = StrategyContext(pyramiding=1)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 11, 9, 10))
    s.entry("L1", "long", qty=1)
    s.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, s, bar(1, 10, 11, 9, 10))
    s.entry("L2", "long", qty=1)
    process(runtime, s, bar(2, 10, 11, 9, 10))
    assert s.position_size == 1
    runtime.begin_bar(bar(3, 10, 11, 9, 10))
    s.entry("S", "short", qty=2)
    s.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, s, bar(4, 10, 11, 9, 10))
    assert s.position_size == -2
    assert s.closedtrades == 1


def test_exit_reservation_reduction_and_bracket_oca() -> None:
    s = StrategyContext()
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 11, 9, 10))
    s.entry("L", "long", qty=3)
    s.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, s, bar(1, 10, 11, 9, 10))
    runtime.begin_bar(bar(2, 10, 11, 9, 10))
    s.exit("x1", "L", qty=2, limit=12, stop=8)
    s.exit("x2", "L", qty=2, limit=13)
    assert any(d["code"] == PL_WARNING_EXIT_QTY_REDUCED for d in runtime.config.diagnostics)
    s.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, s, bar(3, 10, 12, 7, 9))
    assert s.position_size == 1
    assert all(o.parent_exit_id != "x1" for o in s.pending_orders)


def test_commission_slippage_and_percent_sizing() -> None:
    s = StrategyContext(default_qty_type="percent_of_equity", default_qty_value=10, commission_type="percent", commission_value=1, slippage=0.5)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 11, 9, 10))
    s.entry("L", "long")
    s.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, s, bar(1, 10, 11, 9, 10))
    assert round(s.position_size, 6) == 1000.0
    assert s.position_avg_price == 10.5
    assert s.equity < s.initial_capital
