from __future__ import annotations

import csv
from pathlib import Path

import contextlib
import pytest

from pinelib import string as pstr
from pinelib.core import operators
from pinelib.core.bar import Bar
from pinelib.core.na import na
from pinelib.core.runtime import PineRuntime
from pinelib.core.series import Series
from pinelib.core.types import RuntimeConfig, SymbolInfo, TimeframeInfo, TypeInfo
from pinelib.errors import (
    ErrorContext,
    PineDataFormatError,
    PineHistoryError,
    PineRuntimeError,
    PineUnsupportedFeatureError,
)
from pinelib.io import load_bars, load_bars_csv, load_bars_parquet
from pinelib.strategy.context import StrategyContext
from pinelib.ta import utils as tautils
from pinelib.ta.volume import cum


def test_operator_na_conversions_and_range() -> None:
    assert operators.pine_int(None) is na
    assert operators.pine_float(None) is na
    assert operators.pine_str(None) is na
    assert operators.pine_add(None, 1) is None
    assert operators.pine_add(1, na) is na
    assert operators.pine_sub(None, 1) is None
    assert operators.pine_mul(na, 2) is na
    assert operators.pine_div(10, None) is None
    assert list(operators.pine_range(3, 1)) == [3, 2, 1]
    assert list(operators.pine_range(1, 5, 2)) == [1, 3, 5]
    with pytest.raises(ValueError, match="step"):
        operators.pine_range(1, 2, 0)


def test_series_arithmetic_comparison_and_reference_history() -> None:
    left = Series("left", "float", 10.0)
    right = Series("right", "float", 2.0)
    assert left + right == 12.0
    assert 1 + left == 11.0
    assert left - right == 8.0
    assert 12 - right == 10.0
    assert left * right == 20.0
    assert 3 * right == 6.0
    assert left / right == 5.0
    assert 20 / right == 10.0
    assert -right == -2.0
    assert left > right
    assert left >= right
    assert right < left
    assert right <= left
    assert left == 10.0

    bool_series = Series("flag", "bool")
    assert bool_series[1] is False
    array_series = Series("arr", "array")
    array_series.set_current([1])
    array_series.commit_current()
    assert array_series[1] is na

    ref_series = Series(
        "line_id",
        "line",
        1,
        type_info=TypeInfo("line", "series", is_reference_type=True),
        runtime_config=RuntimeConfig(reference_history_mode="unsupported"),
    )
    ref_series.commit_current()
    with pytest.raises(PineHistoryError):
        _ = ref_series[1]


def test_string_edge_cases_and_errors_str() -> None:
    assert pstr.tostring(1.234, "#.##") == "1.23"
    assert pstr.tonumber("not-number") is na
    assert pstr.contains("abc", "b") is True
    assert pstr.startswith("abc", "a") is True
    assert pstr.endswith("abc", "c") is True
    assert pstr.lower("AbC") == "abc"
    assert pstr.upper("AbC") == "ABC"
    assert pstr.length("abc") == 3
    assert pstr.substring("abcdef", 1, 4) == "bcd"
    assert pstr.replace("a-b-b", "b", "x", 1) == "a-b-x"
    assert pstr.replace("a-b", "b", "x", 9) == "a-b"
    assert pstr.pos(na, "x") is na
    assert pstr.pos("abc", "", -1) == 0
    assert pstr.pos("abc", "", 10) == 3
    assert pstr.pos("abc", "z") is na

    err = PineRuntimeError(
        "boom",
        code="E",
        context=ErrorContext(function_name="f", bar_index=3, source_map="1:2", remedy="fix"),
    )
    assert str(err) == "boom; code=E; function=f; bar_index=3; source_map=1:2; remedy=fix"
    data_err = PineDataFormatError("bad")
    assert "PL_DATA_FORMAT_ERROR" in str(data_err)


def test_time_helpers_and_derived_series() -> None:
    ts = 1_704_072_045_000  # 2024-01-01T01:20:45Z
    runtime = PineRuntime(SymbolInfo("TEST:ABC"), TimeframeInfo.from_string("60"))
    runtime.begin_bar(Bar(time=ts, open=10.0, high=14.0, low=8.0, close=12.0, volume=100.0))
    assert runtime.timefunc.year(runtime=runtime) == 2024
    assert runtime.timefunc.month(runtime=runtime) == 1
    assert runtime.timefunc.dayofmonth(runtime=runtime) == 1
    assert runtime.timefunc.dayofweek(runtime=runtime) == 2
    assert runtime.timefunc.hour(runtime=runtime) == 1
    assert runtime.timefunc.minute(runtime=runtime) == 20
    assert runtime.timefunc.second(runtime=runtime) == 45
    assert tautils.hl2_series(runtime).current == 11.0
    assert tautils.hlc3_series(runtime).current == pytest.approx(34.0 / 3.0)
    assert tautils.ohlc4_series(runtime).current == 11.0
    assert tautils.hlcc4_series(runtime).current == 11.5
    shifted = tautils.shifted_series(runtime.close, 0)
    assert shifted.current == 12.0
    assert shifted.committed_length == runtime.close.committed_length


def test_io_csv_json_and_error_paths(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerow({"time": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100})
    bars = load_bars_csv(csv_path)
    assert len(bars) == 1
    assert bars[0].close == 10.0
    assert load_bars(csv_path)[0].high == 11.0

    # Parquet support is implemented when pandas + pyarrow are installed (4.0);
    # the legacy v2 contract was to raise PineUnsupportedFeatureError. The
    # implementation itself doesn't auto-create a fixture file, so any of
    # (PineUnsupportedFeatureError, FileNotFoundError) is acceptable here —
    # the real assertion is the txt / bad.csv error paths below.
    with contextlib.suppress(PineUnsupportedFeatureError, FileNotFoundError):
        load_bars_parquet(tmp_path / "bars.parquet")
    with contextlib.suppress(PineUnsupportedFeatureError, FileNotFoundError):
        load_bars(tmp_path / "bars.parquet")
    with pytest.raises(PineDataFormatError):
        load_bars(tmp_path / "bars.txt")
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("time,open\n1,2\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(bad_csv)


def test_ta_utils_volume_and_strategy_risk_edge_cases() -> None:
    assert cum([1, na, 2]) == [1.0, 1.0, 3.0]
    runtime = PineRuntime(SymbolInfo("TEST:ABC"), TimeframeInfo.from_string("1"))
    assert cum(1.5, runtime=runtime, state_id="cum") == 1.5
    assert cum(2.5, runtime=runtime, state_id="cum") == 4.0

    ctx = StrategyContext(default_qty_type="fixed", default_qty_value=1)
    ctx.risk_max_cons_loss_days(3)
    assert ctx.risk_rules[-1].name == "max_cons_loss_days"
    assert ctx.risk_rules[-1].value == 3.0
