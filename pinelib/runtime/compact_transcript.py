"""Replayable runtime transcript with incremental hashing and an explicit state-hash scheme."""

from __future__ import annotations

from typing import cast

from pinelib.errors import PL_CHECKPOINT_INVALID, PineRuntimeError
from pinelib.runtime.semantic import ALGORITHM
from pinelib.runtime.transcript import RuntimeTranscript
from pinelib.state.checkpoint import sha, to_portable
from pinelib.state.digest import AppendOnlyHistory


class CompactRuntimeTranscript(RuntimeTranscript):
    def __init__(self) -> None:
        super().__init__()
        self.entries = AppendOnlyHistory("runtime-transcript-v2")  # type: ignore[assignment]

    def append(self, entry: dict[str, object]) -> None:
        if not isinstance(entry, dict):
            raise PineRuntimeError(
                "transcript entry must be an object", code=PL_CHECKPOINT_INVALID
            )
        self._validate_entry(entry)
        if self.entries and cast(int, entry["sequence"]) <= cast(
            int, self.entries[-1]["sequence"]
        ):
            raise PineRuntimeError(
                "transcript sequence must increase", code=PL_CHECKPOINT_INVALID
            )
        super().append(entry)

    @property
    def content_hash(self) -> str:
        return sha(
            {
                "schema_id": "openpine.runtime_transcript.v2",
                "state_hash_algorithm": ALGORITHM,
                "chain": cast(
                    AppendOnlyHistory[dict[str, object]], self.entries
                ).identity(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_id": "openpine.runtime_transcript.v2",
            "schema_version": "2.0.0",
            "state_hash_algorithm": ALGORITHM,
            "entries": to_portable(list(self.entries)),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: object) -> CompactRuntimeTranscript:
        if not isinstance(data, dict) or set(data) != {
            "schema_id",
            "schema_version",
            "state_hash_algorithm",
            "entries",
            "content_hash",
        }:
            raise PineRuntimeError(
                "compact transcript schema mismatch", code=PL_CHECKPOINT_INVALID
            )
        if (
            data["schema_id"] != "openpine.runtime_transcript.v2"
            or data["schema_version"] != "2.0.0"
            or data["state_hash_algorithm"] != ALGORITHM
            or not isinstance(data["entries"], list)
        ):
            raise PineRuntimeError(
                "compact transcript identity mismatch", code=PL_CHECKPOINT_INVALID
            )
        result = cls()
        for entry in data["entries"]:
            result.append(entry)
        if result.to_dict() != data:
            raise PineRuntimeError(
                "compact transcript content mismatch", code=PL_CHECKPOINT_INVALID
            )
        return result
