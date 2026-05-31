from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(
    reason="legacy PineLib generated-strategy backtest tests; strategy fills and reports now belong to BacktestEngine"
)

from pinelib import (
    Bar,
    PineRuntime,
    RuntimeConfig,
    StrategyContext,
    SymbolInfo,
    TimeframeInfo,
    compare_golden,
    load_bars_csv,
    run_generated_strategy,
)
from pinelib.backtest import BacktestReport, StrategySchedule
from pinelib.errors import PineDataFormatError, PineGoldenMismatchError, PineRuntimeError

BASE = 1704067200000


def bars() -> list[Bar]:
    return [
        Bar(BASE, 10, 11, 9, 10, 100, BASE + 3_599_999),
        Bar(BASE + 3_600_000, 12, 13, 11, 12, 100, BASE + 7_199_999),
        Bar(BASE + 7_200_000, 14, 15, 13, 14, 100, BASE + 10_799_999),
    ]


def runtime(max_recalcs: int = 16) -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:AAA", mintick=0.01),
        TimeframeInfo.from_string("60"),
        config=RuntimeConfig(max_recalculations_per_bar=max_recalcs),
    )


class GeneratedLikeStrategy:
    params = {"qty": 2}
    INPUT_METADATA = {
        "qty": {"title": "Quantity", "type": "float", "default": 2, "minval": 1, "step": 1},
    }

    def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
        if rt.barstate.isnew and rt.bar_index_series.current == 0:
            strategy.entry("L", "long", qty=float(self.params["qty"]))


def test_generated_strategy_runner_snapshots_report_and_params() -> None:
    strategy = StrategyContext(process_orders_on_close=False)
    result = run_generated_strategy(GeneratedLikeStrategy(), runtime(), strategy, bars())

    assert strategy.position_size == 2
    assert strategy.position_avg_price == 12
    assert [s.bar_index for s in result.snapshots] == [0, 1, 2]
    assert result.report.schema_version == "pinelib.backtest.report.v1"
    assert result.report.package_version == "2.17.0"
    assert result.report.params == {"qty": 2}
    qty_metadata = result.report.params_metadata["qty"]
    assert isinstance(qty_metadata, dict)
    assert qty_metadata["default"] == 2
    assert result.report.fills[0]["fill_source"] == "ohlc_path"


def test_process_orders_on_close_integrated_with_runtime_loop() -> None:
    class EnterFirstBar:
        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            if rt.bar_index_series.current == 0:
                strategy.entry("L", "long", qty=1)

    strategy = StrategyContext(process_orders_on_close=True)
    run_generated_strategy(EnterFirstBar(), runtime(), strategy, bars()[:1])
    assert strategy.position_size == 1
    assert strategy.position_avg_price == 10


def test_next_bar_market_fill_is_visible_to_strategy_pass() -> None:
    from pinelib.ta import change

    class CloseSeesClosedTrades:
        def __init__(self) -> None:
            self.closed_seen: list[tuple[int, int]] = []
            self.closed_changes: list[tuple[int, float]] = []

        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            idx = rt.bar_index_series.current
            self.closed_seen.append((idx, int(strategy.closedtrades)))
            delta = change(strategy.closedtrades)
            if delta == 1:
                self.closed_changes.append((idx, delta))
            if idx == 0:
                strategy.entry("L", "long", qty=1)
            if idx == 2:
                strategy.close("L")

    generated = CloseSeesClosedTrades()
    strategy = StrategyContext(process_orders_on_close=False)
    run_generated_strategy(generated, runtime(), strategy, bars() + [
        Bar(BASE + 10_800_000, 16, 17, 15, 16, 100, BASE + 14_399_999),
    ])

    assert generated.closed_seen[-1] == (3, 1)
    assert generated.closed_changes == [(3, 1.0)]
    assert strategy.closedtrades == 1


def test_calc_on_order_fills_guarded_loop() -> None:
    class RecalcAddsSecondOrder:
        def __init__(self) -> None:
            self.calls = 0

        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            self.calls += 1
            if self.calls == 1:
                strategy.entry("L1", "long", qty=1)
            elif strategy.position_size == 1 and self.calls == 2:
                strategy.entry("L2", "long", qty=1)

    generated = RecalcAddsSecondOrder()
    strategy = StrategyContext(process_orders_on_close=True, calc_on_order_fills=True, pyramiding=2)
    run_generated_strategy(generated, runtime(max_recalcs=4), strategy, bars()[:1])
    assert generated.calls == 3  # initial pass + after first fill + after second fill
    assert strategy.position_size == 2

    class InfiniteFillLoop:
        def __init__(self) -> None:
            self.i = 0

        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            self.i += 1
            strategy.entry(f"L{self.i}", "long", qty=1)

    with pytest.raises(PineRuntimeError):
        run_generated_strategy(
            InfiniteFillLoop(),
            runtime(max_recalcs=1),
            StrategyContext(process_orders_on_close=True, calc_on_order_fills=True, pyramiding=99),
            bars()[:1],
            schedule=StrategySchedule(max_recalculations_per_bar=1),
        )


def test_csv_loader_validation_and_aliases(tmp_path: Path) -> None:
    path = tmp_path / "bars.csv"
    path.write_text(
        "timestamp,o,h,l,c,v,time_close\n"
        f"{BASE},10,11,9,10,123,{BASE + 59999}\n"
        f"{BASE + 60000},10,12,9,11,124,{BASE + 119999}\n",
        encoding="utf-8",
    )
    loaded = load_bars_csv(path)
    assert len(loaded) == 2
    assert loaded[0].volume == 123
    assert loaded[0].time_close == BASE + 59999

    bad = tmp_path / "bad.csv"
    bad.write_text("time,open,high,low\n1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(bad)

    unordered = tmp_path / "unordered.csv"
    unordered.write_text("time,open,high,low,close\n2,1,1,1,1\n1,1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(unordered)


def test_compare_golden_tolerances_and_report_schema_json() -> None:
    compare_golden({"equity": [100.0000001]}, {"equity": [100.0]}, abs_tol=1e-5)
    with pytest.raises(PineGoldenMismatchError):
        compare_golden({"equity": 101.0}, {"equity": 100.0}, abs_tol=1e-5)

    strategy = StrategyContext()
    result = run_generated_strategy(lambda rt, s: None, runtime(), strategy, bars()[:1])
    payload = result.report.to_dict()
    assert set(BacktestReport.__dataclass_fields__) <= set(payload)
    assert json.loads(json.dumps(payload))["schema_version"] == "pinelib.backtest.report.v1"
