from __future__ import annotations

import math
import sys
import types
from pathlib import Path

import pytest

from pinelib.compat.marketdata import (
    ContractBar,
    InstrumentKey,
    InvalidBarError,
    InvalidTimeframeError,
    parse_timeframe,
)
from pinelib.core.inputs import InputRegistry
from pinelib.core.na import na
from pinelib.core.operators import (
    pine_add,
    pine_bool,
    pine_div,
    pine_float,
    pine_int,
    pine_mul,
    pine_range,
    pine_str,
    pine_sub,
)
from pinelib.core.types import RuntimeConfig
from pinelib.errors import (
    PineDataFormatError,
    PineNAError,
    PineRuntimeError,
    PineUnsupportedFeatureError,
)
from pinelib.io import load_bars, load_bars_csv, load_bars_parquet
from pinelib.reference import PineArray, PineMap, PineMatrix, reference_history
from pinelib.string import pos, replace, tonumber, tostring


def test_reference_containers_cover_factories_and_edge_methods() -> None:
    floats = PineArray.new_float(1.5, max_size=3)
    ints = PineArray.new_int(2, max_size=4)
    bools = PineArray.new_bool(False, max_size=5)
    strings = PineArray.new_string("x", max_size=6)
    colors = PineArray.new_color(0xFF00FF, max_size=7)
    assert floats.get(0) == 1.5
    assert ints.get(0) == 2
    assert bools.get(0) is False
    assert strings.get(0) == "x"
    assert colors.get(0) == 0xFF00FF
    assert floats._max_size == 3
    assert colors._max_size == 7

    empty: PineArray[float] = PineArray()
    assert math.isnan(empty.avg())
    assert math.isnan(empty.min())
    assert math.isnan(empty.max())
    assert empty.shift(99) is na
    assert empty.get(-1) is na

    values = PineArray([3, 1, 2])
    assert values.size == 3
    assert values.shift() == 3
    values.sort("desc")
    assert list(values) == [3, 2, 1]
    values.set(1, 99)
    assert values.get(1) == 99
    clone = values.copy()
    clone.push(7)
    assert len(values) == 3
    assert len(clone) == 4

    mapping: PineMap[str, int] = PineMap()
    mapping.put("a", 1)
    assert mapping.contains("a")
    assert mapping.get("missing", 42) == 42
    copy = mapping.copy()
    assert copy.remove("a") == 1
    assert len(mapping) == 1
    assert len(copy) == 0

    matrix = PineMatrix[list[int]](2, 2, [1])
    matrix.get(0, 0).append(2)  # type: ignore[union-attr]
    # Initial values are shallow-copied per cell, so sibling cells stay independent.
    assert matrix.get(0, 1) == [1]
    matrix.set(1, 1, [9])
    clone_matrix = matrix.copy()
    clone_matrix.set(1, 1, [10])
    assert matrix.get(1, 1) == [9]

    config = RuntimeConfig()
    with pytest.raises(PineUnsupportedFeatureError):
        reference_history(object(), 1, config=config)
    assert config.diagnostics[-1]["code"] == "PL_REFERENCE_HISTORY_UNSUPPORTED"


def test_core_operator_and_string_edges() -> None:
    with pytest.raises(PineNAError):
        pine_bool(na)
    with pytest.raises(PineNAError):
        pine_bool(None)
    assert pine_bool(True) is True
    assert pine_bool(0) is False
    assert pine_bool(1.0) is True
    assert pine_bool([1]) is True

    assert pine_int(None) is na
    assert pine_int("7") == 7
    assert pine_float(na) is na
    assert pine_float("1.25") == 1.25
    assert pine_str(None) is na
    assert pine_str(12) == "12"
    assert pine_add(None, 1) is None
    assert pine_add(1, na) is na
    assert pine_sub(5, None) is None
    assert pine_mul(na, 5) is na
    assert pine_div(None, 5) is None
    assert pine_div(10, 2) == 5
    assert list(pine_range(1, 3)) == [1, 2, 3]
    assert list(pine_range(3, 1)) == [3, 2, 1]
    assert list(pine_range(1, 5, 2)) == [1, 3, 5]
    with pytest.raises(ValueError):
        list(pine_range(1, 2, 0))

    assert tostring(na) == "NaN"
    assert tostring(1.234, "#.##") == "1.23"
    assert tonumber("bad") is na
    assert tonumber(na) is na
    assert replace("a-b-b", "b", "x", 0) == "a-x-b"
    assert replace("a-b", "b", "x", 99) == "a-b"
    assert pos("abc", "", -2) == 0
    assert pos("abc", "", 9) == 3
    assert pos("abc", "z") is na


def test_input_registry_validation_edges() -> None:
    config = RuntimeConfig()
    registry = InputRegistry(config)
    assert registry.int("len", 14, minval=1, maxval=100, options=[7, 14]) == 14
    assert registry.float("mult", 2, minval=0.5, maxval=5.0, options=[1.0, 2.0]) == 2.0
    assert registry.bool("enabled", True) is True
    assert registry.string("mode", "fast", options=["fast", "slow"]) == "fast"
    assert registry.timeframe("tf", "60", options=["15", "60"]) == "60"
    assert registry.symbol("sym", "NASDAQ:AAPL") == "NASDAQ:AAPL"
    assert registry.session("sess", "0930-1600:23456") == "0930-1600:23456"
    assert registry.source("src", object()) is not None

    invalid_calls = [
        lambda: registry.int("bad-int", True),
        lambda: registry.float("bad-float", True),
        lambda: registry.bool("bad-bool", 1),
        lambda: registry.string("bad-string", 1),
        lambda: registry.timeframe("bad-tf", "not-a-timeframe"),
        lambda: registry.timeframe("bad-option", "60", options=["60", "nope"]),
        lambda: registry.symbol("bad-symbol", ""),
        lambda: registry.source("bad-source", None),
        lambda: registry.int("bad-range", 1, minval=10, maxval=1),
        lambda: registry.int("bad-options", 2, options=[1, 3]),
        lambda: registry.int("below", 0, minval=1),
        lambda: registry.int("above", 10, maxval=5),
    ]
    for call in invalid_calls:
        with pytest.raises(PineRuntimeError):
            call()
    assert config.diagnostics


def test_io_csv_parquet_and_timeframe_edges(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(empty)

    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text("time,timestamp,open,high,low,close\n1,1,1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(duplicate)

    invalid_row = tmp_path / "invalid_row.csv"
    invalid_row.write_text("time,open,high,low,close\n,1,2,0,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError):
        load_bars_csv(invalid_row)

    csv_path = tmp_path / "bars.csv"
    csv_path.write_text("time,open,high,low,close\n1,1,2,0,1.5\n", encoding="utf-8")
    assert load_bars(csv_path)[0].time == 1
    upper_csv = tmp_path / "bars.CSV"
    upper_csv.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_bars(upper_csv)[0].time == 1
    with pytest.raises(PineDataFormatError):
        load_bars(tmp_path / "bars.txt")

    class GoodFrame:
        columns = ["timestamp", "o", "h", "l", "c", "v", "close_time"]

        def to_dict(self, orient: str) -> list[dict[str, object]]:
            assert orient == "records"
            return [
                {
                    "timestamp": "10",
                    "o": "1.0",
                    "h": "2.0",
                    "l": "0.5",
                    "c": "1.5",
                    "v": "100",
                    "close_time": "20",
                }
            ]

    fake_pandas = types.SimpleNamespace(read_parquet=lambda path: GoodFrame())
    monkeypatch.setitem(sys.modules, "pandas", fake_pandas)
    assert load_bars_parquet(tmp_path / "bars.parquet")[0].time_close == 20
    assert load_bars(tmp_path / "bars.pq")[0].close == 1.5

    class MissingFrame:
        columns = ["time", "open", "high", "low"]

        def to_dict(self, orient: str) -> list[dict[str, object]]:
            return []

    fake_pandas.read_parquet = lambda path: MissingFrame()
    with pytest.raises(PineDataFormatError):
        load_bars_parquet(tmp_path / "missing.parquet")

    class InvalidFrame:
        columns = ["time", "open", "high", "low", "close"]

        def to_dict(self, orient: str) -> list[dict[str, object]]:
            return [{"time": object(), "open": 1, "high": 2, "low": 0, "close": 1}]

    fake_pandas.read_parquet = lambda path: InvalidFrame()
    with pytest.raises(PineDataFormatError):
        load_bars_parquet(tmp_path / "invalid.parquet")

    def raise_import_error(path: object) -> object:
        raise ImportError("no parquet engine")

    fake_pandas.read_parquet = raise_import_error
    with pytest.raises(PineUnsupportedFeatureError):
        load_bars_parquet(tmp_path / "unavailable.parquet")

    assert parse_timeframe("15m").duration_ms == 900_000
    assert parse_timeframe("2H").duration_ms == 7_200_000
    assert parse_timeframe("D").unit == "day"
    assert parse_timeframe("W").unit == "week"
    assert parse_timeframe("1M").unit == "month"
    for bad in ["", "0", "0m", "xm", "1Y"]:
        with pytest.raises(InvalidTimeframeError):
            parse_timeframe(bad)

    key = InstrumentKey("BINANCE", "spot", "BTCUSDT")
    tf = parse_timeframe("1")
    ContractBar(key, tf, 1, 61_000, 1, 2, 0.5, 1.5)
    invalid_bars = [
        dict(time=-1, time_close=1, open=1, high=2, low=0, close=1),
        dict(time=1, time_close=1, open=1, high=2, low=0, close=1),
        dict(time=1, time_close=2, open=3, high=2, low=1, close=2),
        dict(time=1, time_close=2, open=1, high=2, low=2, close=1),
    ]
    for kwargs in invalid_bars:
        with pytest.raises(InvalidBarError):
            ContractBar(key, tf, **kwargs)
