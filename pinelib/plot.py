"""Plot recording for Pine indicator plot() calls.

This module provides PlotRecorder for capturing numeric plot values
per bar, and PlotRecord as the individual record type.
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

    def __init__(self) -> None:
        self._records: list[PlotRecord] = []

    def record(
        self,
        bar_time: int,
        bar_index: int,
        name: str,
        value: Any,
        title: str,
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._records.append(PlotRecord(
            bar_time=bar_time,
            bar_index=bar_index,
            name=name,
            value=value,
            title=title,
            kwargs=kwargs or {},
        ))

    def get_records(self) -> list[PlotRecord]:
        """Return all recorded plot calls in order."""
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
            if r.bar_time not in result:
                result[r.bar_time] = {}
            result[r.bar_time][r.title] = r.value
        return result
