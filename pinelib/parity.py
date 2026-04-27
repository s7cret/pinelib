from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from pinelib.errors import PineDataFormatError, PineGoldenMismatchError


@dataclass(frozen=True, slots=True)
class TradingViewIndicatorFixture:
    """TradingView-exported indicator columns aligned by row index/time."""

    columns: dict[str, list[float | int | str | None]]
    time: list[int] = field(default_factory=list)
    source: str | None = None

    @property
    def rows(self) -> int:
        if self.columns:
            return len(next(iter(self.columns.values())))
        return len(self.time)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StrategyCompareReport:
    schema_version: str
    compared_fields: list[str]
    tolerance: dict[str, float]
    matches: bool
    max_abs_diff: float
    max_rel_diff: float
    mismatches: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True, slots=True)
class TradingViewSampleContract:
    """Placeholder data contract for target strategy integration samples."""

    symbol: str
    timeframe: str
    bars_csv: str
    indicator_export_csv: str
    trades_csv: str
    equity_csv: str
    notes: str = "Replace placeholder paths with TradingView exports before parity runs."

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_tradingview_indicator_csv(path: str | Path, *, time_column: str = "time") -> TradingViewIndicatorFixture:
    """Load a TradingView CSV export preserving indicator columns.

    Empty cells and Pine ``NaN``/``na`` cells normalize to ``None``. A ``time`` column is optional
    and, when present, is converted to integer UTC milliseconds.
    """

    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PineDataFormatError("TradingView indicator CSV is missing a header row")
        columns: dict[str, list[float | int | str | None]] = {name: [] for name in reader.fieldnames if name != time_column}
        times: list[int] = []
        for row_index, row in enumerate(reader, start=2):
            if time_column in row and row[time_column] not in (None, ""):
                try:
                    times.append(int(str(row[time_column]).strip()))
                except ValueError as exc:
                    raise PineDataFormatError(f"Invalid time value at row {row_index}: {row[time_column]!r}") from exc
            for name in columns:
                columns[name].append(_parse_tv_cell(row.get(name)))
    if columns:
        lengths = {len(values) for values in columns.values()}
        if len(lengths) != 1:
            raise PineDataFormatError("TradingView indicator CSV columns have inconsistent lengths")
    if times and columns and len(times) != len(next(iter(columns.values()))):
        raise PineDataFormatError("TradingView indicator CSV time column length differs from data columns")
    return TradingViewIndicatorFixture(columns=columns, time=times, source=str(path))


def load_tradingview_trades_csv(path: str | Path) -> list[dict[str, object]]:
    """Load a TradingView strategy trades export as normalized dictionaries."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PineDataFormatError("TradingView trades CSV is missing a header row")
        return [{key: _parse_tv_cell(value) for key, value in row.items()} for row in reader]


def compare_indicator_fixture(
    actual_columns: Mapping[str, Sequence[object]],
    expected: TradingViewIndicatorFixture,
    *,
    columns: Iterable[str] | None = None,
    abs_tol: float = 1e-9,
    rel_tol: float = 1e-9,
) -> StrategyCompareReport:
    wanted = list(columns) if columns is not None else sorted(expected.columns)
    return _compare_columnar(actual_columns, expected.columns, wanted, abs_tol=abs_tol, rel_tol=rel_tol)


def compare_strategy_reports(
    actual: Mapping[str, object],
    expected: Mapping[str, object],
    *,
    fields: Iterable[str] = ("netprofit", "final_equity", "max_drawdown", "closedtrades"),
    abs_tol: float = 1e-6,
    rel_tol: float = 1e-6,
) -> StrategyCompareReport:
    mismatches: list[dict[str, object]] = []
    max_abs = 0.0
    max_rel = 0.0
    compared = list(fields)
    for field_name in compared:
        if field_name not in actual or field_name not in expected:
            mismatches.append({"field": field_name, "reason": "missing", "actual": actual.get(field_name), "expected": expected.get(field_name)})
            continue
        ok, abs_diff, rel_diff = _values_close(actual[field_name], expected[field_name], abs_tol=abs_tol, rel_tol=rel_tol)
        max_abs = max(max_abs, abs_diff)
        max_rel = max(max_rel, rel_diff)
        if not ok:
            mismatches.append({"field": field_name, "actual": actual[field_name], "expected": expected[field_name], "abs_diff": abs_diff, "rel_diff": rel_diff})
    return StrategyCompareReport("pinelib.parity.compare.v1", compared, {"abs": abs_tol, "rel": rel_tol}, not mismatches, max_abs, max_rel, mismatches)


def assert_strategy_report_close(actual: Mapping[str, object], expected: Mapping[str, object], **kwargs: object) -> None:
    report = compare_strategy_reports(actual, expected, **kwargs)  # type: ignore[arg-type]
    if not report.matches:
        raise PineGoldenMismatchError(f"Strategy report mismatch: {report.mismatches!r}")


def default_sample_contracts() -> dict[str, TradingViewSampleContract]:
    return {
        symbol: TradingViewSampleContract(
            symbol=f"BINANCE:{symbol}USDT",
            timeframe="60",
            bars_csv=f"samples/{symbol.lower()}/bars.csv",
            indicator_export_csv=f"samples/{symbol.lower()}/tradingview_indicators.csv",
            trades_csv=f"samples/{symbol.lower()}/tradingview_trades.csv",
            equity_csv=f"samples/{symbol.lower()}/tradingview_equity.csv",
        )
        for symbol in ("AVAX", "SOL", "XLM")
    }


def write_sample_contracts(path: str | Path) -> None:
    payload = {key: value.to_dict() for key, value in default_sample_contracts().items()}
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _compare_columnar(
    actual: Mapping[str, Sequence[object]],
    expected: Mapping[str, Sequence[object]],
    columns: list[str],
    *,
    abs_tol: float,
    rel_tol: float,
) -> StrategyCompareReport:
    mismatches: list[dict[str, object]] = []
    max_abs = 0.0
    max_rel = 0.0
    for name in columns:
        left = actual.get(name)
        right = expected.get(name)
        if left is None or right is None:
            mismatches.append({"field": name, "reason": "missing"})
            continue
        if len(left) != len(right):
            mismatches.append({"field": name, "reason": "length", "actual": len(left), "expected": len(right)})
            continue
        for idx, (actual_value, expected_value) in enumerate(zip(left, right, strict=True)):
            ok, abs_diff, rel_diff = _values_close(actual_value, expected_value, abs_tol=abs_tol, rel_tol=rel_tol)
            max_abs = max(max_abs, abs_diff)
            max_rel = max(max_rel, rel_diff)
            if not ok:
                mismatches.append({"field": name, "index": idx, "actual": actual_value, "expected": expected_value, "abs_diff": abs_diff, "rel_diff": rel_diff})
    return StrategyCompareReport("pinelib.parity.compare.v1", columns, {"abs": abs_tol, "rel": rel_tol}, not mismatches, max_abs, max_rel, mismatches)


def _values_close(actual: object, expected: object, *, abs_tol: float, rel_tol: float) -> tuple[bool, float, float]:
    if actual is None or expected is None:
        return actual is expected, 0.0 if actual is expected else math.inf, math.inf if actual is not expected else 0.0
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        abs_diff = abs(float(actual) - float(expected))
        denom = max(abs(float(expected)), 1e-12)
        rel_diff = abs_diff / denom
        return math.isclose(float(actual), float(expected), abs_tol=abs_tol, rel_tol=rel_tol), abs_diff, rel_diff
    return actual == expected, 0.0 if actual == expected else math.inf, 0.0 if actual == expected else math.inf


def _parse_tv_cell(value: object) -> float | int | str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"na", "nan", "null"}:
        return None
    normalized = text.replace(",", "")
    try:
        integer = int(normalized)
    except ValueError:
        pass
    else:
        return integer
    try:
        return float(normalized)
    except ValueError:
        return text
