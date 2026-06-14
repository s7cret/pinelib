from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Any, SupportsIndex, SupportsInt

from pinelib.core.bar import Bar
from pinelib.errors import PineDataFormatError, PineUnsupportedFeatureError

_REQUIRED = {"time", "open", "high", "low", "close"}
_OPTIONAL = {"volume", "time_close"}
_ALIASES = {
    "timestamp": "time",
    "datetime": "time",
    "date": "time",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
    "timeclose": "time_close",
    "close_time": "time_close",
}


def load_bars_csv(path: str | Path, *, strict_columns: bool = False) -> list[Bar]:
    """Load OHLCV bars from CSV using stdlib only.

    Accepted required columns are ``time, open, high, low, close`` with optional
    ``volume`` and ``time_close``. Common aliases such as ``timestamp`` and ``o/h/l/c/v``
    are normalized. Timestamps must be UTC milliseconds (integers).
    """

    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PineDataFormatError("CSV file is missing a header row")
        mapping = _column_mapping(reader.fieldnames)
        missing = _REQUIRED - set(mapping.values())
        if missing:
            raise PineDataFormatError(f"CSV missing required bar columns: {sorted(missing)}")
        if strict_columns:
            allowed = _REQUIRED | _OPTIONAL
            extra = set(mapping.values()) - allowed
            if extra:
                raise PineDataFormatError(f"CSV has unsupported bar columns: {sorted(extra)}")
        bars: list[Bar] = []
        for row_index, row in enumerate(reader, start=2):
            normalized = {canonical: row[original] for original, canonical in mapping.items()}
            try:
                bars.append(
                    Bar(
                        time=_int_ms(normalized["time"]),
                        open=float(normalized["open"]),
                        high=float(normalized["high"]),
                        low=float(normalized["low"]),
                        close=float(normalized["close"]),
                        volume=float(normalized.get("volume") or 0.0),
                        time_close=_optional_int_ms(normalized.get("time_close")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise PineDataFormatError(f"Invalid CSV bar at row {row_index}: {exc}") from exc
        _validate_ordering(bars)
        return bars


def load_bars_parquet(path: str | Path) -> list[Bar]:
    """Load OHLCV bars from Parquet when pandas/pyarrow are installed.

    Parquet support is intentionally optional. If dependencies are unavailable, a clear
    PineUnsupportedFeatureError is raised instead of importing a hard dependency.
    """

    try:
        import pandas as pd  # type: ignore[import-untyped]
    except ImportError as exc:
        raise PineUnsupportedFeatureError(
            "Parquet loading requires optional dependency pandas with a parquet engine"
        ) from exc
    try:
        frame = pd.read_parquet(path)
    except ImportError as exc:
        raise PineUnsupportedFeatureError(
            "Parquet loading requires pyarrow or fastparquet"
        ) from exc
    rows: Iterable[dict[str, Any]] = frame.to_dict(orient="records")
    fieldnames = [str(c) for c in frame.columns]
    mapping = _column_mapping(fieldnames)
    missing = _REQUIRED - set(mapping.values())
    if missing:
        raise PineDataFormatError(f"Parquet missing required bar columns: {sorted(missing)}")
    bars: list[Bar] = []
    for idx, row in enumerate(rows):
        normalized = {canonical: row[original] for original, canonical in mapping.items()}
        try:
            bars.append(
                Bar(
                    time=_int_ms(normalized["time"]),
                    open=float(normalized["open"]),
                    high=float(normalized["high"]),
                    low=float(normalized["low"]),
                    close=float(normalized["close"]),
                    volume=float(normalized.get("volume") or 0.0),
                    time_close=_optional_int_ms(normalized.get("time_close")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PineDataFormatError(f"Invalid Parquet bar at row {idx}: {exc}") from exc
    _validate_ordering(bars)
    return bars


def load_bars(path: str | Path) -> list[Bar]:
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return load_bars_csv(path)
    if suffix in {".parquet", ".pq"}:
        return load_bars_parquet(path)
    raise PineDataFormatError(f"Unsupported bar file extension {suffix!r}")


def _column_mapping(fieldnames: Iterable[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    seen: set[str] = set()
    for name in fieldnames:
        canonical = _ALIASES.get(name.strip().lower(), name.strip().lower())
        if canonical in seen:
            raise PineDataFormatError(f"Duplicate bar column after normalization: {canonical}")
        seen.add(canonical)
        mapping[name] = canonical
    return mapping


def _int_ms(value: object) -> int:
    if value is None or value == "":
        raise ValueError("timestamp is empty")
    if isinstance(value, str | bytes | bytearray):
        return int(value)
    if isinstance(value, SupportsInt | SupportsIndex):
        return int(value)
    raise ValueError(f"timestamp must be integer-like, got {type(value).__name__}")


def _optional_int_ms(value: object) -> int | None:
    if value is None or value == "":
        return None
    return _int_ms(value)


def _validate_ordering(bars: list[Bar]) -> None:
    previous: int | None = None
    for bar in bars:
        if previous is not None and bar.time <= previous:
            raise PineDataFormatError("Bars must be strictly increasing by time")
        previous = bar.time
