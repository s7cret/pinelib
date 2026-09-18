"""Stage 2.4: typed collection identity and transactional reference graphs."""
from copy import deepcopy

import pytest

from pinelib.core.values import na
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import (
    array_concat, array_copy, array_get, array_new, array_push, array_set, array_size,
)
from pinelib.reference.heap import ReferenceHandle, RuntimeReferenceHeap
from pinelib.reference.map import (
    map_copy, map_get, map_new, map_put, map_put_all, map_size,
)
from pinelib.reference.matrix import matrix_copy, matrix_get, matrix_new, matrix_set
from tests.stage3_helpers import language


def heap(version=6):
    return RuntimeReferenceHeap(language(version), max_objects=100, max_elements=1000)


def label(h, object_id, text):
    return h.create(object_id, "visual", "label", {"text": text})


@pytest.mark.parametrize(
    "factory",
    [
        lambda h: array_new(h, "bad", "int", 1, "x"),
        lambda h: matrix_new(h, "bad", "int", 1, 1, "x"),
    ],
)
def test_creation_rejects_wrong_ordinary_collection_element_type(factory):
    with pytest.raises(PineRuntimeError, match="declared type"):
        factory(heap())


def test_ordinary_array_map_matrix_mutations_are_typed_and_atomic():
    h = heap()
    a = array_new(h, "a", "int", 1, 1)
    m = map_new(h, "m", "string,int")
    map_put(h, m, "ok", 2)
    x = matrix_new(h, "x", "int", 1, 1, 3)

    before_a, before_m, before_x = h.read_payload(a), h.read_payload(m), h.read_payload(x)
    with pytest.raises(PineRuntimeError, match="declared type"):
        array_push(h, a, "x")
    with pytest.raises(PineRuntimeError, match="declared type"):
        map_put(h, m, 1, 4)
    with pytest.raises(PineRuntimeError, match="declared type"):
        map_put(h, m, "bad", False)
    with pytest.raises(PineRuntimeError, match="declared type"):
        matrix_set(h, x, 0, 0, "x")
    assert h.read_payload(a) == before_a
    assert h.read_payload(m) == before_m
    assert h.read_payload(x) == before_x


def test_direct_map_reads_reject_wrong_key_type():
    h = heap()
    m = map_new(h, "m", "string,int")
    map_put(h, m, "a", 1)
    with pytest.raises(PineRuntimeError, match="declared type"):
        map_get(h, m, 1)


def test_float_widening_does_not_admit_python_bool_as_number():
    h = heap()
    a = array_new(h, "a", "float", 1, 1)
    assert array_get(h, a, 0) == 1
    with pytest.raises(PineRuntimeError, match="declared type"):
        array_push(h, a, True)


def test_v6_bool_collection_rejects_na_while_v5_keeps_legacy_missing_bool():
    with pytest.raises(PineRuntimeError, match="bool collection"):
        array_new(heap(6), "v6", "bool", 1, na)
    h5 = heap(5)
    a = array_new(h5, "v5", "bool", 1, na)
    assert array_size(h5, a) == 1


@pytest.mark.parametrize(
    "factory",
    [
        lambda h: array_new(h, "nested", "array<array<int>>"),
        lambda h: map_new(h, "nested", "map<string,array<int>>"),
        lambda h: matrix_new(h, "nested", "matrix<map<string,int>>", 0, 0, 0),
    ],
)
def test_collections_cannot_directly_contain_collection_ids_even_when_empty(factory):
    with pytest.raises(PineRuntimeError, match="directly contain"):
        factory(heap())


def test_concat_and_put_all_require_exact_types_even_for_empty_source():
    h = heap()
    ai = array_new(h, "ai", "int")
    af = array_new(h, "af", "float")
    with pytest.raises(PineRuntimeError, match="identical element types"):
        array_concat(h, ai, af)

    mi = map_new(h, "mi", "string,int")
    mf = map_new(h, "mf", "string,float")
    with pytest.raises(PineRuntimeError, match="identical key/value types"):
        map_put_all(h, mi, mf)


def test_shallow_copies_split_outer_identity_but_share_reference_elements():
    h = heap()
    shared = label(h, "label:shared", "old")
    other = label(h, "label:other", "other")
    a = array_new(h, "a", "label", 1, shared)
    ac = array_copy(h, a, "a:copy")
    m = map_new(h, "m", "string,label")
    map_put(h, m, "shared", shared)
    mc = map_copy(h, m, "m:copy")
    x = matrix_new(h, "x", "label", 1, 1, shared)
    xc = matrix_copy(h, x, "x:copy")

    assert a != ac and m != mc and x != xc
    assert array_get(h, a, 0) == array_get(h, ac, 0) == shared
    assert map_get(h, m, "shared") == map_get(h, mc, "shared") == shared
    assert matrix_get(h, x, 0, 0) == matrix_get(h, xc, 0, 0) == shared

    array_push(h, ac, other)
    map_put(h, mc, "other", other)
    matrix_set(h, xc, 0, 0, other)
    assert array_size(h, a) == 1 and array_size(h, ac) == 2
    assert map_size(h, m) == 1 and map_size(h, mc) == 2
    assert matrix_get(h, x, 0, 0) == shared and matrix_get(h, xc, 0, 0) == other

    h.mutate_payload(shared, {"text": "changed"})
    assert h.read_payload(array_get(h, a, 0))["text"] == "changed"
    assert h.read_payload(map_get(h, m, "shared"))["text"] == "changed"


def test_commit_rollback_checkpoint_preserve_shared_graph_and_independent_copy():
    h = heap()
    shared = label(h, "label:shared", "committed")
    second = label(h, "label:second", "second")
    a = array_new(h, "a", "label", 1, shared)
    ac = array_copy(h, a, "a:copy")
    m = map_new(h, "m", "string,label")
    map_put(h, m, "x", shared)
    x = matrix_new(h, "x", "label", 1, 1, shared)
    h.commit()

    h.mutate_payload(shared, {"text": "trial"})
    array_push(h, ac, second)
    assert h.read_payload(shared)["text"] == "trial" and array_size(h, ac) == 2
    h.rollback()
    assert h.read_payload(shared)["text"] == "committed"
    assert array_size(h, ac) == 1

    array_push(h, ac, second)
    h.commit()
    saved = deepcopy(h.to_json())
    restored = RuntimeReferenceHeap.from_json(
        saved, language(6), max_objects=100, max_elements=1000
    )
    rs = ReferenceHandle("label:shared", "visual")
    ra = ReferenceHandle("a", "array")
    rac = ReferenceHandle("a:copy", "array")
    rm = ReferenceHandle("m", "map")
    rx = ReferenceHandle("x", "matrix")
    assert array_get(restored, ra, 0) == rs
    assert array_get(restored, rac, 0) == rs
    assert map_get(restored, rm, "x") == rs
    assert matrix_get(restored, rx, 0, 0) == rs
    assert array_size(restored, ra) == 1 and array_size(restored, rac) == 2


def test_copy_does_not_inherit_varip_binding_policy():
    h = heap()
    a = array_new(h, "a", "int", 1, 1)
    h.retain_intrabar(a)
    ac = array_copy(h, a, "a:copy")
    assert h._get(a).working_varip is True
    assert h._get(ac).working_varip is False


def test_checkpoint_rejects_forged_wrong_typed_ordinary_collection():
    h = heap()
    a = array_new(h, "a", "int", 1, 1)
    h.commit()
    data = h.to_json()
    row = next(row for row in data["objects"] if row["object_id"] == "a")
    row["working"] = ["forged"]
    with pytest.raises(PineRuntimeError, match="declared type"):
        RuntimeReferenceHeap.from_json(data, language(6), max_objects=100, max_elements=1000)


def test_direct_collection_id_element_is_rejected_not_reinterpreted_as_alias():
    h = heap()
    inner = array_new(h, "inner", "float", 1, 1.0)
    with pytest.raises(PineRuntimeError, match="declared type"):
        array_new(h, "outer", "array<float>", 1, inner)

@pytest.mark.parametrize("factory", [
    lambda h: array_new(h, "bool-default", "bool", 1),
    lambda h: matrix_new(h, "bool-default", "bool", 1, 1),
])
def test_v6_omitted_bool_collection_initial_uses_false_not_na(factory):
    h = heap(6)
    handle = factory(h)
    payload = h.read_payload(handle)
    values = payload if isinstance(payload, list) else payload["values"]
    assert values == [False]


@pytest.mark.parametrize("factory", [
    lambda h: array_new(h, "bool-default", "bool", 1),
    lambda h: matrix_new(h, "bool-default", "bool", 1, 1),
])
def test_v5_omitted_bool_collection_initial_preserves_legacy_na(factory):
    h = heap(5)
    handle = factory(h)
    payload = h.read_payload(handle)
    values = payload if isinstance(payload, list) else payload["values"]
    assert len(values) == 1 and values[0] is na
