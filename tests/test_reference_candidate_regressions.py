"""Preserved candidate checks against the current single reference owner.

Source: 861ced1, tests/test_reference_language_state.py and
tests/test_reference_variable_storage.py. Only API names are adapted. No
alternative reference binding mixin or old manifest is introduced.
"""

from copy import deepcopy

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_get, array_new, array_set
from pinelib.state.checkpoint import RuntimeCheckpoint
from tests.test_language_scopes_once import begin, session


def create(tx, value=0.0):
    return array_new(tx.references, tx.reference_id_v1("create"), "float", 1, value)


def test_new_varip_object_survives_abort_and_same_callback_retry_without_collision():
    s = session()
    tx = begin(s, 0, bar=0, realtime=True, final=False)
    first = tx.declare_reference_v1("a", "varip", lambda: create(tx, 7.0), "array<float>")
    scratch = create(tx, 99.0)
    tx.abort()
    tx = begin(s, 0, bar=0, realtime=True, final=True)
    retained = tx.declare_reference_v1("a", "varip", lambda: 1 / 0, "array<float>")
    assert retained == first
    assert array_get(tx.references, retained, 0) == 7
    second = create(tx, 2.0)
    assert second != first
    assert second == scratch
    tx.commit()


def test_ordinary_aborted_allocations_replay_deterministically():
    s = session()
    tx = begin(s, 0)
    expected = [create(tx, float(i)) for i in range(3)]
    tx.abort()
    tx = begin(s, 0)
    actual = [create(tx, float(i)) for i in range(3)]
    assert expected == actual and len(set(actual)) == 3
    tx.commit()


@pytest.mark.parametrize("kind", ["array", "udt"])
def test_varip_retry_without_reexecuting_initializer_keeps_prior_object(kind):
    s = session()
    dtype = "array<float>" if kind == "array" else "udt:source:Point"
    def make(tx):
        return (create(tx) if kind == "array" else tx.new_udt_v1(tx.reference_id_v1("create"), dtype,
                {"n": 0}, field_types={"n": "int"}, varip_fields=("n",)))
    tx = begin(s, 0, realtime=True, final=False)
    first = tx.declare_reference_v1("a", "varip", lambda: make(tx), dtype)
    if kind == "array":
        array_set(tx.references, first, 0, 7.0)
    else:
        tx.set_udt_field_v1(first, "n", 7)
    tx.abort()
    tx = begin(s, 0, realtime=True, final=True)
    another = make(tx)
    assert another != first
    assert tx.declare_reference_v1("a", "varip", lambda: 1 / 0, dtype) == first
    assert (array_get(tx.references, first, 0) if kind == "array" else tx.get_udt_field_v1(first, "n")) == 7
    tx.commit()
    restored = session()
    restored.restore(s.checkpoint().to_dict())
    assert restored.state_hash == s.state_hash


@pytest.mark.parametrize("fault", ["unknown_series", "wrong_series_kind", "wrong_series_type", "unknown_slot", "invalid_marker"])
def test_rehashed_checkpoint_cannot_introduce_dangling_or_mistyped_variable(fault):
    s = session()
    tx = begin(s, 0)
    a = tx.declare_reference_v1("a", "var", lambda: create(tx), "array<float>")
    tx.commit()
    saved = s.checkpoint().to_dict()
    state = deepcopy(saved["state"])
    if fault == "unknown_slot":
        state["slots"][0]["working"] = {"$pinelib_ref": {"object_id": "nonexistent", "kind": "array"}}
    elif fault == "invalid_marker":
        state["series"]["a"]["working"] = {"$pinelib_ref": {"object_id": a.object_id, "kind": "array", "extra": 1}}
    elif fault == "wrong_series_type":
        state["series"]["a"]["dtype"] = "array<string>"
    else:
        state["series"]["a"]["working"] = {"$pinelib_ref": {"object_id": "nonexistent" if fault == "unknown_series" else a.object_id,
                                                              "kind": "array" if fault == "unknown_series" else "map"}}
    with pytest.raises(PineRuntimeError, match="reference|collection"):
        s.restore(RuntimeCheckpoint.seal(s.identity_hash, state).to_dict())
    assert s.checkpoint().to_dict() == saved
