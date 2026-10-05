"""Spec §6.6: committed storage roots must survive heap rollback.

Prior committed_reference_closure covers heap-to-heap edges, not history/slot
roots into an otherwise legal provisional allocation. Native runtime scope only;
integer traces are independently hand-authored, not compiled/TV acceptance.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_get, array_new
from pinelib.state.checkpoint import RuntimeCheckpoint
from tests.test_varip_nominal_arrays import (
    COUNTER, begin, counter, factory, increment, state,
)


def portable(value):
    return json.loads(json.dumps(value))


def digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode()).hexdigest()


def reseal(runtime, checkpoint_state):
    transcript = checkpoint_state["transcript"]
    transcript["entries"][-1]["state_hash"] = digest({
        key: value for key, value in checkpoint_state.items() if key != "transcript"
    })
    transcript["content_hash"] = digest({"entries": transcript["entries"]})
    return portable(RuntimeCheckpoint.seal(runtime.identity_hash, checkpoint_state).to_dict())


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("location", ["history", "slot", "nested_slot"])
def test_resealed_committed_storage_cannot_point_to_provisional_heap(version, location):
    make = factory(version)
    source = make()
    tx = begin(source, 0)
    root = tx.declare_reference_v1("root", "var", lambda: array_new(
        tx.references, "root-array", "int", 1, 7), "array<int>")
    tx.set_slot("nested", {"aliases": [root, {"again": root}]}, owner="test")
    tx.commit()
    saved = portable(source.checkpoint().to_dict())
    forged_state = deepcopy(saved["state"])
    orphan = deepcopy(forged_state["references"]["objects"][0])
    orphan["object_id"] = "orphan"
    orphan["committed_exists"] = False
    forged_state["references"]["objects"].append(orphan)
    forged_state["references"]["objects"].sort(key=lambda row: row["object_id"])
    marker = {"$pinelib_ref": {"object_id": "orphan", "kind": "array"}}
    if location == "history":
        forged_state["series"]["root"]["committed"][0] = marker
    elif location == "slot":
        row = next(row for row in forged_state["slots"] if row["state_id"] == "reference-binding:root")
        row["committed"] = marker
    else:
        row = next(row for row in forged_state["slots"] if row["state_id"] == "nested")
        row["committed"]["aliases"][1]["again"] = marker
    forged = reseal(source, forged_state)
    destination = make()
    # A populated destination proves rejection does not erase existing owners.
    destination.restore(saved)
    before = destination.checkpoint().to_dict()
    names = ("series", "slots", "references", "visuals", "alerts", "requests", "transcript")
    owners = [getattr(destination, name) for name in names]
    with pytest.raises(PineRuntimeError, match="committed storage reference.*provisional"):
        destination.restore(forged)
    assert destination.checkpoint().to_dict() == before
    assert all(getattr(destination, name) is owner for name, owner in zip(names, owners, strict=True))
    tx = begin(destination, 1, bar=1)
    assert tx.read_series("root", 1) == root
    assert array_get(tx.references, root, 0) == 7
    tx.commit()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_two_callsites_nested_alias_history_trial_rollback_replay_new_runtime(version, compact):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0)
    handles = []
    for site in ("left", "right"):
        def initialize():
            child = counter(tx, site)
            tx.declare_reference_v1(tx.scoped_id_v1("child"), "var", lambda: child, COUNTER)
            return child
        handles.append(tx.invoke_function_v1(site, initialize, {}))
    tx.set_slot("aliases", {"left": [handles[0], handles[0]], "right": handles[1]}, owner="test")
    tx.commit()
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    increment(tx, handles[0])
    increment(tx, handles[1])
    increment(tx, handles[1])
    assert state(runtime, handles[0]) == [1, 1, 1, 1.0]
    assert state(runtime, handles[1]) == [2, 2, 2, 2.0]
    tx.abort()
    assert state(runtime, handles[0]) == [0, 1, 0, 0.0]
    assert state(runtime, handles[1]) == [0, 2, 0, 0.0]
    tx = begin(runtime, 1, bar=1, realtime=True)
    increment(tx, handles[0])
    increment(tx, handles[1])
    tx.commit()
    assert state(runtime, handles[0]) == [1, 2, 1, 1.0]
    assert state(runtime, handles[1]) == [1, 3, 1, 1.0]
    saved = portable(runtime.checkpoint().to_dict())
    restored = make()
    restored.restore(saved)
    assert restored is not runtime and restored.references is not runtime.references
    assert restored.checkpoint().to_dict() == saved
    # Incompatible source-version identity must reject without replacing owners.
    incompatible = factory(11 - version, compact)()
    before = incompatible.checkpoint().to_dict()
    names = ("series", "slots", "references", "visuals", "alerts", "requests", "transcript")
    owners = [getattr(incompatible, name) for name in names]
    with pytest.raises(PineRuntimeError, match="identity"):
        incompatible.restore(saved)
    assert incompatible.checkpoint().to_dict() == before
    assert all(getattr(incompatible, name) is owner for name, owner in zip(names, owners, strict=True))
    for current in (runtime, restored):
        tx = begin(current, 2, bar=2)
        for site, handle in zip(("left", "right"), handles, strict=True):
            observed = tx.invoke_function_v1(site, lambda: tx.read_series(tx.scoped_id_v1("child"), 1), {})
            assert observed == handle
        aliases = tx.references._decode_value(tx.state("aliases", owner="test", schema_version="1", initial={}))
        assert aliases == {"left": [handles[0], handles[0]], "right": handles[1]}
        increment(tx, aliases["left"][1])
        assert state(current, handles[0]) == [2, 3, 2, 2.0]
        assert state(current, handles[1]) == [1, 3, 1, 1.0]
        tx.commit()
    assert restored.checkpoint().to_dict() == runtime.checkpoint().to_dict()
