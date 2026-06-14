from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

try:
    from marketdata_provider.contracts import InvalidTimeframeError, parse_timeframe
except ModuleNotFoundError:
    from pinelib.compat.marketdata import InvalidTimeframeError, parse_timeframe

Qualifier = Literal["const", "input", "simple", "series"]
ReferenceHistoryMode = Literal["unsupported", "identity"]


@dataclass(frozen=True, slots=True)
class TypeInfo:
    base_type: str
    qualifier: Qualifier
    is_reference_type: bool = False
    can_be_na: bool = True
    is_history_allowed: bool = True


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    tickerid: str
    timezone: str = "UTC"
    session: str = "0000-2359:1234567"
    mintick: float = 0.01
    exchange: str | None = None
    prefix: str | None = None
    description: str | None = None
    # TradingView syminfo.type value: stock, futures, index, forex, crypto,
    # cfd, loan, fund, warrant, struct, bond, right, fund_managed.
    type: str = "stock"
    basecurrency: str | None = None
    currency: str | None = None
    pointvalue: float = 1.0

    @property
    def ticker(self) -> str:
        return self.tickerid.split(":", 1)[-1]


@dataclass(frozen=True, slots=True)
class TimeframeInfo:
    value: str
    interval_ms: int | None = None
    isseconds: bool = False
    isminutes: bool = False
    isdaily: bool = False
    isweekly: bool = False
    ismonthly: bool = False
    multiplier: int | None = None

    @property
    def period(self) -> str:
        """Alias for value, the timeframe period string."""
        return self.value

    @property
    def isintraday(self) -> bool:
        """True if timeframe is intraday (seconds or minutes)."""
        return self.isseconds or self.isminutes

    @classmethod
    def from_string(cls, value: str) -> TimeframeInfo:
        normalized = value.strip().upper()
        interval_ms = parse_timeframe_to_ms(value)
        multiplier: int | None = None
        try:
            parsed = parse_timeframe(value)
        except InvalidTimeframeError:
            parsed = None

        isseconds = False
        # Pine numeric timeframe strings are minutes even when a shared marketdata
        # parser normalizes "60" to an hour-sized duration.
        isminutes = normalized.isdigit() or (
            parsed.unit == "minute" if parsed is not None else False
        )
        isdaily = parsed.unit == "day" if parsed is not None else normalized.endswith("D")
        isweekly = parsed.unit == "week" if parsed is not None else normalized.endswith("W")
        ismonthly = parsed.unit == "month" if parsed is not None else normalized == "M"
        if normalized.isdigit():
            multiplier = int(normalized)
        elif parsed is not None:
            multiplier = parsed.multiplier
        return cls(
            value=value,
            interval_ms=interval_ms,
            isseconds=isseconds,
            isminutes=isminutes,
            isdaily=isdaily,
            isweekly=isweekly,
            ismonthly=ismonthly,
            multiplier=multiplier,
        )


@dataclass(frozen=True, slots=True)
class BarStateInfo:
    isfirst: bool = False
    islast: bool = True
    ishistory: bool = True
    isrealtime: bool = False
    isnew: bool = True
    isconfirmed: bool = False
    islastconfirmedhistory: bool = False


@dataclass(frozen=True, slots=True)
class TickUpdate:
    """Deterministic realtime/tick update for one open chart bar.

    PineLib does not fetch or synthesize TradingView realtime feeds. Callers that
    want ``calc_on_every_tick`` semantics must provide an explicit sequence of
    ticks. The runtime mutates the active bar monotonically using these ticks and
    marks only the final update as confirmed.
    """

    price: float
    volume: float = 0.0
    time: int | None = None
    is_final: bool = False


@dataclass(slots=True)
class RuntimeConfig:
    supports_nested_security: bool = False
    strict_tv_parity: bool = False
    reference_history_mode: ReferenceHistoryMode = "unsupported"
    max_recalculations_per_bar: int = 16
    allow_incomplete_bar_time_close: bool = True
    diagnostics_as_errors: bool = False
    diagnostics: list[dict[str, object]] = field(default_factory=list)
    extra: dict[str, object] = field(default_factory=dict)
    process_orders_on_close: bool | None = None
    calc_on_order_fills: bool | None = None
    calc_on_every_tick: bool | None = None

    def emit_diagnostic(self, code: str, message: str, **extra: object) -> None:
        payload: dict[str, object] = {"code": code, "message": message}
        payload.update(extra)
        self.diagnostics.append(payload)


def parse_timeframe_to_ms(value: str) -> int | None:
    if not value.strip():
        return None
    try:
        return parse_timeframe(value).duration_ms
    except InvalidTimeframeError:
        return None
