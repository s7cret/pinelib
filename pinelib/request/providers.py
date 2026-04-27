from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from pinelib.core.bar import Bar
from pinelib.errors import PineDataFormatError


class DataProvider(Protocol):
    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: int | None,
        end: int | None,
        *,
        max_bars: int | None = None,
    ) -> list[Bar]: ...


class IntrabarDataProvider(Protocol):
    def get_intrabar_bars(
        self,
        symbol: str,
        chart_bar: Bar,
        lower_timeframe: str | None = None,
        *,
        max_bars: int | None = None,
    ) -> list[Bar]: ...


class InMemoryDataProvider:
    def __init__(self, bars_by_key: Mapping[tuple[str, str], list[Bar]]) -> None:
        self._bars_by_key: dict[tuple[str, str], list[Bar]] = {}
        for key, bars in bars_by_key.items():
            self._bars_by_key[key] = self._validate_bars(list(bars))

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: int | None,
        end: int | None,
        *,
        max_bars: int | None = None,
    ) -> list[Bar]:
        bars = list(self._bars_by_key.get((symbol, timeframe), []))
        filtered = [
            bar
            for bar in bars
            if (start is None or bar.time >= start) and (end is None or bar.time <= end)
        ]
        if max_bars is not None:
            return filtered[:max_bars]
        return filtered

    @staticmethod
    def _validate_bars(bars: list[Bar]) -> list[Bar]:
        last_time: int | None = None
        for bar in bars:
            if last_time is not None:
                if bar.time < last_time:
                    raise PineDataFormatError("Bars must be sorted by ascending time")
                if bar.time == last_time:
                    raise PineDataFormatError("Duplicate bar time is not allowed")
            last_time = bar.time
        return bars

