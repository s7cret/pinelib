"""Typed reference identities, shared budgets and transaction/checkpoint fidelity."""

import json
from dataclasses import replace

import pytest

from pinelib import is_na, na
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import (
    array_get,
    array_new,
    array_push,
    array_set,
    array_size,
)
from pinelib.reference.heap import ReferenceHandle
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from tests.test_language_scopes_once import begin, session


def create(tx, value=1.0, dtype="float"):
    return array_new(tx.references, tx.reference_id_v1("factory"), dtype, 1, value)


@pytest.mark.parametrize("history", ["each_bar", "on_evaluation"])
@pytest.mark.parametrize("mode", ["default", "var"])
def test_declared_reference_identity_and_json_continuation(history, mode):
    obj = session()
    handles = []
    for i in range(3):
        tx = begin(obj, i)
        handle = tx.declare_reference_v1(
            "a",
            mode,
            lambda tx=tx, i=i: create(tx, float(i)),
            "array<float>",
            history_policy=history,
        )
        handles.append(handle)
        array_push(tx.references, handle, float(i))
        if i:
            assert tx.op_series_history("a", 1) == handles[i - 1]
        tx.commit()
    assert len(set(handles)) == (3 if mode == "default" else 1)
    saved = json.loads(json.dumps(obj.checkpoint().to_dict()))
    restored = session()
    restored.restore(saved)
    assert restored.checkpoint().to_dict() == saved
    for runtime in (obj, restored):
        tx = begin(runtime, 3)
        handle = tx.declare_reference_v1(
            "a", mode, lambda tx=tx: create(tx, 3.0), "array<float>", history_policy=history
        )
        array_push(tx.references, handle, 3.0)
        assert tx.op_series_history("a", 1) == handles[-1]
        tx.commit()
    assert obj.state_hash == restored.state_hash
    assert obj.semantic_state_hash == restored.semantic_state_hash


@pytest.mark.parametrize("clock", ["each_bar", "on_evaluation"])
def test_reference_reassignment_updates_the_binding_without_copying_payload(clock):
    s = session()
    tx = begin(s, 0)
    old = tx.declare_reference_v1(
        "a", "var", lambda: create(tx, 1.0), "array<float>", history_policy=clock
    )
    new = create(tx, 2.0)
    tx.write_reference_v1("a", "var", new, "array<float>", history_policy=clock)
    array_set(tx.references, new, 0, 7.0)
    assert array_get(tx.references, old, 0) == 1.0
    tx.commit()
    tx = begin(s, 1)
    assert (
        tx.declare_reference_v1(
            "a", "var", lambda: 1 / 0, "array<float>", history_policy=clock
        )
        == new
    )
    assert array_get(tx.references, new, 0) == 7.0
    assert tx.op_series_history("a", 1) == new
    tx.abort()


@pytest.mark.parametrize("mode", ["default", "var"])
def test_abort_discards_reference_binding_and_allocation(mode):
    s = session()
    before = s.checkpoint().to_dict()
    tx = begin(s, 0)
    old = tx.declare_reference_v1("a", mode, lambda: create(tx), "array<float>")
    array_push(tx.references, old, 2.0)
    tx.abort()
    assert s.checkpoint().to_dict() == before
    tx = begin(s, 0)
    new = tx.declare_reference_v1("a", mode, lambda: create(tx), "array<float>")
    assert new == old  # same callback replay, not two accepted allocations
    assert array_size(tx.references, new) == 1
    tx.commit()


def test_realtime_mutation_and_temporary_constructor_roll_back_without_ghost_handles():
    s = session()
    tx = begin(s, 0)
    kept = tx.declare_reference_v1("a", "var", lambda: create(tx), "array<float>")
    tx.commit()
    tx = begin(s, 1, bar=1, realtime=True, final=False)
    assert tx.declare_reference_v1("a", "var", lambda: 1 / 0, "array<float>") == kept
    array_set(tx.references, kept, 0, 9.0)
    temporary = tx.declare_reference_v1(
        "temp", "default", lambda: create(tx, 8.0), "array<float>"
    )
    tx.commit()
    tx = begin(s, 2, bar=1, realtime=True, final=True)
    assert array_get(tx.references, kept, 0) == 1.0
    with pytest.raises(PineRuntimeError):
        array_get(tx.references, temporary, 0)
    array_set(tx.references, kept, 0, 3.0)
    tx.commit()
    tx = begin(s, 3, bar=2)
    assert array_get(tx.references, kept, 0) == 3.0
    tx.abort()


@pytest.mark.parametrize(
    "fault", ["scalar", "kind", "element", "missing", "marker", "varip"]
)
def test_invalid_reference_binding_is_not_silently_coerced(fault):
    s = session()
    tx = begin(s, 0)
    value = create(tx)
    typ = "array<float>"
    mode = "default"
    if fault == "scalar":
        value = 1.0
    if fault == "kind":
        value = ReferenceHandle(value.object_id, "matrix")
    if fault == "element":
        typ = "array<int>"
    if fault == "missing":
        value = ReferenceHandle("does-not-exist", "array")
    if fault == "marker":
        value = {"$pinelib_ref": {"object_id": 1, "kind": "array"}}
    if fault == "varip":
        mode = "varip"
        value = array_new(tx.references, "unsupported", "label", 0, na)
        typ = "array<label>"
    with pytest.raises(PineRuntimeError):
        tx.declare_reference_v1("x", mode, lambda: value, typ)
    tx.abort()


@pytest.mark.parametrize("version", [4, 5, 6])
def test_history_version_gate_and_na_array_binding(version):
    s = session(version)
    tx = begin(s, 0)
    value = tx.declare_reference_v1("a", "var", lambda: na, "array<float>")
    assert is_na(value)
    tx.commit()
    tx = begin(s, 1)
    if version == 4:
        with pytest.raises(PineRuntimeError, match="history"):
            tx.op_series_history("a", 1)
    else:
        assert is_na(tx.op_series_history("a", 1))
    tx.abort()


def test_callback_allocation_occurrences_are_distinct_but_persistent_scope_is_stable():
    s = session()
    tx = begin(s, 0)
    ids = [tx.reference_id_v1("written") for _ in range(3)]
    assert len(set(ids)) == 3
    assert tx.scoped_id_v1("written") == "written"
    tx.abort()
    tx = begin(s, 0)
    assert [tx.reference_id_v1("written") for _ in range(3)] == ids
    tx.commit()
    tx = begin(s, 1)
    assert tx.reference_id_v1("written") not in ids
    tx.abort()


@pytest.mark.parametrize("version", range(1, 7))
def test_shared_iteration_budget_rejects_cumulative_nested_work_and_resets_per_callback(
    version,
):
    policies = RuntimePolicies(
        resource=replace(ResourcePolicy(), max_loop_iterations=3)
    )
    s = session(version, policies)
    tx = begin(s, 0)
    for _ in range(3):
        tx.consume_loop_iteration_v1()
    with pytest.raises(PineRuntimeError, match="budget"):
        tx.consume_loop_iteration_v1()
    tx.abort()
    tx = begin(s, 0)
    for _ in range(3):
        tx.consume_loop_iteration_v1()
    tx.commit()


@pytest.mark.parametrize("indexed", [False, True])
def test_array_iteration_observes_live_mutation_without_copy(indexed):
    s = session()
    tx = begin(s, 0)
    a = create(tx)
    iterator = tx.iter_array_v1(a, indexed=indexed)
    assert next(iterator) == ((0, 1.0) if indexed else 1.0)
    array_push(tx.references, a, 2.0)
    assert next(iterator) == ((1, 2.0) if indexed else 2.0)
    with pytest.raises(StopIteration):
        next(iterator)
    tx.abort()


def test_array_set_has_complete_explicit_abi_binding():
    from pinelib.abi import load_target_manifest

    rows = [r for r in load_target_manifest()["rows"] if r["name"] == "array.set"]
    assert len(rows) == 2
    for row in rows:
        assert all(
            p["binding"] != "UNBOUND_FAIL_CLOSED" for p in row["parameter_bindings"]
        )
        assert [p["name"] for p in row["parameters"]] == (
            ["index", "value"]
            if row["category"] == "methods"
            else ["id", "index", "value"]
        )


@pytest.mark.parametrize("nested", [False, True])
def test_reads_do_not_materialize_the_whole_array_and_slices_remain_live(
    monkeypatch, nested
):
    from pinelib.reference.array import array_slice

    s = session()
    tx = begin(s, 0)
    original = array_new(
        tx.references, tx.reference_id_v1("large"), "float", 10000, 1.0
    )
    handle = original
    if nested:
        handle = array_slice(
            tx.references, original, 10, 100, tx.reference_id_v1("slice")
        )
        handle = array_slice(tx.references, handle, 2, 6, tx.reference_id_v1("slice"))
        array_set(tx.references, original, 12, 7.0)

    def forbidden(*args, **kwargs):
        raise AssertionError("whole-payload read during iteration")

    monkeypatch.setattr(tx.references, "read_payload", forbidden)
    assert array_size(tx.references, handle) == (4 if nested else 10000)
    assert array_get(tx.references, handle, 0) == (7.0 if nested else 1.0)
    assert sum(tx.iter_array_v1(handle)) == (10.0 if nested else 10000.0)
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
def test_optimized_reads_preserve_negative_index_version_and_reference_alias(version):
    s = session(version)
    tx = begin(s, 0)
    a = create(tx)
    if version == 5:
        with pytest.raises(PineRuntimeError):
            array_get(tx.references, a, -1)
    else:
        assert array_get(tx.references, a, -1) == 1.0
    parent = array_new(tx.references, tx.reference_id_v1("refs"), "array<float>", 1, a)
    assert array_get(tx.references, parent, 0) == a
    array_set(tx.references, a, 0, 7.0)
    assert array_get(tx.references, array_get(tx.references, parent, 0), 0) == 7.0
    tx.abort()


def test_nested_slice_bounds_validate_every_parent_after_shrink():
    from pinelib.reference.array import array_pop, array_slice

    s = session()
    tx = begin(s, 0)
    a = array_new(tx.references, tx.reference_id_v1("a"), "float", 5, 1.0)
    parent = array_slice(tx.references, a, 0, 5, tx.reference_id_v1("parent"))
    child = array_slice(tx.references, parent, 0, 1, tx.reference_id_v1("child"))
    array_pop(tx.references, a)
    # Child element itself still exists, but its complete parent window is invalid.
    with pytest.raises(PineRuntimeError, match="bounds"):
        array_get(tx.references, child, 0)
    tx.abort()
