from __future__ import annotations

from typing import Any

from pinelib.core.na import SupportsSeriesLike, is_na, na
from pinelib.core.runtime import PineRuntime


def _history(source: Any, offset: int, function_name: str) -> Any:
    if isinstance(source, SupportsSeriesLike):
        return source[offset]
    return source


def _condition_history(source: Any, offset: int) -> Any:
    if isinstance(source, SupportsSeriesLike):
        return source[offset]
    return source


class _RuntimeDerivedSeries:
    def __init__(self, runtime: PineRuntime, name: str) -> None:
        self.runtime = runtime
        self.name = name

    @property
    def current(self) -> Any:
        return self[0]

    @property
    def committed_length(self) -> int:
        return self.runtime.close.committed_length

    def __getitem__(self, offset: int) -> Any:
        high = self.runtime.high[offset]
        low = self.runtime.low[offset]
        close = self.runtime.close[offset]
        open_ = self.runtime.open[offset]
        if any(is_na(value) for value in (high, low, close)):
            return na
        if self.name == "hl2":
            return (float(high) + float(low)) / 2.0
        if self.name == "hlc3":
            return (float(high) + float(low) + float(close)) / 3.0
        if self.name == "ohlc4":
            if is_na(open_):
                return na
            return (float(open_) + float(high) + float(low) + float(close)) / 4.0
        if self.name == "hlcc4":
            return (float(high) + float(low) + float(close) + float(close)) / 4.0
        return na


def hl2_series(runtime: PineRuntime) -> _RuntimeDerivedSeries:
    return _RuntimeDerivedSeries(runtime, "hl2")


def hlc3_series(runtime: PineRuntime) -> _RuntimeDerivedSeries:
    return _RuntimeDerivedSeries(runtime, "hlc3")


def ohlc4_series(runtime: PineRuntime) -> _RuntimeDerivedSeries:
    return _RuntimeDerivedSeries(runtime, "ohlc4")


def hlcc4_series(runtime: PineRuntime) -> _RuntimeDerivedSeries:
    return _RuntimeDerivedSeries(runtime, "hlcc4")


class _ShiftedSeries:
    def __init__(self, source: SupportsSeriesLike, offset: int) -> None:
        self.source = source
        self.offset = offset

    @property
    def current(self) -> Any:
        return self[0]

    @property
    def committed_length(self) -> int:
        return self.source.committed_length

    def __getitem__(self, offset: int) -> Any:
        return self.source[offset + self.offset]


def shifted_series(source: SupportsSeriesLike, offset: int) -> _ShiftedSeries:
    return _ShiftedSeries(source, offset)

__all__ = [
    "_history",
    "hl2_series",
    "hlc3_series",
    "hlcc4_series",
    "ohlc4_series",
    "shifted_series",
]
