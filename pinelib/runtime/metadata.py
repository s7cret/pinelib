from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pinelib.core.values import is_na, require_number
from pinelib.errors import (
    PL_METADATA_INVALID,
    PL_TIMEZONE_INVALID,
    PineRuntimeError,
)
from pinelib.runtime.context import RuntimeLanguageContext


@dataclass(frozen=True, slots=True)
class InstrumentContext:
    ticker: str
    tickerid: str
    prefix: str
    currency: str
    basecurrency: str
    timezone: str
    instrument_type: str
    mintick: float
    pointvalue: float = 1.0
    mincontract: float = 1.0

    def __post_init__(self) -> None:
        if not self.ticker or not self.tickerid or not self.prefix:
            raise PineRuntimeError(
                "instrument identity is incomplete", code=PL_METADATA_INVALID
            )
        if self.mintick <= 0 or self.pointvalue <= 0 or self.mincontract <= 0:
            raise PineRuntimeError(
                "instrument numeric metadata must be positive",
                code=PL_METADATA_INVALID,
            )
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise PineRuntimeError(
                f"unknown IANA timezone: {self.timezone}",
                code=PL_TIMEZONE_INVALID,
            ) from error

    def identity(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "tickerid": self.tickerid,
            "prefix": self.prefix,
            "currency": self.currency,
            "basecurrency": self.basecurrency,
            "timezone": self.timezone,
            "instrument_type": self.instrument_type,
            "mintick": self.mintick,
            "pointvalue": self.pointvalue,
            "mincontract": self.mincontract,
        }


_TIMEFRAME_RE = re.compile(r"^(?P<count>[1-9][0-9]*)?(?P<unit>[TSDWM]?)$")

_TIMEFRAME_MULTIPLIERS = {
    "T": {1, 10, 100, 1000},
    "S": {1, 5, 10, 15, 30, 45},
    "": range(1, 1441),
    "D": range(1, 366),
    "W": range(1, 53),
    "M": range(1, 13),
}


@dataclass(frozen=True, slots=True)
class TimeframeContext:
    period: str
    multiplier: int
    unit: Literal["tick", "second", "minute", "day", "week", "month"]
    seconds: int | None

    @classmethod
    def parse(cls, period: str) -> TimeframeContext:
        if type(period) is not str:
            raise PineRuntimeError(
                "Pine timeframe must be a string", code=PL_METADATA_INVALID
            )
        normalized = period.strip().upper()
        match = _TIMEFRAME_RE.fullmatch(normalized)
        if not match or not normalized:
            raise PineRuntimeError(
                f"invalid Pine timeframe: {period}", code=PL_METADATA_INVALID
            )
        count_text = match.group("count")
        suffix = match.group("unit")
        if not count_text and not suffix:
            raise PineRuntimeError(
                f"invalid Pine timeframe: {period}", code=PL_METADATA_INVALID
            )
        count = 1 if count_text is None else int(count_text)
        if count not in _TIMEFRAME_MULTIPLIERS[suffix]:
            raise PineRuntimeError(
                f"unsupported Pine timeframe multiplier: {period}",
                code=PL_METADATA_INVALID,
            )
        if suffix == "T":
            unit: Literal["tick", "second", "minute", "day", "week", "month"] = "tick"
            seconds: int | None = None
        elif suffix == "S":
            unit = "second"
            seconds = count
        elif suffix == "D":
            unit = "day"
            seconds = count * 86_400
        elif suffix == "W":
            unit = "week"
            seconds = count * 604_800
        elif suffix == "M":
            unit = "month"
            seconds = None
        else:
            unit = "minute"
            seconds = count * 60
        return cls(normalized, count, unit, seconds)

    def period_for(self, language: RuntimeLanguageContext) -> str:
        del language
        return self.period

    def identity(self) -> dict[str, object]:
        return {
            "period": self.period,
            "multiplier": self.multiplier,
            "unit": self.unit,
            "seconds": self.seconds,
        }


@dataclass(frozen=True, slots=True)
class BarStateView:
    isfirst: bool
    islast: bool
    ishistory: bool
    isrealtime: bool
    isnew: bool
    isconfirmed: bool
    islastconfirmedhistory: bool


@dataclass(frozen=True, slots=True)
class BarValues:
    """Chart-owned bar values injected into one runtime transaction."""

    open: object
    high: object
    low: object
    close: object
    volume: object
    time: int
    time_close: int

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close", "volume"):
            value = getattr(self, name)
            if not is_na(value):
                require_number(value, name=name)
        if (
            type(self.time) is not int
            or type(self.time_close) is not int
            or self.time_close < self.time
        ):
            raise PineRuntimeError(
                "bar time interval is invalid", code=PL_METADATA_INVALID
            )
