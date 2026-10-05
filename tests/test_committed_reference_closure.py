"""Committed edges must survive rollback; constructor edges are provisional.

Spec §6.6: checkpoint preserves reference identity and rollback must not break
aliasing. Expected traces below are hand-authored, not runtime-derived or TV
conformance claims. Exercise the existing direct runtime/heap boundary only.
"""
from copy import deepcopy
import json

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_copy, array_get, array_new
from pinelib.reference.heap import RuntimeReferenceHeap
from pinelib.reference.map import map_get, map_new, map_put
from pinelib.reference.matrix import matrix_get, matrix_new
from tests.test_varip_nominal_arrays import COUNTER, DTYPE, begin, counter, factory, increment, state


def decode(runtime, data):
    return RuntimeReferenceHeap.from_json(
        json.loads(json.dumps(data)), runtime.language,
        max_objects=100, max_elements=1000,
        nominal_registry=runtime.nominal_registry,
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("parent_kind", ["udt", "array", "map", "matrix", "slice"])
def test_restore_rejects_committed_edge_to_provisional_referent(version, parent_kind):
    runtime = factory(version)()
    tx = begin(runtime, 0)
    child = counter(tx)
    if parent_kind == "udt":
        target_id = "counter-values"
    elif parent_kind == "array":
        array_new(tx.references, "parent", COUNTER, 1, child)
        target_id = child.object_id
    elif parent_kind == "map":
        parent = map_new(tx.references, "parent", "string," + COUNTER)
        map_put(tx.references, parent, "child", child)
        target_id = child.object_id
    elif parent_kind == "matrix":
        matrix_new(tx.references, "parent", COUNTER, 1, 1, child)
        target_id = child.object_id
    else:
        from pinelib.reference.array import array_slice
        backing = array_new(tx.references, "backing", "int", 1, 0)
        array_slice(tx.references, backing, 0, 1, "parent")
        target_id = backing.object_id
    tx.commit()
    before = runtime.references.to_json()
    forged = deepcopy(before)
    target = next(row for row in forged["objects"] if row["object_id"] == target_id)
    target["committed_exists"] = False
    # The node still exists and has the correct kind/type. Node-local validation
    # is insufficient: its committed parent will survive but this node will not.
    with pytest.raises(PineRuntimeError, match="committed reference.*provisional"):
        decode(runtime, forged)
    assert runtime.references.to_json() == before


@pytest.mark.parametrize("version", [5, 6])
def test_new_runtime_rejects_resealed_committed_edge_before_publication(version):
    from pinelib.state.checkpoint import RuntimeCheckpoint
    make = factory(version)
    runtime = make()
    tx = begin(runtime, 0)
    child = counter(tx)
    tx.declare_reference_v1("child", "var", lambda: child, COUNTER)
    tx.commit()
    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    checkpoint_state = deepcopy(saved["state"])
    target = next(row for row in checkpoint_state["references"]["objects"]
                  if row["object_id"] == "counter-values")
    target["committed_exists"] = False
    # Reseal the JSON hashes independently so transcript integrity cannot mask
    # the graph defect. This is adversarial input, not an output oracle.
    import hashlib
    def digest(value):
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()
    transcript = checkpoint_state["transcript"]
    transcript["entries"][-1]["state_hash"] = digest(
        {key: value for key, value in checkpoint_state.items() if key != "transcript"})
    transcript["content_hash"] = digest({"entries": transcript["entries"]})
    forged = RuntimeCheckpoint.seal(runtime.identity_hash, checkpoint_state).to_dict()
    destination = make()
    before = destination.checkpoint().to_dict()
    owners = tuple(getattr(destination, key) for key in ("references", "series", "slots", "transcript"))
    with pytest.raises(PineRuntimeError, match="committed reference.*provisional"):
        destination.restore(json.loads(json.dumps(forged)))
    assert destination.checkpoint().to_dict() == before
    assert all(owner is getattr(destination, key) for owner, key in
               zip(owners, ("references", "series", "slots", "transcript"), strict=True))
    destination.restore(saved)
    assert destination.checkpoint().to_dict() == saved


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_provisional_constructor_edges_alias_copy_history_abort_replay_json_restore(version, compact):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0)
    bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER), DTYPE)
    tx.commit()

    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    child = counter(tx, "fresh")
    copy = tx.copy_udt_v1(child, "fresh-copy")
    assert child != copy
    assert tx.get_udt_field_v1(child, "values") == tx.get_udt_field_v1(copy, "values")
    # Both fresh objects and their constructor edges are provisional. Keeping
    # them through a varip root is legal, without promoting ordinary children.
    from pinelib.reference.array import array_push
    array_push(tx.references, bag, child)
    array_push(tx.references, bag, copy)
    increment(tx, child)
    assert state(runtime, child) == [1, 1, 1, 1.0]
    assert state(runtime, copy) == [0, 0, 1, 1.0]
    tx.abort()
    assert state(runtime, child) == [0, 1, 0, 0.0]
    assert state(runtime, copy) == [0, 0, 0, 0.0]
    # Public decoder must still admit constructor baselines of retained nodes.
    decode(runtime, runtime.references.to_json())

    tx = begin(runtime, 1, bar=1, realtime=True)
    assert array_get(tx.references, bag, 0) == child
    assert array_get(tx.references, bag, 1) == copy
    increment(tx, child)
    tx.declare_reference_v1("child", "var", lambda: child, COUNTER)
    outer_copy = array_copy(tx.references, bag, "bag-copy")
    mapping = map_new(tx.references, "mapping", "string," + COUNTER)
    map_put(tx.references, mapping, "shared", child)
    grid = matrix_new(tx.references, "grid", COUNTER, 1, 1, child)
    tx.commit()
    assert state(runtime, child) == [1, 2, 1, 1.0]
    assert state(runtime, copy) == [0, 0, 1, 1.0]

    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    clone = make()
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    assert clone.references is not runtime.references
    for current in (runtime, clone):
        tx = begin(current, 2, bar=2)
        # The previous bar records the same reference identity, not a deep copy.
        assert tx.read_series("child", 1) == child
        assert array_get(tx.references, bag, 0) == child
        assert array_get(tx.references, bag, 1) == copy
        assert outer_copy != bag
        assert array_get(tx.references, outer_copy, 0) == child
        assert map_get(tx.references, mapping, "shared") == child
        assert matrix_get(tx.references, grid, 0, 0) == child
        increment(tx, child)
        assert state(current, child) == [2, 3, 2, 2.0]
        assert state(current, copy) == [0, 0, 2, 2.0]
        tx.commit()
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()
