from __future__ import annotations

from dataclasses import dataclass, field

from pinelib.errors import PL_CHECKPOINT_INVALID, PineRuntimeError
from pinelib.state.checkpoint import is_canonical_sha256, sha, to_portable

_ENTRY_KEYS = {
    "sequence",
    "phase",
    "realtime",
    "final_tick",
    "projection_hash",
    "bar_index",
    "tick_index",
    "committed",
    "state_hash",
    "visual_batch_hash",
    "alert_batch_hash",
}


@dataclass(slots=True)
class RuntimeTranscript:
    entries: list[dict[str, object]] = field(default_factory=list)
    _control_mode: str | None = field(default=None, init=False, repr=False)

    def append(self, entry: dict[str, object]) -> None:
        self._validate_entry(entry)
        control = entry.get("control")
        if control is None:
            if self._control_mode is not None:
                raise PineRuntimeError("legacy transcript entry follows bound control", code=PL_CHECKPOINT_INVALID)
        else:
            mode = control["bar_commit_mode"]
            if self._control_mode is not None and self._control_mode != mode:
                raise PineRuntimeError("runtime transcript control mode changed", code=PL_CHECKPOINT_INVALID)
            if self._control_mode is None and self.entries:
                # Migration follows the established legacy checkpoint decoder;
                # it does not reinterpret the preserved prefix under a new mode.
                legacy_mode = "deferred" if self.entries[-1]["phase"] == "BAR_COMMIT" else "callback"
                if mode != legacy_mode:
                    raise PineRuntimeError("runtime transcript control differs from legacy admission", code=PL_CHECKPOINT_INVALID)
            if control["boundary"] == "bar_commit":
                previous = self.entries[-1] if self.entries else None
                if (previous is None or previous.get("control") != {"bar_commit_mode": "deferred", "boundary": "callback"}
                        or entry["sequence"] != previous["sequence"] + 1
                        or any(entry[key] != previous[key] for key in
                               ("bar_index", "tick_index", "realtime", "final_tick", "projection_hash"))
                        or (entry["realtime"] and not entry["final_tick"])):
                    raise PineRuntimeError("runtime transcript publication lacks its provisional callback", code=PL_CHECKPOINT_INVALID)
            self._control_mode = mode
        portable = to_portable(entry)
        assert isinstance(portable, dict)
        self.entries.append(portable)

    @property
    def control_mode(self) -> str | None:
        return self._control_mode

    @staticmethod
    def is_publication(entry: dict[str, object]) -> bool:
        control = entry.get("control")
        return control["boundary"] == "bar_commit" if control is not None else entry["phase"] == "BAR_COMMIT"

    @property
    def content_hash(self) -> str:
        return sha({"entries": self.entries})

    def to_dict(self) -> dict[str, object]:
        entries = to_portable(self.entries)
        assert isinstance(entries, list)
        return {
            "schema_id": "openpine.runtime_transcript.v1",
            "schema_version": "1.1.0" if self._control_mode is not None else "1.0.0",
            "entries": entries,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: object) -> RuntimeTranscript:
        if (
            isinstance(data, dict)
            and data.get("schema_id") == "openpine.runtime_transcript.v2"
        ):
            from pinelib.runtime.compact_transcript import CompactRuntimeTranscript

            return CompactRuntimeTranscript.from_dict(data)
        required = {"schema_id", "schema_version", "entries", "content_hash"}
        if not isinstance(data, dict) or set(data) != required:
            raise PineRuntimeError(
                "runtime transcript schema mismatch", code=PL_CHECKPOINT_INVALID
            )
        if (
            data["schema_id"] != "openpine.runtime_transcript.v1"
            or data["schema_version"] not in ("1.0.0", "1.1.0")
            or not isinstance(data["entries"], list)
            or not is_canonical_sha256(data["content_hash"])
        ):
            raise PineRuntimeError(
                "runtime transcript identity is invalid", code=PL_CHECKPOINT_INVALID
            )
        transcript = cls()
        previous_sequence = -1
        for entry in data["entries"]:
            if not isinstance(entry, dict):
                raise PineRuntimeError(
                    "runtime transcript entry must be an object",
                    code=PL_CHECKPOINT_INVALID,
                )
            sequence = entry.get("sequence")
            if type(sequence) is not int or sequence <= previous_sequence:
                raise PineRuntimeError(
                    "runtime transcript sequence is not strictly increasing",
                    code=PL_CHECKPOINT_INVALID,
                )
            transcript.append(entry)
            previous_sequence = sequence
        if (
            transcript.content_hash != data["content_hash"]
            or transcript.to_dict() != data
        ):
            raise PineRuntimeError(
                "runtime transcript is not round-trip stable",
                code=PL_CHECKPOINT_INVALID,
            )
        return transcript

    @staticmethod
    def _validate_entry(entry: dict[str, object]) -> None:
        if set(entry) not in (_ENTRY_KEYS, _ENTRY_KEYS | {"control"}):
            raise PineRuntimeError(
                "runtime transcript entry schema mismatch", code=PL_CHECKPOINT_INVALID
            )
        if "control" in entry:
            control = entry["control"]
            if (type(control) is not dict or set(control) != {"bar_commit_mode", "boundary"}
                    or control["bar_commit_mode"] not in ("callback", "deferred")
                    or control["boundary"] not in ("callback", "bar_commit")
                    or entry["committed"] is not True
                    or (control["boundary"] == "bar_commit" and
                        (control["bar_commit_mode"] != "deferred" or entry["phase"] != "BAR_COMMIT"))):
                raise PineRuntimeError("runtime transcript control schema mismatch", code=PL_CHECKPOINT_INVALID)
        if (
            type(entry["sequence"]) is not int
            or entry["sequence"] < 0
            or type(entry["bar_index"]) is not int
            or entry["bar_index"] < 0
            or type(entry["tick_index"]) is not int
            or entry["tick_index"] < 0
            or type(entry["phase"]) is not str
            or not entry["phase"]
            or type(entry["realtime"]) is not bool
            or type(entry["final_tick"]) is not bool
            or type(entry["committed"]) is not bool
        ):
            raise PineRuntimeError(
                "runtime transcript entry types are invalid",
                code=PL_CHECKPOINT_INVALID,
            )
        projection_hash = entry["projection_hash"]
        if projection_hash is not None and not is_canonical_sha256(projection_hash):
            raise PineRuntimeError(
                "runtime transcript projection hash is invalid",
                code=PL_CHECKPOINT_INVALID,
            )
        for name in ("state_hash", "visual_batch_hash", "alert_batch_hash"):
            if not is_canonical_sha256(entry[name]):
                raise PineRuntimeError(
                    "runtime transcript hash is invalid", code=PL_CHECKPOINT_INVALID
                )
