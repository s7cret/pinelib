from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from openpine_contracts import (
    IntentKind,
    decimal_string,
    unsafe_decimal_from_float,
    validate_payload,
)
from openpine_contracts.hashing import CONTENT_HASH_ALG, SERIALIZER_ID, content_hash

from pinelib.version import PACKAGE_VERSION


def _dec(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("bool is not a decimal")
    if isinstance(value, int):
        return decimal_string(value)
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, float):
        return unsafe_decimal_from_float(value)
    return decimal_string(Decimal(str(value)))


class IntentTape:
    def __init__(
        self,
        *,
        run_id: str,
        strategy_id: str,
        producer: str = "pinelib",
        producer_version: str = PACKAGE_VERSION,
        producer_commit: str = "unknown",
        stack_id: str = "openpine-5.0",
        semantic_profile: str = "strict_5x",
        phase: str = "score",
    ) -> None:
        self.run_id = run_id
        self.strategy_id = strategy_id
        self.producer = producer
        self.producer_version = producer_version
        self.producer_commit = producer_commit
        self.stack_id = stack_id
        self.semantic_profile = semantic_profile
        self.phase = phase
        self._events: list[dict[str, Any]] = []
        self._seq = 0
        self._by_key: dict[str, dict[str, Any]] = {}

    @property
    def events(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._events)

    def content_hash(self) -> str:
        return content_hash({"events": list(self._events)}, schema_id="openpine.intent.v2")

    def record(
        self,
        kind: IntentKind | str,
        *,
        command_id: str,
        qty: object = None,
        price: object = None,
        stop: object = None,
        limit: object = None,
        from_entry: str | None = None,
        oca_name: str | None = None,
        oca_type: str | None = None,
        comment: str | None = None,
        bar_index: int = 0,
        bar_open_time_utc_ms: int | None = None,
        source_span: dict[str, object] | None = None,
        origin_command_kind: str | None = None,
    ) -> Mapping[str, Any]:
        kind_value = str(kind)
        idempotency_key = f"{self.run_id}:{self.strategy_id}:{kind_value}:{command_id}:{bar_index}"
        existing = self._by_key.get(idempotency_key)
        if existing is not None:
            return existing
        self._seq += 1
        payload: dict[str, Any] = {
            "schema_id": "openpine.intent.v2",
            "schema_version": "2.0.0-rc.1",
            "producer": self.producer,
            "producer_version": self.producer_version,
            "producer_commit": self.producer_commit,
            "stack_id": self.stack_id,
            "created_at_utc_ms": bar_open_time_utc_ms if bar_open_time_utc_ms is not None else 0,
            "serializer_id": SERIALIZER_ID,
            "content_hash_alg": CONTENT_HASH_ALG,
            "kind": kind_value,
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "bar_index": max(0, bar_index),
            "bar_open_time_utc_ms": bar_open_time_utc_ms,
            "phase": self.phase,
            "source_span": source_span,
            "semantic_profile": self.semantic_profile,
            "idempotency_key": idempotency_key,
            "origin_command_kind": origin_command_kind or kind_value,
            "from_entry": from_entry,
            "oca_name": oca_name,
            "oca_type": oca_type,
            "comment": comment,
        }
        qty_s = _dec(qty)
        if qty_s is not None:
            payload["qty"] = qty_s
        payload["price"] = _dec(price)
        payload["stop"] = _dec(stop)
        payload["limit"] = _dec(limit)
        unsigned = {key: value for key, value in payload.items()}
        payload["content_hash"] = content_hash(unsigned, schema_id="openpine.intent.v2")
        validate_payload("openpine.intent.v2", payload)
        self._events.append(payload)
        self._by_key[idempotency_key] = payload
        return payload
