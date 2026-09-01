from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class MacdResult(NamedTuple):
    macd: object
    signal: object
    histogram: object


class BandsResult(NamedTuple):
    basis: object
    upper: object
    lower: object


class DmiResult(NamedTuple):
    plus_di: object
    minus_di: object
    adx: object


class SupertrendResult(NamedTuple):
    value: object
    direction: object


@dataclass(frozen=True, slots=True)
class KernelSpec:
    symbol: str
    family: str
    state_schema: str
    minimum_samples: int
    na_policy: str
    tuple_arity: int = 0
