from __future__ import annotations

import json
from pathlib import Path

import pytest

from pinelib import Bar, PineRuntime, RuntimeConfig, StrategyContext, SymbolInfo, TimeframeInfo, na
from pinelib.core.timefunc import TimeFunctions, is_timestamp_in_session, parse_session
from pinelib.errors import (
    PineDataFormatError,
    PineGoldenMismatchError,
    PineSessionError,
    StrategyLedgerUnavailableError,
)
from pinelib.io import load_bars_csv
from pinelib.parity import (
    assert_strategy_report_close,
    compare_indicator_fixture,
    compare_strategy_reports,
    load_tradingview_indicator_csv,
    load_tradingview_trades_csv,
    write_sample_contracts,
)


def _runtime(timeframe: str = "60") -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC", session="0930-1600:23456"),
        TimeframeInfo.from_string(timeframe),
        config=RuntimeConfig(),
    )


def _bar(index: int, ts: int, *, time_close: int | None = None) -> Bar:
    return Bar(time=ts, time_close=time_close, open=10, high=11, low=9, close=10.5, volume=100)


class RichLedger:
    equity = 1000.0
    netprofit = 10.0
    openprofit = 1.0
    grossprofit = 12.0
    grossloss = -2.0
    position_size = 3.0
    position_avg_price = 42.0
    position_entry_name = "L"
    opentrades = 1
    wintrades = 2
    losstrades = 3
    eventrades = 4
    max_drawdown = 5.0
    max_runup = 6.0
    fills = ("fill",)
    closed_trade_log = ("closed",)
    open_trade_log = ["open"]

    def closedtrades_entry_price(self, index: int) -> float | None:
        return 100.0 + index

    def closedtrades_exit_price(self, index: int) -> float:
        return 110.0 + index

    def closedtrades_entry_time(self, index: int) -> int:
        return 1000 + index

    def closedtrades_exit_time(self, index: int) -> int:
        return 2000 + index

    def closedtrades_profit(self, index: int) -> float:
        return 7.0 + index

    def closedtrades_profit_percent(self, index: int) -> float:
        return 0.07 + index

    def closedtrades_commission(self, index: int) -> float:
        return 0.5 + index

    def closedtrades_qty(self, index: int) -> float:
        return 2.0 + index

    def closedtrades_side(self, index: int) -> str:
        return "long"

    def closedtrades_size(self, index: int) -> float:
        return 2.0 + index

    def closedtrades_entry_id(self, index: int) -> str:
        return f"E{index}"

    def closedtrades_exit_id(self, index: int) -> str:
        return f"X{index}"

    def closedtrades_entry_comment(self, index: int) -> str:
        return f"entry-{index}"

    def closedtrades_exit_comment(self, index: int) -> str:
        return f"exit-{index}"

    def closedtrades_max_runup(self, index: int) -> float:
        return 3.0 + index

    def closedtrades_max_drawdown(self, index: int) -> float:
        return 1.0 + index

    def closedtrades_entry_bar_index(self, index: int) -> int:
        return 10 + index

    def closedtrades_exit_bar_index(self, index: int) -> int:
        return 20 + index

    def opentrades_entry_price(self, index: int) -> float:
        return 40.0 + index

    def opentrades_profit(self, index: int) -> float:
        return 4.0 + index

    def opentrades_profit_percent(self, index: int) -> float:
        return 0.04 + index

    def opentrades_commission(self, index: int) -> float:
        return 0.2 + index

    def opentrades_qty(self, index: int) -> float:
        return 1.0 + index

    def opentrades_side(self, index: int) -> str:
        return "short"

    def opentrades_entry_id(self, index: int) -> str:
        return f"OE{index}"

    def opentrades_exit_price(self, index: int) -> float:
        return 39.0 + index

    def opentrades_exit_time(self, index: int) -> int:
        return 3000 + index

    def opentrades_exit_id(self, index: int) -> str:
        return f"OX{index}"

    def opentrades_size(self, index: int) -> float:
        return 1.0 + index

    def opentrades_max_runup(self, index: int) -> float:
        return 8.0 + index

    def opentrades_max_drawdown(self, index: int) -> float:
        return 2.0 + index

    def opentrades_entry_bar_index(self, index: int) -> int:
        return 30 + index


def test_strategy_ledger_surface_and_error_edges() -> None:
    strategy = StrategyContext(strategy_ledger_view=RichLedger())
    assert strategy.fills == ["fill"]
    assert strategy.closed_trade_log == ["closed"]
    assert strategy.open_trade_log == ["open"]
    assert strategy.equity == 1000.0
    assert strategy.position_entry_name == "L"
    assert strategy.opentrades == 1
    assert strategy.wintrades == 2
    assert strategy.losstrades == 3
    assert strategy.eventrades == 4
    assert strategy.closedtrades_entry_price(0) == 100.0
    assert strategy.closedtrades_exit_price(0) == 110.0
    assert strategy.closedtrades_entry_time(0) == 1000
    assert strategy.closedtrades_exit_time(0) == 2000
    assert strategy.closedtrades_profit(0) == 7.0
    assert strategy.closedtrades_net_profit(0) == 7.0
    assert strategy.closedtrades_profit_percent(0) == 0.07
    assert strategy.closedtrades_commission(0) == 0.5
    assert strategy.closedtrades_qty(0) == 2.0
    assert strategy.closedtrades_side(0) == "long"
    assert strategy.closedtrades_size(0) == 2.0
    assert strategy.closedtrades_entry_id(0) == "E0"
    assert strategy.closedtrades_exit_id(0) == "X0"
    assert strategy.closedtrades_entry_comment(0) == "entry-0"
    assert strategy.closedtrades_exit_comment(0) == "exit-0"
    assert strategy.closedtrades_max_runup(0) == 3.0
    assert strategy.closedtrades_max_drawdown(0) == 1.0
    assert strategy.closedtrades_entry_bar_index(0) == 10
    assert strategy.closedtrades_exit_bar_index(0) == 20
    assert strategy.opentrades_entry_price(0) == 40.0
    assert strategy.opentrades_profit(0) == 4.0
    assert strategy.opentrades_profit_percent(0) == 0.04
    assert strategy.opentrades_commission(0) == 0.2
    assert strategy.opentrades_qty(0) == 1.0
    assert strategy.opentrades_side(0) == "short"
    assert strategy.opentrades_entry_id(0) == "OE0"
    assert strategy.opentrades_exit_price(0) == 39.0
    assert strategy.opentrades_exit_time(0) == 3000
    assert strategy.opentrades_exit_id(0) == "OX0"
    assert strategy.opentrades_size(0) == 1.0
    assert strategy.opentrades_max_runup(0) == 8.0
    assert strategy.opentrades_max_drawdown(0) == 2.0
    assert strategy.opentrades_entry_bar_index(0) == 30
    assert strategy.closedtrades_entry_price(-1) is na

    class MissingMetric:
        fills = 1

    missing = StrategyContext(strategy_ledger_view=MissingMetric())
    with pytest.raises(StrategyLedgerUnavailableError):
        missing.closedtrades_entry_price(0)
    with pytest.raises(StrategyLedgerUnavailableError):
        _ = missing.fills


def test_timefunc_sessions_calendar_and_bucket_edges() -> None:
    spec = parse_session("2200-0200:23456", "UTC")
    assert spec.is_overnight
    assert is_timestamp_in_session(1_704_139_200_000, "2200-0200:23456", "UTC") is False
    with pytest.raises(PineSessionError):
        parse_session("bad", "UTC")
    with pytest.raises(PineSessionError):
        parse_session("2500-2600", "UTC")
    with pytest.raises(PineSessionError):
        parse_session("0000-0100:9", "UTC")
    with pytest.raises(PineSessionError):
        is_timestamp_in_session(1_700_000_000_000, "0000-2359", "No/Such_Zone")

    tf = TimeFunctions()
    runtime = _runtime("60")
    assert tf.time(runtime=runtime) is na
    assert tf.time_close(runtime=runtime) is na
    ts = 1_704_101_400_000  # 2024-01-01 09:30 UTC, Monday.
    runtime.begin_bar(_bar(0, ts, time_close=ts + 3_600_000 - 1))
    assert tf.change("60", runtime=runtime)
    assert tf.time("60", runtime=runtime) == ts
    assert tf.time_close("60", runtime=runtime) == ts + 3_600_000 - 1
    assert tf.time("D", runtime=runtime) == 1_704_067_200_000
    assert tf.time_close("D", runtime=runtime) == 1_704_153_600_000
    assert tf.time("W", runtime=runtime) == 1_704_067_200_000
    assert tf.year(runtime=runtime) == 2024
    assert tf.month(runtime=runtime) == 1
    assert tf.weekofyear(runtime=runtime) == 1
    assert tf.dayofmonth(runtime=runtime) == 1
    assert tf.dayofweek(runtime=runtime) == 2
    assert tf.hour(runtime=runtime) == 9
    assert tf.minute(runtime=runtime) == 30
    assert tf.second(runtime=runtime) == 0
    assert tf.timestamp_components("UTC", 2024, 1, 1, 9, 30) == ts
    assert tf.timestamp_components("No/Such_Zone", 2024, 1, 1, 9, 30) == ts
    assert tf.timestamp_components("UTC", 10000, 1, 1, 0, 0) is na
    assert tf.time("5", runtime=runtime) is na
    assert runtime.config.diagnostics
    with pytest.raises(PineSessionError):
        tf._calendar_value(runtime, "UTC", "invalid")


def test_io_csv_and_parity_edges(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,o,h,l,c,v,close_time,extra\n"
        "1700000000000,1,2,0.5,1.5,10,1700000059999,x\n"
        "1700000060000,1.5,2.5,1,2,11,1700000119999,y\n",
        encoding="utf-8",
    )
    bars = load_bars_csv(csv_path)
    assert len(bars) == 2
    with pytest.raises(PineDataFormatError):
        load_bars_csv(csv_path, strict_columns=True)
    bad = tmp_path / "bad.csv"
    bad.write_text("time,open,high,low\n1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(bad)
    bad_order = tmp_path / "bad_order.csv"
    bad_order.write_text("time,open,high,low,close\n2,1,2,1,1.5\n1,1,2,1,1.5\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(bad_order)

    indicator = tmp_path / "indicator.csv"
    indicator.write_text("time,fast,slow,label\n1,1.0,na,hello\n2,2,3,4000\n", encoding="utf-8")
    fixture = load_tradingview_indicator_csv(indicator)
    assert fixture.columns["fast"] == [1.0, 2]
    assert fixture.columns["slow"] == [None, 3]
    assert fixture.columns["label"] == ["hello", 4000]
    report = compare_indicator_fixture(
        {"fast": [1.0, 2.001]}, fixture, columns=["fast"], abs_tol=0.0
    )
    assert not report.matches
    report.write_json(tmp_path / "report.json")
    report_payload = json.loads((tmp_path / "report.json").read_text())
    assert report_payload["schema_version"] == "pinelib.parity.compare.v1"
    missing = compare_indicator_fixture({}, fixture, columns=["fast"])
    assert missing.mismatches[0]["reason"] == "missing"
    length = compare_indicator_fixture({"fast": [1.0]}, fixture, columns=["fast"])
    assert length.mismatches[0]["reason"] == "length"

    trades = tmp_path / "trades.csv"
    trades.write_text("id,profit\nL,1.5\n", encoding="utf-8")
    assert load_tradingview_trades_csv(trades)[0]["profit"] == 1.5
    strategy_report = compare_strategy_reports(
        {"netprofit": 1}, {"netprofit": 2}, fields=["netprofit", "missing"]
    )
    assert not strategy_report.matches
    with pytest.raises(PineGoldenMismatchError):
        assert_strategy_report_close({"netprofit": 1}, {"netprofit": 2}, fields=["netprofit"])
    write_sample_contracts(tmp_path / "contracts.json")
    assert "AVAX" in json.loads((tmp_path / "contracts.json").read_text())
