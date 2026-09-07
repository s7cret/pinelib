"""Typed row/pair iteration and detached map projections through the real heap."""

from dataclasses import replace

import pytest

from pinelib.abi import reference as abi
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_set
from pinelib.reference.map import map_clear, map_get, map_new, map_put, map_remove
from pinelib.reference.matrix import matrix_get, matrix_new, matrix_set
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from tests.test_language_scopes_once import begin, session


def mapping(tx):
    h = map_new(tx.references, tx.reference_id_v1("map"), "string,int")
    map_put(tx.references, h, "b", 2)
    map_put(tx.references, h, "a", 1)
    return h


@pytest.mark.parametrize("version", [5, 6])
def test_map_pairs_have_insertion_order_and_live_updated_values(version):
    tx = begin(session(version), 0)
    h = mapping(tx)
    with tx.iter_map_v1(h) as pairs:
        assert next(pairs) == ("b", 2)
        map_put(tx.references, h, "a", 7)
        assert next(pairs) == ("a", 7)
        with pytest.raises(StopIteration):
            next(pairs)
    tx.abort()


@pytest.mark.parametrize("action", ["put", "remove", "clear", "replace_keys"])
def test_map_structure_cannot_change_in_direct_iteration_even_via_alias(action):
    tx = begin(session(), 0)
    h = mapping(tx)
    with tx.iter_map_v1(h) as pairs:
        next(pairs)
        saved = tx.references.to_json()
        with pytest.raises(PineRuntimeError, match="keys cannot change"):
            if action == "put":
                map_put(tx.references, h, "c", 3)
            elif action == "remove":
                map_remove(tx.references, h, "a")
            elif action == "clear":
                map_clear(tx.references, h)
            else:
                tx.references.mutate_payload(h, [["b", 2], ["c", 3]])
        assert tx.references.to_json() == saved
    map_put(tx.references, h, "c", 3)
    assert map_get(tx.references, h, "c") == 3
    tx.abort()


def test_nested_map_iteration_releases_only_its_own_guard_on_break_or_error():
    tx = begin(session(), 0)
    h = mapping(tx)
    with tx.iter_map_v1(h) as outer:
        next(outer)
        with pytest.raises(RuntimeError), tx.iter_map_v1(h) as inner:
            next(inner)
            raise RuntimeError("user callback")
        with pytest.raises(PineRuntimeError):
            map_remove(tx.references, h, "a")
    map_remove(tx.references, h, "a")
    tx.abort()


@pytest.mark.parametrize("kind", ["keys", "values"])
def test_map_projection_is_new_array_and_does_not_modify_source(kind):
    tx = begin(session(), 0)
    h = mapping(tx)
    f = abi.map_keys_v1 if kind == "keys" else abi.map_values_v1
    dtype = "string" if kind == "keys" else "int"
    a = f(tx, h, tx.reference_id_v1("projection"), dtype)
    b = f(tx, h, tx.reference_id_v1("projection"), dtype)
    assert a != b and a.kind == "array"
    expected = ["b", "a"] if kind == "keys" else [2, 1]
    assert tx.references.read_payload(a) == expected
    array_set(tx.references, a, 0, "changed" if kind == "keys" else 90)
    assert tx.references.read_payload(b) == expected
    assert map_get(tx.references, h, "b") == 2
    map_put(tx.references, h, "b", 4)
    assert tx.references.read_payload(b) == expected
    tx.abort()


@pytest.mark.parametrize("indexed", [False, True])
@pytest.mark.parametrize("version", [5, 6])
def test_matrix_iterator_reads_rows_not_elements_and_updates_future_rows(
    version, indexed
):
    tx = begin(session(version), 0)
    h = matrix_new(tx.references, "matrix", "int", 2, 2, 1)
    iterator = tx.iter_matrix_v1(h, "rows", indexed=indexed)
    first = next(iterator)
    if indexed:
        assert first[0] == 0
        first = first[1]
    assert tx.references.read_payload(first) == [1, 1]
    array_set(tx.references, first, 0, 99)
    assert matrix_get(tx.references, h, 0, 0) == 1
    matrix_set(tx.references, h, 1, 1, 7)
    second = next(iterator)
    if indexed:
        assert second[0] == 1
        second = second[1]
    assert first != second and tx.references.read_payload(second) == [1, 7]
    with pytest.raises(StopIteration):
        next(iterator)
    tx.abort()


def test_matrix_live_size_and_old_rows_not_overwritten_by_later_iteration():
    tx = begin(session(), 0)
    h = matrix_new(tx.references, "m", "int", 1, 1, 1)
    it = tx.iter_matrix_v1(h, "written")
    first = next(it)
    tx.references.mutate_payload(h, {"rows": 2, "columns": 1, "values": [5, 7]})
    second = next(it)
    assert tx.references.read_payload(first) == [1]
    assert tx.references.read_payload(second) == [7]
    with pytest.raises(StopIteration):
        next(it)
    tx.abort()


@pytest.mark.parametrize("kind", ["map", "matrix"])
def test_empty_collection_iteration(kind):
    tx = begin(session(), 0)
    if kind == "map":
        h = map_new(tx.references, "empty", "string,int")
        with tx.iter_map_v1(h) as it:
            assert list(it) == []
    else:
        h = matrix_new(tx.references, "empty", "int", 0, 0, 0)
        assert list(tx.iter_matrix_v1(h, "empty")) == []
    tx.abort()


def test_row_allocation_keeps_runtime_object_limit():
    policies = RuntimePolicies(
        resource=replace(ResourcePolicy(), max_reference_objects=2)
    )
    tx = begin(session(policies=policies), 0)
    h = matrix_new(tx.references, "m", "int", 2, 1, 0)
    it = tx.iter_matrix_v1(h, "rows")
    next(it)
    with pytest.raises(PineRuntimeError, match="limit"):
        next(it)
    tx.abort()
