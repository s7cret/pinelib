"""Checkpoint serialization and validation for :class:`IntentTape`."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from openpine_contracts import validate_payload, verify_content_hash

if TYPE_CHECKING:
    from pinelib.strategy.intent_tape import IntentTape


def export_intent_tape_state(tape: IntentTape) -> dict[str, object]:
    """Export all append/idempotency and callback state as a detached checkpoint."""

    from pinelib.strategy.intent_tape import _deep_thaw

    return copy.deepcopy(
        {
            "state_version": "pinelib.intent_tape.state.v1",
            "identity": tape._identity_state(),
            "events": [_deep_thaw(event) for event in tape._events],
            "event_ordinals": list(tape._event_ordinals),
            "idempotency_map": {key: int(event["sequence"]) for key, event in tape._by_key.items()},
            "committed_bars": [list(item) for item in sorted(tape._committed_bars)],
            "callback": {
                "bar_index": tape._callback_bar_index,
                "bar_open_time_utc_ms": tape._callback_bar_open_time_utc_ms,
                "phase": tape._callback_phase,
                "recalc_iteration": tape._callback_recalc_iteration,
            },
            "invocation_counts": [
                {"kind": kind, "command_id": command_id, "count": count}
                for (kind, command_id), count in sorted(tape._invocation_counts.items())
            ],
        }
    )


def restore_intent_tape_state(tape: IntentTape, state: object) -> None:
    """Atomically restore a checkpoint only when its immutable identity matches."""

    from pinelib.strategy.intent_tape import SCHEMA_ID, FrozenDict, _deep_freeze, _nonempty

    if not isinstance(state, dict):
        raise ValueError("IntentTape restore_state() expects a dict snapshot")
    required = {
        "state_version",
        "identity",
        "events",
        "event_ordinals",
        "idempotency_map",
        "committed_bars",
        "callback",
        "invocation_counts",
    }
    if set(state) != required or state.get("state_version") != "pinelib.intent_tape.state.v1":
        raise ValueError("IntentTape checkpoint schema mismatch")
    if state.get("identity") != tape._identity_state():
        raise ValueError("IntentTape checkpoint identity does not match this tape")

    events_raw = state["events"]
    if not isinstance(events_raw, list):
        raise ValueError("IntentTape checkpoint events must be a list")
    ordinals_raw = state["event_ordinals"]
    if (
        not isinstance(ordinals_raw, list)
        or len(ordinals_raw) != len(events_raw)
        or any(
            isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0
            for ordinal in ordinals_raw
        )
    ):
        raise ValueError(
            "IntentTape checkpoint event_ordinals must align with events and be nonnegative"
        )
    ordinals = list(ordinals_raw)
    events: list[FrozenDict] = []
    by_key: dict[str, FrozenDict] = {}
    for sequence, raw in enumerate(events_raw):
        if not isinstance(raw, Mapping):
            raise ValueError("IntentTape checkpoint events must contain mappings")
        event = copy.deepcopy(dict(raw))
        validate_payload(SCHEMA_ID, event)
        if not verify_content_hash(event):
            raise ValueError("IntentTape checkpoint event content_hash is invalid")
        if event.get("sequence") != sequence:
            raise ValueError("IntentTape checkpoint event sequences must be contiguous")
        expected_identity = {
            "producer": tape.producer,
            "producer_version": tape.producer_version,
            "producer_commit": tape.producer_commit,
            "stack_id": tape.stack_id,
            "run_id": tape.run_id,
            "strategy_id": tape.strategy_id,
            "series_id": tape.series_id,
            "instrument_id": tape.instrument_id,
            "timeframe": tape.timeframe,
            "semantic_profile": tape.semantic_profile,
            "created_at_utc_ms": event.get("bar_open_time_utc_ms"),
        }
        for field, expected in expected_identity.items():
            if event.get(field) != expected:
                raise ValueError(
                    f"IntentTape checkpoint event {field} does not match tape identity"
                )
        key = event.get("idempotency_key")
        if not isinstance(key, str) or key in by_key:
            raise ValueError("IntentTape checkpoint idempotency keys must be unique strings")
        expected_event_id, expected_key = tape._delivery_ids(
            bar_index=event["bar_index"],
            bar_open_time_utc_ms=event["bar_open_time_utc_ms"],
            phase=event["phase"],
            recalc_iteration=event["recalc_iteration"],
            kind=event["kind"],
            command_id=event["command_id"],
            invocation_ordinal=ordinals[sequence],
        )
        if event.get("event_id") != expected_event_id or key != expected_key:
            raise ValueError("IntentTape checkpoint event delivery identity is invalid")
        frozen = cast(FrozenDict, _deep_freeze(event))
        events.append(frozen)
        by_key[key] = frozen

    idempotency_raw = state["idempotency_map"]
    expected_map = {key: int(event["sequence"]) for key, event in by_key.items()}
    if (
        not isinstance(idempotency_raw, dict)
        or any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in idempotency_raw.items()
        )
        or idempotency_raw != expected_map
    ):
        raise ValueError("IntentTape checkpoint idempotency map does not match events")

    committed_raw = state["committed_bars"]
    if not isinstance(committed_raw, list):
        raise ValueError("IntentTape checkpoint committed_bars must be a list")
    committed: set[tuple[int, int]] = set()
    for item in committed_raw:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("IntentTape checkpoint committed bar identity is malformed")
        bar_index, bar_time = item
        tape._validate_event_position(
            bar_index=bar_index,
            bar_open_time_utc_ms=bar_time,
            recalc_iteration=0,
        )
        committed.add((bar_index, bar_time))
    if len(committed) != len(committed_raw):
        raise ValueError("IntentTape checkpoint committed bars must be unique")

    callback = state["callback"]
    callback_fields = {"bar_index", "bar_open_time_utc_ms", "phase", "recalc_iteration"}
    if not isinstance(callback, dict) or set(callback) != callback_fields:
        raise ValueError("IntentTape checkpoint callback state is malformed")
    tape._validate_event_position(
        bar_index=callback["bar_index"],
        bar_open_time_utc_ms=callback["bar_open_time_utc_ms"],
        recalc_iteration=callback["recalc_iteration"],
    )
    callback_phase = _nonempty(callback["phase"], field="callback.phase")

    counts_raw = state["invocation_counts"]
    if not isinstance(counts_raw, list):
        raise ValueError("IntentTape checkpoint invocation_counts must be a list")
    counts: dict[tuple[str, str], int] = {}
    for item in counts_raw:
        if not isinstance(item, dict) or set(item) != {"kind", "command_id", "count"}:
            raise ValueError("IntentTape checkpoint invocation count is malformed")
        kind = _nonempty(item["kind"], field="invocation.kind")
        command_id = _nonempty(item["command_id"], field="invocation.command_id")
        count = item["count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("IntentTape checkpoint invocation count must be nonnegative")
        key = (kind, command_id)
        if key in counts:
            raise ValueError("IntentTape checkpoint invocation counts must be unique")
        counts[key] = count

    tape._events = events
    tape._event_ordinals = ordinals
    tape._by_key = by_key
    tape._committed_bars = committed
    tape._callback_bar_index = callback["bar_index"]
    tape._callback_bar_open_time_utc_ms = callback["bar_open_time_utc_ms"]
    tape._callback_phase = callback_phase
    tape._callback_recalc_iteration = callback["recalc_iteration"]
    tape._invocation_counts = counts
