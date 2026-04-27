from __future__ import annotations

from pathlib import Path

import pytest

from pinelib import (
    Bar,
    PineRuntime,
    RuntimeConfig,
    StrategyContext,
    SymbolInfo,
    TimeframeInfo,
    assert_strategy_report_close,
    compare_indicator_fixture,
    compare_strategy_reports,
    default_sample_contracts,
    load_tradingview_indicator_csv,
    load_tradingview_trades_csv,
    run_generated_strategy,
)
from pinelib.errors import PL_MARGIN_FIELDS_DIAGNOSTIC, PL_UNSUPPORTED_STRATEGY_SETTING, PineGoldenMismatchError, PineStrategyError


BASE = 1704067200000


def bars() -> list[Bar]:
    return [
        Bar(BASE, 10, 10, 10, 10),
        Bar(BASE + 60_000, 11, 11, 11, 11),
        Bar(BASE + 120_000, 12, 12, 12, 12),
        Bar(BASE + 180_000, 13, 13, 13, 13),
    ]


def runtime(strict: bool = False) -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:PARITY", mintick=0.01),
        TimeframeInfo.from_string("1"),
        config=RuntimeConfig(strict_tv_parity=strict),
    )


def test_tradingview_indicator_and_trades_fixture_loader(tmp_path: Path) -> None:
    indicators = tmp_path / "tv_indicators.csv"
    indicators.write_text(
        "time,plot_sma,signal,label\n"
        f"{BASE},10.0,na,buy\n"
        f"{BASE + 60_000},10.5,1,\n",
        encoding="utf-8",
    )
    fixture = load_tradingview_indicator_csv(indicators)
    assert fixture.time == [BASE, BASE + 60_000]
    assert fixture.columns["plot_sma"] == [10.0, 10.5]
    assert fixture.columns["signal"] == [None, 1]

    report = compare_indicator_fixture({"plot_sma": [10.00001, 10.49999]}, fixture, columns=["plot_sma"], abs_tol=1e-3)
    assert report.matches
    bad = compare_indicator_fixture({"plot_sma": [9.0, 10.5]}, fixture, columns=["plot_sma"], abs_tol=1e-6)
    assert not bad.matches
    assert bad.mismatches[0]["field"] == "plot_sma"

    trades = tmp_path / "tv_trades.csv"
    trades.write_text("Trade #,Type,Price,Contracts\n1,Exit Long,12.5,2\n", encoding="utf-8")
    assert load_tradingview_trades_csv(trades)[0]["Price"] == 12.5


def test_strategy_compare_reports_and_assertions() -> None:
    actual = {"final_equity": 1000.001, "netprofit": 0.001, "closedtrades": 2, "max_drawdown": 0.0}
    expected = {"final_equity": 1000.0, "netprofit": 0.0, "closedtrades": 2, "max_drawdown": 0.0}
    report = compare_strategy_reports(actual, expected, abs_tol=0.01)
    assert report.matches
    assert report.max_abs_diff == pytest.approx(0.001)
    assert_strategy_report_close(actual, expected, abs_tol=0.01)
    with pytest.raises(PineGoldenMismatchError):
        assert_strategy_report_close(actual, expected, fields=["final_equity"], abs_tol=1e-6, rel_tol=0.0)


def test_strategy_trade_and_equity_tolerance_report() -> None:
    class RoundTrip:
        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            if rt.bar_index_series.current == 0:
                strategy.entry("L", "long", qty=1)
            if rt.bar_index_series.current == 2:
                strategy.close("L")

    result = run_generated_strategy(RoundTrip(), runtime(), StrategyContext(process_orders_on_close=True), bars())
    expected = result.report.to_dict() | {"final_equity": result.report.final_equity + 0.0001}
    report = compare_strategy_reports(result.report.to_dict(), expected, fields=["final_equity", "closedtrades"], abs_tol=0.001)
    assert report.matches
    assert result.report.closed_trades[0]["profit"] == pytest.approx(2.0)


def test_close_entries_rule_fifo_vs_any_basics() -> None:
    class TwoEntriesCloseSecond:
        def on_bar(self, rt: PineRuntime, strategy: StrategyContext) -> None:
            idx = rt.bar_index_series.current
            if idx == 0:
                strategy.entry("L1", "long", qty=1)
            if idx == 1:
                strategy.entry("L2", "long", qty=1)
            if idx == 2:
                strategy.exit("X", from_entry="L2")

    fifo = StrategyContext(process_orders_on_close=True, pyramiding=2, close_entries_rule="FIFO")
    run_generated_strategy(TwoEntriesCloseSecond(), runtime(), fifo, bars())
    assert fifo.closed_trade_log[0].entry_id == "L1"

    any_rule = StrategyContext(process_orders_on_close=True, pyramiding=2, close_entries_rule="ANY")
    run_generated_strategy(TwoEntriesCloseSecond(), runtime(), any_rule, bars())
    assert any_rule.closed_trade_log[0].entry_id == "L2"


def test_unsupported_strategy_settings_strict_and_non_strict_and_margin_diag() -> None:
    non_strict_runtime = runtime()
    strategy = StrategyContext(backtest_fill_limits_assumption=1, margin_long=50, margin_short=75)
    strategy.attach_runtime(non_strict_runtime)
    codes = [diag["code"] for diag in non_strict_runtime.config.diagnostics]
    assert PL_UNSUPPORTED_STRATEGY_SETTING in codes
    assert PL_MARGIN_FIELDS_DIAGNOSTIC in codes

    with pytest.raises(PineStrategyError):
        StrategyContext(backtest_fill_limits_assumption=1).attach_runtime(runtime(strict=True))


def test_avax_sol_xlm_sample_contract_scaffold() -> None:
    contracts = default_sample_contracts()
    assert sorted(contracts) == ["AVAX", "SOL", "XLM"]
    assert contracts["SOL"].indicator_export_csv.endswith("tradingview_indicators.csv")
