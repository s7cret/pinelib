"""A failed callback can temporarily invalidate a view that rollback repairs.

Only temporary upper bounds are deferred in a private witness decoder. Public
checkpoints, graph identity, nominal values and committed bounds remain strict.
"""

from copy import deepcopy

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_new, array_slice, array_pop, array_push, array_size
from pinelib.reference.heap import RuntimeReferenceHeap
from pinelib.state.checkpoint import RuntimeCheckpoint
from tests.test_language_scopes_once import begin
from tests.test_nominal_registry_runtime import E, session
from tests.test_varip_abort_checkpoint import reseal_pending


def fixture(version, compact, nominal=False):
    runtime = session(version)
    runtime.commit_full_identity = not compact
    tx = begin(runtime, 0, bar=0)
    value = tx.enum_value_v1(E, "buy", 0) if nominal else 7
    backing = array_new(tx.references, "backing", E if nominal else "int", 3, value)
    view = array_slice(tx.references, backing, 1, 3, "view")
    tx.declare_scalar_v1("ticks", "varip", lambda: 0, "int")
    tx.commit()
    return runtime, backing, view, value


def decode(heap, runtime, *, attempted=False):
    limits = runtime.policies.resource
    method = RuntimeReferenceHeap._from_abort_witness_json if attempted else RuntimeReferenceHeap.from_json
    return method(heap, runtime.language, max_objects=limits.max_reference_objects,
        max_elements=limits.max_collection_elements, nominal_registry=runtime.nominal_registry)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("nominal", [False, True])
@pytest.mark.parametrize("operation", ["shrink_existing", "grow_new_slice"])
def test_attempted_bounds_defer_only_until_real_abort_rollback(version, compact, nominal, operation):
    runtime, backing, view, value = fixture(version, compact, nominal)
    tx = begin(runtime, 1, bar=1, realtime=True)
    tx.write_scalar_v1("ticks", "varip", 2, "int")
    if operation == "shrink_existing":
        array_pop(tx.references, backing)
        with pytest.raises(PineRuntimeError, match="bounds"):
            array_size(tx.references, view)
    else:
        array_push(tx.references, backing, value)
        new_view = array_slice(tx.references, backing, 3, 4, "new-view")
        assert array_size(tx.references, new_view) == 1
    attempted = runtime._state_json()
    with pytest.raises(PineRuntimeError, match="bounds"):
        decode(attempted["references"], runtime)
    private = decode(attempted["references"], runtime, attempted=True)
    assert private._transient_slice_bounds is False
    if operation == "shrink_existing":
        with pytest.raises(PineRuntimeError, match="bounds"):
            array_size(private, view)
    plain = RuntimeCheckpoint.seal(runtime.identity_hash, {**attempted, "transcript": runtime.transcript.to_dict()})
    clone = session(version)
    with pytest.raises(PineRuntimeError, match="bounds"):
        clone.restore(plain.to_dict())
    tx.abort()
    saved = runtime.checkpoint().to_dict()
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    for current in (runtime, clone):
        assert array_size(current.references, backing) == 3
        assert array_size(current.references, view) == 2
        assert not current.references.contains("new-view")
        tx = begin(current, 1, bar=1, realtime=True)
        assert tx.declare_scalar_v1("ticks", "varip", lambda: None, "int") == 2
        tx.commit()
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("corruption", ["extra_marker", "negative", "reversed", "bool_bound", "cycle",
    "unknown_parent", "wrong_parent_kind", "wrong_parent_type", "committed_bounds", "forged_enum"])
def test_private_witness_decoder_preserves_all_other_reference_invariants(version, compact, corruption):
    runtime, backing, view, _ = fixture(version, compact, True)
    tx = begin(runtime, 1, bar=1, realtime=True)
    tx.write_scalar_v1("ticks", "varip", 2, "int")
    array_pop(tx.references, backing)
    tx.abort()
    before = runtime.checkpoint().to_dict()
    state = deepcopy(before["state"])
    heap = state["pending_abort"]["attempts"][0]["attempted_state"]["references"]
    row = next(row for row in heap["objects"] if row["object_id"] == "view")
    marker = row["working"]["$pinelib_array_slice"]
    if corruption == "extra_marker": marker["extra"] = True
    elif corruption == "negative": marker["start"] = -1
    elif corruption == "reversed": marker["start"], marker["end"] = 3, 1
    elif corruption == "bool_bound": marker["end"] = True
    elif corruption == "cycle": marker["parent"]["$pinelib_ref"]["object_id"] = "view"
    elif corruption == "unknown_parent": marker["parent"]["$pinelib_ref"]["object_id"] = "foreign"
    elif corruption == "wrong_parent_kind": marker["parent"]["$pinelib_ref"]["kind"] = "matrix"
    elif corruption == "wrong_parent_type": row["type_descriptor"] = "int"
    elif corruption == "committed_bounds": row["committed"]["$pinelib_array_slice"]["end"] = 99
    elif corruption == "forged_enum":
        parent = next(row for row in heap["objects"] if row["object_id"] == "backing")
        parent["working"][0]["$pinelib_enum"]["member"] = "forged"
    with pytest.raises(PineRuntimeError):
        runtime.restore(reseal_pending(runtime, state))
    assert runtime.checkpoint().to_dict() == before


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_out_of_bounds_view_surviving_rollback_is_rejected(version, compact):
    runtime, backing, _, _ = fixture(version, compact)
    tx = begin(runtime, 1, bar=1, realtime=True)
    tx.write_scalar_v1("ticks", "varip", 2, "int")
    array_pop(tx.references, backing)
    tx.abort()
    before = runtime.checkpoint().to_dict()
    state = deepcopy(before["state"])
    next(row for row in state["references"]["objects"] if row["object_id"] == "backing")["working"].pop()
    with pytest.raises(PineRuntimeError, match="bounds"):
        runtime.restore(reseal_pending(runtime, state, refresh_state_hash=False))
    assert runtime.checkpoint().to_dict() == before
