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


@dataclass(frozen=True, slots=True)
class TimeframeInfo:
    value: str
    interval_ms: int | None = None

    @classmethod
    def from_string(cls, value: str) -> "TimeframeInfo":
        return cls(value=value, interval_ms=parse_timeframe_to_ms(value))


@dataclass(slots=True)
class RuntimeConfig:
    supports_nested_security: bool = False
    strict_tv_parity: bool = False
    reference_history_mode: ReferenceHistoryMode = "unsupported"
    max_recalculations_per_bar: int = 16
    allow_incomplete_bar_time_close: bool = True
    diagnostics_as_errors: bool = False
    extra: dict[str, object] = field(default_factory=dict)


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
    }
    if normalized in mapping:
        return mapping[normalized]
    suffix = normalized[-1]
    prefix = normalized[:-1]
    if not prefix.isdigit():
        return None
    amount = int(prefix)
    unit_ms = {
        "S": 1_000,
        "M": 60_000,
        "H": 3_600_000,
        "D": 86_400_000,
        "W": 7 * 86_400_000,
    }.get(suffix)
    if unit_ms is None:
        return None
    return amount * unit_ms

