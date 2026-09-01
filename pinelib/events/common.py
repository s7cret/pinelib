from __future__ import annotations

from dataclasses import dataclass

from pinelib.errors import PL_REFERENCE_INVALID, PineRuntimeError
from pinelib.state.checkpoint import is_canonical_sha256, sha


@dataclass(frozen=True, slots=True)
class SourceSpan:
    source_hash: str
    file_id: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def __post_init__(self) -> None:
        if not is_canonical_sha256(self.source_hash):
            raise PineRuntimeError("source span requires canonical source hash")
        if (
            not self.file_id
            or min(
                self.start_line,
                self.start_column,
                self.end_line,
                self.end_column,
            )
            < 0
        ):
            raise PineRuntimeError("invalid source span")
        if (self.end_line, self.end_column) < (self.start_line, self.start_column):
            raise PineRuntimeError("source span end precedes start")

    def identity(self) -> dict[str, object]:
        return {
            "source_hash": self.source_hash,
            "file_id": self.file_id,
            "start_line": self.start_line,
            "start_column": self.start_column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


def event_id(
    kind: str, call_site_id: str, payload: dict[str, object], span: SourceSpan
) -> str:
    if not kind or not call_site_id or call_site_id.startswith("0:"):
        raise PineRuntimeError(
            "event identity is incomplete", code=PL_REFERENCE_INVALID
        )
    return sha(
        {
            "kind": kind,
            "call_site_id": call_site_id,
            "payload": payload,
            "source_span": span.identity(),
        }
    )


def delivery_id(
    semantic_event_id: str,
    *,
    sequence: int,
    phase: str,
    ordinal: int,
) -> str:
    if (
        not is_canonical_sha256(semantic_event_id)
        or sequence < 0
        or not phase
        or ordinal < 0
    ):
        raise PineRuntimeError(
            "delivery identity is incomplete", code=PL_REFERENCE_INVALID
        )
    return sha(
        {
            "event_id": semantic_event_id,
            "sequence": sequence,
            "phase": phase,
            "ordinal": ordinal,
        }
    )
