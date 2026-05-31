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

BASE = 1704067200000


def bars() -> list[Bar]:
    return [
        Bar(BASE, 10, 11, 9, 10, 100, BASE + 3_599_999),
        Bar(BASE + 3_600_000, 12, 13, 11, 12, 100, BASE + 7_199_999),
    ]


def runtime() -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:AAA", mintick=0.01),
        TimeframeInfo.from_string("60"),
        config=RuntimeConfig(),
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

    strategy = StrategyContext(process_orders_on_close=True)
    result = run_generated_strategy(GeneratedLikeStrategy(), runtime(), strategy, bars())

    assert [snapshot.order_intents_count for snapshot in result.snapshots] == [1, 3]
    assert result.report.schema_version == "pinelib.generated_strategy.intent_report.v1"
    assert result.report.execution_mode == "intent_only"
    assert result.report.broker_authority == "backtest_engine"
    assert result.report.final_equity is None
    assert result.report.fills == []
    assert result.report.closed_trades == []
    assert result.report.params == {"qty": 2}
    assert result.report.params_metadata["qty"]["default"] == 2

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
