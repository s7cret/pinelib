"""Reference variables use the existing heap and checkpoints, with explicit roots.

Hand-derived lifecycle expectations; no external TradingView execution is implied.
"""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import (
    array_get,
    array_new,
    array_push,
    array_set,
    array_size,
    array_slice,
)
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from pinelib.runtime.reference_values import (
    collection_type,
    stored_reference,
)
from pinelib.state.checkpoint import sha


def runtime(version=6, compact=False, **resources):
    r = RuntimeSession(
        RuntimeLanguageContext(
            version,
            "refs",
            f"pine-v{version}",
            "sha256:" + "a" * 64,
            "compiler_annotation",
        ),
        RuntimePolicies(resource=replace(ResourcePolicy(), **resources)),
    )
    r.commit_full_identity = not compact
    return r


def begin(r, seq, *, realtime=False, close=False):
    return r.begin(
        CallbackFrame(
            "REALTIME_TICK" if realtime else "HISTORICAL_EVAL",
            seq,
            bar_index=1 if realtime else seq,
            realtime=realtime,
            final_tick=close if realtime else True,
        )
    )


def make(tx, site="allocation", value=0, dtype="float"):
    return array_new(tx.references, tx.new_reference_id_v1(site), dtype, 1, value)


def declare(tx, mode, value=0, name="a"):
    return tx.declare_reference_v1(
        name, mode, lambda: make(tx, name, value), "array<float>"
    )


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize("mode", ["default", "var", "varip"])
def test_reference_identity_aliases_and_history(version, mode):
    r = runtime(version)
    handles = []
    for i in range(3):
        tx = begin(r, i)
        a = declare(tx, mode, i)
        b = tx.declare_reference_v1(
            "alias", "default", lambda value=a: value, "array<float>"
        )
        assert a == b
        array_set(tx.references, b, 0, 10 + i)
        assert array_get(tx.references, a, 0) == 10 + i
        old = tx.op_series_history("a", 1)
        if i == 0:
            assert is_na(old)
        elif mode == "default":
            assert old == handles[-1] and old != a
            assert array_get(tx.references, old, 0) == 9 + i
        else:
            assert old == a and array_get(tx.references, old, 0) == 10 + i
        handles.append(a)
        tx.commit()
    assert len(set(handles)) == (3 if mode == "default" else 1)


@pytest.mark.parametrize("mode", ["var", "varip"])
def test_realtime_rollback_preserves_only_varip_heap(mode):
    r = runtime()
    tx = begin(r, 0)
    a = declare(tx, mode)
    tx.commit()
    for seq in (1, 2):
        tx = begin(r, seq, realtime=True)
        same = declare(tx, mode)
        assert same == a
        expected = seq - 1 if mode == "varip" else 0
        assert array_get(tx.references, a, 0) == expected
        array_set(tx.references, a, 0, expected + 1)
        tx.commit()  # nonclosing tick
    tx = begin(r, 3, realtime=True, close=True)
    a = declare(tx, mode)
    assert array_get(tx.references, a, 0) == (2 if mode == "varip" else 0)
    tx.commit()
    saved = json.loads(json.dumps(r.checkpoint().to_dict()))
    restored = runtime()
    restored.restore(saved)
    assert restored.checkpoint().to_dict() == saved
    assert array_get(restored.references, a, 0) == (2 if mode == "varip" else 0)


def test_varip_first_tick_initialization_and_retry_do_not_leave_dangling_or_duplicate_ids():
    r = runtime()
    tx = begin(r, 0)
    tx.commit()
    tx = begin(r, 1, realtime=True)
    first = declare(tx, "varip")
    # Survives abort just like other varip effects. A retry must allocate fresh
    # ordinary objects at the same written site, not overwrite surviving IDs.
    array_set(tx.references, first, 0, 7)
    tx.abort()
    tx = begin(r, 1, realtime=True)
    another = make(tx, "a", 9)
    assert another != first and array_get(tx.references, first, 0) == 7
    assert declare(tx, "varip") == first
    tx.commit()
    tx = begin(r, 2, realtime=True, close=True)
    assert declare(tx, "varip") == first
    tx.commit()
    restored = runtime()
    restored.restore(json.loads(json.dumps(r.checkpoint().to_dict())))
    assert restored.state_hash == r.state_hash


def test_varip_slice_retains_parent_mutations_ordinary_aliases_observe_same_object():
    r = runtime()
    tx = begin(r, 0)
    parent = array_new(tx.references, tx.new_reference_id_v1("parent"), "float", 2, 0)
    window = array_slice(tx.references, parent, 0, 1, tx.new_reference_id_v1("slice"))
    tx.declare_reference_v1("view", "varip", lambda: window, "array<float>")
    tx.declare_reference_v1("alias", "var", lambda: parent, "array<float>")
    tx.commit()
    tx = begin(r, 1, realtime=True)
    array_set(tx.references, window, 0, 5)
    tx.commit()
    tx = begin(r, 2, realtime=True, close=True)
    assert array_get(tx.references, parent, 0) == 5
    assert array_get(tx.references, window, 0) == 5
    tx.commit()


@pytest.mark.parametrize("compact", [False, True])
def test_json_restore_keeps_alias_history_and_future_allocation_identity(compact):
    def step(r, i):
        tx = begin(r, i)
        a = declare(tx, "default", i)
        p = declare(tx, "var", 0, "persist")
        array_push(tx.references, p, i)
        tx.set_series("copy", a, "array<float>")
        tx.commit()

    whole = runtime(compact=compact)
    for i in range(4):
        step(whole, i)
    split = runtime(compact=compact)
    for i in range(2):
        step(split, i)
    saved = json.loads(json.dumps(split.checkpoint().to_dict()))
    restored = runtime(compact=compact)
    restored.restore(saved)
    for i in range(2, 4):
        step(restored, i)
    assert restored.checkpoint().to_dict() == whole.checkpoint().to_dict()
    assert restored.state_hash == whole.state_hash
    assert restored.semantic_state_hash == whole.semantic_state_hash


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_series",
        "wrong_series_kind",
        "wrong_series_type",
        "unknown_slot",
        "invalid_marker",
    ],
)
def test_rehashed_checkpoint_cannot_introduce_dangling_or_mistyped_variable(fault):
    r = runtime()
    tx = begin(r, 0)
    a = declare(tx, "var")
    tx.commit()
    saved = r.checkpoint().to_dict()
    bad = deepcopy(saved)
    # Recompute outer checksum to exercise structural validation, not hash rejection.
    state = bad["state"]
    if fault == "unknown_slot":
        row = next(s for s in state["slots"] if s["owner"] == "ast2python.reference.v1")
        row["working"] = {"$pinelib_ref": {"object_id": "nonexistent", "kind": "array"}}
    elif fault == "invalid_marker":
        state["series"]["a"]["working"] = {
            "$pinelib_ref": {"object_id": a.object_id, "kind": "array", "extra": 1}
        }
    elif fault == "wrong_series_type":
        state["series"]["a"]["dtype"] = "array<string>"
    else:
        state["series"]["a"]["working"] = {
            "$pinelib_ref": {
                "object_id": "nonexistent"
                if fault == "unknown_series"
                else a.object_id,
                "kind": "array" if fault == "unknown_series" else "map",
            }
        }
    bad["content_hash"] = sha({k: v for k, v in bad.items() if k != "content_hash"})
    with pytest.raises(PineRuntimeError, match="reference|collection"):
        r.restore(bad)
    assert r.checkpoint().to_dict() == saved


@pytest.mark.parametrize(
    "dtype",
    [
        "array<unknown>",
        "array<UDT>",
        "array<array<float>>",
        "map<float>",
        "float",
        "array<float,int>",
    ],
)
def test_unknown_reference_storage_types_are_not_guessed(dtype):
    with pytest.raises(PineRuntimeError):
        collection_type(dtype)


@pytest.mark.parametrize(
    "value",
    [
        False,
        0,
        [],
        {},
        {"$pinelib_ref": {"object_id": "x"}},
        {"$pinelib_ref": {"object_id": 3, "kind": "array"}},
    ],
)
def test_invalid_stored_values_are_not_na_or_reference(value):
    with pytest.raises(PineRuntimeError):
        stored_reference(value)


def test_type_check_and_resource_limit_fail_before_series_or_slot_write():
    r = runtime()
    tx = begin(r, 0)
    a = make(tx, dtype="int")
    with pytest.raises(PineRuntimeError):
        tx.declare_reference_v1("bad", "var", lambda: a, "array<float>")
    assert "bad" not in r.series and not r.slots.contains("reference:bad")
    tx.abort()
    r = runtime(max_reference_objects=2)
    tx = begin(r, 0)
    make(tx)
    make(tx)
    with pytest.raises(PineRuntimeError, match="object limit"):
        make(tx)
    tx.abort()
    assert r.references.to_json() == {"objects": []}


def test_iterator_uses_current_size_and_bounded_budget_without_full_materialization(
    monkeypatch,
):
    r = runtime(max_loop_iterations=3)
    tx = begin(r, 0)
    a = make(tx, value=4)
    # array_size/get should project one element, not copy the entire list per step.
    monkeypatch.setattr(
        tx.references,
        "read_payload",
        lambda *_: (_ for _ in ()).throw(AssertionError("full copy")),
    )
    assert list(tx.array_iterator_v1(a, True)) == [(0, 4)]
    assert array_size(tx.references, a) == 1
    monkeypatch.undo()
    it = tx.array_iterator_v1(a)
    assert next(it) == 4
    array_push(tx.references, a, 5)
    assert next(it) == 5
    array_push(tx.references, a, 6)
    assert next(it) == 6
    array_push(tx.references, a, 7)
    with pytest.raises(PineRuntimeError, match="budget"):
        next(it)
    tx.abort()
