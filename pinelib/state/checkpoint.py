from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from pinelib.core.values import is_na, na
from pinelib.errors import (
    PL_CHECKPOINT_IDENTITY,
    PL_CHECKPOINT_INVALID,
    PineRuntimeError,
)

_NA_MARKER = {"$pine": "na"}


def is_canonical_sha256(value: object) -> bool:
    """Return whether *value* is the exact lowercase canonical digest form."""

    return (
        type(value) is str
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def to_portable(value: object) -> object:
    """Convert supported runtime values to canonical JSON-compatible data."""

    if is_na(value):
        return dict(_NA_MARKER)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PineRuntimeError(
                "non-finite numbers are forbidden at contract boundaries",
                code=PL_CHECKPOINT_INVALID,
            )
        return value
    if isinstance(value, Enum):
        return to_portable(value.value)
    marker = getattr(value, "__pinelib_portable__", None)
    if callable(marker):
        return to_portable(marker())
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PineRuntimeError(
                    "contract object keys must be strings",
                    code=PL_CHECKPOINT_INVALID,
                )
            result[key] = to_portable(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_portable(item) for item in value]
    raise PineRuntimeError(
        f"unsupported checkpoint value type: {type(value).__name__}",
        code=PL_CHECKPOINT_INVALID,
    )


def from_portable(value: object) -> object:
    if isinstance(value, dict):
        if value == _NA_MARKER:
            return na
        return {str(key): from_portable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [from_portable(item) for item in value]
    return value


def clone_runtime_value(value: object) -> object:
    return from_portable(to_portable(value))


def canonical_json(data: object) -> bytes:
    return json.dumps(
        to_portable(data),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha(data: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(data)).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeCheckpoint:
    schema_id: str
    schema_version: str
    identity_hash: str
    state: dict[str, object]
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "identity_hash": self.identity_hash,
            "state": self.state,
            "content_hash": self.content_hash,
        }

    @classmethod
    def seal(cls, identity_hash: str, state: dict[str, object]) -> RuntimeCheckpoint:
        if not is_canonical_sha256(identity_hash):
            raise PineRuntimeError(
                "checkpoint identity must be a canonical sha256",
                code=PL_CHECKPOINT_IDENTITY,
            )
        portable_state = to_portable(state)
        if not isinstance(portable_state, dict):
            raise PineRuntimeError(
                "checkpoint state must be an object",
                code=PL_CHECKPOINT_INVALID,
            )
        body = {
            "schema_id": "openpine.runtime_checkpoint.v1",
            "schema_version": "1.0.0",
            "identity_hash": identity_hash,
            "state": portable_state,
        }
        return cls(
            str(body["schema_id"]),
            str(body["schema_version"]),
            identity_hash,
            portable_state,
            sha(body),
        )

    @classmethod
    def parse(
        cls, data: dict[str, object], expected_identity: str
    ) -> RuntimeCheckpoint:
        required = {
            "schema_id",
            "schema_version",
            "identity_hash",
            "state",
            "content_hash",
        }
        if not isinstance(data, dict) or set(data) != required:
            raise PineRuntimeError(
                "checkpoint schema mismatch", code=PL_CHECKPOINT_INVALID
            )
        if data["schema_id"] != "openpine.runtime_checkpoint.v1":
            raise PineRuntimeError(
                "checkpoint schema id mismatch", code=PL_CHECKPOINT_INVALID
            )
        if data["schema_version"] != "1.0.0":
            raise PineRuntimeError(
                "checkpoint schema version mismatch", code=PL_CHECKPOINT_INVALID
            )
        if data["identity_hash"] != expected_identity:
            raise PineRuntimeError(
                "checkpoint identity mismatch", code=PL_CHECKPOINT_IDENTITY
            )
        if not is_canonical_sha256(expected_identity):
            raise PineRuntimeError(
                "checkpoint identity is not canonical", code=PL_CHECKPOINT_IDENTITY
            )
        if not is_canonical_sha256(data["content_hash"]):
            raise PineRuntimeError(
                "checkpoint content hash is not canonical",
                code=PL_CHECKPOINT_INVALID,
            )
        body = {
            key: data[key]
            for key in ("schema_id", "schema_version", "identity_hash", "state")
        }
        if data["content_hash"] != sha(body):
            raise PineRuntimeError(
                "checkpoint content hash mismatch", code=PL_CHECKPOINT_INVALID
            )
        if not isinstance(data["state"], dict):
            raise PineRuntimeError(
                "checkpoint state must be object", code=PL_CHECKPOINT_INVALID
            )
        # Re-run the canonical encoder to reject unsupported/non-finite payloads.
        portable_state = to_portable(data["state"])
        assert isinstance(portable_state, dict)
        return cls(
            str(data["schema_id"]),
            str(data["schema_version"]),
            str(data["identity_hash"]),
            portable_state,
            str(data["content_hash"]),
        )
