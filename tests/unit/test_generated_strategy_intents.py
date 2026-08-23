from __future__ import annotations

from pinelib import (
    Bar,
    PineRuntime,
    RuntimeConfig,
    StrategyContext,
    SymbolInfo,
    TimeframeInfo,
    run_generated_strategy,
)
from tests.rc4_fixtures import COMMIT, execution_context

BASE = 1704067200000


def _execution_context() -> dict[str, object]:
    return execution_context(
        series_id="TEST:AAA:60",
        instrument_id="TEST:AAA",
        exchange="TEST",
        market="stock",
        symbol="AAA",
        timeframe="60",
    )


def bars() -> list[Bar]:
    return [
        Bar(BASE, 10, 11, 9, 10, 100, BASE + 3_599_999),
        Bar(BASE + 3_600_000, 12, 13, 11, 12, 100, BASE + 7_199_999),
    ]


def runtime() -> PineRuntime:
    return PineRuntime(
        SymbolInfo(
            "TEST:AAA",
            timezone="UTC",
            session="regular",
            mintick=0.01,
            exchange="TEST",
            type="stock",
            currency="USD",
            pointvalue=1.0,
        ),
        TimeframeInfo.from_string("60"),
        config=RuntimeConfig(semantic_profile="strict_5x"),
    )


def test_generated_strategy_runner_records_intents_without_broker_execution() -> None:
    class GeneratedLikeStrategy:
        params = {"qty": 2}
        INPUT_METADATA = {
            "qty": {"title": "Quantity", "type": "float", "default": 2, "minval": 1},
        }

        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            if rt.bar_index_series.current == 0:
                strategy.entry("L", "long", qty=float(self.params["qty"]))
            if rt.bar_index_series.current == 1:
                strategy.exit("XL", "L", qty_percent=50, profit=4, loss=2)
                strategy.close("L", qty_percent=25, immediately=True)

    strategy = StrategyContext(
        process_orders_on_close=True,
        intent_producer_commit=COMMIT,
        intent_strict_production=True,
        intent_execution_context=_execution_context(),
    )
    result = run_generated_strategy(GeneratedLikeStrategy(), runtime(), strategy, bars())

    assert [snapshot.order_intents_count for snapshot in result.snapshots] == [1, 3]
    assert result.report.schema_version == "pinelib.generated_strategy.intent_report.v1"
    assert result.report.execution_mode == "intent_only"
    assert result.report.broker_authority == "backtest_engine"
    assert result.report.final_equity is None
    assert result.report.netprofit is None
    assert result.report.closedtrades is None
    assert result.report.fills == []
    assert result.report.closed_trades == []
    assert result.report.params == {"qty": 2}
    assert result.report.params_metadata["qty"]["default"] == 2
    payload = result.report.to_dict()
    assert payload["order_intents"] == result.report.order_intents
    assert payload["snapshots"][0]["position_size"] is None
    assert payload["snapshots"][0]["fills_count"] is None
    assert payload["snapshots"][0]["closedtrades"] is None

    entry_intent, exit_intent, close_intent = result.report.order_intents
    assert entry_intent["id"] == "L"
    assert entry_intent["direction"] == "long"
    assert entry_intent["qty"] == 2.0

    assert exit_intent["id"] == "XL"
    assert exit_intent["direction"] is None
    assert exit_intent["from_entry"] == "L"
    assert exit_intent["qty_percent"] == 50
    assert exit_intent["profit"] == 4
    assert exit_intent["loss"] == 2
    assert exit_intent["bracket_group"] == "XL"
    assert exit_intent["oca_type"] == "reduce"

    assert close_intent["id"] == "close:L"
    assert close_intent["direction"] is None
    assert close_intent["from_entry"] == "L"
    assert close_intent["qty_percent"] == 25
    assert close_intent["immediate"] is True


def test_broker_projection_hook_runs_before_each_interactive_callback() -> None:
    seen_equity: list[float] = []
    hook_calls: list[float] = []

    class Ledger:
        def __init__(self, equity: float) -> None:
            self.equity = equity

    class InteractiveStrategy:
        def on_bar(self, _rt: PineRuntime, strategy: StrategyContext) -> None:
            seen_equity.append(strategy.equity)

    def project(rt: PineRuntime, _strategy: StrategyContext) -> Ledger:
        value = float(rt.close.current)
        hook_calls.append(value)
        return Ledger(value)

    from pinelib.core.types import TickUpdate

    strategy = StrategyContext(
        calc_on_every_tick=True,
        intent_producer_commit=COMMIT,
        intent_strict_production=True,
        intent_execution_context=_execution_context(),
    )
    tick_values = [10.5, 11.0]
    run_generated_strategy(
        InteractiveStrategy(),
        runtime(),
        strategy,
        bars()[:1],
        realtime_ticks=[
            [
                TickUpdate(tick_values[0], 1.0, BASE + 1, False),
                TickUpdate(tick_values[1], 1.0, BASE + 2, True),
            ]
        ],
        broker_projection_callback=project,
    )

    assert hook_calls == tick_values
    assert seen_equity == tick_values
