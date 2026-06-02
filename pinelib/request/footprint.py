from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pinelib.core.na import na


@dataclass(frozen=True, slots=True)
class FootprintSnapshot:
    buy_volume_value: float
    sell_volume_value: float

    def buy_volume(self) -> float:
        return self.buy_volume_value

    def sell_volume(self) -> float:
        return self.sell_volume_value

    def delta(self) -> float:
        return self.buy_volume_value - self.sell_volume_value


def footprint(
    ticks_per_row: int | float | None = None,
    value_area: int | float | None = None,
    imbalance: int | float | None = None,
    *,
    runtime: Any,
    state_id: str,
) -> FootprintSnapshot | object:
    del ticks_per_row, value_area, imbalance, state_id
    provider = getattr(runtime, "footprint_provider", None)
    if provider is None:
        return na
    get_current = getattr(provider, "get_current_footprint", None)
    if not callable(get_current):
        return na
    result = get_current(runtime.current_bar)
    return result if result is not None else na


__all__ = ["FootprintSnapshot", "footprint"]
