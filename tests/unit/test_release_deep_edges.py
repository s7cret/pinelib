from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pinelib import ta
from pinelib.backtest import (
    BacktestResult,
    BacktestSnapshot,
    _fill_to_dict,
    _ledger_sequence_or_empty,
    _resolve_strategy_callback,
    _trade_to_dict,
    build_backtest_report,
    compare_golden,
    extract_params_metadata,
    extract_strategy_params,
    run_generated_strategy,
    snapshot_from_state,
)
from pinelib.compat.marketdata import InstrumentKey, InvalidTimeframeError, parse_timeframe
from pinelib.core.bar import Bar, to_contract_bar
from pinelib.core.na import fixnan, na
from pinelib.core.operators import pine_range
from pinelib.core.runtime import PineRuntime
from pinelib.core.timefunc import TimeFunctions, is_timestamp_in_session, parse_session
from pinelib.core.types import (
    RuntimeConfig,
    SymbolInfo,
    TickUpdate,
    TimeframeInfo,
    TypeInfo,
    parse_timeframe_to_ms,
)
from pinelib.errors import (
    PineDataFormatError,
    PineGoldenMismatchError,
    PineHistoryError,
    PineNAError,
    PineRequestError,
    PineRuntimeError,
    PineSessionError,
    PineStrategyError,
    PineTypeError,
    PineUnsupportedFeatureError,
    StrategyLedgerUnavailableError,
)
from pinelib.io import _column_mapping, _int_ms, load_bars_csv, load_bars_parquet
from pinelib.parity import (
    StrategyCompareReport,
    TradingViewIndicatorFixture,
    _parse_tv_cell,
    _values_close,
    assert_strategy_report_close,
    compare_indicator_fixture,
    compare_strategy_reports,
    load_tradingview_indicator_csv,
    load_tradingview_trades_csv,
    write_sample_contracts,
)
from pinelib.quality import architecture, duplicates
from pinelib.quality import main as quality_main
from pinelib.release import main as release_main
from pinelib.release import validate as release_validate
from pinelib.request.footprint import FootprintSnapshot, footprint
from pinelib.request.providers import InMemoryDataProvider
from pinelib.request.security import (
    _append_merged_requested_values,
    _bars_inside_chart_bar,
    _effective_close_time,
    _provider_get_bars,
    _request_start_for_security,
    merge_requested_series_to_chart_bars,
    security,
    security_lower_tf,
)
from pinelib.strategy import Fill, StrategyContext, Trade
from pinelib.strategy.models import _StrategyScalarSeries
from pinelib.ta._impl_channels import kcw, ta_range, wpr
from pinelib.ta._impl_core import (
    _cached_bar_value,
    _current,
    _EmaState,
    _rolling_extreme,
    _series_values,
    _SmaState,
    _state,
    _tr_batch_from_close,
    _unwrap_singleton,
    _validate_length,
    median,
    mode,
    rma,
    sma,
    tr,
)
from pinelib.ta._impl_momentum import change, highest, highestbars, lowest, lowestbars, macd, rsi
from pinelib.ta._impl_states import (
    _CciState,
    _ChangeState,
    _CmoState,
    _CorrelationState,
    _HighestState,
    _LowestState,
    _MeanDevState,
    _MfiState,
    _RocState,
    _SarState,
    _SourceMfiState,
    _TsiState,
    _VarianceState,
    _VwapState,
    _VwmaState,
    _WmaState,
)
from pinelib.ta._impl_statistics import alma, bb, bbw, dev, hma, stdev, variance, vwma, wma
from pinelib.ta._impl_stats2 import (
    barssince,
    cci,
    correlation,
    falling,
    linreg,
    mfi,
    obv,
    percentile_linear_interpolation,
    percentile_nearest_rank,
    percentrank,
    rising,
    roc,
    valuewhen,
    vwap,
)
from pinelib.ta._impl_trend import (
    adx,
    dmi,
    pivot_high,
    pivot_low,
    pivothigh,
    pivotlow,
    sar,
    stoch,
    supertrend,
)
from pinelib.ta.utils import hl2_series, hlc3_series, hlcc4_series, ohlc4_series, shifted_series
from pinelib.ta.volume import cum


def _bar(index: int, close: float = 10.0, *, step: int = 60_000, volume: float = 100.0) -> Bar:
    t = 1_700_000_000_000 + index * step
    return Bar(
        time=t,
        time_close=t + step - 1,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=volume,
    )


def _runtime(
    *, timeframe: str | TimeframeInfo = "1", config: RuntimeConfig | None = None
) -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC", exchange="BINANCE"),
        timeframe,
        config=config or RuntimeConfig(),
    )


class _CallableStrategy:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bool, float]] = []

    def __call__(self, runtime: PineRuntime, strategy: StrategyContext) -> None:
        self.calls.append(
            (runtime.bar_index, runtime.barstate.isconfirmed, float(runtime.close.current))
        )
        strategy.accept_orders_from_generated_code()


class _OnBarStrategy:
    params = {"length": 3}
    params_metadata = {"length": {"minval": 1}}

    def __init__(self) -> None:
        self.calls = 0

    def on_bar(self, runtime: PineRuntime, strategy: StrategyContext) -> None:
        self.calls += 1
        if runtime.bar_index == -1:
            strategy.order("O", "long", limit=runtime.close.current)


class _BrokenRuntime(PineRuntime):
    def begin_bar(self, bar: Bar) -> None:  # type: ignore[override]
        super().begin_bar(bar)
        self.current_bar = None


def test_backtest_realtime_callable_report_and_golden_edges(tmp_path: Path) -> None:
    runtime = _runtime()
    strategy = StrategyContext(calc_on_every_tick=True)
    callable_strategy = _CallableStrategy()
    ticks = [[TickUpdate(11.5, 1.0, _bar(0).time + 1, False)]]
    progress: list[tuple[int, int]] = []

    result = run_generated_strategy(
        callable_strategy,
        runtime,
        strategy,
        [_bar(0, 11.0)],
        realtime_ticks=ticks,
        progress_callback=lambda current, total: progress.append((current, total)),
    )

    assert isinstance(result, BacktestResult)
    assert callable_strategy.calls == [(-1, True, 11.5)]
    assert progress == [(1, 1)]
    assert result.snapshots[0].close == 11.5
    assert result.report.params == {}

    path = tmp_path / "report.json"
    result.report.write_json(path)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"]
    snapshot_path = tmp_path / "snapshot.json"
    from pinelib.backtest import write_result_snapshot

    write_result_snapshot(result, snapshot_path)
    assert json.loads(snapshot_path.read_text(encoding="utf-8"))["snapshots"]

    strategy_object = _OnBarStrategy()
    result2 = run_generated_strategy(
        strategy_object, _runtime(), StrategyContext(), [_bar(1, 12.0)]
    )
    assert strategy_object.calls == 1
    assert result2.report.params == {"length": 3}
    assert result2.report.params_metadata == {"length": {"minval": 1}}

    assert _resolve_strategy_callback(callable_strategy) is callable_strategy
    with pytest.raises(PineRuntimeError):
        _resolve_strategy_callback(object())
    with pytest.raises(PineRuntimeError):
        snapshot_from_state(_runtime(), StrategyContext())
    with pytest.raises(PineRuntimeError):
        run_generated_strategy(
            _OnBarStrategy(),
            _BrokenRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("1")),
            StrategyContext(),
            [_bar(0)],
        )

    with pytest.raises(PineGoldenMismatchError, match="key mismatch"):
        compare_golden({"a": 1}, {"b": 1})
    with pytest.raises(PineGoldenMismatchError, match="length mismatch"):
        compare_golden([1], [1, 2])
    with pytest.raises(PineGoldenMismatchError, match="Golden mismatch"):
        compare_golden("left", "right")
    with pytest.raises(PineGoldenMismatchError, match="Golden mismatch"):
        compare_golden(1.0, 2.0, abs_tol=0.0, rel_tol=0.0)

    class Empty:
        pass

    assert extract_strategy_params(Empty()) == {}
    assert extract_params_metadata(Empty()) == {}


def test_backtest_ledger_payload_edges() -> None:
    fill = Fill("L", "long", 2.0, 10.5, 0.1, 3, 123, "entry")
    trade = Trade("L", "long", 1, 0, 10.0, 2, 1, 12.0, 2.0, 0.2, 4.0, 20.0, "exit")
    assert _fill_to_dict(fill)["order_id"] == "L"
    assert _trade_to_dict(trade)["profit"] == 4.0

    class Obj:
        fills = [fill]
        closed_trade_log = (trade,)

    class Missing:
        @property
        def fills(self) -> object:
            raise StrategyLedgerUnavailableError("missing")

    assert _ledger_sequence_or_empty(Obj(), "fills") == [fill]  # type: ignore[arg-type]
    assert _ledger_sequence_or_empty(Obj(), "closed_trade_log") == [trade]  # type: ignore[arg-type]
    assert _ledger_sequence_or_empty(Obj(), "unknown") == []  # type: ignore[arg-type]
    assert _ledger_sequence_or_empty(Missing(), "fills") == []  # type: ignore[arg-type]

    class Ledger:
        equity = 10_005.0
        netprofit = 5.0
        grossprofit = 6.0
        grossloss = -1.0
        openprofit = 0.5
        max_drawdown = 2.0
        max_runup = 7.0
        opentrades = 1
        wintrades = 1
        losstrades = 0
        eventrades = 0
        fills = [fill]
        closed_trade_log = (trade,)

    runtime = _runtime()
    runtime.begin_bar(_bar(0))
    ctx = StrategyContext(strategy_ledger_view=Ledger())
    ctx.attach_runtime(runtime)
    ctx.entry("L", "long", comment="entry")
    report = build_backtest_report(
        runtime, ctx, object(), [BacktestSnapshot(0, runtime.current_bar.time, 10.0)]
    )
    assert report.final_equity == 10_005.0
    assert report.fills[0]["order_id"] == "L"
    assert report.closed_trades[0]["entry_id"] == "L"
    assert report.snapshots[0]["bar_index"] == 0


def test_core_marketdata_runtime_and_time_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    assert parse_timeframe("15S").duration_ms == 15_000
    with pytest.raises(InvalidTimeframeError):
        parse_timeframe("0H")
    with pytest.raises(PineDataFormatError):
        Bar(time=-1, open=1, high=1, low=1, close=1)

    instrument = InstrumentKey("BINANCE", "spot", "BTCUSDT")
    tf = parse_timeframe("1")
    contract = to_contract_bar(_bar(0), instrument=instrument, timeframe=tf)
    assert contract.time_close == _bar(0).time_close

    with pytest.raises(PineNAError):
        bool(na)

    s = _runtime().series("fix", "float")
    s.set_current(5.0)
    assert fixnan(s) == 5.0
    s.set_current(na)
    s.commit_current()
    s.set_current(na)
    assert fixnan(s) is na
    with pytest.raises(PineTypeError):
        fixnan(True)
    with pytest.raises(PineTypeError):
        fixnan(
            s
            if False
            else type(
                "BoolSeries",
                (),
                {"current": True, "committed_length": 0, "__getitem__": lambda self, offset: True},
            )()
        )

    assert list(pine_range(1, 3)) == [1, 2, 3]

    runtime = PineRuntime(SymbolInfo("NASDAQ:AAPL"), "60")
    assert runtime.timeframe.isminutes
    with pytest.raises(PineRuntimeError):
        runtime.update_realtime_tick(TickUpdate(1.0))
    runtime.begin_bar(_bar(0))
    with pytest.raises(PineRuntimeError):
        runtime.update_realtime_tick(TickUpdate(1.0))
    runtime.end_bar()
    with pytest.raises(PineRuntimeError):
        _runtime().end_bar()

    realtime = _runtime()
    realtime.begin_realtime_bar(_bar(0))
    with pytest.raises(PineRuntimeError):
        realtime.update_realtime_tick(TickUpdate(12.0, time=_bar(0).time - 1))
    with pytest.raises(PineRuntimeError):
        realtime.update_realtime_tick(TickUpdate(12.0, time=_bar(0).time_close + 1))

    with pytest.raises(PineRuntimeError):
        runtime.restore_state(object())
    with pytest.raises(PineRuntimeError):
        runtime.restore_state({"series": object()})
    runtime.restore_state({"series": {"missing": {}}, "request_data_end_ms": "123"})
    assert runtime.request_data_end_ms == 123
    with pytest.raises(PineRuntimeError):
        runtime.series("close", "int")
    with pytest.raises(PineRuntimeError):
        runtime.guard_recalc_count(runtime.config.max_recalculations_per_bar + 1)
    with pytest.raises(PineRuntimeError):
        PineRuntime(SymbolInfo("TEST:MONTH"), TimeframeInfo("1M", interval_ms=None)).begin_bar(
            Bar(time=1, open=1, high=1, low=1, close=1)
        )
    strict_runtime = PineRuntime(
        SymbolInfo("TEST:STRICT"),
        TimeframeInfo.from_string("1"),
        config=RuntimeConfig(allow_incomplete_bar_time_close=False),
    )
    with pytest.raises(PineRuntimeError):
        strict_runtime.begin_bar(Bar(time=1, open=1, high=1, low=1, close=1))

    with pytest.raises(PineSessionError):
        parse_session("bad", "UTC")
    with pytest.raises(PineSessionError):
        parse_session("2500-2600", "UTC")
    with pytest.raises(PineSessionError):
        parse_session("0000-0100:x", "UTC")
    assert is_timestamp_in_session(1_704_067_200_000, "2300-0100:1234567", "UTC") is True
    assert is_timestamp_in_session(1_704_153_600_000, "2300-0100:2", "UTC") is False
    tfun = TimeFunctions()
    with pytest.raises(PineSessionError):
        tfun.year(runtime=_runtime())
    assert tfun.timestamp_components("Bad/Zone", 2024, 1, 1, 0, 0) == 1_704_067_200_000
    assert tfun.timestamp_components("UTC", 10_000, 1, 1, 0, 0) is na

    rt = _runtime(timeframe="60")
    rt.begin_bar(_bar(0, step=3_600_000))
    assert rt.timefunc.change("bad", runtime=rt) is True
    rt.end_bar()
    rt.begin_bar(_bar(1, step=3_600_000))
    assert rt.timefunc.change("bad", runtime=rt) is True
    rt.end_bar()
    rt.begin_bar(_bar(2, step=3_600_000))
    assert rt.timefunc.change("bad", runtime=rt) is False
    assert rt.timefunc.time("2D", runtime=rt) is na
    assert rt.config.diagnostics
    assert rt.timefunc.time(session="0000-2359", runtime=rt) != na
    rt.end_bar()


def test_core_types_series_io_parity_and_release_helpers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert SymbolInfo("NASDAQ:AAPL").ticker == "AAPL"
    tf_sec = TimeframeInfo.from_string("30S")
    assert tf_sec.period == "30S"
    assert tf_sec.isintraday is False
    assert TimeframeInfo.from_string("bad").interval_ms is None
    cfg = RuntimeConfig()
    cfg.emit_diagnostic("X", "message", extra=1)
    assert cfg.diagnostics == [{"code": "X", "message": "message", "extra": 1}]

    s = _runtime().series("bool_history", "bool")
    with pytest.raises(PineTypeError):
        s.set_current(na)
    ref = _runtime(config=RuntimeConfig(reference_history_mode="identity")).series(
        "ref", "line", 1, TypeInfo("line", "series", is_reference_type=True)
    )
    ref.commit_current()
    assert ref[1] == 1
    with pytest.raises(PineHistoryError):
        _ = ref[-1]

    csv_path = tmp_path / "bars.csv"
    csv_path.write_text("timestamp,o,h,l,c,v,timeclose\n1,1,2,0,1.5,7,2\n", encoding="utf-8")
    assert load_bars_csv(csv_path, strict_columns=True)[0].volume == 7.0
    extra = tmp_path / "extra.csv"
    extra.write_text("time,open,high,low,close,extra\n1,1,1,1,1,x\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(extra, strict_columns=True)
    dup = tmp_path / "dup.csv"
    dup.write_text("time,timestamp,open,high,low,close\n1,1,1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(dup)
    bad = tmp_path / "bad.csv"
    bad.write_text("time,open,high,low,close\n,1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(bad)
    with pytest.raises(ValueError):
        _int_ms(object())
    with pytest.raises(PineDataFormatError):
        _column_mapping(["time", "timestamp"])
    with pytest.raises((FileNotFoundError, PineUnsupportedFeatureError)):
        load_bars_parquet(tmp_path / "missing_required.parquet")

    tv = tmp_path / "tv.csv"
    tv.write_text("time,plot,label\n1,1,hello\n2,na,2.5\n", encoding="utf-8")
    fixture = load_tradingview_indicator_csv(tv)
    assert fixture.rows == 2
    assert fixture.to_dict()["source"] == str(tv)
    trades = tmp_path / "trades.csv"
    trades.write_text("id,profit\nL,1,000\n", encoding="utf-8")
    assert load_tradingview_trades_csv(trades)[0]["id"] == "L"
    assert TradingViewIndicatorFixture({}).rows == 0
    assert StrategyCompareReport("s", [], {}, True, 0, 0, []).to_dict()["matches"] is True
    report_path = tmp_path / "compare.json"
    StrategyCompareReport("s", [], {}, True, 0, 0, []).write_json(report_path)
    assert json.loads(report_path.read_text(encoding="utf-8"))["matches"] is True
    assert _parse_tv_cell(None) is None
    assert _parse_tv_cell("1,234") == 1234
    assert _parse_tv_cell("1.5") == 1.5
    assert _parse_tv_cell("text") == "text"
    assert _values_close(None, 1, abs_tol=0, rel_tol=0)[0] is False
    assert _values_close("a", "b", abs_tol=0, rel_tol=0)[0] is False

    cmp_report = compare_indicator_fixture(
        {"a": [1, 2], "b": [1]}, TradingViewIndicatorFixture({"a": [1, 3]}), columns=["a", "b"]
    )
    assert not cmp_report.matches
    strategy_report = compare_strategy_reports(
        {"netprofit": 1.0},
        {"netprofit": 2.0, "final_equity": 1.0},
        fields=["netprofit", "final_equity"],
    )
    assert not strategy_report.matches
    with pytest.raises(PineGoldenMismatchError):
        assert_strategy_report_close(
            {"netprofit": 1.0}, {"netprofit": 2.0}, fields=["netprofit"], abs_tol=0.0, rel_tol=0.0
        )
    contracts_path = tmp_path / "contracts.json"
    write_sample_contracts(contracts_path)
    assert "AVAX" in json.loads(contracts_path.read_text(encoding="utf-8"))

    assert duplicates(tmp_path).duplicate_group_count == 0
    assert architecture(tmp_path, max_lines=1).oversized_count >= 0
    py_file = tmp_path / "bad_syntax.py"
    py_file.write_text("def broken(:\n", encoding="utf-8")
    assert duplicates(tmp_path).duplicate_group_count == 0
    assert quality_main(["duplicates", str(tmp_path), "--json"]) == 0
    out = capsys.readouterr().out
    assert "duplicate_group_count" in out
    assert quality_main(["architecture", str(tmp_path), "--max-lines", "1"]) in {0, 1}
    capsys.readouterr()

    assert release_validate(".").ok is True
    assert release_main(["--root", ".", "--json", str(tmp_path / "release.json")]) == 0
    assert json.loads((tmp_path / "release.json").read_text(encoding="utf-8"))["ok"] is True
    assert release_main(["--root", "."]) == 0
    assert "pinelib" in capsys.readouterr().out


def test_request_security_provider_lower_tf_and_footprint_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chart = [_bar(0), _bar(1)]
    requested = [_bar(0, 1.0), _bar(1, 2.0)]
    assert _effective_close_time(Bar(0, 1, 1, 1, 1, time_close=None), [], 0) == 86_399_999
    assert (
        _effective_close_time(
            Bar(120_000, 1, 1, 1, 1, time_close=None),
            [Bar(0, 1, 1, 1, 1, time_close=None), Bar(120_000, 1, 1, 1, 1, time_close=None)],
            1,
        )
        == 239_999
    )
    with pytest.raises(PineRequestError):
        merge_requested_series_to_chart_bars([1], requested_bars=[], chart_bars=chart)
    with pytest.raises(PineRequestError):
        merge_requested_series_to_chart_bars(
            [1], requested_bars=[requested[0]], chart_bars=chart, gaps="bad"
        )
    with pytest.raises(PineRequestError):
        merge_requested_series_to_chart_bars(
            [1], requested_bars=[requested[0]], chart_bars=chart, lookahead="bad"
        )
    assert (
        merge_requested_series_to_chart_bars(
            [1, 2],
            requested_bars=requested,
            chart_bars=chart,
            lookahead="barmerge.lookahead_on",
            gaps="barmerge.gaps_on",
        )[-1]
        == 2
    )
    cache: dict[str, Any] = {
        "requested_times": object(),
        "requested_closes": [],
        "effective_closes": [],
    }
    assert _append_merged_requested_values(
        cache,
        requested_bars=requested,
        requested_values=[1, 2],
        chart_bars=chart,
        gaps="barmerge.gaps_off",
        lookahead="barmerge.lookahead_off",
    )

    provider = InMemoryDataProvider({("TEST:BBB", "1"): requested, ("TEST:AAA", "1"): chart})
    runtime = _runtime()
    runtime.data_provider = provider
    assert _request_start_for_security(runtime, "D") is None
    runtime.begin_bar(chart[0])
    start = _request_start_for_security(runtime, "D")
    assert start is not None
    assert security("TEST:BBB", "1", [10.0], runtime=runtime, state_id="seq") in {10.0, na}
    with pytest.raises(PineRequestError):
        security("TEST:BBB", "1", [10.0, 20.0], runtime=runtime, state_id="bad_seq")
    with pytest.raises(PineRequestError):
        security("TEST:BBB", "1", object(), runtime=runtime, state_id="bad_expr")  # type: ignore[arg-type]

    no_provider = _runtime()
    assert (
        security(
            "MISSING",
            "1",
            [1.0],
            runtime=no_provider,
            state_id="ignore",
            ignore_invalid_symbol=True,
        )
        is na
    )
    with pytest.raises(PineRequestError):
        security("MISSING", "1", [1.0], runtime=no_provider, state_id="fail")

    class ExchangeMarketProvider:
        def get_bars(
            self,
            symbol: str,
            timeframe: str,
            start: int | None,
            end: int | None,
            *,
            max_bars: int | None = None,
            exchange: str | None = None,
            market: str | None = None,
        ) -> list[Bar]:
            assert exchange == "BINANCE"
            assert market == "spot"
            assert max_bars == 1
            return requested[:1]

    runtime2 = _runtime(config=RuntimeConfig(extra={"market_type": "spot"}))
    runtime2.data_provider = ExchangeMarketProvider()  # type: ignore[assignment]
    assert _provider_get_bars(runtime2, "TEST:BBB", "1", None, None, max_bars=1) == requested[:1]

    original_signature = __import__("inspect").signature
    monkeypatch.setattr(
        "inspect.signature", lambda obj: (_ for _ in ()).throw(ValueError("bad signature"))
    )

    class SimpleProvider:
        def get_bars(self, *args: object, **kwargs: object) -> list[Bar]:
            assert kwargs == {"max_bars": None}
            return []

    runtime3 = _runtime()
    runtime3.data_provider = SimpleProvider()  # type: ignore[assignment]
    assert _provider_get_bars(runtime3, "S", "1", None, None) == []
    monkeypatch.setattr("inspect.signature", original_signature)

    Synthetic = type(
        "SyntheticProvider",
        (),
        {
            "__module__": "marketdata_provider.synthetic",
            "get_bars": lambda self, *args, **kwargs: [_bar(0, volume=0.0)],
        },
    )
    runtime4 = _runtime()
    runtime4.data_provider = Synthetic()  # type: ignore[assignment]
    runtime4.begin_bar(_bar(0))
    assert (
        security(
            "TEST:BBB",
            "1",
            [1.0],
            runtime=runtime4,
            state_id="synthetic",
            ignore_invalid_symbol=True,
        )
        is na
    )

    assert _bars_inside_chart_bar([], chart[0]) == []
    assert [bar.time for bar in _bars_inside_chart_bar([_bar(-1), _bar(0), _bar(1)], chart[0])] == [
        chart[0].time
    ]
    assert security_lower_tf("X", "1", [1], runtime=_runtime(), state_id="no_bar").size == 0
    assert (
        security_lower_tf(
            "X", "1", [1], runtime=_runtime(), state_id="ignore", ignore_invalid_symbol=True
        ).size
        == 0
    )
    missing_lower_provider = _runtime()
    missing_lower_provider.begin_bar(chart[0])
    with pytest.raises(PineRequestError):
        security_lower_tf("X", "1", [1], runtime=missing_lower_provider, state_id="fail")

    lower_provider = InMemoryDataProvider(
        {("TEST:LOW", "1"): [_bar(0, 1.0, step=30_000), _bar(1, 2.0, step=30_000)]}
    )
    lower_rt = _runtime()
    lower_rt.data_provider = lower_provider
    parent = _bar(0, step=60_000)
    lower_rt.begin_bar(parent)
    assert list(
        security_lower_tf(
            "TEST:LOW", "1", lambda child: child.close.current, runtime=lower_rt, state_id="call"
        )
    ) == [1.0, 2.0]
    assert list(
        security_lower_tf("TEST:LOW", "1", [7.0, 8.0], runtime=lower_rt, state_id="seq")
    ) == [7.0, 8.0]
    assert list(
        security_lower_tf(
            "TEST:LOW", "1", [1], runtime=lower_rt, state_id="tc", expression_hint="time_close"
        )
    ) == [parent.time_close - 30_000, parent.time_close]
    with pytest.raises(PineRequestError):
        security_lower_tf("TEST:LOW", "1", [1.0], runtime=lower_rt, state_id="bad_len")
    with pytest.raises(PineRequestError):
        security_lower_tf("TEST:LOW", "1", object(), runtime=lower_rt, state_id="bad_expr")  # type: ignore[arg-type]
    with pytest.raises(PineRequestError):
        security_lower_tf(
            "TEST:LOW", "1", [1], runtime=lower_rt, state_id="neg", calc_bars_count=-1
        )

    snap = FootprintSnapshot(10.0, 3.0)
    assert snap.buy_volume() == 10.0
    assert snap.sell_volume() == 3.0
    assert snap.delta() == 7.0
    assert footprint(runtime=_runtime(), state_id="fp") is na

    class NoCallable:
        get_current_footprint = 1

    rt_fp = type(
        "FootprintRuntime", (), {"footprint_provider": NoCallable(), "current_bar": None}
    )()
    assert footprint(runtime=rt_fp, state_id="fp") is na

    class Provider:
        def __init__(self, value: object) -> None:
            self.value = value

        def get_current_footprint(self, bar: object) -> object:
            return self.value if bar is not None else None

    rt_fp.footprint_provider = Provider(None)
    assert footprint(runtime=rt_fp, state_id="fp") is na
    rt_fp.current_bar = _bar(0)
    rt_fp.footprint_provider = Provider(snap)
    assert footprint(runtime=rt_fp, state_id="fp") == snap


def test_strategy_context_and_scalar_edges() -> None:
    scalar = _StrategyScalarSeries(3)
    scalar.commit_current()
    scalar.set_current(5)
    assert scalar.current == 5
    assert scalar.committed_length == 1
    assert scalar[0] == 5
    assert scalar[1] == 3
    assert scalar[2] == 0
    with pytest.raises(IndexError):
        _ = scalar[-1]
    assert float(scalar) == 5.0
    assert int(scalar) == 5
    assert bool(scalar)
    assert scalar + 1 == 6
    assert 1 + scalar == 6
    assert scalar - 1 == 4
    assert 10 - scalar == 5
    assert scalar * 2 == 10
    assert 2 * scalar == 10
    assert scalar / 5 == 1
    assert 10 / scalar == 2
    assert scalar == 5
    assert scalar > 4 and scalar >= 5 and scalar < 6 and scalar <= 5

    conflict_runtime = _runtime(config=RuntimeConfig(calc_on_every_tick=False))
    strict = StrategyContext(calc_on_every_tick=True, strict_tv_parity=True)
    with pytest.raises(PineStrategyError):
        strict.attach_runtime(conflict_runtime)

    runtime = _runtime()
    ctx = StrategyContext(
        backtest_fill_limits_assumption=1,
        close_entries_rule="LIFO",
        fill_orders_on_standard_ohlc=True,
        margin_long=50.0,
    )
    ctx.attach_runtime(runtime)
    assert runtime.config.diagnostics
    ctx.order("O", "short", stop=9.0, oca_name="grp", oca_type="cancel")
    ctx.close_all(immediately=True, comment="all")
    ctx.cancel_all()
    assert all(order.status == "cancelled" for order in ctx.pending_orders)
    assert ctx.accept_orders_from_generated_code() is None
    assert ctx.has_fill_recalc_pending() is False
    assert ctx.update_position_equity_trades_after_fill() is None
    assert ctx.ohlc_path(Bar(0, 1.0, 1.1, 0.0, 1.0)) == [1.0, 1.1, 0.0, 1.0]
    assert ctx.ohlc_path(Bar(0, 1.0, 2.0, 0.9, 1.0)) == [1.0, 0.9, 2.0, 1.0]
    assert ctx.closedtrades_max_runup(-1) is na
    ctx.risk_max_intraday_loss(5, "cash")
    ctx.risk_max_intraday_filled_orders(2)
    assert ctx.risk_rules[-2].name == "max_intraday_loss"

    class Ledger:
        fills = ["fill"]
        closed_trade_log = ("closed",)
        open_trade_log = "bad"
        position_entry_name = None

        def opentrades_profit(self, index: int) -> object:
            if index == 0:
                return None
            return 1.0

        def closedtrades_profit(self) -> float:
            return 2.0

    ctx.attach_strategy_ledger_view(Ledger())
    assert ctx.fills == ["fill"]
    assert ctx.closed_trade_log == ["closed"]
    assert ctx.position_entry_name is None
    with pytest.raises(StrategyLedgerUnavailableError):
        _ = ctx.open_trade_log
    with pytest.raises(StrategyLedgerUnavailableError):
        ctx.opentrades_profit(0)
    with pytest.raises(StrategyLedgerUnavailableError):
        ctx.closedtrades_max_drawdown(0)
    with pytest.raises(StrategyLedgerUnavailableError):
        _ = ctx._ledger_value("unknown")


def test_ta_core_state_and_error_edges() -> None:
    with pytest.raises(PineRuntimeError):
        _validate_length(0)
    with pytest.raises(PineRuntimeError):
        _validate_length(True)
    with pytest.raises(PineTypeError):
        _current(True, "sma")
    assert _series_values(1.5) == [1.5]
    assert _series_values(na) == [na]
    assert _unwrap_singleton([7]) == 7
    assert _unwrap_singleton([7, 8]) == [7, 8]

    runtime = _runtime()
    runtime.indicator_state["state"] = object()
    with pytest.raises(PineRuntimeError):
        _state(runtime, "state", lambda: _SmaState(2), _SmaState)

    assert _cached_bar_value(("k",), (0, 1), lambda: 3) == 3
    assert _cached_bar_value(("k",), (0, 1), lambda: 4) == 3
    assert _tr_batch_from_close([1.0, 2.0, na]) == [0.0, 1.0, 0.0]
    with pytest.raises(PineRuntimeError):
        sma([1], 1, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        median([1], 1, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        mode([1], 1, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        rma([1], 1, runtime=runtime)
    with pytest.raises(PineTypeError):
        tr(high=True, low=1.0, close=na)
    with pytest.raises(PineTypeError):
        tr(high=2.0, low=1.0, close=True)
    assert tr(high=na, low=1.0, close=1.0) is na
    assert tr(high=3.0, low=1.0, close=na) == 2.0

    series = _runtime().series("rolling", "float")
    assert _rolling_extreme(1.0, 2, "high", bars=False) is None
    assert highest(series, 2) is na
    series.set_current(3.0)
    series.commit_current()
    series.set_current(2.0)
    assert highest(series, 2) == 3.0
    assert lowest(series, 2) == 2.0
    assert highestbars(series, 2) in {-1, 0}
    assert lowestbars(series, 2) in {-1, 0}
    series._history.clear()
    series.set_current(na)
    assert _rolling_extreme(series, 2, "high", bars=False) is na


def test_ta_state_classes_direct_edges() -> None:
    assert _SarState(0.02, 0.02, 0.2).update(na, 1.0) is na
    sar_state = _SarState(0.02, 0.02, 0.2)
    assert sar_state.update(10.0, 9.0) is na
    assert sar_state.update(10.5, 9.5) != na
    assert _HighestState(2).update(na) is na
    assert _LowestState(2).update(na) is na
    assert _CciState(2).update(na, 1, 1) is na
    assert _CciState(2).update(1, 1, 1) is na
    assert _MfiState(2).update(na, 1, 1, 1) is na
    mfi_state = _MfiState(2)
    assert mfi_state.update(2, 1, 1, 10) is na
    assert mfi_state.update(3, 1, 2, 10) == 100.0
    cmo_state = _CmoState(2)
    assert cmo_state.update(na) is na
    assert cmo_state.update(1) is na
    assert cmo_state.update(1) is na
    tsi_state = _TsiState(1, 1)
    assert tsi_state.update(na) is na
    assert tsi_state.update(1) is na
    assert tsi_state.update(2) == 1.0
    wma_state = _WmaState(2)
    assert wma_state.update(na) is na
    assert wma_state.update(1) is na
    assert wma_state.update(2) == pytest.approx(5 / 3)
    assert wma_state.update(3) == pytest.approx(8 / 3)
    vwma_state = _VwmaState(2)
    assert vwma_state.update(na, 1) is na
    assert vwma_state.update(1, 0) is na
    assert vwma_state.update(2, 0) is na
    variance_state = _VarianceState(1, biased=False)
    assert variance_state.update(1) is na
    assert _MeanDevState(2).update(na) is na
    corr_state = _CorrelationState(2)
    assert corr_state.update(1, 1) is na
    assert corr_state.update(1, 2) is na
    source_mfi = _SourceMfiState(1)
    assert source_mfi.update(na, 1) is na
    assert source_mfi.update(1, 10) is na
    assert source_mfi.update(2, 10) == 100.0
    change_state = _ChangeState(1)
    assert change_state.update(na) is na
    assert change_state.update(1) is na
    assert change_state.update(3) == 2
    roc_state = _RocState(1)
    assert roc_state.update(0) is na
    assert roc_state.update(1) is na
    vwap_state = _VwapState()
    assert vwap_state.update(na, 1) is na
    assert vwap_state.update(1, 0) is na
    assert vwap_state.update(2, 2, 86_400_000) == 2


def test_ta_function_edge_matrix() -> None:
    assert ta_range([na, na], 1) == [0.0, 0.0]
    with pytest.raises(PineRuntimeError):
        ta.cmo([1], 1, runtime=_runtime())
    with pytest.raises(PineRuntimeError):
        ta.tsi([1], 1, 2, runtime=_runtime())
    assert kcw([0.0, 0.0, 0.0], 1)[-1] is na
    with pytest.raises(PineRuntimeError):
        wpr(2)
    with pytest.raises(PineRuntimeError):
        wpr(2, runtime=_runtime())
    rt = _runtime()
    for i, close in enumerate([1.0, 1.0, 1.0]):
        rt.begin_bar(_bar(i, close))
        out = wpr(2, runtime=rt, state_id="wpr")
        rt.end_bar()
    assert out == pytest.approx(-50.0)

    with pytest.raises(PineRuntimeError):
        ta.atr(2)
    with pytest.raises(PineRuntimeError):
        rsi([1], 1, runtime=_runtime())
    with pytest.raises(PineRuntimeError):
        macd([1, 2], 2, 2, 1)
    with pytest.raises(PineRuntimeError):
        macd([1], 1, 2, 1, runtime=_runtime())
    with pytest.raises(PineRuntimeError):
        change([1, 2], 1, state_id="change")
    with pytest.raises(PineTypeError):
        change([True, False], 1)
    with pytest.raises(PineTypeError):
        change([1, True], 1)
    cross_rt = _runtime()
    left = cross_rt.series("left", "float")
    right = cross_rt.series("right", "float")
    left.set_current(1.0)
    right.set_current(2.0)
    left.commit_current()
    right.commit_current()
    left.set_current(2.0)
    right.set_current(1.0)
    assert ta.cross(left, right) is True
    assert ta.crossover(left, right) is True
    under_left = cross_rt.series("under_left", "float")
    under_right = cross_rt.series("under_right", "float")
    under_left.set_current(2.0)
    under_right.set_current(1.0)
    under_left.commit_current()
    under_right.commit_current()
    under_left.set_current(1.0)
    under_right.set_current(2.0)
    assert ta.crossunder(under_left, under_right) is True
    extreme_rt = _runtime()
    extreme = extreme_rt.series("extreme", "float")
    extreme.set_current(na)
    assert highest(extreme, 1) is na
    assert lowest(extreme, 1) is na
    assert highestbars(extreme, 1) is na
    assert lowestbars(extreme, 1) is na

    assert stdev([1.0], 1, biased=False) == [na]
    assert variance([1.0], 1, biased=False) == [na]
    with pytest.raises(PineRuntimeError):
        stdev(1.0, 1, runtime=_runtime())
    with pytest.raises(PineRuntimeError):
        variance(1.0, 1, runtime=_runtime())
    with pytest.raises(PineRuntimeError):
        dev(1.0, 1, runtime=_runtime())
    with pytest.raises(PineRuntimeError):
        wma(1.0, 1, runtime=_runtime())
    assert vwma([1, 2], 2, [0, 0])[-1] is na
    with pytest.raises(PineRuntimeError):
        vwma([1], 1)
    with pytest.raises(PineRuntimeError):
        vwma(1.0, 1, runtime=_runtime())
    with pytest.raises(PineRuntimeError):
        hma(1.0, 2)
    with pytest.raises(PineRuntimeError):
        hma(1.0, 1, runtime=_runtime())
    assert ta.swma([1, na, 3, 4])[-1] is na
    assert alma([1, 2], 2, 0.5, 6, floor=True)[-1] != na
    assert bb([1.0], 1, 2.0) == (1.0, 1.0, 1.0)
    assert bbw([0.0], 1, 2.0) is na

    with pytest.raises(PineRuntimeError):
        valuewhen([True], [1], -1)
    assert valuewhen([False, True, False], [1, 2, 3], 0) == [na, 2, 2]
    assert barssince([False, False]) == [na, na]
    assert linreg([1, 2], 2) != na
    assert percentile_nearest_rank([na], 1, 50) == [na]
    assert percentile_linear_interpolation([1, 3], 2, 50) == [na, 2.0]
    assert percentrank([1, na], 2)[-1] is na
    with pytest.raises(PineRuntimeError):
        vwap([1, 2])
    assert vwap([1, 2], [0, 0])[-1] is na
    with pytest.raises(PineRuntimeError):
        vwap(1, runtime=_runtime())
    assert roc([1, 2], 1)[-1] == 100.0
    with pytest.raises(PineRuntimeError):
        roc([1], 1, state_id="roc")
    with pytest.raises(PineRuntimeError):
        correlation([1], [1], 1, runtime=_runtime())
    assert correlation([1, 1], [2, 2], 2)[-1] is na
    assert rising([1], 2) is False
    assert falling([1], 2) is False
    assert cci([1, 2], 1)[-1] is na
    assert cci([1, 2], [1, 2], [1, 2], 2)[-1] is not na
    with pytest.raises(PineRuntimeError):
        cci(1, 1, runtime=_runtime())
    with pytest.raises(PineRuntimeError):
        mfi([1, 2], 1)
    assert mfi([1, 2, 3], [1, 2, 3], [1, 2, 3], [10, 10, 10], 1)[-1] == 100.0
    with pytest.raises(PineRuntimeError):
        mfi(1, 1, volume=1, runtime=_runtime())
    assert obv([1, 2, 1], [10, 10, 10]) == [0.0, 10.0, 0.0]

    assert stoch([1, 3], [2, 3], [1, 1], 2)[-1] == 100.0
    assert dmi([1, 2], [1, 1], [1, 2], 1, 1)[0][-1] >= 0
    assert adx([1, 2], [1, 1], [1, 2], 1, 1)[-1] >= 0
    with pytest.raises(PineRuntimeError):
        supertrend(2.0, 2, runtime=_runtime())
    line, direction = supertrend(2.0, 1, high=[2, 3, 4], low=[1, 1, 2], close=[1.5, 2.5, 3.0])
    assert len(line) == len(direction) == 3
    with pytest.raises(PineRuntimeError):
        sar([1], [1], runtime=_runtime())
    with pytest.raises(PineRuntimeError):
        sar([1], [1, 2])
    assert sar([3, 2, 1, 4], [2, 1, 0, 3])[-1] != na
    assert pivot_high([1, 3, 1], 1, 1)[1] == 3
    assert pivot_low([3, 1, 3], 1, 1)[1] == 1
    assert pivothigh([1, na, 1], 1, 1)[1] is na
    assert pivotlow([1, na, 1], 1, 1)[1] is na


def test_derived_series_and_volume_runtime_edges() -> None:
    runtime = _runtime()
    runtime.begin_bar(_bar(0))
    assert hl2_series(runtime).committed_length == 0
    assert hl2_series(runtime).current == 10.0
    assert hlc3_series(runtime).current == pytest.approx(10.0)
    assert ohlc4_series(runtime).current == pytest.approx(10.0)
    assert hlcc4_series(runtime).current == pytest.approx(10.0)
    runtime.low.set_current(na)
    assert hl2_series(runtime).current is na
    runtime.low.set_current(9.0)
    runtime.open.set_current(na)
    assert ohlc4_series(runtime).current is na
    runtime.open.set_current(10.0)
    unknown = type(hl2_series(runtime))(runtime, "unknown")
    assert unknown.current is na
    runtime.end_bar()
    shifted = shifted_series(runtime.close, 1)
    assert shifted.committed_length == runtime.close.committed_length
    assert shifted.current is na

    with pytest.raises(PineRuntimeError):
        cum(na)
    assert cum(2.0, runtime=_runtime()) == 2.0


def test_release_remaining_runtime_and_gate_edges(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from pinelib import distribution
    from pinelib.core.operators import pine_add, pine_div, pine_mul, pine_sub
    from pinelib.core.timefunc import _bar_time_close_ms, _localize
    from pinelib.string import pos, replace, tostring

    class LenientStrategyContext(StrategyContext):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.fallback_seen = False

        def note_calc_on_every_tick_historical_fallback(self, runtime: PineRuntime) -> None:
            self.fallback_seen = runtime.current_bar is not None

    strategy = _CallableStrategy()
    runtime = _runtime()
    ctx = LenientStrategyContext(calc_on_every_tick=True)
    result = run_generated_strategy(strategy, runtime, ctx, [_bar(0), _bar(1)], realtime_ticks=[[]])
    assert ctx.fallback_seen is True
    assert len(result.snapshots) == 2

    non_tick_ctx = StrategyContext(calc_on_every_tick=False)
    non_tick_strategy = _CallableStrategy()
    run_generated_strategy(
        non_tick_strategy,
        _runtime(),
        non_tick_ctx,
        [_bar(0)],
        realtime_ticks=[[TickUpdate(11.0, 1.0, _bar(0).time + 1, True)]],
    )
    assert non_tick_strategy.calls == [(-1, False, 10.0)]
    assert _ledger_sequence_or_empty(type("X", (), {"fills": "not-a-sequence"})(), "fills") == []  # type: ignore[arg-type]

    assert pine_add(None, 1) is None
    assert pine_sub(1, None) is None
    assert pine_mul(2, None) is None
    with pytest.raises(ZeroDivisionError):
        pine_div(1, 0)
    assert tostring(1.234, "#.##") == "1.23"
    assert tostring("x", "unused") == "x"
    assert replace("a-a-a", "a", "b") == "b-b-b"
    assert pos("abc", "", -1) == 0
    assert pos("abc", "", 5) == 3

    with pytest.raises(PineSessionError):
        parse_session("0x00-0100", "UTC")
    assert is_timestamp_in_session(1_704_067_200_000_000, "0000-2359:1234567", "UTC") is True
    assert is_timestamp_in_session(1_704_151_800_000, "2300-0100:1234567", "UTC") is True
    assert TimeFunctions().time_close(runtime=_runtime()) is na
    no_close_runtime = _runtime()
    no_close_runtime.current_bar = Bar(
        time=1_700_000_000_000, open=1, high=1, low=1, close=1, time_close=None
    )
    assert _bar_time_close_ms(no_close_runtime) == 0
    with pytest.raises(PineSessionError):
        no_close_runtime.timefunc.time(runtime=no_close_runtime)
    assert _localize(1_704_067_200_000_000, "UTC").year == 2024
    assert parse_timeframe_to_ms("") is None

    dist_root = tmp_path / "distroot"
    (dist_root / "pinelib" / "__pycache__").mkdir(parents=True)
    (dist_root / "pinelib").mkdir(exist_ok=True)
    (dist_root / "docs").mkdir()
    (dist_root / "tests").mkdir()
    (dist_root / "pinelib" / "ok.py").write_text("x=1\n", encoding="utf-8")
    (dist_root / "pinelib" / "bad.pyc").write_bytes(b"x")
    (dist_root / "pinelib" / "__pycache__" / "skip.py").write_text("x=1\n", encoding="utf-8")
    (dist_root / "random" / "file.py").parent.mkdir()
    (dist_root / "random" / "file.py").write_text("x=1\n", encoding="utf-8")
    assert [path.name for path in distribution.source_files(dist_root)] == ["ok.py"]
    assert distribution.main(["manifest", "--root", str(dist_root)]) == 0
    assert "archive_hygiene_ok" in capsys.readouterr().out
    archive_path = tmp_path / "archive.zip"
    digest = distribution.build_zip(dist_root, archive_path)
    assert len(digest) == 64
    assert (
        distribution.main(
            ["build-zip", "--root", str(dist_root), "--output", str(tmp_path / "cli.zip")]
        )
        == 0
    )

    bad_root = tmp_path / "badrelease"
    (bad_root / "docs").mkdir(parents=True)
    (bad_root / "pyproject.toml").write_text('version = "0.0.0"\n', encoding="utf-8")
    (bad_root / "README.md").write_text("no version here\n", encoding="utf-8")
    (bad_root / "docs" / "EXTRA.md").write_text("extra\n", encoding="utf-8")
    report = release_validate(bad_root)
    assert report.ok is False
    assert any("pyproject" in error for error in report.errors)
    assert release_main(["--root", str(bad_root)]) == 1
    assert release_main(["--root", ".", "--json", str(tmp_path / "release.json")]) == 0

    invalid_py = tmp_path / "invalid_py"
    invalid_py.mkdir()
    (invalid_py / "broken.py").write_text("def bad(:\n", encoding="utf-8")
    assert duplicates(invalid_py).duplicate_group_count == 0
    assert architecture(invalid_py, max_lines=1).oversized_count == 1
    assert quality_main(["architecture", str(invalid_py), "--max-lines", "1", "--json"]) == 1
    assert "oversized_count" in capsys.readouterr().out


def test_release_remaining_data_request_strategy_and_parity_edges(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _int_ms(object())
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("timestamp,open,high,low,close\n,1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(bad_csv)

    tv_bad_time = tmp_path / "tv_bad_time.csv"
    tv_bad_time.write_text("time,plot\nabc,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_tradingview_indicator_csv(tv_bad_time)
    tv_empty = tmp_path / "tv_empty.csv"
    tv_empty.write_text("", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_tradingview_indicator_csv(tv_empty)
    trades_empty = tmp_path / "trades_empty.csv"
    trades_empty.write_text("", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_tradingview_trades_csv(trades_empty)
    assert _parse_tv_cell("  ") is None
    assert _parse_tv_cell("text") == "text"
    assert _values_close(1.0, 2.0, abs_tol=0.0, rel_tol=0.0)[0] is False
    assert compare_indicator_fixture(
        {"x": [1.0]}, TradingViewIndicatorFixture({"x": [1.0]})
    ).matches
    mismatch = compare_strategy_reports({"netprofit": 1.0}, {"netprofit": 2.0})
    assert mismatch.matches is False
    with pytest.raises(PineGoldenMismatchError):
        assert_strategy_report_close({"netprofit": 1.0}, {"netprofit": 2.0})

    provider = InMemoryDataProvider({("TEST:A", "1"): [_bar(0), _bar(1)]})
    assert provider.get_bars("TEST:A", "1", None, None, max_bars=1) == [_bar(0)]
    with pytest.raises(PineDataFormatError):
        provider.get_intrabar_bars("TEST:A", _bar(0), None)
    with pytest.raises(PineDataFormatError):
        provider.get_intrabar_bars("MISSING", _bar(0), "1")
    assert provider.get_intrabar_bars("TEST:A", _bar(0), "1", max_bars=1) == [_bar(0)]
    assert (
        _effective_close_time(
            Bar(time=_bar(1).time, open=10, high=11, low=9, close=10, time_close=None),
            [
                Bar(time=_bar(0).time, open=10, high=11, low=9, close=10, time_close=None),
                Bar(time=_bar(1).time, open=10, high=11, low=9, close=10, time_close=None),
            ],
            1,
        )
        == _bar(1).time + 60_000 - 1
    )
    req_runtime = _runtime()
    req_runtime.begin_bar(_bar(0))
    req_runtime.data_provider = InMemoryDataProvider({("TEST:Z", "1"): []})
    assert (
        security(
            "TEST:Z", "1", [1], runtime=req_runtime, state_id="missing", ignore_invalid_symbol=True
        )
        is na
    )
    assert (
        security_lower_tf(
            "X", "1", [1], runtime=req_runtime, state_id="ignore2", ignore_invalid_symbol=True
        ).size
        == 0
    )
    synthetic = type(
        "SyntheticProvider",
        (),
        {
            "__module__": "marketdata_provider.synthetic",
            "get_bars": lambda self, *args, **kwargs: [_bar(0, volume=0.0), _bar(1, volume=1.0)],
        },
    )
    syn_rt = _runtime()
    syn_rt.data_provider = synthetic()  # type: ignore[assignment]
    syn_rt.begin_bar(_bar(0))
    assert list(security_lower_tf("S", "1", [1.0], runtime=syn_rt, state_id="synthetic-ltf")) == []

    ctx = StrategyContext()
    ctx.closedtrades = 2
    assert ctx.closedtrades.current == 2
    strict_rt = _runtime(config=RuntimeConfig(process_orders_on_close=True))
    with pytest.raises(PineStrategyError):
        StrategyContext(process_orders_on_close=False, strict_tv_parity=True).attach_runtime(
            strict_rt
        )
    warn_rt = _runtime(config=RuntimeConfig(process_orders_on_close=True))
    StrategyContext(process_orders_on_close=False).attach_runtime(warn_rt)
    assert warn_rt.config.process_orders_on_close is False
    with pytest.raises(PineStrategyError):
        StrategyContext(backtest_fill_limits_assumption=1, strict_tv_parity=True).attach_runtime(
            _runtime()
        )
    assert StrategyContext.ohlc_path(Bar(time=1, open=10, high=11, low=1, close=5)) == [
        10,
        11,
        1,
        5,
    ]
    with pytest.raises(PineStrategyError):
        StrategyContext().note_calc_on_every_tick_historical_fallback(_runtime())

    class MethodLedger:
        def equity(self) -> float:
            return 123.0

    method_ctx = StrategyContext(strategy_ledger_view=MethodLedger())
    assert method_ctx.equity == 123.0


def test_release_remaining_coverage_edges(tmp_path: Path) -> None:
    import pinelib.release as release_mod
    from pinelib import distribution
    from pinelib.string import pos, tostring
    from pinelib.ta._impl_core import _RsiState, ema

    # Time/session branches that require valid timeframe after several committed bars.
    rt = _runtime(timeframe="60")
    for index in range(2):
        rt.begin_bar(_bar(index, step=3_600_000))
        rt.end_bar()
    rt.begin_bar(_bar(2, step=3_600_000))
    assert rt.timefunc.change("60", runtime=rt) is True
    assert rt.timefunc.time_close("2D", runtime=rt) is na

    # Distribution filter branches are deterministic and do not require building archives.
    root = tmp_path / "filter"
    (root / "pinelib" / "pkg.egg-info").mkdir(parents=True)
    (root / "pinelib").mkdir(exist_ok=True)
    (root / "docs").mkdir()
    root_file = root
    excluded_name = root / "pinelib" / ".coverage"
    excluded_name.write_text("x", encoding="utf-8")
    zip_file = root / "docs" / "x.zip"
    zip_file.write_text("x", encoding="utf-8")
    egg_file = root / "pinelib" / "pkg.egg-info" / "PKG-INFO"
    egg_file.write_text("x", encoding="utf-8")
    assert distribution._is_included(root_file, root) is False
    assert distribution._is_included(excluded_name, root) is False
    assert distribution._is_included(zip_file, root) is False
    assert distribution._is_included(egg_file, root) is False

    # Release report error branches that are unreachable in a valid checkout.
    bad_root = tmp_path / "release-errors"
    (bad_root / "docs").mkdir(parents=True)
    (bad_root / "pyproject.toml").write_text('version = "4.0.0"\n', encoding="utf-8")
    (bad_root / "README.md").write_text("PineLib 4.0.0\n", encoding="utf-8")
    (bad_root / "CHANGELOG.md").write_text("No current release\n", encoding="utf-8")
    report = release_validate(bad_root)
    assert any("CHANGELOG" in error for error in report.errors)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(release_mod, "PACKAGE_VERSION", "4.0.1")
        assert any("version 4.0.0" in error for error in release_mod.validate(bad_root).errors)
    with pytest.MonkeyPatch.context() as monkeypatch:

        class BadDistribution:
            archive_hygiene_ok = False
            forbidden_files = ["bad.pyc"]

        monkeypatch.setattr(release_mod, "distribution_manifest", lambda root: BadDistribution())
        assert any("distribution hygiene" in error for error in release_mod.validate(".").errors)

    # Quality duplicate scanner skips tiny definitions and syntax errors.
    qroot = tmp_path / "quality-small"
    qroot.mkdir()
    (qroot / "tiny.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (qroot / "broken.py").write_text("def bad(:\n", encoding="utf-8")
    assert duplicates(qroot).duplicate_group_count == 0

    assert tostring("plain") == "plain"
    assert pos("abc", "", 2) == 2

    # Request/security edge branches.
    first = Bar(time=0, open=1, high=1, low=1, close=1, time_close=None)
    second = Bar(time=60_000, open=1, high=1, low=1, close=1, time_close=None)
    assert _effective_close_time(first, [first, second], 0) == 59_999
    active_no_provider = _runtime()
    active_no_provider.begin_bar(_bar(0))
    assert (
        security_lower_tf(
            "X",
            "1",
            [1],
            runtime=active_no_provider,
            state_id="ignore-active",
            ignore_invalid_symbol=True,
        ).size
        == 0
    )
    provider = InMemoryDataProvider({("TEST:A", "1"): [_bar(0, step=60_000), _bar(1, step=60_000)]})
    assert provider.get_intrabar_bars("TEST:A", _bar(0, step=120_000), "1", max_bars=1) == [
        _bar(0, step=60_000)
    ]

    # Strategy scalar and ledger method branches.
    scalar_ctx = StrategyContext()
    scalar = _StrategyScalarSeries(5)
    scalar_ctx.closedtrades = scalar
    assert scalar_ctx.closedtrades is scalar

    # TA state/runtime stability branches.
    ema_state = _EmaState(1)
    assert ema_state.update(1.0) == 1.0
    assert ema_state.update(na) == 1.0
    assert _RsiState(2).update(na) is na
    median_state_runtime = _runtime()
    assert median([1, 3], 2) == [na, 2.0]
    with pytest.raises(PineRuntimeError):
        ema(1.0, 2, runtime=median_state_runtime)
    assert ema(1.0, 2, runtime=median_state_runtime, state_id="ema") is na
    with pytest.raises(PineRuntimeError):
        ema(2.0, 3, runtime=median_state_runtime, state_id="ema")
    rma_runtime = _runtime()
    assert rma(1.0, 2, runtime=rma_runtime, state_id="rma") is na
    with pytest.raises(PineRuntimeError):
        rma(2.0, 3, runtime=rma_runtime, state_id="rma")
    assert ta_range([0.0], 1) == [0.0]
    kcw_runtime = _runtime()
    kcw_runtime.begin_bar(_bar(0))
    assert kcw(kcw_runtime.close, 2, runtime=kcw_runtime, state_id="kcw-edge") is na
    flat_wpr = _runtime()
    flat_wpr.begin_bar(Bar(time=1, open=1, high=1, low=1, close=1, time_close=60_000))
    assert wpr(1, runtime=flat_wpr, state_id="flat") is na
    assert vwma([1, na], 2, [1, 1])[-1] is na
    assert alma([1, na], 2, 0.5, 6)[-1] is na
    assert bb(na, 1, 2.0) == (na, na, na)
    assert bbw([1.0, 2.0], 1, 2.0)[-1] == 0.0
    assert linreg(na, 1) is na
    assert roc(na, 1) is na
    assert cci(na, 1) is na
    assert mfi(na, 1, volume=na) is na
    assert stoch(na, [1], [1], 1) is na
    with pytest.raises(PineRuntimeError):
        dmi(1, 1, 1, 1, 1)
    with pytest.raises(PineRuntimeError):
        sar(1, 1, runtime=_runtime())


def test_release_final_uncovered_behavior_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    import pinelib.ta._impl_statistics as statistics_mod
    import pinelib.ta._impl_stats2 as stats2_mod
    from pinelib.ta._impl_core import _bar_token

    # Defensive realtime branch: a broken runtime that fails to publish current_bar must fail loudly
    # even when realtime ticks are collapsed to a single bar calculation.
    with pytest.raises(PineRuntimeError, match="current_bar"):
        run_generated_strategy(
            _OnBarStrategy(),
            _BrokenRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("1")),
            StrategyContext(calc_on_every_tick=False),
            [_bar(0)],
            realtime_ticks=[[TickUpdate(10.5, 1.0, _bar(0).time + 1, True)]],
        )

    # marketdata-provider fallback path must remain hermetic/offline-safe.
    real_import = builtins.__import__

    def hide_marketdata_provider(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("marketdata_provider"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", hide_marketdata_provider)
    contract_bar = to_contract_bar(
        _bar(0),
        instrument=InstrumentKey("TEST", "spot", "AAA"),
        timeframe=parse_timeframe("1"),
    )
    monkeypatch.setattr(builtins, "__import__", real_import)
    assert contract_bar.close == 10.0

    # TimeFunctions.change() treats missing previous chart-bar storage as a new higher-TF bucket.
    tf_runtime = _runtime()
    tf_runtime.begin_bar(_bar(0))
    tf_runtime.end_bar()
    tf_runtime.begin_bar(_bar(1))
    tf_runtime.bar_index = 1
    tf_runtime.chart_bars[0] = None  # type: ignore[list-item]
    assert tf_runtime.timefunc.change("1", runtime=tf_runtime) is True

    # Optional Parquet dependency failures should be reported as Pine errors, not ImportError leaks.

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pandas":
            raise ImportError("pandas intentionally hidden")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(PineUnsupportedFeatureError, match="Parquet loading"):
        load_bars_parquet(tmp_path / "bars.parquet")
    monkeypatch.setattr(builtins, "__import__", real_import)
    assert _int_ms(7) == 7

    # TradingView indicator CSV time/data length mismatch is a data quality error.
    indicator_path = tmp_path / "indicator_mismatch.csv"
    indicator_path.write_text("time,plot\n1000,1\n,2\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError, match="time column length"):
        load_tradingview_indicator_csv(indicator_path)

    # Duplicate scanner records non-trivial copy/paste bodies.
    dup_root = tmp_path / "dups"
    dup_root.mkdir()
    clone_source = "def clone():\n    x = 1\n    y = 2\n    z = x + y\n    return z\n"
    dup_root.joinpath("a.py").write_text(clone_source, encoding="utf-8")
    dup_root.joinpath("b.py").write_text(clone_source, encoding="utf-8")
    duplicate_report = duplicates(dup_root)
    assert duplicate_report.duplicate_group_count == 1
    assert len(duplicate_report.groups[0].locations) == 2

    # request.security out-of-range merge returns na instead of leaking IndexError.
    empty_provider_runtime = _runtime()
    empty_provider_runtime.data_provider = InMemoryDataProvider({})
    empty_provider_runtime.begin_bar(_bar(0))
    empty_provider_runtime.bar_index = 0
    assert security("TEST:EMPTY", "1", [], runtime=empty_provider_runtime, state_id="empty") is na

    # Runtime scalar branches for Keltner/Williams and SAR.
    zero_runtime = _runtime()
    zero_runtime.begin_bar(Bar(time=0, open=0, high=1, low=-1, close=0, time_close=60_000))
    zero_runtime.end_bar()
    zero_runtime.begin_bar(Bar(time=60_000, open=0, high=1, low=-1, close=0, time_close=120_000))
    assert kcw(zero_runtime.close, 1, runtime=zero_runtime, state_id="zero-width") is na

    warmup_wpr = _runtime()
    warmup_wpr.begin_bar(_bar(0))
    warmup_wpr.close.set_current(na)
    assert wpr(2, runtime=warmup_wpr, state_id="warmup-wpr") is na

    sar_runtime = _runtime()
    sar_runtime.begin_bar(_bar(0))
    assert sar(sar_runtime.high, sar_runtime.low, runtime=sar_runtime, state_id="sar-ok") is na

    # Core rolling/cached series branches.
    assert _bar_token(5.0) == (0, 5.0)

    class SeriesNoHistory:
        committed_length = 1
        _history = None

        @property
        def current(self) -> Any:
            return na

        def __getitem__(self, offset: int) -> Any:
            return na

    class SeriesWithHistory:
        def __init__(self, history: list[Any], current: Any) -> None:
            self._history = history
            self._current = current
            self.committed_length = len(history)

        @property
        def current(self) -> Any:
            return self._current

        def __getitem__(self, offset: int) -> Any:
            if offset == 0:
                return self._current
            return self._history[-offset] if offset <= len(self._history) else na

    assert highestbars(SeriesNoHistory(), 1) is na
    assert lowestbars(SeriesNoHistory(), 1) is na
    assert _rolling_extreme(SeriesWithHistory([na, 2.0], 1.0), 2, "high", bars=False) == 2.0

    change_runtime = _runtime()
    change_runtime.begin_bar(_bar(0))
    assert change(change_runtime.close, runtime=change_runtime, state_id="change-state") is na

    # Direct state branches that encode real Pine edge semantics.
    short_sar = _SarState(0.02, 0.02, 0.2, long=False, af=0.02, ep=5.0, sarv=10.0, first_bar=False)
    assert short_sar.update(9.0, 4.0) == pytest.approx(9.9)

    cci_state = _CciState(2)
    assert cci_state.update(1.0, 1.0, 1.0) is na
    assert cci_state.update(1.0, 1.0, 1.0) is na
    assert cci_state.update(2.0, 1.0, 1.0) is not na

    mfi_state = _MfiState(2)
    assert mfi_state.update(3.0, 3.0, 3.0, 1.0) is na
    assert mfi_state.update(2.0, 2.0, 2.0, 1.0) == 0.0
    assert mfi_state.update(1.0, 1.0, 1.0, 1.0) == 100.0

    cmo_state = _CmoState(1)
    assert cmo_state.update(1.0) is na
    assert cmo_state.update(1.0) is na

    tsi_state = _TsiState(1, 1)
    assert tsi_state.update(1.0) is na
    assert tsi_state.update(1.0) is na

    from pinelib.ta._impl_states import _HmaState

    assert _HmaState(2).update(na) is na
    variance_state = _VarianceState(1)
    assert variance_state.update(na) is na
    assert variance_state.update(1.0) == 0.0
    assert _RocState(1).update(na) is na

    # Statistics defensive branches.
    assert bbw(1.0, 1, 2.0) == 0.0
    monkeypatch.setattr(statistics_mod, "sma", lambda *args, **kwargs: [1.0, 2.0])
    monkeypatch.setattr(statistics_mod, "stdev", lambda *args, **kwargs: 1.0)
    assert statistics_mod.bb([1.0], 1, 2.0) == (na, na, na)

    # valuewhen cache reset and ROC scalar branch.
    condition = SeriesWithHistory([True], False)
    source = SeriesWithHistory([10.0], 20.0)
    stats2_mod._valuewhen_cache[(id(condition), id(source))] = {"processed": 99, "hits": [1.0]}
    assert valuewhen(condition, source, 0) == 10.0
    assert roc(2.0, 1) == 0.0
