from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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
    type: str = "stock"  # security type: stock, futures, index, forex, crypto, cfd, loan, fund, warrant, struct, bond, right, fund_managed
    basecurrency: str | None = None
    currency: str | None = None
    pointvalue: float = 1.0


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
        # Monthly: "M" alone or "3MO", "12MO" etc. Also "3M" means 3 months (not 3 minutes in Pine)
        ismonthly = normalized == "M" or normalized.endswith("MO") or (
            normalized.endswith("M") and len(normalized) > 1 and normalized[:-1].isdigit()
        )
        isseconds = normalized.endswith("S") and not normalized.endswith("MS")
        isdaily = normalized.endswith("D") and not normalized.endswith("WD")
        isweekly = normalized.endswith("W") and not normalized.endswith("MW")
        # Intraday: digit-only ("60"), or ends with H ("1H"), or ends with M for minutes ("15M") but NOT monthly
        isminutes = (normalized.isdigit()) or (normalized.endswith("M") and not ismonthly)
        if normalized.isdigit():
            multiplier = int(normalized)
        elif normalized in {"S", "D", "W", "M"}:
            multiplier = 1
        elif len(normalized) > 1 and normalized[:-1].isdigit():
            multiplier = int(normalized[:-1])
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
    normalized = value.strip().upper()
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized) * 60_000
    mapping = {
        "S": 1_000,
        "D": 86_400_000,
        "W": 7 * 86_400_000,
        "MO": 30 * 86_400_000,  # monthly (approximate as 30 days)
        "M": 60_000,  # minutes (intraday)
    }
    if normalized in mapping:
        return mapping[normalized]
    # Handle "3MO", "12MO" etc: monthly with explicit multiplier
    if normalized.endswith("MO") and len(normalized) > 2 and normalized[:-2].isdigit():
        amount = int(normalized[:-2])
        return amount * 30 * 86_400_000
    suffix = normalized[-1]
    prefix = normalized[:-1]
    if not prefix.isdigit():
        return None
    amount = int(prefix)
    unit_ms = {
        "S": 1_000,
        "M": 60_000,  # minutes (intraday)
        "H": 3_600_000,
        "D": 86_400_000,
        "W": 7 * 86_400_000,
    }.get(suffix)
    if unit_ms is None:
        return None
    return amount * unit_ms
