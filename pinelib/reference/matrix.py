from __future__ import annotations

from typing import cast

from pinelib.errors import PL_REFERENCE_TYPE, PineRuntimeError
from pinelib.reference.heap import ReferenceHandle, RuntimeReferenceHeap


def matrix_new(
    heap: RuntimeReferenceHeap,
    object_id: str,
    type_descriptor: str,
    rows: int,
    columns: int,
    initial: object,
) -> ReferenceHandle:
    if type(rows) is not int or type(columns) is not int or rows < 0 or columns < 0:
        raise PineRuntimeError(
            "matrix dimensions must be nonnegative ints", code=PL_REFERENCE_TYPE
        )
    return heap.create(
        object_id,
        "matrix",
        type_descriptor,
        {"rows": rows, "columns": columns, "values": [initial] * (rows * columns)},
    )


def _payload(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> dict[str, object]:
    if handle.kind != "matrix":
        raise PineRuntimeError("expected matrix handle", code=PL_REFERENCE_TYPE)
    payload = heap.read_payload(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("values"), list):
        raise PineRuntimeError("invalid matrix heap payload", code=PL_REFERENCE_TYPE)
    rows = payload.get("rows")
    columns = payload.get("columns")
    values = payload["values"]
    if type(rows) is not int or type(columns) is not int:
        raise PineRuntimeError("invalid matrix dimensions", code=PL_REFERENCE_TYPE)
    if rows < 0 or columns < 0 or len(values) != rows * columns:
        raise PineRuntimeError("invalid matrix heap payload", code=PL_REFERENCE_TYPE)
    return payload


def matrix_rows(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> int:
    return cast(int, _payload(heap, handle)["rows"])


def matrix_columns(heap: RuntimeReferenceHeap, handle: ReferenceHandle) -> int:
    return cast(int, _payload(heap, handle)["columns"])


def _index(
    heap: RuntimeReferenceHeap, payload: dict[str, object], row: int, column: int
) -> int:
    rows = cast(int, payload["rows"])
    columns = cast(int, payload["columns"])
    normalized_row = heap.normalize_index(row, rows)
    normalized_column = heap.normalize_index(column, columns)
    return normalized_row * columns + normalized_column


def matrix_get(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, row: int, column: int
) -> object:
    payload = _payload(heap, handle)
    values = payload["values"]
    assert isinstance(values, list)
    return values[_index(heap, payload, row, column)]


def matrix_set(
    heap: RuntimeReferenceHeap,
    handle: ReferenceHandle,
    row: int,
    column: int,
    value: object,
) -> None:
    payload = _payload(heap, handle)
    values = payload["values"]
    assert isinstance(values, list)
    values[_index(heap, payload, row, column)] = value
    heap.mutate_payload(handle, payload)


def matrix_copy(
    heap: RuntimeReferenceHeap, handle: ReferenceHandle, new_object_id: str
) -> ReferenceHandle:
    return heap.copy(handle, new_object_id)
