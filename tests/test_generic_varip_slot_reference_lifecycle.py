"""Generic varip slots retain allocation identity, not ordinary mutations.

The integer traces are hand-authored native-runtime expectations. This separate
P2 lifecycle obligation predates the committed heap/storage closure repair.
"""
import json

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_get, array_new, array_push, array_set, array_size, array_slice
from pinelib.state.checkpoint import to_portable
from tests.test_varip_nominal_arrays import begin, counter, factory, increment, state


def prepare(version, compact, deferred=False):
    make = factory(version, compact)
    runtime = make()
    begin(runtime, 0, deferred=deferred).commit()
    if deferred:
        runtime.finalize_bar(0)
    return runtime, make


def checkpoint_clone(runtime, make):
    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    restored = make()
    restored.restore(saved)
    assert restored.checkpoint().to_dict() == saved
    return restored


def aliases(tx):
    value = tx.state("aliases", owner="extension", schema_version="1",
                     initial=None, varip=True)
    return tx.references._decode_value(to_portable(value))


def assert_ordinary_policy(runtime, *handles):
    rows = {row["object_id"]: row for row in runtime.references.to_json()["objects"]}
    for handle in handles:
        assert "intrabar_persistence" not in rows[handle.object_id]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("finish", ["abort", "retry_nonfinal_commit_next_begin"])
@pytest.mark.parametrize("binding", ["set_new", "set_replace", "state_new"])
def test_varip_slot_rejects_slice_outside_ordinary_constructor_baseline_atomically(version, compact, finish, binding):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0)
    backing = array_new(tx.references, "backing", "int", 1, 7)
    if binding == "set_replace":
        tx.set_slot("aliases", 7, owner="extension", varip=True)
    tx.commit()
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    array_push(tx.references, backing, 8)
    window = array_slice(tx.references, backing, 1, 2, "window")
    assert array_get(tx.references, window, 0) == 8
    before = runtime.slots.to_json()
    with pytest.raises(PineRuntimeError, match="bounds") as rejected:
        if binding == "state_new":
            tx.state("aliases", owner="extension", schema_version="1", initial={"nested": [window]}, varip=True)
        else:
            tx.set_slot("aliases", {"nested": [window]}, owner="extension", varip=True)
    assert rejected.value.code == "PL1611"
    assert runtime.slots.to_json() == before
    assert_ordinary_policy(runtime, backing, window)
    # Admission raises in the original callback before either finish path can
    # persist the unsupported root. Abort that failed callback, then retry the
    # nonfinal path with a view whose constructor fits the ordinary baseline.
    tx.abort()
    assert array_size(runtime.references, backing) == 1
    assert array_get(runtime.references, backing, 0) == 7
    assert not runtime.references.contains("window")
    restored = checkpoint_clone(runtime, make)
    assert array_get(restored.references, backing, 0) == 7
    if finish == "retry_nonfinal_commit_next_begin":
        for current in (runtime, restored):
            tx = begin(current, 2, bar=1, realtime=True, final=False)
            safe = array_slice(tx.references, backing, 0, 1, "safe-window")
            tx.set_slot("aliases", {"nested": [safe]}, owner="extension", varip=True)
            tx.commit()
            checkpoint_clone(current, make)
            tx = begin(current, 3, bar=1, realtime=True, final=False)
            assert aliases(tx) == {"nested": [safe]}
            assert array_get(tx.references, safe, 0) == 7
            assert_ordinary_policy(current, backing, safe)
            tx.abort()
            checkpoint_clone(current, make)
        assert restored.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("finish", ["commit", "abort"])
def test_realtime_nested_slot_identity_survives_restore_abort_retry_without_promotion(version, compact, finish):
    runtime, make = prepare(version, compact)
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    handle = array_new(tx.references, "ordinary", "int", 1, 7)
    array_new(tx.references, "unrooted", "int", 1, 3)
    tx.set_slot("aliases", {"nested": [handle, {"same": handle}]}, owner="extension", varip=True)
    array_set(tx.references, handle, 0, 9)
    getattr(tx, finish)()
    assert runtime.references.contains(handle.object_id)
    assert array_get(runtime.references, handle, 0) == (9 if finish == "commit" else 7)
    assert_ordinary_policy(runtime, handle)
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, current.sequence + 1, bar=1, realtime=True)
        assert tx.references.contains(handle.object_id)
        assert not tx.references.contains("unrooted")
        assert aliases(tx) == {"nested": [handle, {"same": handle}]}
        assert array_get(tx.references, handle, 0) == 7
        array_set(tx.references, aliases(tx)["nested"][1]["same"], 0, 11)
        assert array_get(tx.references, aliases(tx)["nested"][0], 0) == 11
        assert_ordinary_policy(current, handle)
        tx.commit()
    assert restored.checkpoint().to_dict() == runtime.checkpoint().to_dict()
    checkpoint_clone(runtime, make)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_deferred_abort_slot_roots_survive_scratch_witness_restore_and_retry(version, compact):
    runtime, make = prepare(version, compact, deferred=True)
    sequence = runtime.sequence + 1
    tx = begin(runtime, sequence, bar=1, deferred=True)
    handle = array_new(tx.references, "ordinary", "int", 1, 7)
    tx.set_slot("aliases", {"nested": [handle, handle]}, owner="extension", varip=True)
    array_set(tx.references, handle, 0, 9)
    tx.abort()
    assert runtime.references.contains(handle.object_id)
    assert array_get(runtime.references, handle, 0) == 7
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, sequence, bar=1, deferred=True)
        assert aliases(tx) == {"nested": [handle, handle]}
        assert array_get(tx.references, handle, 0) == 7
        array_set(tx.references, handle, 0, 11)
        tx.commit()
        current.finalize_bar(1)
    assert restored.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_deferred_callback_roots_survive_until_published_boundary_and_restore(version, compact):
    runtime, make = prepare(version, compact, deferred=True)
    tx = begin(runtime, runtime.sequence + 1, bar=1, deferred=True)
    handle = array_new(tx.references, "ordinary", "int", 1, 7)
    tx.set_slot("aliases", {"nested": [handle, handle]}, owner="extension", varip=True)
    array_set(tx.references, handle, 0, 9)
    tx.commit()
    with pytest.raises(PineRuntimeError, match="active|provisional"):
        runtime.checkpoint()
    tx = begin(runtime, runtime.sequence + 1, bar=1, deferred=True)
    assert tx.references.contains(handle.object_id)
    assert aliases(tx) == {"nested": [handle, handle]}
    assert array_get(tx.references, handle, 0) == 7
    assert_ordinary_policy(runtime, handle)
    array_set(tx.references, handle, 0, 11)
    tx.commit()
    runtime.finalize_bar(1)
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, current.sequence + 1, bar=2, deferred=True)
        assert array_get(tx.references, aliases(tx)["nested"][0], 0) == 11
        tx.commit()
        current.finalize_bar(2)
    assert restored.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_tuple_slot_slice_aliases_retain_ordinary_backing_identity(version, compact):
    runtime, make = prepare(version, compact)
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    backing = array_new(tx.references, "backing", "int", 3, 4)
    window = array_slice(tx.references, backing, 1, 3, "window")
    tx.set_slot("aliases", {"slices": (window, window)}, owner="extension", varip=True)
    array_set(tx.references, window, 0, 9)
    tx.commit()
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, 2, bar=1, realtime=True)
        assert tx.references.contains(window.object_id)
        assert tx.references.contains(backing.object_id)
        assert aliases(tx) == {"slices": [window, window]}
        assert array_get(tx.references, window, 0) == 4
        array_set(tx.references, aliases(tx)["slices"][1], 0, 11)
        assert array_get(tx.references, backing, 1) == 11
        assert_ordinary_policy(current, window, backing)
        tx.commit()
    assert restored.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("finish", ["commit", "abort"])
def test_slot_root_retains_constructor_graph_and_existing_udt_field_rollback(version, compact, finish):
    runtime, make = prepare(version, compact)
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    child = counter(tx, "child")
    original = tx.get_udt_field_v1(child, "values")
    replacement = array_new(tx.references, "replacement", "int", 1, 10)
    tx.set_udt_field_v1(child, "values", replacement)
    tx.set_slot("aliases", {"children": [child, child]}, owner="extension", varip=True)
    increment(tx, child)
    getattr(tx, finish)()
    assert runtime.references.contains(child.object_id)
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, current.sequence + 1, bar=1, realtime=True)
        assert aliases(tx) == {"children": [child, child]}
        assert state(current, child) == [0, 1, 0, 0.0]
        assert tx.get_udt_field_v1(child, "values") == original
        assert tx.references.contains(replacement.object_id) is (finish == "commit")
        assert_ordinary_policy(current, child, original)
        increment(tx, child)
        assert state(current, child) == [1, 2, 1, 1.0]
        tx.commit()
    assert restored.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_replacing_slot_root_does_not_permanently_promote_old_allocation(version, compact):
    runtime, _ = prepare(version, compact)
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    old = array_new(tx.references, "old", "int", 1, 7)
    tx.set_slot("aliases", {"root": old}, owner="extension", varip=True)
    tx.commit()
    tx = begin(runtime, 2, bar=1, realtime=True, final=False)
    new = array_new(tx.references, "new", "int", 1, 8)
    tx.set_slot("aliases", {"root": new}, owner="extension", varip=True)
    tx.commit()
    tx = begin(runtime, 3, bar=1, realtime=True)
    assert not tx.references.contains(old.object_id)
    assert tx.references.contains(new.object_id)
    assert aliases(tx) == {"root": new}
    assert array_get(tx.references, new, 0) == 8
    assert_ordinary_policy(runtime, new)
    tx.commit()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("context,varip", [("historical", False), ("historical", True),
    ("realtime", False), ("deferred", False)])
def test_unpreserved_extension_slots_do_not_retain_provisional_allocations(version, context, varip):
    deferred = context == "deferred"
    runtime, _ = prepare(version, False, deferred=deferred)
    tx = begin(runtime, runtime.sequence + 1, bar=1, realtime=context == "realtime", deferred=deferred)
    handle = array_new(tx.references, "unretained", "int", 1, 7)
    tx.set_slot("aliases", {"root": handle}, owner="extension", varip=varip)
    tx.abort()
    assert not runtime.slots.contains("aliases")
    assert not runtime.references.contains(handle.object_id)
