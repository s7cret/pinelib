from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IntentEvent:
    schema_id: str
    kind: str
    order_id: str
    direction: str | None
    qty: float | None
    limit: float | None
    stop: float | None
    from_entry: str | None
    comment: str | None
    bar_index: int | None
    time: int | None
    extra: dict[str, Any]


class IntentTape:
    def __init__(self) -> None:
        self.events: list[IntentEvent] = []

    def record(self, event: IntentEvent) -> None:
        self.events.append(event)

    def __len__(self) -> int:
        return len(self.events)
