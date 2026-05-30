from __future__ import annotations

import bisect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, Sequence

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


@dataclass(frozen=True, slots=True)
class ProviderQueryMetadata:
    requested_symbol: str
    requested_timeframe: str
    normalized_symbol: str
    normalized_timeframe: str
    start: int | None
    end: int | None
    returned_bars: int
    max_bars: int | None = None


@dataclass(frozen=True, slots=True)
class LowerTfQueryMetadata:
    requested_symbol: str
    requested_timeframe: str
    provider_source: str
    state_id: str
    chart_bar_index: int
    chart_bar_time: int
    chart_bar_time_close: int | None
    query_start: int | None
    query_end: int | None
    calc_bars_count: int | None
    requested_bars: int
    selected_bars: int
    selected_bar_times: tuple[int, ...]


class InMemoryDataProvider:
    def __init__(self, bars_by_key: Mapping[tuple[str, str], list[Bar]]) -> None:
        self._bars_by_key: dict[tuple[str, str], list[Bar]] = {}
        self.metadata_log: list[ProviderQueryMetadata] = []
        for key, bars in bars_by_key.items():
            symbol, timeframe = key
            normalized_key = (self.normalize_symbol(symbol), self.normalize_timeframe(timeframe))
            self._bars_by_key[normalized_key] = self._validate_bars(list(bars))

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: int | None,
        end: int | None,
        *,
        max_bars: int | None = None,
    ) -> list[Bar]:
        normalized_symbol = self.normalize_symbol(symbol)
        normalized_timeframe = self.normalize_timeframe(timeframe)
        bars = list(self._bars_by_key.get((normalized_symbol, normalized_timeframe), []))
        filtered = [
            bar
            for bar in bars
            if (start is None or bar.time >= start) and (end is None or bar.time < end)
        ]
        if max_bars is not None:
            filtered = filtered[:max_bars]
        self.metadata_log.append(
            ProviderQueryMetadata(
                requested_symbol=symbol,
                requested_timeframe=timeframe,
                normalized_symbol=normalized_symbol,
                normalized_timeframe=normalized_timeframe,
                start=start,
                end=end,
                returned_bars=len(filtered),
                max_bars=max_bars,
            )
        )
        return filtered

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return symbol.strip().upper()

    @staticmethod
    def normalize_timeframe(timeframe: str) -> str:
        return timeframe.strip().upper()

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

    def get_intrabar_bars(
        self,
        symbol: str,
        chart_bar: Bar,
        lower_timeframe: str | None = None,
        *,
        max_bars: int | None = None,
    ) -> list[Bar]:
        """Return lower-timeframe bars inside a parent chart bar using O(log N) lookup.

        Uses LowerTimeframeIndex for O(log N) binary search instead of O(N) scan.
        Returns bars where:
          - bar.time >= chart_bar.time  (bar started at or after parent open)
          - bar_close_time(bar) <= chart_bar_close  (bar fully closed within parent)

        Bars must be pre-loaded under the (symbol, lower_timeframe) key.
        """
        if lower_timeframe is None:
            return []

        normalized_symbol = self.normalize_symbol(symbol)
        normalized_tf = self.normalize_timeframe(lower_timeframe)
        key = (normalized_symbol, normalized_tf)
        bars = self._bars_by_key.get(key)
        if not bars:
            return []

        chart_close = chart_bar.time_close if chart_bar.time_close is not None else chart_bar.time

        # Binary search for first bar with time >= chart_bar.time
        i = bisect.bisect_left(bars, chart_bar.time, key=lambda b: b.time)

        selected: list[Bar] = []
        while i < len(bars):
            bar = bars[i]
            if bar.time > chart_close:
                break
            # Check bar fully closes within chart bar
            bar_close = bar.time_close if bar.time_close is not None else bar.time
            if bar_close <= chart_close:
                selected.append(bar)
            i += 1

        if max_bars is not None and len(selected) > max_bars:
            selected = selected[:max_bars]

        return selected
