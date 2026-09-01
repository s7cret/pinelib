from __future__ import annotations

from pinelib.core.values import na
from pinelib.errors import PL_REFERENCE_TYPE, PineRuntimeError
from pinelib.reference.heap import ReferenceHandle, RuntimeReferenceHeap


def map_new(
    heap: RuntimeReferenceHeap, object_id: str, type_descriptor: str
) -> ReferenceHandle:
    return heap.create(object_id, "map", type_descriptor, [])


def _entries(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> list[list[object]]:
    if handle.kind != "map":
        raise PineRuntimeError("expected map handle", code=PL_REFERENCE_TYPE)
    payload = heap.read_payload(handle)
    if not isinstance(payload, list) or any(
        not isinstance(item, list) or len(item) != 2 for item in payload
    ):
        raise PineRuntimeError("invalid map heap payload", code=PL_REFERENCE_TYPE)
    return payload


def map_put(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, key: object, value: object
) -> object:
    entries = _entries(heap, handle)
    previous: object = na
    for item in entries:
        if item[0] == key:
            previous = item[1]
            item[1] = value
            heap.mutate_payload(handle, entries)
            return previous
    entries.append([key, value])
    heap.mutate_payload(handle, entries)
    return previous


def map_get(heap: RuntimeReferenceHeap, handle: ReferenceHandle, key: object) -> object:
    for item in _entries(heap, handle):
        if item[0] == key:
            return item[1]
    return na


def map_contains(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, key: object
) -> bool:
    return any(item[0] == key for item in _entries(heap, handle))


def map_remove(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, key: object
) -> object:
    entries = _entries(heap, handle)
    for index, item in enumerate(entries):
        if item[0] == key:
            value = entries.pop(index)[1]
            heap.mutate_payload(handle, entries)
            return value
    return na


def map_keys(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> tuple[object, ...]:
    return tuple(item[0] for item in _entries(heap, handle))


def map_values(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle
) -> tuple[object, ...]:
    return tuple(item[1] for item in _entries(heap, handle))


def map_size(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> int:
    return len(_entries(heap, handle))


def map_clear(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> None:
    _entries(heap, handle)
    heap.mutate_payload(handle, [])


def map_copy(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, new_object_id: str
) -> ReferenceHandle:
    return heap.copy(handle, new_object_id)


def map_put_all(
    heap: RuntimeReferenceHeap,
    target: ReferenceHandle,
    source: ReferenceHandle,
) -> None:
    for key, value in _entries(heap, source):
        map_put(heap, target, key, value)
