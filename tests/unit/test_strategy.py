import pytest

from pinelib import (
    Bar,
    PineRuntime,
    RuntimeConfig,
    StrategyContext,
    StrategyLedgerUnavailableError,
    SymbolInfo,
    TimeframeInfo,
)
from pinelib.errors import PineStrategyError


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


def test_strategy_context_records_entry_intent_without_filling() -> None:
    s = StrategyContext(default_qty_value=2)
    runtime = rt(s)
    runtime.begin_bar(bar(0, 10, 12, 9, 11))

    s.entry("L", "long", comment="signal")

    order = s.pending_orders[-1]
    assert (order.id, order.direction, order.qty, order.kind, order.comment) == (
        "L",
        "long",
        None,
        "entry",
        "signal",
    )
    with pytest.raises(PineStrategyError, match="records order intents only"):
        s.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]


def test_strategy_context_records_exit_close_cancel_intents() -> None:
    s = StrategyContext()

    s.exit("XL", from_entry="L", qty=1, limit=12, stop=9, comment="bracket")
    s.close("L", comment="flatten")
    s.cancel("XL")

    exit_order, close_order = s.pending_orders
    assert exit_order.kind == "exit"
    assert exit_order.from_entry == "L"
    assert exit_order.status == "cancelled"
    assert close_order.kind == "close"
    assert close_order.from_entry == "L"
    assert close_order.comment == "flatten"


def test_broker_owned_state_requires_strategy_ledger_view() -> None:
    s = StrategyContext()

    with pytest.raises(StrategyLedgerUnavailableError):
        _ = s.equity
    with pytest.raises(StrategyLedgerUnavailableError):
        _ = s.max_runup
    with pytest.raises(StrategyLedgerUnavailableError):
        s.closedtrades_max_runup(0)


def test_broker_owned_state_uses_strategy_ledger_view() -> None:
    class Ledger:
        equity = 10005.0
        netprofit = 5.0
        openprofit = 0.0
        grossprofit = 6.0
        grossloss = -1.0
        position_size = 2.0
        position_avg_price = 10.0
        position_entry_name = "L"
        opentrades = 1
        wintrades = 1
        losstrades = 0
        eventrades = 0
        max_drawdown = 3.0
        max_runup = 8.0
        fills = ()
        closed_trade_log = ()
        open_trade_log = ()

        def closedtrades_max_runup(self, index: int) -> float:
            return 11.0 + index

        def closedtrades_max_drawdown(self, index: int) -> float:
            return 3.0 + index

        def opentrades_max_runup(self, index: int) -> float:
            return 7.0 + index

        def opentrades_max_drawdown(self, index: int) -> float:
            return 2.0 + index

    s = StrategyContext(strategy_ledger_view=Ledger())

    assert s.equity == 10005.0
    assert s.position_size == 2.0
    assert s.max_runup == 8.0
    assert s.closedtrades_max_runup(0) == 11.0
    assert s.opentrades_max_drawdown(0) == 2.0


def test_risk_api_registers_risk_rules_only() -> None:
    s = StrategyContext()

    s.risk_allow_entry_in("long")
    s.risk_max_drawdown(10, "percent_of_equity")
    s.risk_max_position_size(3)

    assert [(r.name, r.value, r.value_type, r.direction) for r in s.risk_rules] == [
        ("allow_entry_in", None, None, "long"),
        ("max_drawdown", 10.0, "percent_of_equity", None),
        ("max_position_size", 3.0, "fixed", None),
    ]


def test_daily_time_session_uses_bar_open_not_inferred_daily_close():
    from pinelib.core import Bar, PineRuntime, SymbolInfo, TimeframeInfo

    rt = PineRuntime(SymbolInfo("NASDAQ:AAPL", timezone="America/New_York"), TimeframeInfo.from_string("1D"))
    # 2026-04-28 13:30 UTC / 09:30 New York, a regular US equity daily open.
    rt.begin_bar(Bar(time=1777383000000, open=1, high=1, low=1, close=1))
    try:
        assert rt.timefunc.time("D", "0930-1600", "America/New_York", runtime=rt) == 1777383000000
    finally:
        rt.end_bar()
