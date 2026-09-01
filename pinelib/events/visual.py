from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pinelib.errors import PL_VISUAL_LIMIT, PineRuntimeError
from pinelib.events.common import SourceSpan, delivery_id, event_id
from pinelib.state.checkpoint import clone_runtime_value, sha, to_portable


@dataclass(frozen=True, slots=True)
class VisualEvent:
    kind: str
    event_id: str
    delivery_id: str
    call_site_id: str
    sequence: int
    phase: str
    ordinal: int
    payload: dict[str, object]
    source_span: SourceSpan

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "event_id": self.event_id,
            "delivery_id": self.delivery_id,
            "call_site_id": self.call_site_id,
            "sequence": self.sequence,
            "phase": self.phase,
            "ordinal": self.ordinal,
            "payload": to_portable(self.payload),
            "source_span": self.source_span.identity(),
        }


class VisualTape:
    def __init__(self, limit: int = 100_000) -> None:
        self.limit = limit
        self.committed: list[VisualEvent] = []
        self.working: list[VisualEvent] = []

    def begin(self) -> None:
        self.working = []

    def record(
        self,
        *,
        kind: str,
        call_site_id: str,
        sequence: int,
        phase: str,
        payload: dict[str, object],
        source_span: SourceSpan,
    ) -> VisualEvent:
        if len(self.committed) + len(self.working) >= self.limit:
            raise PineRuntimeError("visual event limit exceeded", code=PL_VISUAL_LIMIT)
        ordinal = len(self.working)
        detached = clone_runtime_value(payload)
        if not isinstance(detached, dict):
            raise PineRuntimeError("visual payload must be an object")
        semantic_id = event_id(kind, call_site_id, detached, source_span)
        event = VisualEvent(
            kind,
            semantic_id,
            delivery_id(semantic_id, sequence=sequence, phase=phase, ordinal=ordinal),
            call_site_id,
            sequence,
            phase,
            ordinal,
            detached,
            source_span,
        )
        self.working.append(event)
        return event

    def commit(self) -> None:
        self.committed.extend(self.working)
        self.working = []

    def rollback(self) -> None:
        self.working = []

    @property
    def working_hash(self) -> str:
        return sha({"events": [event.to_dict() for event in self.working]})

    def to_json(self) -> dict[str, object]:
        return {
            "committed": [event.to_dict() for event in self.committed],
            "working": [event.to_dict() for event in self.working],
        }

    @classmethod
    def from_json(cls, data: dict[str, object], limit: int) -> VisualTape:
        tape = cls(limit)
        tape.committed = [_parse_event(row) for row in _rows(data, "committed")]
        tape.working = [_parse_event(row) for row in _rows(data, "working")]
        return tape


def _rows(data: dict[str, object], key: str) -> list[dict[str, object]]:
    rows = data.get(key, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PineRuntimeError("visual tape rows must be objects")
    return cast(list[dict[str, object]], rows)


def _strict_int(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if type(value) is not int:
        raise PineRuntimeError(f"visual event {key} must be an int")
    return value


def _parse_span(data: object) -> SourceSpan:
    if not isinstance(data, dict):
        raise PineRuntimeError("visual event source span must be an object")
    return SourceSpan(
        str(data["source_hash"]),
        str(data["file_id"]),
        int(data["start_line"]),
        int(data["start_column"]),
        int(data["end_line"]),
        int(data["end_column"]),
    )


def _parse_event(data: dict[str, object]) -> VisualEvent:
    payload = data["payload"]
    if not isinstance(payload, dict):
        raise PineRuntimeError("visual event payload must be an object")
    return VisualEvent(
        str(data["kind"]),
        str(data["event_id"]),
        str(data["delivery_id"]),
        str(data["call_site_id"]),
        _strict_int(data, "sequence"),
        str(data["phase"]),
        _strict_int(data, "ordinal"),
        payload,
        _parse_span(data["source_span"]),
    )
