from __future__ import annotations

from operator import lt
from typing import Any, cast

from pinelib.core.values import na
from pinelib.errors import PL_REFERENCE_BOUNDS, PL_REFERENCE_TYPE, PineRuntimeError
from pinelib.reference.heap import ReferenceHandle, RuntimeReferenceHeap


def array_new(
    heap: RuntimeReferenceHeap,
    object_id: str,
    type_descriptor: str,
    size: int = 0,
    initial: object = na,
) -> ReferenceHandle:
    if type(size) is not int or size < 0:
        raise PineRuntimeError(
            "array size must be a nonnegative int", code=PL_REFERENCE_TYPE
        )
    return heap.create(
        object_id, "array", type_descriptor, [initial for _ in range(size)]
    )


def _values(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> list[object]:
    if handle.kind != "array":
        raise PineRuntimeError("expected array handle", code=PL_REFERENCE_TYPE)
    payload = heap.read_payload(handle)
    if not isinstance(payload, list):
        raise PineRuntimeError("invalid array heap payload", code=PL_REFERENCE_TYPE)
    return payload


def array_size(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> int:
    return len(_values(heap, handle))


def array_get(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, index: int
) -> object:
    values = _values(heap, handle)
    return values[heap.normalize_index(index, len(values))]


def array_set(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, index: int, value: object
) -> None:
    values = _values(heap, handle)
    values[heap.normalize_index(index, len(values))] = value
    heap.mutate_payload(handle, values)


def array_push(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, value: object
) -> None:
    values = _values(heap, handle)
    values.append(value)
    heap.mutate_payload(handle, values)


def array_pop(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> object:
    values = _values(heap, handle)
    if not values:
        raise PineRuntimeError(
            "cannot pop from an empty array", code=PL_REFERENCE_BOUNDS
        )
    value = values.pop()
    heap.mutate_payload(handle, values)
    return value


def array_shift(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> object:
    values = _values(heap, handle)
    if not values:
        raise PineRuntimeError("cannot shift an empty array", code=PL_REFERENCE_BOUNDS)
    value = values.pop(0)
    heap.mutate_payload(handle, values)
    return value


def array_unshift(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, value: object
) -> None:
    values = _values(heap, handle)
    values.insert(0, value)
    heap.mutate_payload(handle, values)


def array_insert(
    heap: RuntimeReferenceHeap,
    handle: ReferenceHandle,
    index: int,
    value: object,
) -> None:
    values = _values(heap, handle)
    normalized = heap.normalize_index(index, len(values), allow_end=True)
    values.insert(normalized, value)
    heap.mutate_payload(handle, values)


def array_remove(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, index: int
) -> object:
    values = _values(heap, handle)
    value = values.pop(heap.normalize_index(index, len(values)))
    heap.mutate_payload(handle, values)
    return value


def array_clear(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> None:
    _values(heap, handle)
    heap.mutate_payload(handle, [])


def array_copy(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, new_object_id: str
) -> ReferenceHandle:
    return heap.copy(handle, new_object_id)


def array_slice(
    heap: RuntimeReferenceHeap,
    handle: ReferenceHandle,
    start: int,
    end: int,
    new_object_id: str,
) -> ReferenceHandle:
    values = _values(heap, handle)
    if type(start) is not int or type(end) is not int:
        raise PineRuntimeError("slice bounds must be ints", code=PL_REFERENCE_TYPE)
    normalized_start = (
        start + len(values) if start < 0 and heap.language.pine_version >= 6 else start
    )
    normalized_end = (
        end + len(values) if end < 0 and heap.language.pine_version >= 6 else end
    )
    if (
        normalized_start < 0
        or normalized_end < normalized_start
        or normalized_end > len(values)
    ):
        raise PineRuntimeError("invalid array slice bounds", code=PL_REFERENCE_BOUNDS)
    return heap.create_array_slice(
        handle,
        normalized_start,
        normalized_end,
        new_object_id,
    )


def array_sort(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, *, descending: bool = False
) -> None:
    values = _values(heap, handle)
    try:
        values.sort(reverse=descending)
    except TypeError as error:
        raise PineRuntimeError(
            "array values are not mutually sortable", code=PL_REFERENCE_TYPE
        ) from error
    heap.mutate_payload(handle, values)


def array_indexof(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, value: object
) -> int:
    values = _values(heap, handle)
    try:
        return values.index(value)
    except ValueError:
        return -1


def array_lastindexof(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, value: object
) -> int:
    values = _values(heap, handle)
    for index in range(len(values) - 1, -1, -1):
        if values[index] == value:
            return index
    return -1


def array_binary_search(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, value: object
) -> int:
    values = _values(heap, handle)
    low, high = 0, len(values)
    try:
        while low < high:
            middle = (low + high) // 2
            if lt(cast(Any, values[middle]), cast(Any, value)):
                low = middle + 1
            else:
                high = middle
    except TypeError as error:
        raise PineRuntimeError(
            "array values are not searchable", code=PL_REFERENCE_TYPE
        ) from error
    return low if low < len(values) and values[low] == value else -1


def array_values(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle
) -> tuple[object, ...]:
    return tuple(_values(heap, handle))


def array_first(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> object:
    values = _values(heap, handle)
    if not values:
        raise PineRuntimeError(
            "cannot read first from an empty array", code=PL_REFERENCE_BOUNDS
        )
    return values[0]


def array_last(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> object:
    values = _values(heap, handle)
    if not values:
        raise PineRuntimeError(
            "cannot read last from an empty array", code=PL_REFERENCE_BOUNDS
        )
    return values[-1]


def array_includes(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, value: object
) -> bool:
    return value in _values(heap, handle)


def array_reverse(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> None:
    values = _values(heap, handle)
    values.reverse()
    heap.mutate_payload(handle, values)


def array_fill(
    heap: RuntimeReferenceHeap,
    handle: ReferenceHandle,
    value: object,
    start: int = 0,
    end: int | None = None,
) -> None:
    values = _values(heap, handle)
    if type(start) is not int or (end is not None and type(end) is not int):
        raise PineRuntimeError("array fill bounds must be ints", code=PL_REFERENCE_TYPE)
    stop = len(values) if end is None else end
    if start < 0 or stop < start or stop > len(values):
        raise PineRuntimeError("invalid array fill bounds", code=PL_REFERENCE_BOUNDS)
    values[start:stop] = [value] * (stop - start)
    heap.mutate_payload(handle, values)


def array_concat(
    heap: RuntimeReferenceHeap,
    target: ReferenceHandle,
    source: ReferenceHandle,
) -> None:
    values = _values(heap, target)
    values.extend(_values(heap, source))
    heap.mutate_payload(target, values)


def array_binary_search_leftmost(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, value: object
) -> int:
    values = _values(heap, handle)
    low, high = 0, len(values)
    try:
        while low < high:
            middle = (low + high) // 2
            if lt(cast(Any, values[middle]), cast(Any, value)):
                low = middle + 1
            else:
                high = middle
    except TypeError as error:
        raise PineRuntimeError(
            "array values are not searchable", code=PL_REFERENCE_TYPE
        ) from error
    return low if low < len(values) and values[low] == value else -1


def array_binary_search_rightmost(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, value: object
) -> int:
    values = _values(heap, handle)
    low, high = 0, len(values)
    try:
        while low < high:
            middle = (low + high) // 2
            if not lt(cast(Any, value), cast(Any, values[middle])):
                low = middle + 1
            else:
                high = middle
    except TypeError as error:
        raise PineRuntimeError(
            "array values are not searchable", code=PL_REFERENCE_TYPE
        ) from error
    index = low - 1
    return index if index >= 0 and values[index] == value else -1
