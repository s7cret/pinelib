"""Plot recording for Pine indicator plot() calls.

This module provides PlotRecorder for capturing numeric plot values
per bar, and PlotRecord as the individual record type.

Fast-path strategy: for the common 'plot' case, we store tuples directly
(bar_time, bar_index, value, title) instead of full PlotRecord dataclass.
This eliminates 258K+ dataclass allocations per strategy execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PlotRecord:
    """A single plot() call recorded for one bar."""
    bar_time: int       # Unix milliseconds
    bar_index: int
    name: str           # 'plot'
    value: Any          # evaluated numeric value
    title: str          # plot title / column name
    kwargs: dict[str, Any] = field(default_factory=dict)


class PlotRecorder:
    """Records plot() calls per bar for later CSV serialization.

    This is NOT a visual renderer. It only records numeric values
    for the data window / exported chart data.
    """

    __slots__ = ('_records', '_from_time', '_to_time')

    def __init__(self) -> None:
        object.__setattr__(self, '_records', [])
        object.__setattr__(self, '_from_time', None)
        object.__setattr__(self, '_to_time', None)

    def set_time_window(self, from_time: int | None = None, to_time: int | None = None) -> None:
        """Restrict recorded plot calls to an inclusive timestamp window."""
        object.__setattr__(self, '_from_time', from_time)
        object.__setattr__(self, '_to_time', to_time)

    def _in_time_window(self, bar_time: int) -> bool:
        from_time = self._from_time
        to_time = self._to_time
        return (from_time is None or bar_time >= from_time) and (to_time is None or bar_time <= to_time)

    def record(
        self,
        bar_time: int,
        bar_index: int,
        name: str,
        value: Any,
        title: str,
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        if not self._in_time_window(bar_time):
            return
        self._records.append(PlotRecord(
            bar_time=bar_time,
            bar_index=bar_index,
            name=name,
            value=value,
            title=title,
            kwargs=kwargs or {},
        ))

    def record_plot(
        self,
        bar_time: int,
        bar_index: int,
        value: Any,
        title: str,
    ) -> None:
        """Fast-path for plot() calls: no dataclass, just a tuple.
        
        Format: (bar_time, bar_index, value, title)
        This saves ~2.8μs per call vs PlotRecord dataclass.
        """
        if not self._in_time_window(bar_time):
            return
        self._records.append((bar_time, bar_index, value, title))

    def get_records(self) -> list[PlotRecord]:
        """Return all recorded plot calls in order.
        
        Note: may contain tuples (fast-path) or PlotRecord objects.
        Callers should check with isinstance(r, PlotRecord).
        """
        return self._records

    def reset(self) -> None:
        """Clear all recorded plot calls."""
        self._records.clear()

    def get_data_by_time(self) -> dict[int, dict[str, Any]]:
        """Return {bar_time: {title: value}} for CSV serialization.

        If multiple plot calls for same bar+title exist, the last one wins
        (consistent with TradingView's overwrite behavior).
        """
        result: dict[int, dict[str, Any]] = {}
        for r in self._records:
            if isinstance(r, PlotRecord):
                bar_time, title, value = r.bar_time, r.title, r.value
            else:
                # Tuple fast-path: (bar_time, bar_index, value, title)
                bar_time, _, value, title = r
            if bar_time not in result:
                result[bar_time] = {}
            result[bar_time][title] = value
        return result
