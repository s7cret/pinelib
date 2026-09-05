from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pinelib.errors import PL_CHECKPOINT_INVALID, PL_SERIES_HISTORY, PineRuntimeError
from pinelib.state.checkpoint import (
    clone_runtime_value,
    from_portable,
    sha,
    to_portable,
)
from pinelib.state.digest import AppendOnlyHistory

T = TypeVar("T")


@dataclass(slots=True)
class SeriesStorage(Generic[T]):
    name: str
    dtype: str
    committed: AppendOnlyHistory[T] = field(
        default_factory=lambda: AppendOnlyHistory("series-history-v1")
    )
    working: T | None = None
    initialized: bool = False
    revision: int = 0

    def begin(self, value: T | None = None) -> None:
        baseline = self.committed[-1] if value is None and self.committed else value
        self.working = clone_runtime_value(baseline)  # type: ignore[assignment]
        self.initialized = True

    def set(self, value: T) -> None:
        if not self.initialized:
            raise PineRuntimeError("series not initialized")
        self.working = clone_runtime_value(value)  # type: ignore[assignment]

    def read(self, offset: int = 0) -> T | None:
        if offset < 0:
            raise PineRuntimeError("negative history offset", code=PL_SERIES_HISTORY)
        if offset == 0:
            return self.working
        index = len(self.committed) - offset
        return self.committed[index] if index >= 0 else None

    def commit(self) -> None:
        self.committed.append(clone_runtime_value(self.working))  # type: ignore[arg-type]
        self.revision += 1

    def rollback(self) -> None:
        baseline = self.committed[-1] if self.committed else None
        self.working = clone_runtime_value(baseline)  # type: ignore[assignment]

    @property
    def semantic_hash(self) -> str:
        return sha(
            {
                "algorithm": "pinelib.series-state.v1",
                "name": self.name,
                "dtype": self.dtype,
                "history": self.committed.identity(),
                "working": self.working,
                "initialized": self.initialized,
                "revision": self.revision,
            }
        )

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "committed": to_portable(list(self.committed)),
            "working": to_portable(self.working),
            "initialized": self.initialized,
            "revision": self.revision,
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> SeriesStorage[object]:
        required = {
            "name",
            "dtype",
            "committed",
            "working",
            "initialized",
            "revision",
        }
        if not isinstance(data, dict) or set(data) != required:
            raise PineRuntimeError(
                "series checkpoint schema mismatch", code=PL_CHECKPOINT_INVALID
            )
        if (
            type(data["name"]) is not str
            or not data["name"]
            or type(data["dtype"]) is not str
            or not data["dtype"]
            or not isinstance(data["committed"], list)
            or type(data["initialized"]) is not bool
            or type(data["revision"]) is not int
            or data["revision"] < 0
        ):
            raise PineRuntimeError(
                "series checkpoint types are invalid", code=PL_CHECKPOINT_INVALID
            )
        committed = from_portable(data["committed"])
        if not isinstance(committed, list):
            raise PineRuntimeError(
                "series committed history must be a list", code=PL_CHECKPOINT_INVALID
            )
        if data["revision"] != len(committed):
            raise PineRuntimeError(
                "series checkpoint revision is inconsistent",
                code=PL_CHECKPOINT_INVALID,
            )
        storage = SeriesStorage[object](data["name"], data["dtype"])
        storage.committed = AppendOnlyHistory("series-history-v1", committed)
        storage.working = from_portable(data["working"])
        storage.initialized = data["initialized"]
        storage.revision = data["revision"]
        if storage.to_json() != data:
            raise PineRuntimeError(
                "series checkpoint is not round-trip stable",
                code=PL_CHECKPOINT_INVALID,
            )
        return storage
