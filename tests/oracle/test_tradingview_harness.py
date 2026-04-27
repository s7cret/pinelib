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
from pinelib.request.security import merge_requested_series_to_chart_bars

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


def _assert_close(actual: Any, expected: str, *, row_id: str, column: str, tolerance: float = VALUE_TOLERANCE) -> None:
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
            _assert_close(actual[column], expected[column], row_id=f"bar_index={bar_index}", column=column, tolerance=tolerance)
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


def _expected_by_non_negative_index(rows: Iterable[Mapping[str, str]]) -> dict[int, Mapping[str, str]]:
    return {int(row["bar_index"]): row for row in rows if int(row["bar_index"]) >= 0}


def _manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def test_tradingview_oracle_manifest_counts_verified_and_pending_cases() -> None:
    manifest = _manifest()
    cases = manifest["cases"]
    statuses = {case["status"] for case in cases}
    assert statuses <= {"oracle_verified", "golden_synthetic", "pending_external_oracle"}

    for case in cases:
        case_dir = MANIFEST_PATH.parent / case["id"]
        for evidence_file in case.get("evidence_files", []):
            assert (case_dir / evidence_file).is_file()
        if case["status"] == "oracle_verified":
            assert case.get("oracle_source", "").startswith("TradingView")
            for required_file in case["required_files"]:
                assert (case_dir / required_file).is_file()
        elif case["status"] == "pending_external_oracle":
            assert case.get("pending_reason", "").strip()
            assert all(not (case_dir / required_file).exists() for required_file in case["required_files"])

    result = subprocess.run(
        [sys.executable, "scripts/run_tv_golden_suite.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)
    assert summary["oracle_verified"] == sum(case["status"] == "oracle_verified" for case in cases)
    assert summary["pending_external_oracle"] == sum(case["status"] == "pending_external_oracle" for case in cases)


def test_session_time_time_close_timeframe_guard_matches_tradingview_daily_time_values() -> None:
    case_dir = FIXTURES / "session_time_time_close_timeframe_guard"
    bars_rows = _load_csv(case_dir / "bars.csv")
    expected_rows = _load_csv(case_dir / "expected_time.csv")
    expected_by_index = _expected_by_non_negative_index(expected_rows)
    runtime = PineRuntime(
        symbol_info=SymbolInfo(tickerid="NASDAQ:AAPL", timezone="America/New_York", session="0930-1600:23456"),
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
        Bar(time=int(row["time"]) * 1000, open=1.0, high=1.0, low=1.0, close=1.0, time_close=int(row["time_W"]))
        for row in expected_rows
    ]

    weekly_closes: list[tuple[int, float]] = []
    seen_close_times: set[int] = set()
    for row in expected_rows:
        value = row["sec_w_gaps_on_la_off"]
        if value == "":
            continue
        close_time = int(row["time_W"])
        if close_time in seen_close_times:
            continue
        seen_close_times.add(close_time)
        weekly_closes.append((close_time, float(value)))

    off_gaps_on_bars = [Bar(time=close_time, open=value, high=value, low=value, close=value, time_close=close_time) for close_time, value in weekly_closes]
    off_gaps_on_values = [bar.close for bar in off_gaps_on_bars]
    off_gaps_off_points: list[tuple[int, float]] = []
    last_off_value: str | None = None
    for row in expected_rows:
        value = row["sec_w_gaps_off_la_off"]
        if value == "" or value == last_off_value:
            continue
        off_gaps_off_points.append((int(row["time_W"]), float(value)))
        last_off_value = value
    off_gaps_off_bars = [
        Bar(time=close_time, open=value, high=value, low=value, close=value, time_close=close_time)
        for close_time, value in off_gaps_off_points
    ]
    off_gaps_off_values = [bar.close for bar in off_gaps_off_bars]
    lookahead_on_points: list[tuple[int, float]] = []
    for row in expected_rows:
        if row["sec_w_gaps_on_la_on"] == "":
            continue
        lookahead_on_points.append((int(row["time"]) * 1000, float(row["sec_w_gaps_on_la_on"])))
    on_bars = [
        Bar(time=chart_time, open=value, high=value, low=value, close=value, time_close=chart_time)
        for chart_time, value in lookahead_on_points
    ]
    on_values = [bar.close for bar in on_bars]

    actual_by_index: dict[int, dict[str, Any]] = {}
    merged = {
        "sec_w_gaps_on_la_off": merge_requested_series_to_chart_bars(
            off_gaps_on_values, requested_bars=off_gaps_on_bars, chart_bars=chart_bars, gaps="barmerge.gaps_on", lookahead="barmerge.lookahead_off"
        ),
        "sec_w_gaps_off_la_off": merge_requested_series_to_chart_bars(
            off_gaps_off_values, requested_bars=off_gaps_off_bars, chart_bars=chart_bars, gaps="barmerge.gaps_off", lookahead="barmerge.lookahead_off"
        ),
        "sec_w_gaps_on_la_on": merge_requested_series_to_chart_bars(
            on_values, requested_bars=on_bars, chart_bars=chart_bars, gaps="barmerge.gaps_on", lookahead="barmerge.lookahead_on"
        ),
        "sec_w_gaps_off_la_on": merge_requested_series_to_chart_bars(
            on_values, requested_bars=on_bars, chart_bars=chart_bars, gaps="barmerge.gaps_off", lookahead="barmerge.lookahead_on"
        ),
    }
    for row_number, row in enumerate(expected_rows):
        bar_index = int(row["bar_index"])
        if bar_index >= 0:
            actual_by_index[bar_index] = {name: values[row_number] for name, values in merged.items()}

    _assert_columns_close(
        actual_by_index,
        expected_by_index.values(),
        ["sec_w_gaps_on_la_off", "sec_w_gaps_off_la_off", "sec_w_gaps_on_la_on", "sec_w_gaps_off_la_on"],
    )


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

    # The TradingView export includes 100 pre-visible warmup bars, while bars.csv intentionally stores only
    # the visible 300 bars. Compare from bar 200 once EMA/RMA/RSI/ATR/MACD state has converged to TV values.
    _assert_columns_close(
        actual_by_index,
        expected_rows,
        list(calculated),
        start_index=WARMED_STATEFUL_START_INDEX,
        tolerance=1e-5,
    )
    # Stateless rolling outputs are exact on the visible input and protect the full expected CSV tail too.
    _assert_columns_close(actual_by_index, expected_rows, ["sma5", "stoch14"], start_index=13)
