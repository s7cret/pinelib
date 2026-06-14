from __future__ import annotations

from dataclasses import dataclass


class InvalidTimeframeError(ValueError):
    """Raised when a timeframe string cannot be parsed."""


class InvalidBarError(ValueError):
    """Raised when an OHLCV contract bar is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class InstrumentKey:
    venue: str
    market_type: str
    symbol: str


@dataclass(frozen=True, slots=True)
class Timeframe:
    value: str
    multiplier: int
    unit: str
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class ContractBar:
    instrument: InstrumentKey
    timeframe: Timeframe
    time: int
    time_close: int
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    closed: bool = True

    def __post_init__(self) -> None:
        if self.time < 0:
            raise InvalidBarError("time must be non-negative")
        if self.time_close <= self.time:
            raise InvalidBarError("time_close must be greater than time")
        if self.high < max(self.open, self.close):
            raise InvalidBarError("high must be greater than or equal to max(open, close)")
        if self.low > min(self.open, self.close):
            raise InvalidBarError("low must be less than or equal to min(open, close)")


_UNITS_MS: dict[str, int | None] = {
    "S": 1_000,
    "": 60_000,
    "M": None,  # Ambiguous in Pine/TradingView syntax: bare 1M is monthly.
    "H": 3_600_000,
    "D": 86_400_000,
    "W": 7 * 86_400_000,
}


def parse_timeframe(value: str) -> Timeframe:
    raw = value.strip()
    if not raw:
        raise InvalidTimeframeError("empty timeframe")
    normalized = raw.upper()
    if raw.endswith("m") and raw[:-1].isdigit():
        multiplier = int(raw[:-1])
        if multiplier <= 0:
            raise InvalidTimeframeError(f"invalid timeframe: {value!r}")
        return Timeframe(
            value=raw,
            multiplier=multiplier,
            unit="minute",
            duration_ms=multiplier * 60_000,
        )
    if normalized.isdigit():
        multiplier = int(normalized)
        if multiplier <= 0:
            raise InvalidTimeframeError(f"invalid timeframe: {value!r}")
        return Timeframe(
            value=raw,
            multiplier=multiplier,
            unit="minute",
            duration_ms=multiplier * 60_000,
        )

    suffix = normalized[-1]
    amount = normalized[:-1]
    try:
        multiplier = int(amount) if amount else 1
    except ValueError as exc:
        raise InvalidTimeframeError(f"invalid timeframe: {value!r}") from exc
    if multiplier <= 0:
        raise InvalidTimeframeError(f"invalid timeframe: {value!r}")
    if suffix == "S":
        return Timeframe(raw, multiplier, "second", multiplier * 1_000)
    if suffix == "H":
        return Timeframe(raw, multiplier, "hour", multiplier * 3_600_000)
    if suffix == "D":
        return Timeframe(raw, multiplier, "day", multiplier * 86_400_000)
    if suffix == "W":
        return Timeframe(raw, multiplier, "week", multiplier * 7 * 86_400_000)
    if suffix == "M":
        return Timeframe(raw, multiplier, "month", None)
    raise InvalidTimeframeError(f"invalid timeframe: {value!r}")
