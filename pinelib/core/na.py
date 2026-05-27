from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pinelib.errors import PineNAError, PineTypeError


@dataclass(frozen=True, slots=True)
class PineNASentinel:
    def __repr__(self) -> str:
        return "na"

    def __bool__(self) -> bool:
        raise PineNAError("Boolean usage of Pine na is not allowed")


na = PineNASentinel()


@runtime_checkable
class SupportsSeriesLike(Protocol):
    @property
    def current(self) -> Any: ...

    def __getitem__(self, offset: int) -> Any: ...

    @property
    def committed_length(self) -> int: ...


_NA_SENTINEL_TYPE = type(na)


def is_na(value: Any) -> bool:
    # Fast path for None (most common in hot loops): O(1) pointer comparison
    if value is None:
        return True
    # Fast path for float (second most common): avoid isinstance overhead
    # Use type() comparison which is faster than isinstance()
    t = type(value)
    if t is float:
        # NaN check: a float NaN is not equal to itself
        return value != value
    # Remaining cases (na singleton, series objects, etc.)
    return value is na


def _reject_bool_argument(value: Any, *, function_name: str) -> None:
    if isinstance(value, bool):
        raise PineTypeError(f"{function_name}() does not accept bool arguments in Pine v6")


def nz(value: Any, replacement: Any = 0) -> Any:
    _reject_bool_argument(value, function_name="nz")
    _reject_bool_argument(replacement, function_name="nz")
    return replacement if is_na(value) else value


def fixnan(value: Any) -> Any:
    _reject_bool_argument(value, function_name="fixnan")
    if isinstance(value, SupportsSeriesLike):
        current = value.current
        _reject_bool_argument(current, function_name="fixnan")
        if not is_na(current):
            return current
        for offset in range(1, value.committed_length + 1):
            historical = value[offset]
            _reject_bool_argument(historical, function_name="fixnan")
            if not is_na(historical):
                return historical
        return na
    return na if is_na(value) else value
