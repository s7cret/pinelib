from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from pinelib import (
    Bar,
    PineArray,
    PineDataFormatError,
    PineMap,
    PineMatrix,
    PineRuntime,
    RuntimeConfig,
    StrategyContext,
    SymbolInfo,
    TimeframeInfo,
    VisualRecorder,
    color,
    is_na,
    na,
    reference_history,
    string,
    ta,
)
from pinelib.backtest import (
    BacktestSnapshot,
    compare_golden,
    extract_params_metadata,
    extract_strategy_params,
    write_result_snapshot,
)
from pinelib.compat.marketdata import (
    ContractBar,
    InstrumentKey,
    InvalidBarError,
    InvalidTimeframeError,
    parse_timeframe,
)
from pinelib.core import operators, pine_eq, pine_gt, pine_gte, pine_lt, pine_lte, pine_ne
from pinelib.core.na import fixnan, nz
from pinelib.errors import PineGoldenMismatchError, PineRuntimeError, PineUnsupportedFeatureError
from pinelib.io import load_bars, load_bars_csv
from pinelib.math import avg, pine_sum, random, round, sqrt
from pinelib.math import max as pine_max
from pinelib.math import min as pine_min
from pinelib.parity import (
    StrategyCompareReport,
    TradingViewIndicatorFixture,
    compare_indicator_fixture,
    compare_strategy_reports,
    default_sample_contracts,
    load_tradingview_indicator_csv,
    load_tradingview_trades_csv,
    write_sample_contracts,
)
from pinelib.plot import PlotRecorder
from pinelib.request.footprint import FootprintSnapshot, footprint
from pinelib.request.providers import InMemoryDataProvider
from pinelib.strategy.models import _StrategyScalarSeries


def _runtime() -> PineRuntime:
    return PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60"))


def test_compat_marketdata_and_bar_file_io(tmp_path) -> None:
    one_minute = parse_timeframe("1m")
    assert one_minute.unit == "minute"
    assert one_minute.duration_ms == 60_000
    assert parse_timeframe("1H").duration_ms == 3_600_000
    assert parse_timeframe("D").unit == "day"
    assert parse_timeframe("1M").duration_ms is None
    with pytest.raises(InvalidTimeframeError):
        parse_timeframe("bad")
    with pytest.raises(InvalidBarError):
        ContractBar(
            InstrumentKey("x", "spot", "AAA"),
            one_minute,
            10,
            10,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
        )

    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,o,h,l,c,v,close_time\n" "1000,1,2,0.5,1.5,9,1999\n" "2000,2,3,1.5,2.5,8,2999\n",
        encoding="utf-8",
    )
    bars = load_bars_csv(csv_path)
    assert [bar.close for bar in bars] == [1.5, 2.5]
    assert load_bars(csv_path) == bars
    with pytest.raises(PineDataFormatError):
        load_bars(tmp_path / "bars.txt")
    bad_path = tmp_path / "bad.csv"
    bad_path.write_text("time,open,high,low\n1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(bad_path)


def test_math_string_color_reference_visual_and_footprint() -> None:
    assert sqrt(9) == 3
    assert round(1.25, 1) == 1.3
    assert pine_min(3, 1, 2) == 1
    assert pine_max(3, 1, 2) == 3
    assert avg(1, 2, 3) == 2
    assert pine_sum([1, na, 2]) == 3
    assert 0 <= random(seed=1) <= 1
    with pytest.raises(ValueError):
        pine_min()

    assert string.tostring(1.234, "#.##") == "1.23"
    assert string.tonumber("12.5") == 12.5
    assert is_na(string.tonumber("x"))
    assert string.contains("abc", "b")
    assert string.startswith("abc", "a")
    assert string.endswith("abc", "c")
    assert string.lower("ABC") == "abc"
    assert string.upper("abc") == "ABC"
    assert string.length("abc") == 3
    assert string.substring("abcd", 1, 3) == "bc"
    assert string.replace("a-b-a", "a", "x", 1) == "a-b-x"
    assert string.pos("abc", "b") == 1

    c = color.rgb(10, 20, 30, 50)
    assert color.r(c) == 10 and color.g(c) == 20 and color.b(c) == 30
    assert color.new(c, 0).a == 0
    assert c.to_hex().startswith("#")
    with pytest.raises(ValueError):
        color.Color(-1, 0, 0)

    arr = PineArray.new_float(1.0)
    arr.push(2.0)
    assert arr.get(0) == 1.0
    assert arr.avg() == 1.5
    assert arr.sum() == 3.0
    assert arr.min() == 1.0
    assert arr.max() == 2.0
    arr.sort("desc")
    assert list(arr) == [2.0, 1.0]
    assert arr.copy().size == arr.size
    assert is_na(arr.shift(99))

    mapping: PineMap[str, int] = PineMap({"a": 1})
    mapping.put("b", 2)
    assert mapping.contains("a")
    assert mapping.get("b") == 2
    assert mapping.remove("a") == 1
    assert len(mapping.copy()) == 1

    matrix: PineMatrix[int] = PineMatrix(2, 2, 0)
    matrix.set(1, 1, 7)
    assert matrix.get(1, 1) == 7
    assert matrix.copy().get(1, 1) == 7

    config = RuntimeConfig()
    with pytest.raises(PineUnsupportedFeatureError):
        reference_history(arr, 1, config)
    assert config.diagnostics[-1]["code"]

    recorder = VisualRecorder(RuntimeConfig(), max_labels_count=1)
    label_id = recorder.label_new(text="x")
    recorder.set(label_id, text="y")
    recorder.delete(label_id)
    recorder.line_new(x1=0, y1=1)
    recorder.box_new(left=0)
    recorder.table_new(columns=1)
    with pytest.raises(PineRuntimeError):
        recorder.set(label_id, text="z")
    recorder.label_new(text="a")
    with pytest.raises(PineRuntimeError):
        recorder.label_new(text="b")

    class Provider:
        def get_current_footprint(self, bar: Bar | None) -> FootprintSnapshot:
            assert bar is None or isinstance(bar, Bar)
            return FootprintSnapshot(10, 4)

    runtime = SimpleNamespace(current_bar=None, footprint_provider=Provider())
    snapshot = footprint(runtime=runtime, state_id="fp")
    assert isinstance(snapshot, FootprintSnapshot)
    assert snapshot.delta() == 6
    runtime.footprint_provider = object()
    assert is_na(footprint(runtime=runtime, state_id="fp"))


def test_operators_na_precision_and_scalar_series() -> None:
    assert nz(na, 5) == 5
    assert fixnan(na) is na
    assert fixnan(7) == 7
    assert operators.pine_add(1, 2) == 3
    assert operators.pine_sub(3, 1) == 2
    assert operators.pine_mul(2, 4) == 8
    assert operators.pine_div(5, 2) == 2.5
    with pytest.raises(ZeroDivisionError):
        operators.pine_div(5, 0)
    assert pine_eq(1, 1)
    assert pine_ne(1, 2)
    assert pine_gt(2, 1)
    assert pine_gte(2, 2)
    assert pine_lt(1, 2)
    assert pine_lte(2, 2)
    assert operators.pine_bool(1)
    assert list(operators.pine_range(1, 3)) == [1, 2, 3]
    assert list(operators.pine_range(3, 1)) == [3, 2, 1]

    scalar = _StrategyScalarSeries(2)
    scalar.commit_current()
    scalar.set_current(5)
    assert scalar[0] == 5
    assert scalar[1] == 2
    assert scalar[99] == 0
    assert float(scalar) == 5.0
    assert int(scalar) == 5
    assert scalar + 1 == 6
    assert 1 + scalar == 6
    assert scalar - 2 == 3
    assert 8 - scalar == 3
    assert scalar * 2 == 10
    assert 2 * scalar == 10
    assert scalar / 2 == 2.5
    assert 10 / scalar == 2
    assert scalar > 4 and scalar >= 5 and scalar < 6 and scalar <= 5
    with pytest.raises(IndexError):
        _ = scalar[-1]


def test_ta_public_batch_smoke_and_edge_paths() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    highs = [v + 0.5 for v in values]
    lows = [v - 0.5 for v in values]
    volumes = [10.0 + i for i in range(len(values))]

    assert ta.median(values, 3)[-1] == 2.0
    assert ta.mode([1, 2, 2, 3], 3)[-1] == 2
    bars_runtime = _runtime()
    highbars = []
    lowbars = []
    for idx, value in enumerate(values):
        bars_runtime.begin_bar(Bar(10_000 + idx * 1000, value, value + 0.5, value - 0.5, value))
        highbars.append(ta.highestbars(bars_runtime.close, 4))
        lowbars.append(ta.lowestbars(bars_runtime.close, 4))
        bars_runtime.end_bar()
    assert highbars[-1] == -3
    assert lowbars[-1] == 0
    assert len(ta.stdev(values, 3)) == len(values)
    assert len(ta.variance(values, 3)) == len(values)
    assert len(ta.dev(values, 3)) == len(values)
    assert len(ta.wma(values, 3)) == len(values)
    assert len(ta.vwma(values, 3, volumes)) == len(values)
    assert len(ta.hma(values, 4)) == len(values)
    assert len(ta.swma(values)) == len(values)
    assert len(ta.alma(values, 4, 0.85, 6)) == len(values)
    assert len(ta.bb(values, 3, 2.0)[0]) == len(values)
    assert len(ta.bbw(values, 3, 2.0)) == len(values)
    assert len(ta.stoch(values, highs, lows, 3)) == len(values)
    assert len(ta.dmi(highs, lows, values, 3, 3)[0]) == len(values)
    assert len(ta.adx(highs, lows, values, 3, 3)) == len(values)
    assert len(ta.supertrend(2.0, 3, high=highs, low=lows, close=values)[0]) == len(values)
    assert len(ta.sar(highs, lows, 0.02, 0.02, 0.2)) == len(values)
    pivot_runtime = _runtime()
    pivots_high = []
    pivots_low = []
    for idx, value in enumerate(values):
        pivot_runtime.begin_bar(Bar(20_000 + idx * 1000, value, value + 0.5, value - 0.5, value))
        pivots_high.append(ta.pivothigh(pivot_runtime.close, 2, 2))
        pivots_low.append(ta.pivotlow(pivot_runtime.close, 2, 2))
        pivot_runtime.end_bar()
    assert all(is_na(item) or isinstance(item, float) for item in pivots_high)
    assert all(is_na(item) or isinstance(item, float) for item in pivots_low)
    assert ta.valuewhen([False, True, False, True], values[:4], 0)[-1] == 4.0
    assert ta.barssince([False, True, False])[-1] == 1
    assert len(ta.linreg(values, 3, 0)) == len(values)
    assert len(ta.percentile_nearest_rank(values, 3, 50)) == len(values)
    assert len(ta.percentile_linear_interpolation(values, 3, 50)) == len(values)
    assert len(ta.percentrank(values, 3)) == len(values)
    assert len(ta.vwap(values, volumes)) == len(values)
    assert len(ta.mom(values, 2)) == len(values)
    assert len(ta.roc(values, 2)) == len(values)
    assert len(ta.correlation(values, list(reversed(values)), 3)) == len(values)
    trend_runtime = _runtime()
    rising_values = []
    falling_values = []
    for idx, value in enumerate(values):
        trend_runtime.begin_bar(Bar(30_000 + idx * 1000, value, value + 0.5, value - 0.5, value))
        rising_values.append(ta.rising(trend_runtime.close, 3))
        falling_values.append(ta.falling(trend_runtime.close, 3))
        trend_runtime.end_bar()
    assert rising_values[-1] is False
    assert falling_values[-1] is True
    assert len(ta.cci(values, 3)) == len(values)
    assert len(ta.mfi(values, 3, volume=volumes)) == len(values)
    assert len(ta.obv(values, volumes)) == len(values)
    assert len(ta.ta_range(values, 3)) == len(values)
    assert len(ta.cmo(values, 3)) == len(values)
    assert len(ta.tsi(values, 3, 5)) == len(values)
    assert len(ta.kc(values, 3, 1.5, runtime=None)[0]) == len(values)
    assert len(ta.kcw(values, 3, 1.5, runtime=None)) == len(values)
    wpr_runtime = _runtime()
    wpr_values = []
    for idx, (value, high, low) in enumerate(zip(values, highs, lows, strict=True)):
        wpr_runtime.begin_bar(Bar(40_000 + idx * 1000, value, high, low, value))
        wpr_values.append(ta.wpr(3, runtime=wpr_runtime, state_id="wpr"))
        wpr_runtime.end_bar()
    assert len(wpr_values) == len(values)
    assert ta.cum([1, na, 2]) == [1.0, 1.0, 3.0]


def test_runtime_strategy_backtest_plot_provider_and_parity(tmp_path) -> None:
    runtime = _runtime()
    strategy = StrategyContext(default_qty_value=2, margin_long=50, margin_short=50)
    runtime.begin_bar(Bar(1000, 1, 2, 0.5, 1.5, 10, 1999))
    strategy.attach_runtime(runtime)
    strategy.entry("L", "long", qty=2, limit=1.4, comment="entry")
    strategy.order("S", "short", qty=1, stop=1.0, oca_name="grp", oca_type="cancel")
    strategy.exit("XL", from_entry="L", qty_percent=50, profit=10, loss=5, trail_offset=1)
    strategy.close("L", qty=1, immediately=True)
    strategy.cancel("S")
    strategy.cancel_all()
    strategy.risk_max_drawdown(10, "percent")
    strategy.risk_max_intraday_loss(5, "cash")
    strategy.risk_max_position_size(3)
    strategy.risk_allow_entry_in("long")
    strategy.risk_max_cons_loss_days(2)
    strategy.risk_max_intraday_filled_orders(5)
    strategy.commit_scalar_history()
    snapshot = BacktestSnapshot(runtime.bar_index, runtime.time, runtime.close.current)

    @dataclass
    class Generated:
        params = {"qty": 2}
        INPUT_METADATA = {"qty": {"default": 2}}

        def on_bar(self, rt: PineRuntime, st: StrategyContext) -> None:
            st.entry("G", "long", qty=1)

    assert extract_strategy_params(Generated()) == {"qty": 2}
    assert extract_params_metadata(Generated()) == {"qty": {"default": 2}}
    from pinelib.backtest import build_backtest_report, run_generated_strategy

    report = build_backtest_report(runtime, strategy, Generated(), [snapshot])
    assert report.order_intents
    result = run_generated_strategy(
        Generated(),
        _runtime(),
        StrategyContext(),
        [Bar(2000, 1, 2, 0.5, 1.0, 1, 2999)],
        progress_callback=lambda done, total: assert_progress(done, total),
    )
    out = tmp_path / "snapshot.json"
    write_result_snapshot(result, out)
    assert json.loads(out.read_text())["report"]["bars"] == 1
    compare_golden({"x": [1.0]}, {"x": [1.0 + 1e-10]}, abs_tol=1e-8)
    with pytest.raises(PineGoldenMismatchError):
        compare_golden({"x": 1}, {"x": 2})

    recorder = PlotRecorder()
    recorder.record_plot(1000, 0, 1.0, "A")
    recorder.record(1000, 0, "plotshape", True, "B", {"text": "yes"})
    recorder.record(1000, 0, "plotchar", True, "C", {"char": "*"})
    assert len(recorder.get_records()) == 3
    assert recorder.get_data_by_time()[1000]["A"] == 1.0

    provider = InMemoryDataProvider({("test:aaa", "1"): [Bar(0, 1, 1, 1, 1, time_close=59_999)]})
    assert provider.get_bars("TEST:AAA", "1", None, None)
    assert provider.get_intrabar_bars("TEST:AAA", Bar(0, 1, 1, 1, 1, time_close=59_999), "1")

    csv = tmp_path / "indicator.csv"
    csv.write_text("time,value\n1,2.5\n", encoding="utf-8")
    fixture = load_tradingview_indicator_csv(csv)
    assert isinstance(fixture, TradingViewIndicatorFixture)
    assert compare_indicator_fixture({"value": [2.5]}, fixture).matches
    trades_csv = tmp_path / "trades.csv"
    trades_csv.write_text("entry_id,profit\nL,1.5\n", encoding="utf-8")
    assert load_tradingview_trades_csv(trades_csv)[0]["entry_id"] == "L"
    cmp_report = compare_strategy_reports(
        {"final_equity": 1.0}, {"final_equity": 1.0}, fields=("final_equity",)
    )
    assert isinstance(cmp_report, StrategyCompareReport) and cmp_report.matches
    samples_path = tmp_path / "samples.json"
    assert default_sample_contracts()
    write_sample_contracts(samples_path)
    assert samples_path.exists()


def assert_progress(done: int, total: int) -> None:
    assert 0 < done <= total
