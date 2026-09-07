"""Object-level intrabar persistence without disabling ordinary heap rollback."""

import json
from copy import deepcopy

import pytest

from pinelib import na
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import (
    array_copy,
    array_get,
    array_new,
    array_set,
    array_slice,
)
from pinelib.reference.heap import RuntimeReferenceHeap
from pinelib.reference.map import map_get, map_new, map_put
from pinelib.reference.matrix import matrix_get, matrix_new, matrix_set
from tests.test_language_scopes_once import begin, session


def make(tx, kind, value=0):
    identity = tx.reference_id_v1("constructor")
    if kind == "array":
        return array_new(tx.references, identity, "int", 1, value)
    if kind == "matrix":
        return matrix_new(tx.references, identity, "int", 1, 1, value)
    obj = map_new(tx.references, identity, "string,int")
    map_put(tx.references, obj, "k", value)
    return obj


def read(tx, handle):
    if handle.kind == "array":
        return array_get(tx.references, handle, 0)
    if handle.kind == "matrix":
        return matrix_get(tx.references, handle, 0, 0)
    return map_get(tx.references, handle, "k")


def write(tx, handle, value):
    if handle.kind == "array":
        return array_set(tx.references, handle, 0, value)
    if handle.kind == "matrix":
        return matrix_set(tx.references, handle, 0, 0, value)
    return map_put(tx.references, handle, "k", value)


def declare(tx, kind, mode):
    typ = "map<string,int>" if kind == "map" else f"{kind}<int>"
    return tx.declare_reference_v1(mode, mode, lambda: make(tx, kind), typ)


@pytest.mark.parametrize("kind", ["array", "map", "matrix"])
@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("preexisting", [False, True])
def test_varip_changes_survive_ticks_while_var_rolls_back(kind, version, preexisting):
    s = session(version)
    if preexisting:
        tx = begin(s, 0)
        declare(tx, kind, "var")
        declare(tx, kind, "varip")
        tx.commit()
    first = 1 if preexisting else 0
    histories = []
    for tick in range(4):
        tx = begin(s, first + tick, bar=1, realtime=True, final=tick == 3)
        ordinary, persistent = declare(tx, kind, "var"), declare(tx, kind, "varip")
        for handle in (ordinary, persistent):
            write(tx, handle, read(tx, handle) + 1)
        histories.append((read(tx, ordinary), read(tx, persistent)))
        tx.commit()
    assert histories == [(1, 1), (1, 2), (1, 3), (1, 4)]
    tx = begin(s, first + 4, bar=2)
    assert read(tx, declare(tx, kind, "var")) == 1
    assert read(tx, declare(tx, kind, "varip")) == 4
    tx.abort()


@pytest.mark.parametrize("kind", ["array", "map", "matrix"])
def test_deferred_bar_callbacks_use_same_preservation_policy_as_scalar_varip(kind):
    s = session()
    for seq in range(3):
        tx = begin(s, seq, bar=0, deferred=True)
        h = declare(tx, kind, "varip")
        write(tx, h, read(tx, h) + 1)
        tx.commit()
    s.finalize_bar(0)
    tx = begin(s, s.sequence + 1, bar=1, deferred=True)
    assert read(tx, declare(tx, kind, "varip")) == 3
    tx.abort()


@pytest.mark.parametrize("kind", ["array", "map", "matrix"])
def test_historical_abort_does_not_commit_promotion_or_allocation(kind):
    s = session()
    before = s.checkpoint().to_dict()
    tx = begin(s, 0)
    h = declare(tx, kind, "varip")
    write(tx, h, 9)
    tx.abort()
    assert s.checkpoint().to_dict() == before


def test_alias_observes_same_object_policy_but_copy_remains_ordinary():
    s = session()
    tx = begin(s, 0)
    a = tx.declare_reference_v1("a", "var", lambda: make(tx, "array"), "array<int>")
    tx.declare_reference_v1("p", "varip", lambda: a, "array<int>")
    c = array_copy(tx.references, a, tx.reference_id_v1("copy"))
    tx.commit()
    tx = begin(s, 1, bar=1, realtime=True, final=False)
    write(tx, a, 7)
    write(tx, c, 8)
    tx.commit()
    tx = begin(s, 2, bar=1, realtime=True)
    assert read(tx, a) == 7
    assert read(tx, c) == 0
    tx.abort()


def test_slice_promotes_backing_and_mutations_through_either_alias_persist():
    s = session()
    tx = begin(s, 0)
    a = array_new(tx.references, "base", "int", 3, 0)
    window = array_slice(tx.references, a, 1, 3, "slice")
    tx.declare_reference_v1("p", "varip", lambda: window, "array<int>")
    tx.commit()
    tx = begin(s, 1, bar=1, realtime=True, final=False)
    array_set(tx.references, a, 1, 7)
    array_set(tx.references, window, 1, 8)
    tx.commit()
    tx = begin(s, 2, bar=1, realtime=True)
    assert tx.references.read_payload(a) == [0, 7, 8]
    assert tx.references.read_payload(window) == [7, 8]
    tx.abort()


@pytest.mark.parametrize("kind", ["array", "map", "matrix"])
def test_reassignment_preserves_new_object_and_previous_history_identity(kind):
    s = session()
    typ = "map<string,int>" if kind == "map" else f"{kind}<int>"
    tx = begin(s, 0)
    old = declare(tx, kind, "varip")
    tx.commit()
    tx = begin(s, 1, bar=1, realtime=True, final=False)
    new = make(tx, kind, 10)
    tx.write_reference_v1("varip", "varip", new, typ)
    write(tx, old, 5)
    tx.commit()
    tx = begin(s, 2, bar=1, realtime=True)
    assert declare(tx, kind, "varip") == new
    assert read(tx, new) == 10 and read(tx, old) == 5
    assert tx.op_series_history("varip", 1) == old
    tx.commit()


@pytest.mark.parametrize("kind", ["array", "map", "matrix"])
def test_json_checkpoint_resumes_persistent_and_ordinary_policies(kind):
    s = session()
    for seq in range(2):
        tx = begin(s, seq, bar=0, realtime=True, final=seq == 1)
        for mode in ("var", "varip"):
            h = declare(tx, kind, mode)
            write(tx, h, read(tx, h) + 1)
        tx.commit()
    saved = json.loads(json.dumps(s.checkpoint().to_dict()))
    restored = session()
    restored.restore(saved)
    assert restored.checkpoint().to_dict() == saved
    for runtime in (s, restored):
        for seq in (2, 3):
            tx = begin(runtime, seq, bar=1, realtime=True, final=seq == 3)
            for mode in ("var", "varip"):
                h = declare(tx, kind, mode)
                write(tx, h, read(tx, h) + 1)
            tx.commit()
    assert restored.state_hash == s.state_hash
    assert restored.semantic_state_hash == s.semantic_state_hash


@pytest.mark.parametrize(
    "dtype,value",
    [
        ("int", 1),
        ("float", 1.25),
        ("bool", False),
        ("string", ""),
        ("color", "#aaff00"),
        ("float", na),
    ],
)
def test_admitted_fundamental_values(dtype, value):
    tx = begin(session(), 0)
    h = array_new(tx.references, "a", dtype, 1, value)
    assert tx.declare_reference_v1("p", "varip", lambda: h, f"array<{dtype}>") == h
    tx.abort()


@pytest.mark.parametrize("kind", ["array", "matrix", "map"])
@pytest.mark.parametrize(
    "value", [None, True, "bad", {"$pinelib_ref": {"object_id": "a", "kind": "array"}}]
)
def test_wrong_typed_mutation_is_atomic(kind, value):
    tx = begin(session(), 0)
    h = declare(tx, kind, "varip")
    before = tx.references.to_json()
    with pytest.raises(PineRuntimeError):
        write(tx, h, value)
    assert tx.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("descriptor", ["label", "array<int>", "Point", "any"])
def test_unsupported_varip_element_type_rejected_even_for_empty_array(descriptor):
    tx = begin(session(), 0)
    h = array_new(tx.references, "a", descriptor, 0, na)
    before = tx.references.to_json()
    with pytest.raises(PineRuntimeError):
        tx.declare_reference_v1("p", "varip", lambda: h, f"array<{descriptor}>")
    assert tx.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize(
    "fault",
    ["flag_type", "no_working", "bad_element", "missing_backing", "old_version"],
)
def test_corrupt_heap_policy_cannot_silently_be_restored(fault):
    tx = begin(session(), 0)
    a = array_new(tx.references, "base", "int", 3, 0)
    window = array_slice(tx.references, a, 0, 2, "slice")
    tx.references.retain_intrabar(window)
    tx.commit()
    raw = deepcopy(tx.session.references.to_json())
    item = raw["objects"][0]
    version = 6
    if fault == "flag_type":
        item["intrabar_persistence"]["committed"] = 1
    elif fault == "no_working":
        item["intrabar_persistence"]["working"] = False
    elif fault == "bad_element":
        item["working"][0] = "bad"
    elif fault == "missing_backing":
        item.pop("intrabar_persistence")
    else:
        version = 4
    with pytest.raises(PineRuntimeError):
        RuntimeReferenceHeap.from_json(
            raw, session(version).language, max_objects=100, max_elements=100
        )


def test_ordinary_heap_export_retains_existing_format():
    tx = begin(session(), 0)
    make(tx, "array")
    assert all(
        "intrabar_persistence" not in row for row in tx.references.to_json()["objects"]
    )
    tx.abort()


@pytest.mark.parametrize(
    "fault", ["lost_policy", "wrong_kind", "missing_object", "lost_committed_policy"]
)
def test_rehashed_invalid_varip_slot_heap_relationship_does_not_replace_session(fault):
    from pinelib.state.checkpoint import RuntimeCheckpoint

    s = session()
    tx = begin(s, 0)
    declare(tx, "array", "varip")
    tx.commit()
    saved = s.checkpoint().to_dict()
    bad = deepcopy(saved)
    row = bad["state"]["references"]["objects"][0]
    if fault == "lost_policy":
        row.pop("intrabar_persistence")
    elif fault == "lost_committed_policy":
        row["intrabar_persistence"]["committed"] = False
    elif fault == "wrong_kind":
        bad["state"]["slots"][0]["working"]["$pinelib_ref"]["kind"] = "matrix"
    else:
        bad["state"]["references"]["objects"] = []
    bad = RuntimeCheckpoint.seal(s.identity_hash, bad["state"]).to_dict()
    with pytest.raises(PineRuntimeError):
        s.restore(bad)
    assert s.checkpoint().to_dict() == saved
