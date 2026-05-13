from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from pinelib import ta
from pinelib.core.bar import Bar
from pinelib.core.na import is_na, na
from pinelib.core.runtime import PineRuntime
from pinelib.core.types import SymbolInfo, TimeframeInfo
from pinelib.errors import PineUnsupportedFeatureError
from pinelib.request.providers import InMemoryDataProvider
from pinelib.request.security import merge_requested_series_to_chart_bars, security_lower_tf

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "tradingview"
MANIFEST_PATH = FIXTURES / "cases.json"
VALUE_TOLERANCE = 1e-9
WARMED_STATEFUL_START_INDEX = 200


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _value(raw: str) -> float | object:
    return na if raw == "" else float(raw)


def _assert_close(
    actual: Any, expected: str, *, row_id: str, column: str, tolerance: float = VALUE_TOLERANCE
) -> None:
    expected_value = _value(expected)
    if is_na(expected_value):
        assert is_na(actual), f"{row_id} {column}: expected na, got {actual!r}"
        return
    assert not is_na(actual), f"{row_id} {column}: expected {expected_value!r}, got na"
    assert isinstance(expected_value, float)
    assert math.isclose(float(actual), expected_value, rel_tol=tolerance, abs_tol=tolerance), (
        f"{row_id} {column}: expected {expected_value!r}, got {actual!r}"
    )


def _assert_columns_close(
    actual_rows: Mapping[int, Mapping[str, Any]],
    expected_rows: Iterable[Mapping[str, str]],
    columns: Sequence[str],
    *,
    start_index: int = 0,
    tolerance: float = VALUE_TOLERANCE,
) -> None:
    checked = 0
    for expected in expected_rows:
        bar_index = int(expected["bar_index"])
        if bar_index < start_index:
            continue
        actual = actual_rows[bar_index]
        for column in columns:
            _assert_close(
                actual[column],
                expected[column],
                row_id=f"bar_index={bar_index}",
                column=column,
                tolerance=tolerance,
            )
            checked += 1
    assert checked > 0


def _bar_from_row(row: Mapping[str, str], *, time_close: int | None = None) -> Bar:
    return Bar(
        time=int(float(row["time"])) * 1000,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume", "0") or 0),
        time_close=time_close,
    )


def _expected_by_non_negative_index(
    rows: Iterable[Mapping[str, str]],
) -> dict[int, Mapping[str, str]]:
    return {int(row["bar_index"]): row for row in rows if int(row["bar_index"]) >= 0}


def _manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def test_tradingview_oracle_manifest_counts_verified_and_blocked_cases_without_pending() -> None:
    manifest = _manifest()
    cases = manifest["cases"]
    statuses = {case["status"] for case in cases}
    assert statuses <= {"oracle_verified", "golden_synthetic", "platform_blocked"}
    assert "pending_external_oracle" not in statuses

    for case in cases:
        case_dir = MANIFEST_PATH.parent / case["id"]
        for evidence_file in case.get("evidence_files", []):
            assert (case_dir / evidence_file).is_file()
        if case["status"] == "oracle_verified":
            assert case.get("oracle_source", "").startswith("TradingView")
            for required_file in case["required_files"]:
                assert (case_dir / required_file).is_file()
        elif case["status"] == "platform_blocked":
            assert case.get("blocked_reason", "").strip()
            assert case.get("blocked_by", "").strip()
            assert all(
                not (case_dir / required_file).exists() for required_file in case["required_files"]
            )

    result = subprocess.run(
        [sys.executable, "scripts/run_tv_golden_suite.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)
    assert summary["oracle_verified"] == sum(case["status"] == "oracle_verified" for case in cases)
    assert summary["platform_blocked"] == sum(
        case["status"] == "platform_blocked" for case in cases
    )
    assert summary["pending_external_oracle"] == 0


def test_calc_on_every_tick_supplied_ticks_is_platform_blocked_not_pending() -> None:
    case_dir = FIXTURES / "calc_on_every_tick_supplied_ticks"
    case = next(
        case for case in _manifest()["cases"] if case["id"] == "calc_on_every_tick_supplied_ticks"
    )
    evidence = json.loads((case_dir / "evidence.json").read_text(encoding="utf-8"))
    blocked_evidence = (case_dir / "platform_blocked_evidence.md").read_text(encoding="utf-8")

    assert case["status"] == "platform_blocked"
    assert evidence["status"] == "platform_blocked"
    assert evidence["candidate_verified"] is False
    assert evidence["oracle_not_applicable"] is True
    assert "No ticks.csv" in evidence["hard_rule_note"]
    assert "historical bars contain no tick data" in blocked_evidence
    assert "no deterministic tick stream" in blocked_evidence
    assert all(not (case_dir / required_file).exists() for required_file in case["required_files"])


def test_session_time_time_close_timeframe_guard_matches_tradingview_daily_time_values() -> None:
    case_dir = FIXTURES / "session_time_time_close_timeframe_guard"
    bars_rows = _load_csv(case_dir / "bars.csv")
    expected_rows = _load_csv(case_dir / "expected_time.csv")
    expected_by_index = _expected_by_non_negative_index(expected_rows)
    runtime = PineRuntime(
        symbol_info=SymbolInfo(
            tickerid="NASDAQ:AAPL", timezone="America/New_York", session="0930-1600:23456"
        ),
        timeframe=TimeframeInfo.from_string("1D"),
    )

    actual: dict[int, dict[str, Any]] = {}
    for bar_row in bars_rows:
        bar_index = int(bar_row["bar_index"])
        expected = expected_by_index[bar_index]
        runtime.begin_bar(_bar_from_row(bar_row, time_close=int(expected["bar_time_close"])))
        bar_time = runtime.timefunc.time(runtime=runtime)
        assert isinstance(bar_time, int)
        actual[bar_index] = {
            "bar_time": float(bar_time) / 1000.0,
            "bar_time_close": runtime.timefunc.time_close(runtime=runtime),
        }
        with pytest.raises(PineUnsupportedFeatureError):
            runtime.timefunc.time("W", runtime=runtime)
        with pytest.raises(PineUnsupportedFeatureError):
            runtime.timefunc.time_close("W", runtime=runtime)
        runtime.end_bar()

    _assert_columns_close(actual, expected_by_index.values(), ["bar_time", "bar_time_close"])
    assert all(row["time_W"] and row["time_close_W"] for row in expected_rows)


def test_request_security_gaps_and_lookahead_matches_tradingview_expected_csv() -> None:
    case_dir = FIXTURES / "request_security_gaps_lookahead"
    chart_rows = _load_csv(case_dir / "bars.csv")
    expected_rows = _load_csv(case_dir / "expected_security.csv")
    expected_by_index = _expected_by_non_negative_index(expected_rows)
    assert len(chart_rows) == len(expected_by_index)
    chart_bars = [
        Bar(
            time=int(row["time"]) * 1000,
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            time_close=int(row["time_W"]),
        )
        for row in expected_rows
    ]

    # TradingView weekly chart export: time_W is the weekly bar's CLOSE time (end of week),
    # time_close_W is the weekly bar's OPEN time (start of week). All rows: time_W > time_close_W.
    # Use time_close_W for Bar.time (bar open) and time_W for Bar.time_close (bar close).
    weekly_closes: list[tuple[int, int, float]] = []  # (open_time, close_time, value)
    seen_close_times: set[int] = set()
    for row in expected_rows:
        value = row["sec_w_gaps_on_la_off"]
        if value == "":
            continue
        close_time = int(row["time_W"])
        if close_time in seen_close_times:
            continue
        seen_close_times.add(close_time)
        open_time = int(row["time_close_W"])
        weekly_closes.append((open_time, close_time, float(value)))

    off_gaps_on_bars = [
        Bar(time=open_time, open=value, high=value, low=value, close=value, time_close=close_time)
        for open_time, close_time, value in weekly_closes
    ]
    off_gaps_on_values = [bar.close for bar in off_gaps_on_bars]
    # Build time_W -> time_close_W lookup from expected_rows
    time_w_to_time_close_w: dict[int, int] = {}
    for row in expected_rows:
        tw = int(row["time_W"])
        if tw not in time_w_to_time_close_w:
            time_w_to_time_close_w[tw] = int(row["time_close_W"])

    off_gaps_off_points: list[tuple[int, int, float]] = []  # (open_time, close_time, value)
    last_off_value: str | None = None
    for row in expected_rows:
        value = row["sec_w_gaps_off_la_off"]
        if value == "" or value == last_off_value:
            continue
        close_time = int(row["time_W"])
        open_time = time_w_to_time_close_w[close_time]
        off_gaps_off_points.append((open_time, close_time, float(value)))
        last_off_value = value
    off_gaps_off_bars = [
        Bar(time=open_time, open=value, high=value, low=value, close=value, time_close=close_time)
        for open_time, close_time, value in off_gaps_off_points
    ]
    off_gaps_off_values = [bar.close for bar in off_gaps_off_bars]
    # For lookahead_on, use the weekly bar's open/close times (time_close_W / time_W)
    # rather than chart_time, since we are requesting a weekly timeframe.
    lookahead_on_points: list[tuple[int, int, float]] = []  # (open_time, close_time, value)
    for row in expected_rows:
        if row["sec_w_gaps_on_la_on"] == "":
            continue
        open_time = int(row["time_close_W"])
        close_time = int(row["time_W"])
        lookahead_on_points.append((open_time, close_time, float(row["sec_w_gaps_on_la_on"])))
    on_bars = [
        Bar(time=open_time, open=value, high=value, low=value, close=value, time_close=close_time)
        for open_time, close_time, value in lookahead_on_points
    ]
    on_values = [bar.close for bar in on_bars]

    actual_by_index: dict[int, dict[str, Any]] = {}
    merged = {
        "sec_w_gaps_on_la_off": merge_requested_series_to_chart_bars(
            off_gaps_on_values,
            requested_bars=off_gaps_on_bars,
            chart_bars=chart_bars,
            gaps="barmerge.gaps_on",
            lookahead="barmerge.lookahead_off",
        ),
        "sec_w_gaps_off_la_off": merge_requested_series_to_chart_bars(
            off_gaps_off_values,
            requested_bars=off_gaps_off_bars,
            chart_bars=chart_bars,
            gaps="barmerge.gaps_off",
            lookahead="barmerge.lookahead_off",
        ),
        "sec_w_gaps_on_la_on": merge_requested_series_to_chart_bars(
            on_values,
            requested_bars=on_bars,
            chart_bars=chart_bars,
            gaps="barmerge.gaps_on",
            lookahead="barmerge.lookahead_on",
        ),
        "sec_w_gaps_off_la_on": merge_requested_series_to_chart_bars(
            on_values,
            requested_bars=on_bars,
            chart_bars=chart_bars,
            gaps="barmerge.gaps_off",
            lookahead="barmerge.lookahead_on",
        ),
    }
    for row_number, row in enumerate(expected_rows):
        bar_index = int(row["bar_index"])
        if bar_index >= 0:
            actual_by_index[bar_index] = {
                name: values[row_number] for name, values in merged.items()
            }

    _assert_columns_close(
        actual_by_index,
        expected_by_index.values(),
        [
            "sec_w_gaps_on_la_off",
            "sec_w_gaps_off_la_off",
            "sec_w_gaps_on_la_on",
            "sec_w_gaps_off_la_on",
        ],
    )


def test_request_security_lower_tf_matches_tradingview_intrabar_fixture() -> None:
    case_dir = FIXTURES / "request_security_lower_tf_intrabar_validation"
    chart_rows = _load_csv(case_dir / "bars.csv")
    lower_rows = _load_csv(case_dir / "lower_tf_bars.csv")
    expected = json.loads((case_dir / "expected_lower_tf.json").read_text(encoding="utf-8"))["bars"]
    expected_by_index = {int(row["bar_index"]): row for row in expected}
    lower_bars = [
        Bar(
            time=int(row["time"]) * 1000,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for row in lower_rows
    ]
    runtime = PineRuntime(
        symbol_info=SymbolInfo(
            tickerid="NASDAQ:AAPL", timezone="America/New_York", session="0930-1600:23456"
        ),
        timeframe=TimeframeInfo.from_string("1D"),
        data_provider=InMemoryDataProvider({("NASDAQ:AAPL", "60"): lower_bars}),
    )

    checked = 0
    for row in chart_rows:
        bar_index = int(row["bar_index"])
        runtime.begin_bar(_bar_from_row(row, time_close=int(row["time_close"]) * 1000))
        close_values = list(
            security_lower_tf(
                "NASDAQ:AAPL",
                "60",
                lambda child: child.close[0],
                runtime=runtime,
                state_id="ltf_close",
            )
        )
        high_values = list(
            security_lower_tf(
                "NASDAQ:AAPL",
                "60",
                lambda child: child.high[0],
                runtime=runtime,
                state_id="ltf_high",
            )
        )
        low_values = list(
            security_lower_tf(
                "NASDAQ:AAPL", "60", lambda child: child.low[0], runtime=runtime, state_id="ltf_low"
            )
        )
        exp = expected_by_index[bar_index]
        assert len(close_values) == exp["count"]
        assert len(high_values) == exp["count"]
        assert len(low_values) == exp["count"]
        for actual, expected_close in zip(close_values, exp["close_values"], strict=True):
            assert math.isclose(
                float(actual),
                float(expected_close),
                rel_tol=VALUE_TOLERANCE,
                abs_tol=VALUE_TOLERANCE,
            )
        assert math.isclose(
            float(close_values[0]),
            float(exp["first_close"]),
            rel_tol=VALUE_TOLERANCE,
            abs_tol=VALUE_TOLERANCE,
        )
        assert math.isclose(
            float(close_values[-1]),
            float(exp["last_close"]),
            rel_tol=VALUE_TOLERANCE,
            abs_tol=VALUE_TOLERANCE,
        )
        assert math.isclose(
            max(float(value) for value in high_values),
            float(exp["high_max"]),
            rel_tol=VALUE_TOLERANCE,
            abs_tol=VALUE_TOLERANCE,
        )
        assert math.isclose(
            min(float(value) for value in low_values),
            float(exp["low_min"]),
            rel_tol=VALUE_TOLERANCE,
            abs_tol=VALUE_TOLERANCE,
        )
        runtime.end_bar()
        checked += 1

    assert checked == len(expected)
    assert {entry.selected_bars for entry in runtime.lower_tf_metadata_log} == {7}


def test_crypto_247_intraday_fixture_preserves_tradingview_hourly_bars() -> None:
    case_dir = FIXTURES / "crypto_247_intraday_bars"
    rows = _load_csv(case_dir / "bars.csv")
    expected = json.loads((case_dir / "expected_bars.json").read_text(encoding="utf-8"))
    assert len(rows) == expected["bar_count"] == 300
    assert int(rows[0]["time"]) == expected["first_time"]
    assert int(rows[-1]["time"]) == expected["last_time"]
    assert math.isclose(
        float(rows[0]["close"]),
        float(expected["first_close"]),
        rel_tol=VALUE_TOLERANCE,
        abs_tol=VALUE_TOLERANCE,
    )
    assert math.isclose(
        float(rows[-1]["close"]),
        float(expected["last_close"]),
        rel_tol=VALUE_TOLERANCE,
        abs_tol=VALUE_TOLERANCE,
    )
    for previous, current in zip(rows, rows[1:], strict=False):
        assert int(current["time"]) - int(previous["time"]) == expected["expected_step_seconds"]
    assert math.isclose(
        sum(float(row["volume"]) for row in rows),
        float(expected["total_volume"]),
        rel_tol=VALUE_TOLERANCE,
        abs_tol=1e-6,
    )

    runtime = PineRuntime(
        symbol_info=SymbolInfo(tickerid="BINANCE:BTCUSDT", timezone="Etc/UTC", session="24x7"),
        timeframe=TimeframeInfo.from_string("60"),
    )
    for row in rows:
        runtime.begin_bar(_bar_from_row(row, time_close=int(row["time_close"]) * 1000))
        assert runtime.time[0] == int(row["time"]) * 1000
        assert runtime.time_close[0] == int(row["time_close"]) * 1000
        runtime.end_bar()
    assert runtime.bar_index == expected["bar_count"] - 1


def test_strategy_tester_trade_exports_are_tradingview_reportdata_backed() -> None:
    cases = {
        "strategy_market_limit_stop_stop_limit": {"trades": 4, "filled_orders": 8},
        "strategy_exit_oca_reservation": {"trades": 2, "filled_orders": 3},
    }
    for case_id, expected_counts in cases.items():
        case_dir = FIXTURES / case_id
        trades = _load_csv(case_dir / "expected_trades.csv")
        filled_orders = _load_csv(case_dir / "filled_orders.csv")
        evidence = json.loads((case_dir / "evidence.json").read_text(encoding="utf-8"))
        report_data = json.loads(
            (case_dir / "strategy_report_data.json").read_text(encoding="utf-8")
        )

        assert len(trades) == expected_counts["trades"]
        assert len(filled_orders) == expected_counts["filled_orders"]
        assert evidence["candidate_verified"] is True
        assert "TradingView" in evidence["oracle_source"]
        assert "reportData" in evidence["oracle_source"]
        assert len(report_data["trades"]) == expected_counts["trades"]
        assert len(report_data["filledOrders"]) == expected_counts["filled_orders"]
        for idx, row in enumerate(trades):
            assert int(row["trade_no"]) == idx
            assert row["entry_comment"]
            assert row["exit_comment"]
            assert float(row["quantity"]) > 0
            assert int(row["entry_time_ms"]) > 0
            assert int(row["exit_time_ms"]) >= int(row["entry_time_ms"])

    oca_trades = _load_csv(FIXTURES / "strategy_exit_oca_reservation" / "expected_trades.csv")
    assert [float(row["quantity"]) for row in oca_trades] == [1.0, 19.0]
    assert {row["exit_comment"] for row in oca_trades} == {"STOP_REDUCED_20", "LIM_RESERVE_19"}


def test_ta_stateful_indicators_match_tradingview_after_visible_warmup() -> None:
    case_dir = FIXTURES / "ta_stateful_indicators"
    bars_rows = _load_csv(case_dir / "bars.csv")
    expected_rows = _load_csv(case_dir / "expected_indicators.csv")
    closes = [float(row["close"]) for row in bars_rows]
    highs = [float(row["high"]) for row in bars_rows]
    lows = [float(row["low"]) for row in bars_rows]
    macd_line, macd_signal, macd_hist = ta.macd(closes, 12, 26, 9)
    calculated = {
        "sma5": ta.sma(closes, 5),
        "ema5": ta.ema(closes, 5),
        "rma5": ta.rma(closes, 5),
        "rsi14": ta.rsi(closes, 14),
        "atr14": ta.atr(14, high=highs, low=lows, close=closes),
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "stoch14": ta.stoch(closes, highs, lows, 14),
    }
    actual_by_index = {
        int(row["bar_index"]): {name: values[position] for name, values in calculated.items()}
        for position, row in enumerate(bars_rows)
    }

    # The TradingView export includes 100 pre-visible warmup bars, while bars.csv intentionally stores only  # noqa: E501
    # the visible 300 bars. Compare from bar 200 once EMA/RMA/RSI/ATR/MACD state has converged to TV values.  # noqa: E501
    _assert_columns_close(
        actual_by_index,
        expected_rows,
        list(calculated),
        start_index=WARMED_STATEFUL_START_INDEX,
        tolerance=1e-5,
    )
    # Stateless rolling outputs are exact on the visible input and protect the full expected CSV tail too.  # noqa: E501
    _assert_columns_close(actual_by_index, expected_rows, ["sma5", "stoch14"], start_index=13)
