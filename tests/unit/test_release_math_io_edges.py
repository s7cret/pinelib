from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pinelib import math as pmath
from pinelib.core.na import na
from pinelib.core.precision import (
    pine_eq,
    pine_gt,
    pine_gte,
    pine_isclose,
    pine_lt,
    pine_lte,
    pine_ne,
)
from pinelib.errors import PineDataFormatError, PineTypeError
from pinelib.io import load_bars_csv
from pinelib.plot import PlotRecorder


def test_math_full_surface_and_error_edges() -> None:
    assert pmath.abs(-3) == 3
    assert pmath.sign(-2) == -1
    assert pmath.sign(0) == 0
    assert pmath.sign(2) == 1
    assert pmath.sqrt(4) == 2
    assert pmath.pow(2, 3) == 8
    assert pmath.exp(0) == 1
    assert pmath.log(pmath.e) == pytest.approx(1)
    assert pmath.log10(100) == 2
    assert pmath.sin(0) == 0
    assert pmath.cos(0) == 1
    assert pmath.tan(0) == 0
    assert pmath.asin(0) == 0
    assert pmath.acos(1) == 0
    assert pmath.atan(0) == 0
    assert pmath.todegrees(pmath.pi) == pytest.approx(180)
    assert pmath.toradians(180) == pytest.approx(pmath.pi)
    assert pmath.ceil(1.1) == 2
    assert pmath.floor(1.9) == 1
    assert pmath.trunc(1.9) == 1
    assert pmath.round(1.5) == 2
    assert pmath.round(1.234, 2) == 1.23
    assert pmath.round(na) is na
    assert pmath.min(3, 1, 2) == 1
    assert pmath.min(3, na, 2) is na
    assert pmath.max(3, 1, 2) == 3
    assert pmath.max(3, na, 2) is na
    assert pmath.avg(1, 2, 3) == 2
    assert pmath.avg(1, na, 3) is na
    assert pmath.sum([na, 1, 2]) == 3.0
    assert pmath.sum([na]) is na
    assert pmath.random(0, 1, seed=1) == pmath.random(0, 1, seed=1)
    assert pmath.sqrt(na) is na
    assert pmath.pow(na, 2) is na
    with pytest.raises(PineTypeError):
        pmath.sqrt(True)
    with pytest.raises(PineTypeError):
        pmath.pow(1, False)
    with pytest.raises(ValueError):
        pmath.min()
    with pytest.raises(ValueError):
        pmath.max()
    with pytest.raises(ValueError):
        pmath.avg()


def test_precision_helpers_with_na_and_series_like() -> None:
    class CurrentBox:
        def __init__(self, value: float) -> None:
            self._current = value

    assert pine_isclose(CurrentBox(1.0), 1.0)
    assert pine_eq(1.0, 1.0 + 1e-12)
    assert pine_ne(1.0, 1.1)
    assert pine_gt(2.0, 1.0)
    assert pine_gte(1.0, 1.0)
    assert pine_lt(1.0, 2.0)
    assert pine_lte(1.0, 1.0)
    assert not pine_isclose(na, 1.0)
    assert not pine_ne(na, 1.0)
    assert not pine_gt(na, 1.0)
    assert not pine_gte(na, 1.0)
    assert not pine_lt(na, 1.0)
    assert not pine_lte(na, 1.0)


def test_csv_aliases_strict_and_ordering_errors(tmp_path: Path) -> None:
    alias_path = tmp_path / "alias.csv"
    with alias_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["timestamp", "o", "h", "l", "c", "v", "close_time"])
        writer.writeheader()
        writer.writerow(
            {"timestamp": 1, "o": 10, "h": 11, "l": 9, "c": 10, "v": 5, "close_time": 2}
        )
    bar = load_bars_csv(alias_path, strict_columns=True)[0]
    assert bar.volume == 5
    assert bar.time_close == 2

    duplicate_path = tmp_path / "duplicate.csv"
    duplicate_path.write_text("time,timestamp,open,high,low,close\n1,1,1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError, match="Duplicate"):
        load_bars_csv(duplicate_path)

    unordered_path = tmp_path / "unordered.csv"
    unordered_path.write_text(
        "time,open,high,low,close\n2,1,1,1,1\n1,1,1,1,1\n",
        encoding="utf-8",
    )
    with pytest.raises(PineDataFormatError, match="increasing"):
        load_bars_csv(unordered_path)

    extra_path = tmp_path / "extra.csv"
    extra_path.write_text("time,open,high,low,close,foo\n1,1,1,1,1,x\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError, match="unsupported"):
        load_bars_csv(extra_path, strict_columns=True)


def test_plot_reset_and_csv_invalid_row(tmp_path: Path) -> None:
    recorder = PlotRecorder()
    recorder.record_plot(1, 0, 1.0, "x")
    assert recorder.get_records()
    recorder.reset()
    assert recorder.get_records() == []

    bad_row = tmp_path / "bad-row.csv"
    bad_row.write_text("time,open,high,low,close\n,1,1,1,1\n", encoding="utf-8")
    with pytest.raises(PineDataFormatError, match="Invalid CSV bar"):
        load_bars_csv(bad_row)
