from __future__ import annotations

from pinelib.core.values import na
from pinelib.reference import (
    PineEnumValue,
    ReferenceHandle,
    array_binary_search,
    array_binary_search_leftmost,
    array_binary_search_rightmost,
    array_clear,
    array_concat,
    array_copy,
    array_fill,
    array_first,
    array_get,
    array_includes,
    array_indexof,
    array_insert,
    array_last,
    array_lastindexof,
    array_new,
    array_pop,
    array_push,
    array_remove,
    array_reverse,
    array_set,
    array_shift,
    array_size,
    array_slice,
    array_sort,
    array_unshift,
    array_values,
    enum_value,
    map_clear,
    map_contains,
    map_copy,
    map_get,
    map_keys,
    map_new,
    map_put,
    map_put_all,
    map_remove,
    map_size,
    map_values,
    matrix_columns,
    matrix_copy,
    matrix_get,
    matrix_new,
    matrix_rows,
    matrix_set,
    udt_copy,
    udt_get,
    udt_new,
    udt_set,
)
from pinelib.runtime.session import RuntimeTransaction


def array_new_v1(
    tx: RuntimeTransaction,
    object_id: str,
    type_descriptor: str,
    size: int = 0,
    initial: object = na,
) -> ReferenceHandle:
    return array_new(tx.references, object_id, type_descriptor, size, initial)


def array_size_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> int:
    return array_size(tx.references, handle)


def array_get_v1(tx: RuntimeTransaction, handle: ReferenceHandle, index: int) -> object:
    return array_get(tx.references, handle, index)


def array_set_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, index: int, value: object
) -> None:
    array_set(tx.references, handle, index, value)


def array_push_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, value: object
) -> None:
    array_push(tx.references, handle, value)


def array_pop_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> object:
    return array_pop(tx.references, handle)


def array_shift_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> object:
    return array_shift(tx.references, handle)


def array_unshift_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, value: object
) -> None:
    array_unshift(tx.references, handle, value)


def array_insert_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, index: int, value: object
) -> None:
    array_insert(tx.references, handle, index, value)


def array_remove_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, index: int
) -> object:
    return array_remove(tx.references, handle, index)


def array_clear_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> None:
    array_clear(tx.references, handle)


def array_copy_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, new_object_id: str
) -> ReferenceHandle:
    return array_copy(tx.references, handle, new_object_id)


def array_slice_v1(
    tx: RuntimeTransaction,
    handle: ReferenceHandle,
    start: int,
    end: int,
    new_object_id: str,
) -> ReferenceHandle:
    return array_slice(tx.references, handle, start, end, new_object_id)


def array_sort_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, descending: bool = False
) -> None:
    array_sort(tx.references, handle, descending=descending)


def array_indexof_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, value: object
) -> int:
    return array_indexof(tx.references, handle, value)


def array_lastindexof_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, value: object
) -> int:
    return array_lastindexof(tx.references, handle, value)


def array_binary_search_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, value: object
) -> int:
    return array_binary_search(tx.references, handle, value)


def array_values_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle
) -> tuple[object, ...]:
    return array_values(tx.references, handle)


def array_first_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> object:
    return array_first(tx.references, handle)


def array_last_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> object:
    return array_last(tx.references, handle)


def array_includes_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, value: object
) -> bool:
    return array_includes(tx.references, handle, value)


def array_reverse_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> None:
    array_reverse(tx.references, handle)


def array_fill_v1(
    tx: RuntimeTransaction,
    handle: ReferenceHandle,
    value: object,
    start: int = 0,
    end: int | None = None,
) -> None:
    array_fill(tx.references, handle, value, start, end)


def array_concat_v1(
    tx: RuntimeTransaction,
    id1: ReferenceHandle,
    id2: ReferenceHandle,
) -> None:
    array_concat(tx.references, id1, id2)


def array_binary_search_leftmost_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, value: object
) -> int:
    return array_binary_search_leftmost(tx.references, handle, value)


def array_binary_search_rightmost_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, value: object
) -> int:
    return array_binary_search_rightmost(tx.references, handle, value)


def map_new_v1(
    tx: RuntimeTransaction, object_id: str, type_descriptor: str
) -> ReferenceHandle:
    return map_new(tx.references, object_id, type_descriptor)


def map_put_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, key: object, value: object
) -> object:
    return map_put(tx.references, handle, key, value)


def map_get_v1(tx: RuntimeTransaction, handle: ReferenceHandle, key: object) -> object:
    return map_get(tx.references, handle, key)


def map_contains_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, key: object
) -> bool:
    return map_contains(tx.references, handle, key)


def map_remove_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, key: object
) -> object:
    return map_remove(tx.references, handle, key)


def map_keys_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> tuple[object, ...]:
    return map_keys(tx.references, handle)


def map_values_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle
) -> tuple[object, ...]:
    return map_values(tx.references, handle)


def map_size_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> int:
    return map_size(tx.references, handle)


def map_clear_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> None:
    map_clear(tx.references, handle)


def map_copy_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, new_object_id: str
) -> ReferenceHandle:
    return map_copy(tx.references, handle, new_object_id)


def map_put_all_v1(
    tx: RuntimeTransaction,
    handle: ReferenceHandle,
    from_handle: ReferenceHandle,
) -> None:
    map_put_all(tx.references, handle, from_handle)


def matrix_new_v1(
    tx: RuntimeTransaction,
    object_id: str,
    type_descriptor: str,
    rows: int,
    columns: int,
    initial: object,
) -> ReferenceHandle:
    return matrix_new(tx.references, object_id, type_descriptor, rows, columns, initial)


def matrix_rows_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> int:
    return matrix_rows(tx.references, handle)


def matrix_columns_v1(tx: RuntimeTransaction, handle: ReferenceHandle) -> int:
    return matrix_columns(tx.references, handle)


def matrix_get_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, row: int, column: int
) -> object:
    return matrix_get(tx.references, handle, row, column)


def matrix_set_v1(
    tx: RuntimeTransaction,
    handle: ReferenceHandle,
    row: int,
    column: int,
    value: object,
) -> None:
    matrix_set(tx.references, handle, row, column, value)


def matrix_copy_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, new_object_id: str
) -> ReferenceHandle:
    return matrix_copy(tx.references, handle, new_object_id)


def udt_new_v1(
    tx: RuntimeTransaction,
    object_id: str,
    type_descriptor: str,
    fields: dict[str, object],
) -> ReferenceHandle:
    return udt_new(tx.references, object_id, type_descriptor, fields)


def udt_get_v1(tx: RuntimeTransaction, handle: ReferenceHandle, field: str) -> object:
    return udt_get(tx.references, handle, field)


def udt_set_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, field: str, value: object
) -> None:
    udt_set(tx.references, handle, field, value)


def udt_copy_v1(
    tx: RuntimeTransaction, handle: ReferenceHandle, new_object_id: str
) -> ReferenceHandle:
    return udt_copy(tx.references, handle, new_object_id)


def enum_value_v1(enum_id: str, member: str, ordinal: int) -> PineEnumValue:
    return enum_value(enum_id, member, ordinal)
