"""Canonical intent tape. Numeric fields are decimal strings, never float."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from openpine_contracts import IntentKind, decimal_string
from openpine_contracts.errors import MoneyError

SCHEMA_ID = "openpine.intent.v2"


def _decimal_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        raise MoneyError("float is forbidden on intent boundary")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise MoneyError("intent numeric field must be decimal string or int")
    return decimal_string(value)


@dataclass(frozen=True, slots=True)
class IntentEvent:
    schema_id: str
    kind: str
    run_id: str
    strategy_id: str
    bar_index: int
    phase: str
    idempotency_key: str
    origin_command_kind: str
    order_id: str
    qty: str | None = None
    price: str | None = None
    stop: str | None = None
    limit: str | None = None
    from_entry: str | None = None
    oca_name: str | None = None
    oca_type: str | None = None
    comment: str | None = None
    source_span: Mapping[str, object] | None = None
    semantic_profile: str | None = None

    def to_contract_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_id": self.schema_id,
            "kind": self.kind,
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "bar_index": self.bar_index,
            "phase": self.phase,
            "idempotency_key": self.idempotency_key,
            "origin_command_kind": self.origin_command_kind,
            "order_id": self.order_id,
        }
        if self.qty is not None:
            payload["qty"] = self.qty
        if self.price is not None:
            payload["price"] = self.price
        if self.stop is not None:
            payload["stop"] = self.stop
        if self.limit is not None:
            payload["limit"] = self.limit
        if self.from_entry is not None:
            payload["from_entry"] = self.from_entry
        if self.oca_name is not None:
            payload["oca_name"] = self.oca_name
        if self.oca_type is not None:
            payload["oca_type"] = self.oca_type
        if self.comment is not None:
            payload["comment"] = self.comment
        if self.source_span is not None:
            payload["source_span"] = dict(self.source_span)
        if self.semantic_profile is not None:
            payload["semantic_profile"] = self.semantic_profile
        return payload


class IntentTape:
    def __init__(self) -> None:
        self._events: list[IntentEvent] = []
        self._seen: set[str] = set()

    def record(self, event: IntentEvent) -> None:
        if event.idempotency_key in self._seen:
            return
        self._seen.add(event.idempotency_key)
        self._events.append(event)

    @property
    def events(self) -> tuple[IntentEvent, ...]:
        return tuple(self._events)

    def __len__(self) -> int:
        return len(self._events)


def make_intent(
    *,
    kind: IntentKind | str,
    order_id: str,
    run_id: str = "run",
    strategy_id: str = "strategy",
    bar_index: int = 0,
    phase: str = "SCORE",
    qty: object = None,
    stop: object = None,
    limit: object = None,
    from_entry: str | None = None,
    oca_name: str | None = None,
    oca_type: str | None = None,
    comment: str | None = None,
    source_span: Mapping[str, object] | None = None,
) -> IntentEvent:
    kind_value = kind.value if isinstance(kind, IntentKind) else str(kind)
    key = f"{kind_value}:{order_id}:{from_entry or ''}:{bar_index}:{phase}"
    return IntentEvent(
        schema_id=SCHEMA_ID,
        kind=kind_value,
        run_id=run_id,
        strategy_id=strategy_id,
        bar_index=bar_index,
        phase=phase,
        idempotency_key=key,
        origin_command_kind=kind_value,
        order_id=order_id,
        qty=_decimal_or_none(qty),
        stop=_decimal_or_none(stop),
        limit=_decimal_or_none(limit),
        from_entry=from_entry,
        oca_name=oca_name,
        oca_type=oca_type,
        comment=comment,
        source_span=source_span,
    )
