from __future__ import annotations

from dataclasses import dataclass

from pinelib.errors import PineDataFormatError


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

    def with_time_close(self, time_close: int) -> "Bar":
        return Bar(
            time=self.time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            time_close=time_close,
        )

