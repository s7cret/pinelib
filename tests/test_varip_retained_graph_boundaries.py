"""Retained graphs are admitted at callback cuts, including live Python aliases."""

from copy import deepcopy

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.state.checkpoint import RuntimeCheckpoint
from pinelib.reference.array import array_get, array_new, array_pop, array_push, array_size, array_slice
from tests.test_generic_varip_slot_reference_lifecycle import aliases, assert_ordinary_policy, checkpoint_clone
from tests.test_varip_nominal_arrays import begin, counter, factory


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize("finish", ["abort", "commit"])
@pytest.mark.parametrize("mutation", ["state_alias", "setter_alias", "ordinary_udt_field"])
def test_late_invalid_retained_graph_rejects_whole_attempt_and_preserves_previous_abort(version, compact, deferred, finish, mutation):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0, deferred=deferred)
    if mutation.endswith("udt_field"):
        child = counter(tx)
        backing = tx.get_udt_field_v1(child, "values")
        tx.set_slot("aliases", {"nested": [child]}, owner="extension", varip=True)
    else:
        backing = array_new(tx.references, "backing", "int", 1, 7)
    tx.declare_scalar_v1("ticks", "varip", lambda: 0, "int")
    tx.commit()
    if deferred:
        runtime.finalize_bar(0)
    sequence = runtime.sequence + 1
    tx = begin(runtime, sequence, bar=1, realtime=True, final=False, deferred=deferred)
    tx.write_scalar_v1("ticks", "varip", 1, "int")
    tx.abort()
    before = runtime.checkpoint().to_dict()
    assert "pending_abort" in before["state"]
    tx = begin(runtime, sequence, bar=1, realtime=True, final=False, deferred=deferred)
    if mutation == "state_alias":
        value = tx.state("aliases", owner="extension", schema_version="1", initial={"nested": []}, varip=True)
    elif mutation == "setter_alias":
        value = {"nested": []}
        tx.set_slot("aliases", value, owner="extension", varip=True)
    array_push(tx.references, backing, 8)
    window = array_slice(tx.references, backing, 1, 2, "late-window")
    if mutation.endswith("udt_field"):
        tx.set_udt_field_v1(child, "values", window)
    else:
        value["nested"].append(window)
    tx.write_scalar_v1("ticks", "varip", 99, "int")
    with pytest.raises(PineRuntimeError, match="bounds") as rejected:
        getattr(tx, finish)()
    assert rejected.value.code == "PL1611"
    assert tx.closed and runtime._active is None
    assert runtime.checkpoint().to_dict() == before
    assert not runtime.references.contains(window.object_id)
    assert array_size(runtime.references, backing) == 1
    assert_ordinary_policy(runtime, backing)
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, sequence, bar=1, realtime=True, final=deferred, deferred=deferred)
        safe = array_slice(tx.references, backing, 0, 1, "safe-window")
        tx.set_slot("safe", {"nested": [safe, safe]}, owner="extension", varip=True)
        assert array_get(tx.references, safe, 0) == (0 if mutation.endswith("udt_field") else 7)
        tx.commit()
        if deferred:
            current.finalize_bar(1)
        checkpoint_clone(current, make)
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("finish", ["abort", "commit"])
def test_finished_callback_detaches_mutable_varip_slot_alias(version, compact, finish):
    make = factory(version, compact)
    runtime = make()
    begin(runtime, 0).commit()
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    value = tx.state("aliases", owner="extension", schema_version="1", initial={"nested": []}, varip=True)
    unrooted = array_new(tx.references, "unrooted", "int", 1, 7)
    getattr(tx, finish)()
    before = runtime.checkpoint().to_dict()
    value["nested"].append(unrooted)
    assert runtime.checkpoint().to_dict() == before
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, current.sequence + 1, bar=1, realtime=True, final=False)
        assert aliases(tx) == {"nested": []}
        assert not current.references.contains(unrooted.object_id)
        tx.abort()
        checkpoint_clone(current, make)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("realtime", [False, True])
def test_confirmed_deferred_ordinary_growth_slice_publishes_new_baseline(version, compact, realtime):
    make = factory(version, compact)
    runtime = make()
    if realtime:
        begin(runtime, 0, deferred=True).commit()
        runtime.finalize_bar(0)
    bar = int(realtime)
    tx = begin(runtime, runtime.sequence + 1, bar=bar, realtime=realtime, deferred=True)
    backing = array_new(tx.references, "backing", "int", 1, 7)
    array_push(tx.references, backing, 8)
    window = array_slice(tx.references, backing, 1, 2, "ordinary-window")
    assert array_get(tx.references, window, 0) == 8
    tx.commit()
    with pytest.raises(PineRuntimeError, match="active|provisional"):
        runtime.checkpoint()
    runtime.finalize_bar(bar)
    assert array_size(runtime.references, backing) == 2
    assert array_get(runtime.references, window, 0) == 8
    assert_ordinary_policy(runtime, backing, window)
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, current.sequence + 1, bar=bar + 1, deferred=True)
        assert array_size(tx.references, backing) == 2
        assert array_get(tx.references, window, 0) == 8
        tx.abort()
        checkpoint_clone(current, make)


def provisional_growth(version, compact):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0, deferred=True)
    backing = array_new(tx.references, "first-backing", "int", 1, 7)
    array_push(tx.references, backing, 8)
    window = array_slice(tx.references, backing, 1, 2, "first-window")
    tx.commit()
    return runtime, make, backing, window


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_confirmed_deferred_transient_baseline_replays_same_bar_callback_abort(version, compact):
    runtime, make, backing, window = provisional_growth(version, compact)
    tx = begin(runtime, runtime.sequence + 1, deferred=True)
    assert not runtime.references.contains(window.object_id)
    tx.abort()
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, current.sequence + 1, deferred=True)
        tx.commit()
        current.finalize_bar(0)
        checkpoint_clone(current, make)
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("corruption", ["plain_public_baseline", "inner_working_bounds"])
def test_transient_abort_baseline_cannot_bypass_strict_public_or_working_admission(version, compact, corruption):
    runtime, make, backing, window = provisional_growth(version, compact)
    begin(runtime, runtime.sequence + 1, deferred=True).abort()
    before = runtime.checkpoint().to_dict()
    checkpoint_clone(runtime, make)
    if corruption == "plain_public_baseline":
        record = before["state"]["pending_abort"]
        plain = RuntimeCheckpoint.seal(runtime.identity_hash,
            {**record["successful_state"], "transcript": before["state"]["transcript"]})
        target = make()
        empty = target.checkpoint().to_dict()
        with pytest.raises(PineRuntimeError, match="bounds"):
            target.restore(plain.to_dict())
        assert target.checkpoint().to_dict() == empty
    else:
        state = deepcopy(before["state"])
        rows = state["pending_abort"]["successful_state"]["references"]["objects"]
        row = next(row for row in rows if row["object_id"] == window.object_id)
        row["working"]["$pinelib_array_slice"]["end"] = 99
        forged = RuntimeCheckpoint.seal(runtime.identity_hash, state)
        with pytest.raises(PineRuntimeError, match="bounds"):
            runtime.restore(forged.to_dict())
        assert runtime.checkpoint().to_dict() == before


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("finish", ["commit", "abort"])
def test_rejected_late_root_restores_prior_transient_confirmed_deferred_callback_atomically(version, compact, finish):
    runtime, make, backing, window = provisional_growth(version, compact)
    previous = runtime._state_json()
    transcript = runtime.transcript.to_dict()
    pending = runtime._pending_bar_frame
    tx = begin(runtime, runtime.sequence + 1, deferred=True)
    value = tx.state("aliases", owner="extension", schema_version="1", initial={"nested": []}, varip=True)
    new_backing = array_new(tx.references, "late-backing", "int", 1, 7)
    array_push(tx.references, new_backing, 8)
    late = array_slice(tx.references, new_backing, 1, 2, "late-window")
    value["nested"].append(late)
    with pytest.raises(PineRuntimeError, match="bounds") as rejected:
        getattr(tx, finish)()
    assert rejected.value.code == "PL1611"
    assert tx.closed and runtime._active is None
    assert runtime._state_json() == previous
    assert runtime.transcript.to_dict() == transcript
    assert runtime._pending_bar_frame == pending
    with pytest.raises(PineRuntimeError, match="active|provisional"):
        runtime.checkpoint()
    runtime.finalize_bar(0)
    assert array_size(runtime.references, backing) == 2
    assert array_get(runtime.references, window, 0) == 8
    assert not runtime.references.contains(late.object_id)
    checkpoint_clone(runtime, make)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_confirmed_deferred_invalid_working_slice_rejects_before_publication(version, compact):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0, deferred=True)
    backing = array_new(tx.references, "backing", "int", 3, 7)
    window = array_slice(tx.references, backing, 1, 3, "ordinary-window")
    tx.commit()
    runtime.finalize_bar(0)
    previous = runtime.checkpoint().to_dict()
    tx = begin(runtime, runtime.sequence + 1, bar=1, deferred=True)
    array_pop(tx.references, backing)
    with pytest.raises(PineRuntimeError, match="bounds"):
        tx.commit()
    assert tx.closed and runtime._active is None
    assert runtime.checkpoint().to_dict() == previous
    with pytest.raises(PineRuntimeError, match="provisional"):
        runtime.finalize_bar(1)
    assert array_get(runtime.references, window, 0) == 7
    checkpoint_clone(runtime, make)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_deferred_publication_detaches_callback_root_alias(version, compact):
    make = factory(version, compact)
    runtime = make()
    begin(runtime, 0, deferred=True).commit()
    runtime.finalize_bar(0)
    tx = begin(runtime, runtime.sequence + 1, bar=1, realtime=True, deferred=True)
    value = tx.state("aliases", owner="extension", schema_version="1", initial={"nested": []}, varip=True)
    handle = array_new(tx.references, "unrooted", "int", 1, 7)
    tx.commit()
    value["nested"].append(handle)
    runtime.finalize_bar(1)
    restored = checkpoint_clone(runtime, make)
    for current in (runtime, restored):
        tx = begin(current, current.sequence + 1, bar=2, realtime=True, deferred=True)
        assert aliases(tx) == {"nested": []}
        tx.abort()
        checkpoint_clone(current, make)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize("operation", ["declare", "write"])
def test_typed_varip_slice_gate_runs_before_intrabar_promotion(version, compact, deferred, operation):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0, deferred=deferred)
    backing = array_new(tx.references, "backing", "int", 1, 7)
    if operation == "write":
        tx.declare_reference_v1("typed", "varip", lambda: array_new(tx.references, "old", "int", 1, 4), "array<int>")
    tx.commit()
    if deferred:
        runtime.finalize_bar(0)
    tx = begin(runtime, runtime.sequence + 1, bar=1, realtime=True, final=False, deferred=deferred)
    array_push(tx.references, backing, 8)
    window = array_slice(tx.references, backing, 1, 2, "typed-window")
    slots = runtime.slots.to_json()
    heap = runtime.references.to_json()
    with pytest.raises(PineRuntimeError, match="bounds") as rejected:
        if operation == "declare":
            tx.declare_reference_v1("typed", "varip", lambda: window, "array<int>")
        else:
            tx.write_reference_v1("typed", "varip", window, "array<int>")
    assert rejected.value.code == "PL1611"
    assert runtime.slots.to_json() == slots
    assert runtime.references.to_json() == heap
    assert_ordinary_policy(runtime, backing, window)
    tx.abort()
    assert array_size(runtime.references, backing) == 1
    assert not runtime.references.contains(window.object_id)
    checkpoint_clone(runtime, make)
