from pinelib import Bar, PineRuntime, RuntimeConfig, StrategyContext, SymbolInfo, TimeframeInfo
from pinelib.errors import PL_WARNING_EXIT_QTY_REDUCED


def rt(strategy: StrategyContext | None = None) -> PineRuntime:
    runtime = PineRuntime(
        SymbolInfo("TEST:AAA", mintick=0.01),
        TimeframeInfo.from_string("60"),
        config=RuntimeConfig(),
    )
    if strategy:
        strategy.attach_runtime(runtime)
    return runtime


def bar(i: int, o: float, h: float, low: float, c: float) -> Bar:
    t = 1704067200000 + i * 3_600_000
    return Bar(time=t, time_close=t + 3_599_999, open=o, high=h, low=low, close=c)


def process(runtime: PineRuntime, strategy: StrategyContext, b: Bar) -> None:
    runtime.begin_bar(b)
    strategy.process_orders_for_bar(runtime=runtime, bar=b)
    runtime.end_bar()


def current_bar(runtime: PineRuntime) -> Bar:
    assert runtime.current_bar is not None
    return runtime.current_bar


def test_market_entry_fills_next_bar_open() -> None:
    s = StrategyContext(default_qty_value=2)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))
    s.entry("L", "long")
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(1, 20, 21, 19, 20))
    assert s.position_size == 2
    assert s.position_avg_price == 20


def test_strategy_close_accepts_comment() -> None:
    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))
    s.entry("L", "long")
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    s.close("L", comment="P4_CLOSE_LONG")
    assert s.pending_orders[-1].comment == "P4_CLOSE_LONG"
    runtime.end_bar()


def test_strategy_entry_accepts_comment() -> None:
    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))
    s.entry("L", "long", comment="P4_LONG_SuperTrend")
    assert s.pending_orders[-1].comment == "P4_LONG_SuperTrend"
    runtime.end_bar()


def test_strategy_entry_accepts_dynamic_comment() -> None:
    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))
    engine = "MACD"
    s.entry("L", "long", comment=f"P4_LONG_{engine}")
    assert s.pending_orders[-1].comment == "P4_LONG_MACD"
    runtime.end_bar()


def test_strategy_exit_accepts_comment() -> None:
    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))
    runtime.begin_bar(bar(1, 10, 12, 9, 11))
    s.entry("L", "long", qty=1.0)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    s.exit("XL", from_entry="L", comment="TP_hit", limit=12.0)
    assert s.pending_orders[-1].comment == "TP_hit"
    runtime.end_bar()


def test_strategy_exit_accepts_comment_and_order_model_has_comment() -> None:
    from pinelib.strategy.context import Order
    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))
    runtime.begin_bar(bar(1, 10, 12, 9, 11))
    s.entry("L", "long", qty=1.0)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    s.exit("XL", from_entry="L", comment="stop_loss", stop=9.0)
    last = s.pending_orders[-1]
    assert last.comment == "stop_loss"
    runtime.end_bar()


def test_order_model_accepts_comment_field() -> None:
    from pinelib.strategy.context import Order
    o = Order(id="test", direction="long", qty=1.0, type="market", kind="entry", comment="test_comment")
    assert o.comment == "test_comment"


def test_process_orders_on_close_market_fills_current_close() -> None:
    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))
    s.entry("L", "long")
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    assert s.position_size == 1
    assert s.position_avg_price == 11


def test_limit_stop_ohlc_path_ordering_and_gap_open_fill() -> None:
    s = StrategyContext()
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 15, 8, 12))
    s.order("buy_limit", "long", qty=1, limit=9)
    s.order("buy_stop", "long", qty=1, stop=14)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(1, 20, 25, 18, 22))
    assert [f.order_id for f in s.fills] == ["buy_stop"]
    assert s.fills[0].price == 20


def test_entry_reversal_and_pyramiding() -> None:
    s = StrategyContext(pyramiding=1)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 11, 9, 10))
    s.entry("L1", "long", qty=1)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(1, 10, 11, 9, 10))
    s.entry("L2", "long", qty=1)
    process(runtime, s, bar(2, 10, 11, 9, 10))
    assert s.position_size == 1
    runtime.begin_bar(bar(3, 10, 11, 9, 10))
    s.entry("S", "short", qty=2)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(4, 10, 11, 9, 10))
    assert s.position_size == -2
    assert s.closedtrades == 1


def test_exit_reservation_reduction_and_bracket_oca() -> None:
    s = StrategyContext()
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 11, 9, 10))
    s.entry("L", "long", qty=3)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(1, 10, 11, 9, 10))
    runtime.begin_bar(bar(2, 10, 11, 9, 10))
    s.exit("x1", "L", qty=2, limit=12, stop=8)
    s.exit("x2", "L", qty=2, limit=13)
    assert any(d["code"] == PL_WARNING_EXIT_QTY_REDUCED for d in runtime.config.diagnostics)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(3, 10, 12, 7, 9))
    assert s.position_size == 1
    assert all(o.parent_exit_id != "x1" for o in s.pending_orders)


def test_commission_slippage_and_percent_sizing() -> None:
    s = StrategyContext(
        default_qty_type="percent_of_equity",
        default_qty_value=10,
        commission_type="percent",
        commission_value=1,
        slippage=0.5,
    )
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 11, 9, 10))
    s.entry("L", "long")
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(1, 10, 11, 9, 10))
    assert round(s.position_size, 6) == 1000.0
    assert s.position_avg_price == 10.5
    assert s.equity < s.initial_capital


def test_max_runup_tracks_monotonic_mark_to_market_gain() -> None:
    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 10, 10, 10))
    s.entry("L", "long", qty=1)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(1, 15, 15, 15, 15))
    assert s.max_runup == 5.0
    assert s.max_drawdown == 0.0


def test_max_drawdown_tracks_drop_from_prior_equity_peak() -> None:
    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 10, 10, 10))
    s.entry("L", "long", qty=1)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(1, 15, 15, 15, 15))
    process(runtime, s, bar(2, 12, 12, 12, 12))
    assert s.max_runup == 5.0
    assert s.max_drawdown == 3.0


def test_open_position_mark_to_market_updates_risk_metrics_and_report() -> None:
    from pinelib.backtest import build_backtest_report

    s = StrategyContext(process_orders_on_close=True)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 10, 10, 10))
    s.entry("L", "long", qty=2)
    s.process_orders_for_bar(runtime=runtime, bar=current_bar(runtime))
    runtime.end_bar()
    process(runtime, s, bar(1, 13, 13, 13, 13))
    assert s.openprofit == 6.0
    assert s.max_runup == 6.0
    report = build_backtest_report(runtime, s, object())
    assert report.max_runup == s.max_runup
    assert report.max_drawdown == s.max_drawdown


def test_daily_time_session_uses_bar_open_not_inferred_daily_close():
    from pinelib.core import Bar, PineRuntime, SymbolInfo, TimeframeInfo

    rt = PineRuntime(SymbolInfo("NASDAQ:AAPL", timezone="America/New_York"), TimeframeInfo.from_string("1D"))
    # 2026-04-28 13:30 UTC / 09:30 New York, a regular US equity daily open.
    rt.begin_bar(Bar(time=1777383000000, open=1, high=1, low=1, close=1))
    try:
        assert rt.timefunc.time("D", "0930-1600", "America/New_York", runtime=rt) == 1777383000000
    finally:
        rt.end_bar()
