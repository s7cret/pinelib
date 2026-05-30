from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pinelib.errors import PineDataFormatError

if TYPE_CHECKING:
    from marketdata_provider.contracts import InstrumentKey, Timeframe
    from marketdata_provider.contracts.bar import Bar as ContractBar


@dataclass(frozen=True, slots=True)
class Bar:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    time_close: int | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.time < 0:
            raise PineDataFormatError("Bar.time must be a non-negative UTC millisecond timestamp")
        if self.time_close is not None and self.time_close < self.time:
            raise PineDataFormatError("Bar.time_close must be greater than or equal to Bar.time")
        if self.high < max(self.open, self.close):
            raise PineDataFormatError("Bar high must be >= max(open, close)")
        if self.low > min(self.open, self.close):
            raise PineDataFormatError("Bar low must be <= min(open, close)")

    def with_time_close(self, time_close: int) -> Bar:
        return Bar(
            time=self.time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            time_close=time_close,
        )


def to_contract_bar(
    bar: Bar,
    *,
    instrument: InstrumentKey,
    timeframe: Timeframe,
    closed: bool = True,
) -> ContractBar:
    from marketdata_provider.contracts.bar import Bar as ContractBar
    from marketdata_provider.contracts.errors import InvalidBarError

    time_close = bar.time_close
    if time_close is None:
        if timeframe.duration_ms is None:
            raise PineDataFormatError("Bar.time_close is required for non-fixed-duration timeframes")
        time_close = bar.time + timeframe.duration_ms - 1

    try:
        return ContractBar(
            instrument=instrument,
            timeframe=timeframe,
            time=bar.time,
            time_close=time_close,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            closed=closed,
        )
    except InvalidBarError as exc:
        raise PineDataFormatError(str(exc)) from exc


def from_contract_bar(bar: ContractBar) -> Bar:
    return Bar(
        time=bar.time,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=0.0 if bar.volume is None else bar.volume,
        time_close=bar.time_close,
    )
