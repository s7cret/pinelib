from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, TypeVar

from openpine_contracts import (
    IntentKind,
    decimal_string,
    get_schema,
    validate_payload,
)
from openpine_contracts.hashing import (
    CONTENT_HASH_ALG,
    SERIALIZER_ID,
    content_hash,
    seal_content_hash,
)

from pinelib.execution_context import ExecutionContext
from pinelib.strategy.intent_validation import (
    direction as _direction,
)
from pinelib.strategy.intent_validation import (
    reject_unrelated_business_fields as _reject_unrelated_business_fields,
)
from pinelib.strategy.intent_validation import (
    source_span as _source_span,
)

SCHEMA_ID = "openpine.intent.v2"
SCHEMA_VERSION = "2.2.0"
PRODUCER_VERSION = "5.0.0-rc.4"
PINE_DOUBLE_DECIMAL_POLICY = "ieee754-binary64-shortest-round-trip-v1"
_STRICT_GENERIC_IDENTITIES = {
    "run_id": {"run"},
    "strategy_id": {"strategy"},
    "series_id": {"series"},
    "instrument_id": {"instrument"},
    "timeframe": {"unspecified"},
}
_COMPAT_PRODUCER_COMMIT = "0" * 40
_COMPAT_STACK_ID = content_hash(
    {"compatibility_profile": "pinelib.compat.v4"},
    schema_id="pinelib.intent.compat.v4",
)
_SCHEMA_PROPERTIES = frozenset(get_schema(SCHEMA_ID)["properties"])
_T = TypeVar("_T")


class FrozenDict(dict[str, Any]):
    """A JSON-object-compatible immutable mapping.

    ``jsonschema`` and the canonical contracts serializer intentionally recognize
    concrete ``dict`` instances. Public values are detached copies as well as
    frozen, so even deliberately calling ``dict.__setitem__`` cannot alter tape
    state.
    """

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("intent event values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def copy(self) -> FrozenDict:
        return FrozenDict(self)


def _deep_freeze(value: _T) -> _T:
    if isinstance(value, Mapping):
        frozen = FrozenDict()
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("intent mapping keys must be strings")
            dict.__setitem__(frozen, key, _deep_freeze(item))
        return frozen  # type: ignore[return-value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_deep_freeze(item) for item in value)  # type: ignore[return-value]
    return value


def _deep_thaw(value: _T) -> _T:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}  # type: ignore[return-value]
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]  # type: ignore[return-value]
    return value


def _dec(value: object) -> str | None:
    """Convert a Pine numeric value under an explicit binary64 policy.

    Pine runtime numerics are IEEE-754 doubles. Python's ``repr(float)`` is the
    shortest decimal string that round-trips to the identical binary64 value;
    normalizing that string through the contracts decimal helper gives a stable,
    float-free contract value without using the migration-only unsafe helper.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("bool is not a decimal")
    if isinstance(value, int):
        return decimal_string(value)
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Pine double must be finite")
        return decimal_string(repr(value))
    return decimal_string(Decimal(str(value)))


def _nonempty(value: object, *, field: str) -> str:
    text = str(value)
    if not text.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return text


class IntentTape:
    """Append-only, immutable producer for ``openpine.intent.v2`` 2.2.0.

    ``begin_callback`` creates a deterministic invocation-ordinal scope. Replaying
    the same callback therefore returns the same events, while two invocations of
    the same Pine command in one callback receive distinct identities. A
    ``commit_bar`` call permanently seals that bar against later writes.
    """

    def __init__(
        self,
        *,
        run_id: str,
        strategy_id: str,
        series_id: str = "series",
        instrument_id: str = "instrument",
        timeframe: str = "unspecified",
        producer: str = "pinelib",
        producer_version: str = PRODUCER_VERSION,
        producer_commit: str | None = None,
        stack_id: str | None = None,
        semantic_profile: str = "strict_5x",
        phase: str = "BAR_COMMIT",
        strict_production: bool = False,
        execution_context: ExecutionContext | Mapping[str, Any] | None = None,
    ) -> None:
        context = None if execution_context is None else ExecutionContext.coerce(execution_context)
        if strict_production and context is None:
            raise ValueError("strict production IntentTape requires execution_context")

        resolved_commit = producer_commit or os.environ.get("PINELIB_PRODUCER_COMMIT")
        if resolved_commit is None:
            resolved_commit = (
                context.pinelib_commit if context is not None else _COMPAT_PRODUCER_COMMIT
            )
        resolved_stack_id = (
            str(context["stack_id"])
            if stack_id is None and context is not None
            else (_COMPAT_STACK_ID if stack_id is None else stack_id)
        )

        supplied_identity = {
            "run_id": _nonempty(run_id, field="run_id"),
            "strategy_id": _nonempty(strategy_id, field="strategy_id"),
            "series_id": _nonempty(series_id, field="series_id"),
            "instrument_id": _nonempty(instrument_id, field="instrument_id"),
            "timeframe": _nonempty(timeframe, field="timeframe"),
            "semantic_profile": _nonempty(semantic_profile, field="semantic_profile"),
            "producer_commit": _nonempty(resolved_commit, field="producer_commit"),
            "stack_id": _nonempty(resolved_stack_id, field="stack_id"),
        }
        if strict_production:
            assert context is not None
            if producer != "pinelib":
                raise ValueError("strict intent producer must be pinelib")
            if producer_version != PRODUCER_VERSION:
                raise ValueError(f"strict intent producer_version must be {PRODUCER_VERSION}")
            expected_identity = {
                "run_id": context["run_id"],
                "strategy_id": context["strategy_id"],
                "series_id": context["series_id"],
                "instrument_id": context["instrument_id"],
                "timeframe": context["timeframe"],
                "semantic_profile": context["semantic_profile"],
                "producer_commit": context.pinelib_commit,
                "stack_id": context["stack_id"],
            }
            for field, expected in expected_identity.items():
                actual = supplied_identity[field]
                if actual != expected:
                    raise ValueError(
                        f"strict intent {field} must match execution_context: "
                        f"expected {expected!r}, got {actual!r}"
                    )
            for field, sentinels in _STRICT_GENERIC_IDENTITIES.items():
                if supplied_identity[field] in sentinels:
                    raise ValueError(f"strict intent {field} cannot use a generic identity")
            # The validated ExecutionContext schema already proves exact nonzero
            # commit and stack-hash shapes; equality above binds the event producer
            # to those admitted values without a second, drifting validator.

        self.run_id = supplied_identity["run_id"]
        self.strategy_id = supplied_identity["strategy_id"]
        self.series_id = supplied_identity["series_id"]
        self.instrument_id = supplied_identity["instrument_id"]
        self.timeframe = supplied_identity["timeframe"]
        self.producer = _nonempty(producer, field="producer")
        self.producer_version = _nonempty(producer_version, field="producer_version")
        self.producer_commit = supplied_identity["producer_commit"]
        self.stack_id = supplied_identity["stack_id"]
        self.semantic_profile = supplied_identity["semantic_profile"]
        self.strict_production = strict_production
        self._execution_context = context
        self.execution_context_hash = None if context is None else context.content_hash

        self._events: list[FrozenDict] = []
        self._event_ordinals: list[int] = []
        self._by_key: dict[str, FrozenDict] = {}
        self._committed_bars: set[tuple[int, int]] = set()
        self._callback_bar_index = 0
        self._callback_bar_open_time_utc_ms = 0
        self._callback_phase = _nonempty(phase, field="phase")
        self._callback_recalc_iteration = 0
        self._invocation_counts: dict[tuple[str, str], int] = {}

    @property
    def events(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._public_event(event) for event in self._events)

    @property
    def execution_context(self) -> ExecutionContext | None:
        return self._execution_context

    def content_hash(self) -> str:
        return content_hash(
            {"events": [_deep_thaw(event) for event in self._events]},
            schema_id=SCHEMA_ID,
        )

    def _identity_state(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "series_id": self.series_id,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "producer_commit": self.producer_commit,
            "stack_id": self.stack_id,
            "semantic_profile": self.semantic_profile,
            "strict_production": self.strict_production,
            "execution_context_hash": self.execution_context_hash,
        }

    def export_state(self) -> dict[str, object]:
        from pinelib.strategy.intent_checkpoint import export_intent_tape_state

        return export_intent_tape_state(self)

    def restore_state(self, state: object) -> None:
        from pinelib.strategy.intent_checkpoint import restore_intent_tape_state

        restore_intent_tape_state(self, state)

    def set_series_identity(
        self,
        *,
        series_id: str,
        instrument_id: str,
        timeframe: str,
        semantic_profile: str | None = None,
    ) -> None:
        identity = (
            _nonempty(series_id, field="series_id"),
            _nonempty(instrument_id, field="instrument_id"),
            _nonempty(timeframe, field="timeframe"),
            (
                self.semantic_profile
                if semantic_profile is None
                else _nonempty(semantic_profile, field="semantic_profile")
            ),
        )
        current = (self.series_id, self.instrument_id, self.timeframe, self.semantic_profile)
        if self.strict_production and self._execution_context is not None:
            expected = (
                self._execution_context["series_id"],
                self._execution_context["instrument_id"],
                self._execution_context["timeframe"],
                self._execution_context["semantic_profile"],
            )
            if identity != expected:
                raise ValueError("strict intent series identity must match execution_context")
        if self._events and identity != current:
            raise RuntimeError("intent series identity cannot change after the first event")
        self.series_id, self.instrument_id, self.timeframe, self.semantic_profile = identity

    def begin_callback(
        self,
        *,
        bar_index: int,
        bar_open_time_utc_ms: int,
        phase: str,
        recalc_iteration: int = 0,
    ) -> None:
        if isinstance(bar_index, bool) or not isinstance(bar_index, int) or bar_index < 0:
            raise ValueError("bar_index must be a nonnegative integer")
        if (
            isinstance(bar_open_time_utc_ms, bool)
            or not isinstance(bar_open_time_utc_ms, int)
            or bar_open_time_utc_ms < 0
        ):
            raise ValueError("bar_open_time_utc_ms must be a nonnegative integer")
        if (
            isinstance(recalc_iteration, bool)
            or not isinstance(recalc_iteration, int)
            or recalc_iteration < 0
        ):
            raise ValueError("recalc_iteration must be a nonnegative integer")
        self._callback_bar_index = bar_index
        self._callback_bar_open_time_utc_ms = bar_open_time_utc_ms
        self._callback_phase = _nonempty(phase, field="phase")
        self._callback_recalc_iteration = recalc_iteration
        self._invocation_counts = {}

    def commit_bar(self, *, bar_index: int, bar_open_time_utc_ms: int) -> None:
        key = (bar_index, bar_open_time_utc_ms)
        self._committed_bars.add(key)

    def _delivery_ids(
        self,
        *,
        bar_index: int,
        bar_open_time_utc_ms: int,
        phase: str,
        recalc_iteration: int,
        kind: str,
        command_id: str,
        invocation_ordinal: int,
    ) -> tuple[str, str]:
        delivery_identity = {
            "execution_context_hash": self.execution_context_hash,
            "stack_id": self.stack_id,
            "producer_commit": self.producer_commit,
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "series_id": self.series_id,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "bar_index": bar_index,
            "bar_open_time_utc_ms": bar_open_time_utc_ms,
            "phase": _nonempty(phase, field="phase"),
            "recalc_iteration": recalc_iteration,
            "kind": kind,
            "command_id": command_id,
            "invocation_ordinal": invocation_ordinal,
        }
        digest = content_hash(delivery_identity, schema_id=SCHEMA_ID).removeprefix("sha256:")
        return (
            f"intent-event:sha256:{digest}",
            f"intent-delivery:sha256:{digest}",
        )

    def record(
        self,
        kind: IntentKind | str,
        *,
        command_id: str,
        order_id: str | None = None,
        direction: str | None = None,
        qty: object = None,
        qty_percent: object = None,
        price: object = None,
        stop: object = None,
        limit: object = None,
        profit: object = None,
        loss: object = None,
        trail_price: object = None,
        trail_points: object = None,
        trail_offset: object = None,
        from_entry: str | None = None,
        oca_name: str | None = None,
        oca_type: str | None = None,
        comment: str | None = None,
        immediately: bool | None = None,
        risk_rule: str | None = None,
        risk_value: object = None,
        risk_unit: str | None = None,
        risk_scope: str | None = None,
        bar_index: int | None = None,
        bar_open_time_utc_ms: int | None = None,
        phase: str | None = None,
        recalc_iteration: int | None = None,
        source_span: Mapping[str, object] | object | None = None,
        origin_command_kind: str | None = None,
        invocation_ordinal: int | None = None,
    ) -> Mapping[str, Any]:
        if price is not None:
            raise ValueError("price is not an allowed openpine.intent.v2 2.2 field")
        if origin_command_kind is not None:
            raise ValueError("origin_command_kind is not an allowed openpine.intent.v2 2.2 field")
        kind_value = str(kind)
        _reject_unrelated_business_fields(
            kind_value,
            {
                "order_id": order_id,
                "direction": direction,
                "qty": qty,
                "qty_percent": qty_percent,
                "stop": stop,
                "limit": limit,
                "profit": profit,
                "loss": loss,
                "trail_price": trail_price,
                "trail_points": trail_points,
                "trail_offset": trail_offset,
                "from_entry": from_entry,
                "oca_name": oca_name,
                "oca_type": oca_type,
                "comment": comment,
                "immediately": immediately,
                "risk_rule": risk_rule,
                "risk_value": risk_value,
                "risk_unit": risk_unit,
                "risk_scope": risk_scope,
            },
        )
        command_value = _nonempty(command_id, field="command_id")
        event_bar_index = self._callback_bar_index if bar_index is None else bar_index
        event_bar_time = (
            self._callback_bar_open_time_utc_ms
            if bar_open_time_utc_ms is None
            else bar_open_time_utc_ms
        )
        event_phase = self._callback_phase if phase is None else phase
        event_recalc = (
            self._callback_recalc_iteration if recalc_iteration is None else recalc_iteration
        )
        self._validate_event_position(
            bar_index=event_bar_index,
            bar_open_time_utc_ms=event_bar_time,
            recalc_iteration=event_recalc,
        )
        if (event_bar_index, event_bar_time) in self._committed_bars:
            raise RuntimeError(
                f"bar {event_bar_index}@{event_bar_time} is already committed; intents are frozen"
            )

        ordinal_key = (kind_value, command_value)
        automatic_ordinal = invocation_ordinal is None
        if automatic_ordinal:
            ordinal = self._invocation_counts.get(ordinal_key, 0)
        else:
            if (
                isinstance(invocation_ordinal, bool)
                or not isinstance(invocation_ordinal, int)
                or invocation_ordinal < 0
            ):
                raise ValueError("invocation_ordinal must be a nonnegative integer")
            ordinal = invocation_ordinal

        event_id, idempotency_key = self._delivery_ids(
            bar_index=event_bar_index,
            bar_open_time_utc_ms=event_bar_time,
            phase=event_phase,
            recalc_iteration=event_recalc,
            kind=kind_value,
            command_id=command_value,
            invocation_ordinal=ordinal,
        )
        existing = self._by_key.get(idempotency_key)
        sequence = existing["sequence"] if existing is not None else len(self._events)

        payload: dict[str, Any] = {
            "schema_id": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "producer_commit": self.producer_commit,
            "stack_id": self.stack_id,
            "created_at_utc_ms": event_bar_time,
            "serializer_id": SERIALIZER_ID,
            "content_hash_alg": CONTENT_HASH_ALG,
            "event_id": event_id,
            "sequence": sequence,
            "command_id": command_value,
            "kind": kind_value,
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "series_id": self.series_id,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "bar_index": event_bar_index,
            "bar_open_time_utc_ms": event_bar_time,
            "phase": _nonempty(event_phase, field="phase"),
            "recalc_iteration": event_recalc,
            "semantic_profile": self.semantic_profile,
            "source_span": _source_span(
                source_span,
                strict_production=self.strict_production,
                expected_source_hash=(
                    None if self._execution_context is None else self._execution_context.source_hash
                ),
            ),
            "idempotency_key": idempotency_key,
        }

        self._add_business_fields(
            payload,
            kind=kind_value,
            command_id=command_value,
            order_id=order_id,
            direction=direction,
            qty=qty,
            qty_percent=qty_percent,
            stop=stop,
            limit=limit,
            profit=profit,
            loss=loss,
            trail_price=trail_price,
            trail_points=trail_points,
            trail_offset=trail_offset,
            from_entry=from_entry,
            oca_name=oca_name,
            oca_type=oca_type,
            comment=comment,
            immediately=immediately,
            risk_rule=risk_rule,
            risk_value=risk_value,
            risk_unit=risk_unit,
            risk_scope=risk_scope,
        )
        sealed = seal_content_hash(payload, schema_id=SCHEMA_ID)
        validate_payload(SCHEMA_ID, sealed)

        if existing is not None:
            if _deep_thaw(existing) != sealed:
                raise ValueError(
                    "conflicting repeated delivery for the same intent invocation ordinal"
                )
            if automatic_ordinal:
                self._invocation_counts[ordinal_key] = ordinal + 1
            return self._public_event(existing)

        frozen = _deep_freeze(sealed)
        self._events.append(frozen)
        self._event_ordinals.append(ordinal)
        self._by_key[idempotency_key] = frozen
        if automatic_ordinal:
            self._invocation_counts[ordinal_key] = ordinal + 1
        return self._public_event(frozen)

    @staticmethod
    def _validate_event_position(
        *, bar_index: object, bar_open_time_utc_ms: object, recalc_iteration: object
    ) -> None:
        for field, value in (
            ("bar_index", bar_index),
            ("bar_open_time_utc_ms", bar_open_time_utc_ms),
            ("recalc_iteration", recalc_iteration),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a nonnegative integer")

    @staticmethod
    def _public_event(event: Mapping[str, Any]) -> FrozenDict:
        return _deep_freeze(_deep_thaw(event))

    @staticmethod
    def _add_business_fields(
        payload: dict[str, Any],
        *,
        kind: str,
        command_id: str,
        order_id: str | None,
        direction: str | None,
        qty: object,
        qty_percent: object,
        stop: object,
        limit: object,
        profit: object,
        loss: object,
        trail_price: object,
        trail_points: object,
        trail_offset: object,
        from_entry: str | None,
        oca_name: str | None,
        oca_type: str | None,
        comment: str | None,
        immediately: bool | None,
        risk_rule: str | None,
        risk_value: object,
        risk_unit: str | None,
        risk_scope: str | None,
    ) -> None:
        if kind in (IntentKind.ENTRY, IntentKind.ORDER):
            if order_id is None or direction is None or qty is None:
                raise ValueError(f"{kind} intent requires direct order_id, direction, and qty")
            payload.update(
                {
                    "order_id": _nonempty(order_id, field="order_id"),
                    "direction": _direction(direction),
                    "qty": _dec(qty),
                    "stop": _dec(stop),
                    "limit": _dec(limit),
                    "oca_name": oca_name,
                    "oca_type": oca_type,
                    "comment": comment,
                }
            )
        elif kind == IntentKind.EXIT:
            if order_id is None or from_entry is None:
                raise ValueError("exit intent requires direct order_id and from_entry")
            payload.update(
                {
                    "order_id": _nonempty(order_id, field="order_id"),
                    "from_entry": _nonempty(from_entry, field="from_entry"),
                    "stop": _dec(stop),
                    "limit": _dec(limit),
                    "oca_name": oca_name,
                    "comment": comment,
                }
            )
            IntentTape._optional_decimal(payload, "qty", qty)
            IntentTape._optional_decimal(payload, "qty_percent", qty_percent)
            for field, value in {
                "profit": _dec(profit),
                "loss": _dec(loss),
                "trail_price": _dec(trail_price),
                "trail_points": _dec(trail_points),
                "trail_offset": _dec(trail_offset),
            }.items():
                if field in _SCHEMA_PROPERTIES and value is not None:
                    payload[field] = value
        elif kind == IntentKind.CLOSE:
            if from_entry is None:
                raise ValueError("close intent requires a direct from_entry target")
            payload["from_entry"] = _nonempty(from_entry, field="from_entry")
            payload["immediately"] = bool(immediately)
            payload["comment"] = comment
            IntentTape._optional_decimal(payload, "qty", qty)
            IntentTape._optional_decimal(payload, "qty_percent", qty_percent)
        elif kind == IntentKind.CLOSE_ALL:
            payload["immediately"] = bool(immediately)
            payload["comment"] = comment
        elif kind == IntentKind.CANCEL:
            if order_id is None:
                raise ValueError("cancel intent requires a direct order_id")
            payload["order_id"] = _nonempty(order_id, field="order_id")
        elif kind == IntentKind.CANCEL_ALL:
            pass
        elif kind == IntentKind.RISK:
            if risk_rule is None or risk_value is None or risk_unit is None or risk_scope is None:
                raise ValueError("risk intent requires direct rule, value, unit, and scope")
            payload["risk_rule"] = _nonempty(risk_rule, field="risk_rule")
            payload["risk_value"] = _dec(risk_value)
            payload["risk_unit"] = _nonempty(risk_unit, field="risk_unit")
            payload["risk_scope"] = _nonempty(risk_scope, field="risk_scope")
        # Keep command_id direct and opaque. It is never parsed to reconstruct an
        # order target, risk rule, direction, unit, or scope.
        assert payload["command_id"] == command_id

    @staticmethod
    def _optional_decimal(payload: dict[str, Any], field: str, value: object) -> None:
        converted = _dec(value)
        if converted is not None:
            payload[field] = converted
