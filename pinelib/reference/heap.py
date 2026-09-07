from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from pinelib.errors import (
    PL_REFERENCE_BOUNDS,
    PL_REFERENCE_INVALID,
    PL_REFERENCE_TYPE,
    PL_RESOURCE_LIMIT,
    PineRuntimeError,
)
from pinelib.runtime.context import RuntimeLanguageContext
from pinelib.state.checkpoint import clone_runtime_value, from_portable, to_portable

ReferenceKind = Literal["array", "map", "matrix", "udt", "visual"]
_ARRAY_SLICE_MARKER = "$pinelib_array_slice"


@dataclass(frozen=True, slots=True)
class ReferenceHandle:
    object_id: str
    kind: ReferenceKind

    def __post_init__(self) -> None:
        if not self.object_id or self.object_id.startswith("0:"):
            raise PineRuntimeError(
                "reference object_id must be an exact non-zero identity",
                code=PL_REFERENCE_INVALID,
            )

    def __pinelib_portable__(self) -> dict[str, object]:
        return {"$pinelib_ref": {"object_id": self.object_id, "kind": self.kind}}


@dataclass(frozen=True, slots=True)
class PineEnumValue:
    enum_id: str
    member: str
    ordinal: int

    def __post_init__(self) -> None:
        if not self.enum_id or not self.member or self.ordinal < 0:
            raise PineRuntimeError("invalid enum value", code=PL_REFERENCE_TYPE)

    def __pinelib_portable__(self) -> dict[str, object]:
        return {
            "$pinelib_enum": {
                "enum_id": self.enum_id,
                "member": self.member,
                "ordinal": self.ordinal,
            }
        }


@dataclass(slots=True)
class _HeapObject:
    object_id: str
    kind: ReferenceKind
    type_descriptor: str
    committed: object
    working: object
    committed_revision: int
    working_revision: int
    committed_exists: bool
    committed_varip: bool = False
    working_varip: bool = False


class RuntimeReferenceHeap:
    """Transactional deterministic heap for Pine reference values."""

    def __init__(
        self,
        language: RuntimeLanguageContext,
        *,
        max_objects: int = 10_000,
        max_elements: int = 100_000,
    ) -> None:
        self.language = language
        self.max_objects = max_objects
        self.max_elements = max_elements
        self._objects: dict[str, _HeapObject] = {}
        self._map_iterations: dict[str, int] = {}

    def begin(self, *, preserve_varip: bool = False) -> None:
        for object_id, item in tuple(self._objects.items()):
            if preserve_varip and item.working_varip:
                continue
            if not item.committed_exists:
                del self._objects[object_id]
                continue
            item.working = clone_runtime_value(item.committed)
            item.working_revision = item.committed_revision
            item.working_varip = item.committed_varip

    def commit(self) -> None:
        for item in self._objects.values():
            item.committed = clone_runtime_value(item.working)
            item.committed_revision = item.working_revision
            item.committed_exists = True
            item.committed_varip = item.working_varip

    def rollback(self, *, preserve_varip: bool = False) -> None:
        self.begin(preserve_varip=preserve_varip)

    def retain_intrabar(self, handle: ReferenceHandle) -> None:
        """Promote a typed collection and its slice backing as one validated change.

        Persistence belongs to the object, so mutations through another alias see
        the same policy. Copying an object does not copy this binding policy.
        Ordinary objects continue to roll back. The policy is itself transactional
        and serialized, rather than inferred from whichever name currently points
        to an object or from an unverified checkpoint root.
        """
        if self.language.pine_version < 5:
            raise PineRuntimeError("varip collection bindings require Pine v5 or v6", code=PL_REFERENCE_TYPE)
        pending = [handle]
        marked: set[str] = set()
        while pending:
            current = pending.pop()
            item = self._get(current)
            if item.object_id in marked:
                continue
            parent = self._validate_intrabar_payload(item, item.working)
            marked.add(item.object_id)
            if parent is not None:
                pending.append(parent)
        # No flags are changed until every backing object has passed validation.
        for object_id in marked:
            self._objects[object_id].working_varip = True

    def _validate_intrabar_payload(self, item: _HeapObject, payload: object) -> ReferenceHandle | None:
        from pinelib.reference.persistence import validate_collection_payload

        parent = None
        if item.kind == "array":
            descriptor = self._array_slice_descriptor(payload)
            if descriptor is not None:
                parent, _, _ = descriptor
                backing = self._get(parent)
                if backing.type_descriptor != item.type_descriptor:
                    raise PineRuntimeError("varip slice/backing type mismatch", code=PL_REFERENCE_TYPE)
                # The parent is validated separately; validate the window as well.
                payload = self._materialize(ReferenceHandle(item.object_id, "array"), committed=False, active=set())
        validate_collection_payload(item.kind, item.type_descriptor, payload, self.language.pine_version)
        return parent

    def validate_intrabar_binding(self, value: object, *, committed: bool = False) -> None:
        """Cross-check a serialized varip slot against admitted object policy."""
        from pinelib.core.values import is_na
        if is_na(value):
            return
        handles = self._reference_handles(value)
        if len(handles) != 1 or not isinstance(value, dict) or set(value) != {"$pinelib_ref"}:
            raise PineRuntimeError("varip slot has an invalid collection identity", code=PL_REFERENCE_INVALID)
        item = self._get(handles[0])
        if not item.working_varip or (committed and not item.committed_varip):
            raise PineRuntimeError("varip slot points to nonpersistent collection", code=PL_REFERENCE_INVALID)

    def create(
        self,
        object_id: str,
        kind: ReferenceKind,
        type_descriptor: str,
        payload: object,
    ) -> ReferenceHandle:
        if object_id in self._objects:
            raise PineRuntimeError(
                f"reference identity already exists: {object_id}",
                code=PL_REFERENCE_INVALID,
            )
        if len(self._objects) >= self.max_objects:
            raise PineRuntimeError(
                "reference object limit exceeded", code=PL_RESOURCE_LIMIT
            )
        handle = ReferenceHandle(object_id, kind)
        encoded = self._encode_value(payload)
        self._validate_payload_size(encoded)
        self._objects[object_id] = _HeapObject(
            object_id,
            kind,
            type_descriptor,
            clone_runtime_value(encoded),
            clone_runtime_value(encoded),
            0,
            0,
            False,
        )
        return handle

    def copy(self, handle: ReferenceHandle, new_object_id: str) -> ReferenceHandle:
        source = self._get(handle)
        return self.create(
            new_object_id,
            source.kind,
            source.type_descriptor,
            self.read_payload(handle),
        )

    def read_payload(self, handle: ReferenceHandle) -> object:
        return clone_runtime_value(
            self._materialize(handle, committed=False, active=set())
        )

    def _array_window(self, handle: ReferenceHandle) -> tuple[list[object], int, int]:
        """Resolve a live slice window without materializing or decoding the array."""
        seen: set[str] = set()
        slices: list[tuple[int, int]] = []
        while True:
            if handle.kind != "array":
                raise PineRuntimeError("expected array handle", code=PL_REFERENCE_TYPE)
            if handle.object_id in seen:
                raise PineRuntimeError(
                    "array slice parent graph contains a cycle",
                    code=PL_REFERENCE_INVALID,
                )
            seen.add(handle.object_id)
            payload = self._get(handle).working
            if isinstance(payload, list):
                start, length = 0, len(payload)
                for low, high in reversed(slices):
                    if high > length:
                        raise PineRuntimeError(
                            "array slice is out of bounds of its parent",
                            code=PL_REFERENCE_BOUNDS,
                        )
                    start, length = start + low, high - low
                return payload, start, length
            descriptor = self._array_slice_descriptor(payload)
            if descriptor is None:
                raise PineRuntimeError(
                    "invalid array heap payload", code=PL_REFERENCE_TYPE
                )
            handle, low, high = descriptor
            slices.append((low, high))

    def array_length(self, handle: ReferenceHandle) -> int:
        return self._array_window(handle)[2]

    def read_array_element(self, handle: ReferenceHandle, index: int) -> object:
        payload, start, length = self._array_window(handle)
        offset = self.normalize_index(index, length)
        # Return a detached value, while reference elements keep reference identity.
        return self._decode_value(clone_runtime_value(payload[start + offset]))

    def matrix_dimensions(self, handle: ReferenceHandle) -> tuple[int, int]:
        if handle.kind != "matrix":
            raise PineRuntimeError("expected matrix handle", code=PL_REFERENCE_TYPE)
        p = self._get(handle).working
        if (not isinstance(p, dict) or set(p) != {"rows", "columns", "values"}
            or type(p["rows"]) is not int or type(p["columns"]) is not int
            or p["rows"] < 0 or p["columns"] < 0 or not isinstance(p["values"], list)
            or len(p["values"]) != p["rows"] * p["columns"]):
            raise PineRuntimeError("invalid matrix payload", code=PL_REFERENCE_TYPE)
        return p["rows"], p["columns"]

    def read_matrix_row(self, handle: ReferenceHandle, index: int) -> list[object]:
        rows, columns = self.matrix_dimensions(handle)
        index = self.normalize_index(index, rows)
        values = self._get(handle).working["values"]
        return self._decode_value(clone_runtime_value(values[index * columns:(index + 1) * columns]))

    @contextmanager
    def map_iteration(self, handle: ReferenceHandle):
        """Keep keys stable while reading each next value live, without whole-map copies.

        The guard is ephemeral, lexical, and not part of a checkpoint. It is released
        even when compiled loop control breaks or raises inside nested iterations.
        """
        if handle.kind != "map":
            raise PineRuntimeError("expected map handle", code=PL_REFERENCE_TYPE)
        item = self._get(handle)
        if not isinstance(item.working, list) or any(not isinstance(p, list) or len(p) != 2 for p in item.working):
            raise PineRuntimeError("invalid map payload", code=PL_REFERENCE_TYPE)
        oid = handle.object_id
        self._map_iterations[oid] = self._map_iterations.get(oid, 0) + 1
        def pairs():
            for index in range(len(item.working)):
                if not self._map_iterations.get(oid):
                    raise PineRuntimeError("map iterator used outside its lifetime", code=PL_REFERENCE_INVALID)
                key, value = self._decode_value(clone_runtime_value(self._get(handle).working[index]))
                yield key, value
        iterator = pairs()
        try:
            yield iterator
        finally:
            iterator.close()
            self._map_iterations[oid] -= 1
            if not self._map_iterations[oid]:
                del self._map_iterations[oid]

    def create_array_slice(
        self,
        parent: ReferenceHandle,
        start: int,
        end: int,
        new_object_id: str,
    ) -> ReferenceHandle:
        if parent.kind != "array":
            raise PineRuntimeError(
                "array slice parent must be an array", code=PL_REFERENCE_TYPE
            )
        return self.create(
            new_object_id,
            "array",
            self.type_descriptor(parent),
            {
                _ARRAY_SLICE_MARKER: {
                    "parent": parent,
                    "start": start,
                    "end": end,
                }
            },
        )

    def mutate_payload(self, handle: ReferenceHandle, payload: object) -> None:
        item = self._get(handle)
        if item.kind == "map" and self._map_iterations.get(item.object_id, 0):
            if not isinstance(payload, list) or any(not isinstance(p, list) or len(p) != 2 for p in payload):
                raise PineRuntimeError("invalid map payload during iteration", code=PL_REFERENCE_TYPE)
            old_keys = [self._decode_value(p[0]) for p in item.working]
            if [p[0] for p in payload] != old_keys:
                raise PineRuntimeError("map keys cannot change during direct iteration", code=PL_REFERENCE_INVALID)
        if item.working_varip:
            from pinelib.reference.persistence import validate_collection_payload
            validate_collection_payload(item.kind, item.type_descriptor, payload, self.language.pine_version)
        descriptor = self._array_slice_descriptor(item.working)
        if descriptor is not None:
            if not isinstance(payload, list):
                raise PineRuntimeError(
                    "array slice payload must be a list", code=PL_REFERENCE_TYPE
                )
            parent, start, end = descriptor
            current = self._materialize(handle, committed=False, active=set())
            assert isinstance(current, list)
            parent_values = self._materialize(parent, committed=False, active=set())
            if not isinstance(parent_values, list):
                raise PineRuntimeError(
                    "array slice parent payload must be a list",
                    code=PL_REFERENCE_TYPE,
                )
            parent_values[start:end] = payload
            self.mutate_payload(parent, parent_values)
            encoded_descriptor = self._encode_value(
                {
                    _ARRAY_SLICE_MARKER: {
                        "parent": parent,
                        "start": start,
                        "end": start + len(payload),
                    }
                }
            )
            self._validate_payload_size(encoded_descriptor)
            item.working = clone_runtime_value(encoded_descriptor)
            item.working_revision += 1
            return
        encoded = self._encode_value(payload)
        self._validate_payload_size(encoded)
        item.working = clone_runtime_value(encoded)
        item.working_revision += 1

    def revision(self, handle: ReferenceHandle) -> int:
        return self._get(handle).working_revision

    def type_descriptor(self, handle: ReferenceHandle) -> str:
        return self._get(handle).type_descriptor

    def _get(self, handle: ReferenceHandle) -> _HeapObject:
        try:
            item = self._objects[handle.object_id]
        except KeyError as error:
            raise PineRuntimeError(
                f"unknown reference handle: {handle.object_id}",
                code=PL_REFERENCE_INVALID,
            ) from error
        if item.kind != handle.kind:
            raise PineRuntimeError(
                "reference handle kind mismatch", code=PL_REFERENCE_TYPE
            )
        return item

    def normalize_index(
        self, index: int, length: int, *, allow_end: bool = False
    ) -> int:
        if type(index) is not int:
            raise PineRuntimeError(
                "collection index must be int", code=PL_REFERENCE_TYPE
            )
        normalized = index
        if normalized < 0:
            if self.language.pine_version < 6:
                raise PineRuntimeError(
                    "negative collection indexes are unavailable for this Pine version",
                    code=PL_REFERENCE_BOUNDS,
                )
            normalized += length
        upper = length if allow_end else length - 1
        if normalized < 0 or normalized > upper:
            raise PineRuntimeError(
                f"collection index {index} is out of bounds for size {length}",
                code=PL_REFERENCE_BOUNDS,
            )
        return normalized

    def _validate_payload_size(self, payload: object) -> None:
        count = self._element_count(payload)
        if count > self.max_elements:
            raise PineRuntimeError(
                "collection element limit exceeded", code=PL_RESOURCE_LIMIT
            )

    def _element_count(self, value: object) -> int:
        if isinstance(value, list):
            return len(value) + sum(self._element_count(item) for item in value)
        if isinstance(value, dict):
            return len(value) + sum(
                self._element_count(item) for item in value.values()
            )
        return 0

    def _encode_value(self, value: object) -> object:
        if isinstance(value, ReferenceHandle):
            return value.__pinelib_portable__()
        if isinstance(value, PineEnumValue):
            return value.__pinelib_portable__()
        if isinstance(value, tuple):
            return [self._encode_value(item) for item in value]
        if isinstance(value, list):
            return [self._encode_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._encode_value(item) for key, item in value.items()}
        return value

    def _decode_value(self, value: object) -> object:
        if isinstance(value, dict):
            ref = value.get("$pinelib_ref")
            if isinstance(ref, dict):
                return ReferenceHandle(str(ref["object_id"]), str(ref["kind"]))  # type: ignore[arg-type]
            enum = value.get("$pinelib_enum")
            if isinstance(enum, dict):
                return PineEnumValue(
                    str(enum["enum_id"]), str(enum["member"]), int(enum["ordinal"])
                )
            return {str(key): self._decode_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._decode_value(item) for item in value]
        return value

    def _array_slice_descriptor(
        self, payload: object
    ) -> tuple[ReferenceHandle, int, int] | None:
        decoded = self._decode_value(payload)
        if not isinstance(decoded, dict) or _ARRAY_SLICE_MARKER not in decoded:
            return None
        if set(decoded) != {_ARRAY_SLICE_MARKER}:
            raise PineRuntimeError(
                "array slice marker schema is invalid", code=PL_REFERENCE_INVALID
            )
        marker = decoded[_ARRAY_SLICE_MARKER]
        if not isinstance(marker, dict) or set(marker) != {"parent", "start", "end"}:
            raise PineRuntimeError(
                "array slice descriptor is invalid", code=PL_REFERENCE_INVALID
            )
        parent = marker["parent"]
        start = marker["start"]
        end = marker["end"]
        if (
            not isinstance(parent, ReferenceHandle)
            or parent.kind != "array"
            or type(start) is not int
            or type(end) is not int
            or start < 0
            or end < start
        ):
            raise PineRuntimeError(
                "array slice descriptor identity is invalid",
                code=PL_REFERENCE_INVALID,
            )
        return parent, start, end

    def _materialize(
        self,
        handle: ReferenceHandle,
        *,
        committed: bool,
        active: set[str],
    ) -> object:
        item = self._get(handle)
        payload = item.committed if committed else item.working
        descriptor = self._array_slice_descriptor(payload)
        if descriptor is None:
            return self._decode_value(clone_runtime_value(payload))
        if handle.object_id in active:
            raise PineRuntimeError(
                "array slice parent graph contains a cycle",
                code=PL_REFERENCE_INVALID,
            )
        active.add(handle.object_id)
        try:
            parent, start, end = descriptor
            parent_values = self._materialize(
                parent, committed=committed, active=active
            )
            if not isinstance(parent_values, list):
                raise PineRuntimeError(
                    "array slice parent payload must be a list",
                    code=PL_REFERENCE_TYPE,
                )
            if end > len(parent_values):
                raise PineRuntimeError(
                    "array slice is out of bounds of its parent",
                    code=PL_REFERENCE_BOUNDS,
                    details={
                        "parent_size": len(parent_values),
                        "start": start,
                        "end": end,
                    },
                )
            return parent_values[start:end]
        finally:
            active.remove(handle.object_id)

    def _reference_handles(self, value: object) -> list[ReferenceHandle]:
        handles: list[ReferenceHandle] = []
        if isinstance(value, dict):
            if "$pinelib_ref" in value:
                if set(value) != {"$pinelib_ref"}:
                    raise PineRuntimeError(
                        "reference marker schema is invalid", code=PL_REFERENCE_INVALID
                    )
                marker = value["$pinelib_ref"]
                if (
                    not isinstance(marker, dict)
                    or set(marker) != {"object_id", "kind"}
                    or type(marker["object_id"]) is not str
                    or type(marker["kind"]) is not str
                ):
                    raise PineRuntimeError(
                        "reference marker identity is invalid",
                        code=PL_REFERENCE_INVALID,
                    )
                handles.append(
                    ReferenceHandle(marker["object_id"], marker["kind"])  # type: ignore[arg-type]
                )
                return handles
            for item in value.values():
                handles.extend(self._reference_handles(item))
        elif isinstance(value, list):
            for item in value:
                handles.extend(self._reference_handles(item))
        return handles

    def _validate_closed_graph(self) -> None:
        for item in self._objects.values():
            for payload in (item.committed, item.working):
                for handle in self._reference_handles(payload):
                    self._get(handle)
            if item.kind == "array" and self._array_slice_descriptor(item.working):
                handle = ReferenceHandle(item.object_id, "array")
                self._materialize(handle, committed=True, active=set())
                self._materialize(handle, committed=False, active=set())

    def to_json(self) -> dict[str, object]:
        return {
            "objects": [
                {
                    "object_id": item.object_id,
                    "kind": item.kind,
                    "type_descriptor": item.type_descriptor,
                    "committed": to_portable(item.committed),
                    "working": to_portable(item.working),
                    "committed_revision": item.committed_revision,
                    "working_revision": item.working_revision,
                    "committed_exists": item.committed_exists,
                    **({"intrabar_persistence": {"committed": item.committed_varip, "working": item.working_varip}}
                       if item.committed_varip or item.working_varip else {}),
                }
                for item in sorted(
                    self._objects.values(), key=lambda row: row.object_id
                )
            ]
        }

    @classmethod
    def from_json(
        cls,
        data: dict[str, object],
        language: RuntimeLanguageContext,
        *,
        max_objects: int,
        max_elements: int,
    ) -> RuntimeReferenceHeap:
        heap = cls(language, max_objects=max_objects, max_elements=max_elements)
        rows = data.get("objects")
        if not isinstance(rows, list):
            raise PineRuntimeError("reference heap objects must be a list")
        for raw in rows:
            if not isinstance(raw, dict) or set(raw) - {"intrabar_persistence"} != {
                "object_id",
                "kind",
                "type_descriptor",
                "committed",
                "working",
                "committed_revision",
                "working_revision",
                "committed_exists",
            }:
                raise PineRuntimeError("reference heap row must be an object")
            committed_revision = raw["committed_revision"]
            working_revision = raw["working_revision"]
            committed_exists = raw["committed_exists"]
            if (
                type(committed_revision) is not int
                or committed_revision < 0
                or type(working_revision) is not int
                or working_revision < 0
                or type(committed_exists) is not bool
            ):
                raise PineRuntimeError("reference heap revision state is invalid")
            object_id = str(raw["object_id"])
            kind = str(raw["kind"])
            handle = heap.create(
                object_id,
                kind,  # type: ignore[arg-type]
                str(raw["type_descriptor"]),
                heap._decode_value(from_portable(raw["committed"])),
            )
            item = heap._get(handle)
            item.committed = from_portable(raw["committed"])
            item.working = from_portable(raw["working"])
            item.committed_revision = committed_revision
            item.working_revision = working_revision
            item.committed_exists = committed_exists
            persistence = raw.get("intrabar_persistence")
            if "intrabar_persistence" in raw:
                if (not isinstance(persistence, dict) or set(persistence) != {"committed", "working"}
                    or any(type(v) is not bool for v in persistence.values())
                    or not persistence["working"]
                    or (persistence["committed"] and not committed_exists)):
                    raise PineRuntimeError("invalid intrabar persistence checkpoint")
                item.committed_varip = persistence["committed"]
                item.working_varip = persistence["working"]
        heap._validate_closed_graph()
        for item in heap._objects.values():
            if item.working_varip:
                if language.pine_version < 5:
                    raise PineRuntimeError("varip collection checkpoint requires Pine v5/v6")
                parent = heap._validate_intrabar_payload(item, item.working)
                if parent is not None and not heap._get(parent).working_varip:
                    raise PineRuntimeError("varip slice checkpoint lacks persistent backing")
                if item.committed_varip:
                    descriptor = heap._array_slice_descriptor(item.committed) if item.kind == "array" else None
                    if descriptor is not None and not heap._get(descriptor[0]).committed_varip:
                        raise PineRuntimeError("committed varip slice lacks committed backing policy")
                    from pinelib.reference.persistence import (
                        validate_collection_payload,
                    )
                    committed = heap._materialize(ReferenceHandle(item.object_id, item.kind), committed=True, active=set())
                    validate_collection_payload(item.kind, item.type_descriptor, committed, language.pine_version)
        return heap
