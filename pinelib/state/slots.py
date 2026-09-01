from __future__ import annotations

from dataclasses import dataclass

from pinelib.errors import (
    PL_CHECKPOINT_INVALID,
    PL_RESOURCE_LIMIT,
    PL_STATE_SLOT,
    PineRuntimeError,
)
from pinelib.state.checkpoint import clone_runtime_value, from_portable, to_portable


@dataclass(slots=True)
class StateSlot:
    state_id: str
    owner: str
    schema_version: str
    committed: object = None
    working: object = None
    varip: bool = False
    committed_exists: bool = False


class StateSlotRegistry:
    def __init__(self, limit: int = 10_000) -> None:
        self._slots: dict[str, StateSlot] = {}
        self.limit = limit

    def register(
        self,
        state_id: str,
        owner: str,
        schema_version: str,
        *,
        varip: bool = False,
        initial: object = None,
    ) -> StateSlot:
        if not state_id or not owner or not schema_version:
            raise PineRuntimeError(
                "state slot identity is incomplete", code=PL_STATE_SLOT
            )
        existing = self._slots.get(state_id)
        if existing:
            expected = (owner, schema_version, varip)
            actual = (existing.owner, existing.schema_version, existing.varip)
            if actual != expected:
                raise PineRuntimeError(
                    "incompatible duplicate state slot",
                    code=PL_STATE_SLOT,
                    details={"state_id": state_id, "owner": owner},
                )
            return existing
        if len(self._slots) >= self.limit:
            raise PineRuntimeError("state slot limit exceeded", code=PL_RESOURCE_LIMIT)
        initial_copy = clone_runtime_value(initial)
        slot = StateSlot(
            state_id,
            owner,
            schema_version,
            initial_copy,
            clone_runtime_value(initial_copy),
            varip,
            False,
        )
        self._slots[state_id] = slot
        return slot

    def get_working(
        self,
        state_id: str,
        owner: str,
        schema_version: str,
        *,
        varip: bool = False,
        initial: object = None,
    ) -> object:
        return self.register(
            state_id,
            owner,
            schema_version,
            varip=varip,
            initial=initial,
        ).working

    def begin(self, *, preserve_varip: bool = False) -> None:
        for state_id, slot in tuple(self._slots.items()):
            if preserve_varip and slot.varip:
                continue
            if not slot.committed_exists:
                del self._slots[state_id]
                continue
            slot.working = clone_runtime_value(slot.committed)

    def rollback(self, *, preserve_varip: bool) -> None:
        self.begin(preserve_varip=preserve_varip)

    def commit(self) -> None:
        for slot in self._slots.values():
            slot.committed = clone_runtime_value(slot.working)
            slot.committed_exists = True

    def to_json(self) -> list[dict[str, object]]:
        return [
            {
                "state_id": slot.state_id,
                "owner": slot.owner,
                "schema_version": slot.schema_version,
                "committed": to_portable(slot.committed),
                "working": to_portable(slot.working),
                "varip": slot.varip,
                "committed_exists": slot.committed_exists,
            }
            for slot in sorted(self._slots.values(), key=lambda item: item.state_id)
        ]

    @classmethod
    def from_json(
        cls, rows: list[dict[str, object]], limit: int = 10_000
    ) -> StateSlotRegistry:
        if not isinstance(rows, list):
            raise PineRuntimeError(
                "state slot checkpoint must be a list", code=PL_CHECKPOINT_INVALID
            )
        registry = cls(limit)
        seen: set[str] = set()
        for row in rows:
            required = {
                "state_id",
                "owner",
                "schema_version",
                "committed",
                "working",
                "varip",
                "committed_exists",
            }
            if not isinstance(row, dict) or set(row) != required:
                raise PineRuntimeError(
                    "state slot checkpoint schema mismatch",
                    code=PL_CHECKPOINT_INVALID,
                )
            if (
                type(row["state_id"]) is not str
                or not row["state_id"]
                or type(row["owner"]) is not str
                or not row["owner"]
                or type(row["schema_version"]) is not str
                or not row["schema_version"]
                or type(row["varip"]) is not bool
                or type(row["committed_exists"]) is not bool
                or row["state_id"] in seen
            ):
                raise PineRuntimeError(
                    "state slot checkpoint types are invalid",
                    code=PL_CHECKPOINT_INVALID,
                )
            seen.add(row["state_id"])
            slot = registry.register(
                row["state_id"],
                row["owner"],
                row["schema_version"],
                varip=row["varip"],
                initial=from_portable(row["committed"]),
            )
            slot.committed = from_portable(row["committed"])
            slot.working = from_portable(row["working"])
            slot.committed_exists = row["committed_exists"]
        if registry.to_json() != rows:
            raise PineRuntimeError(
                "state slot checkpoint is not round-trip stable",
                code=PL_CHECKPOINT_INVALID,
            )
        return registry
