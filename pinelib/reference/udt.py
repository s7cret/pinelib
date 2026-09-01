from __future__ import annotations

from pinelib.errors import PL_REFERENCE_TYPE, PineRuntimeError
from pinelib.reference.heap import PineEnumValue, ReferenceHandle, RuntimeReferenceHeap


def udt_new(
    heap: RuntimeReferenceHeap,
    object_id: str,
    type_descriptor: str,
    fields: dict[str, object],
) -> ReferenceHandle:
    if not all(isinstance(key, str) and key for key in fields):
        raise PineRuntimeError(
            "UDT field names must be non-empty strings", code=PL_REFERENCE_TYPE
        )
    return heap.create(object_id, "udt", type_descriptor, dict(fields))


def _fields(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> dict[str, object]:
    if handle.kind != "udt":
        raise PineRuntimeError("expected UDT handle", code=PL_REFERENCE_TYPE)
    payload = heap.read_payload(handle)
    if not isinstance(payload, dict):
        raise PineRuntimeError("invalid UDT heap payload", code=PL_REFERENCE_TYPE)
    return payload


def udt_get(heap: RuntimeReferenceHeap, handle: ReferenceHandle, field: str) -> object:
    fields = _fields(heap, handle)
    if field not in fields:
        raise PineRuntimeError(f"unknown UDT field: {field}", code=PL_REFERENCE_TYPE)
    return fields[field]


def udt_set(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, field: str, value: object
) -> None:
    fields = _fields(heap, handle)
    if field not in fields:
        raise PineRuntimeError(f"unknown UDT field: {field}", code=PL_REFERENCE_TYPE)
    fields[field] = value
    heap.mutate_payload(handle, fields)


def udt_copy(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, new_object_id: str
) -> ReferenceHandle:
    return heap.copy(handle, new_object_id)


def enum_value(enum_id: str, member: str, ordinal: int) -> PineEnumValue:
    return PineEnumValue(enum_id, member, ordinal)
