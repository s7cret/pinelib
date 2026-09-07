"""Independent state-owner regression: abort preserves state, not sequence.

The historical/trial/abort/retry trace was reproduced on published c90c267 and
the registry candidate before this fix. No checksum assertion is relaxed.
"""

from copy import deepcopy
import json

import pytest

from pinelib import CallbackFrame, RuntimeSession
from pinelib.errors import PineRuntimeError
from pinelib.runtime.semantic import semantic_state_digest
from pinelib.state.checkpoint import RuntimeCheckpoint, sha
from pinelib.reference.udt import udt_get
from tests.test_language_scopes_once import begin, session as plain_session
from tests.test_nominal_registry_runtime import registry, NODE


def values(runtime, handle):
    return [udt_get(runtime.references, handle, field) for field in ("n", "ticks")]


def fixture(version, compact, mode):
    # The schema is authored here so the expected varip field is explicit.
    from pinelib.reference.registry import NominalTypeRegistry
    payload = registry(version).to_json()
    dtype = NODE + ":abort-counter"
    payload["types"].append({"id": dtype, "kind": "udt", "fields": [
        {"name": "n", "type": "int", "varip": False},
        {"name": "ticks", "type": "int", "varip": True},
    ]})
    payload["types"].sort(key=lambda row: row["id"])
    admitted = NominalTypeRegistry.from_json(payload, pine_version=version, expected_source_hash=payload["source_hash"])

    def make():
        runtime = RuntimeSession(plain_session(version).language, nominal_registry=admitted)
        runtime.commit_full_identity = not compact
        return runtime

    runtime = make()
    tx = begin(runtime, 0, bar=0)
    handle = tx.new_udt_v1("counter", dtype, {"n": 0, "ticks": 0},
        field_types={"n": "int", "ticks": "int"}, varip_fields=("ticks",))
    tx.declare_reference_v1("root", mode, lambda: handle, dtype)
    tx.commit()
    return runtime, handle, dtype, make


def attempt(runtime, handle, dtype, mode, *, abort=False, final=False):
    tx = begin(runtime, runtime.sequence + 1, bar=1, realtime=True, final=final)
    assert tx.declare_reference_v1("root", mode, lambda: None, dtype) == handle
    n, ticks = values(runtime, handle)
    tx.set_udt_field_v1(handle, "n", n + 1)
    tx.set_udt_field_v1(handle, "ticks", ticks + 1)
    return tx.abort() if abort else tx.commit()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("mode", ["var", "varip"])
def test_post_abort_checkpoint_restores_retained_fields_before_same_sequence_retry(version, compact, mode):
    runtime, handle, dtype, make = fixture(version, compact, mode)
    initial = runtime.checkpoint().to_dict()
    clone = make()
    clone.restore(initial)
    assert clone.checkpoint().to_dict() == initial
    assert values(runtime, handle) == [0, 0]

    attempt(runtime, handle, dtype, mode)
    assert values(runtime, handle) == [1, 1]
    successful = deepcopy(runtime.transcript.to_dict())
    result = attempt(runtime, handle, dtype, mode, abort=True)
    assert result.aborted and not result.committed
    assert runtime.sequence == 1
    assert values(runtime, handle) == [0, 2]
    assert runtime.transcript.to_dict() == successful

    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    assert saved["schema_version"] == "1.1.0"
    assert saved["state"]["pending_abort"]["attempts"][-1]["frame"]["sequence"] == 2
    clone = make()
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    assert clone.sequence == 1
    assert values(clone, handle) == [0, 2]
    assert clone.transcript.to_dict() == successful
    for current in (runtime, clone):
        attempt(current, handle, dtype, mode, final=True)
        assert current.sequence == 2
        assert values(current, handle) == [1, 3]
        assert [entry["sequence"] for entry in current.transcript.entries] == [0, 1, 2]
        assert list(current.transcript.entries)[:2] == successful["entries"]
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


def reseal_pending(runtime, state, *, refresh_state_hash=True, version="1.1.0"):
    """An attacker can reseal integrity hashes; preserve the successful transcript."""
    from pinelib.events import AlertTape, VisualTape
    from pinelib.reference import RuntimeReferenceHeap
    from pinelib.request import RequestEngine
    from pinelib.state.series import SeriesStorage
    from pinelib.state.slots import StateSlotRegistry
    if refresh_state_hash and isinstance(state.get("pending_abort"), dict):
        if runtime.commit_full_identity:
            digest = sha({key: value for key, value in state.items() if key not in ("transcript", "pending_abort")})
        else:
            limits = runtime.policies.resource
            requests = RequestEngine(runtime.language, runtime.policies, runtime.requests.provider)
            requests.bind_parent_identity(runtime.identity_hash)
            requests.restore(state["requests"])
            digest = semantic_state_digest(runtime.identity_hash, state["sequence"],
                {key: SeriesStorage.from_json(row) for key, row in state["series"].items()},
                StateSlotRegistry.from_json(state["slots"], limits.max_state_slots),
                RuntimeReferenceHeap.from_json(state["references"], runtime.language,
                    max_objects=limits.max_reference_objects, max_elements=limits.max_collection_elements,
                    nominal_registry=runtime.nominal_registry),
                VisualTape.from_json(state["visuals"], limits.max_visual_events),
                AlertTape.from_json(state["alerts"], limits.max_alert_events), requests)
        state["pending_abort"]["state_hash"] = digest
    return RuntimeCheckpoint.seal(runtime.identity_hash, state, schema_version=version).to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("corruption", ["missing", "null", "extra", "old_version", "bad_anchor", "algorithm",
    "bad_state_hash", "missing_frame_field", "extra_frame_field", "bool_sequence", "old_sequence",
    "successful_state_extra", "successful_history", "current_history", "ordinary_working",
    "ordinary_heap_working", "committed_heap", "new_committed_object"])
def test_resealed_pending_abort_corruption_rejects_atomically(version, compact, corruption):
    runtime, handle, dtype, make = fixture(version, compact, "varip")
    attempt(runtime, handle, dtype, "varip")
    attempt(runtime, handle, dtype, "varip", abort=True)
    before = runtime.checkpoint().to_dict()
    state = deepcopy(before["state"])
    record = state["pending_abort"]
    schema_version = "1.1.0"
    if corruption == "missing": del state["pending_abort"]
    elif corruption == "null": state["pending_abort"] = None
    elif corruption == "extra": record["forged"] = True
    elif corruption == "old_version": schema_version = "1.0.0"
    elif corruption == "bad_anchor": record["transcript_hash"] = "sha256:" + "0" * 64
    elif corruption == "algorithm": record["state_hash_algorithm"] = "forged"
    elif corruption == "bad_state_hash": record["state_hash"] = "sha256:" + "0" * 64
    elif corruption == "missing_frame_field": del record["attempts"][-1]["frame"]["defer_bar_commit"]
    elif corruption == "extra_frame_field": record["attempts"][-1]["frame"]["forged"] = True
    elif corruption == "bool_sequence": record["attempts"][-1]["frame"]["sequence"] = True
    elif corruption == "old_sequence": record["attempts"][-1]["frame"]["sequence"] = state["sequence"]
    elif corruption == "successful_state_extra": record["successful_state"]["transcript"] = state["transcript"]
    elif corruption == "successful_history": record["successful_state"]["series"]["root"]["revision"] += 1
    elif corruption == "current_history":
        state["series"]["root"]["revision"] += 1
        state["series"]["root"]["committed"].append(deepcopy(state["series"]["root"]["committed"][-1]))
    elif corruption == "ordinary_working": state["series"]["root"]["working"] = None
    elif corruption == "ordinary_heap_working": state["references"]["objects"][0]["working"]["n"] = 99
    elif corruption == "committed_heap":
        for heap in (state["references"], record["attempts"][-1]["attempted_state"]["references"]):
            heap["objects"][0]["committed"]["n"] = 99
        state["references"]["objects"][0]["working"]["n"] = 99
    elif corruption == "new_committed_object":
        obj = deepcopy(record["attempts"][-1]["attempted_state"]["references"]["objects"][0])
        obj["object_id"] = "forged-committed"
        record["attempts"][-1]["attempted_state"]["references"]["objects"].append(obj)
    forged = reseal_pending(runtime, state, refresh_state_hash=corruption != "bad_state_hash", version=schema_version)
    owners = tuple(getattr(runtime, name) for name in ("series", "slots", "references", "requests", "transcript"))
    with pytest.raises(PineRuntimeError):
        runtime.restore(forged)
    assert runtime.checkpoint().to_dict() == before
    assert all(owner is getattr(runtime, name) for owner, name in zip(
        owners, ("series", "slots", "references", "requests", "transcript"), strict=True))


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("kind", ["enum", "udt"])
@pytest.mark.parametrize("deferred", [False, True])
def test_first_typed_varip_abort_preserves_declaration_and_same_sequence_retry(version, compact, kind, deferred):
    from tests.test_nominal_registry_runtime import E
    runtime, _, dtype, make = fixture(version, compact, "varip")
    runtime = make()
    tx = begin(runtime, 7, bar=0, realtime=not deferred, deferred=deferred)
    if kind == "enum":
        initial = tx.enum_value_v1(E, "buy", 0)
        value = tx.enum_value_v1(E, "sell", 1)
        tx.declare_enum_v1("first", "varip", lambda: initial, E)
        tx.write_enum_v1("first", "varip", value, E)
    else:
        value = tx.new_udt_v1("first", dtype, {"n": 1, "ticks": 1},
            field_types={"n": "int", "ticks": "int"}, varip_fields=("ticks",))
        tx.declare_reference_v1("first", "varip", lambda: value, dtype)
        tx.set_udt_field_v1(value, "n", 9)
        tx.set_udt_field_v1(value, "ticks", 2)
    tx.abort()
    saved = runtime.checkpoint().to_dict()
    assert runtime.sequence == -1 and not runtime.transcript.entries
    assert "first" in saved["state"]["series"]
    clone = make()
    clone.restore(json.loads(json.dumps(saved)))
    assert clone.checkpoint().to_dict() == saved
    def never():
        raise AssertionError("retained binding initializer reran")
    for current in (runtime, clone):
        tx = begin(current, 7, bar=0, realtime=not deferred, deferred=deferred)
        if kind == "enum": assert tx.declare_enum_v1("first", "varip", never, E) == value
        else:
            assert tx.declare_reference_v1("first", "varip", never, dtype) == value
            assert values(current, value) == [1, 2]
        tx.commit()
        if deferred: current.finalize_bar(0)
        assert current.checkpoint().schema_version == "1.1.0"
        assert "pending_abort" not in current.checkpoint().state
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_empty_deferred_abort_retains_mode_and_native_sequence_gap(version, compact):
    runtime = plain_session(version)
    runtime.commit_full_identity = not compact
    begin(runtime, 9, bar=0, deferred=True).abort()
    saved = runtime.checkpoint().to_dict()
    clone = plain_session(version)
    clone.restore(saved)
    for current in (runtime, clone):
        with pytest.raises(PineRuntimeError, match="bar commit mode"):
            begin(current, 9, bar=0)
        begin(current, 9, bar=0, deferred=True).commit()
        current.finalize_bar(0)
        assert [entry["sequence"] for entry in current.transcript.entries] == [9, 10]
        assert current.checkpoint().schema_version == "1.1.0"
        assert "pending_abort" not in current.checkpoint().state
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_repeated_abort_reuses_successful_proof_and_latest_attempt(version, compact):
    runtime, handle, dtype, make = fixture(version, compact, "varip")
    attempt(runtime, handle, dtype, "varip")
    attempt(runtime, handle, dtype, "varip", abort=True)
    proof = deepcopy(runtime.checkpoint().state["pending_abort"]["successful_state"])
    clone = make()
    clone.restore(runtime.checkpoint().to_dict())
    for current in (runtime, clone):
        attempt(current, handle, dtype, "varip", abort=True)
        assert values(current, handle) == [0, 3]
        assert current.sequence == 1
        assert current.checkpoint().state["pending_abort"]["successful_state"] == proof
        restored = make()
        restored.restore(current.checkpoint().to_dict())
        assert restored.checkpoint().to_dict() == current.checkpoint().to_dict()
        attempt(current, handle, dtype, "varip", final=True)
        assert values(current, handle) == [1, 4]
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()
@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("mode", ["var", "varip"])
def test_retry_final_commit_control_has_an_unchanged_valid_checkpoint(version, compact, mode):
    runtime, handle, dtype, make = fixture(version, compact, mode)
    attempt(runtime, handle, dtype, mode)
    attempt(runtime, handle, dtype, mode, abort=True)
    attempt(runtime, handle, dtype, mode, final=True)
    assert runtime.sequence == 2
    assert values(runtime, handle) == [1, 3]
    saved = runtime.checkpoint().to_dict()
    assert saved["schema_version"] == "1.1.0"
    assert "pending_abort" not in saved["state"]
    clone = make()
    clone.restore(json.loads(json.dumps(saved)))
    assert clone.checkpoint().to_dict() == saved


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_deferred_abort_after_provisional_success_preserves_publication_boundary(version, compact):
    runtime = plain_session(version)
    runtime.commit_full_identity = not compact
    tx = begin(runtime, 0, bar=0, deferred=True)
    tx.declare_scalar_v1("n", "var", lambda: 0, "int")
    tx.declare_scalar_v1("ticks", "varip", lambda: 0, "int")
    tx.commit()
    runtime.finalize_bar(0)
    for sequence, abort in ((2, False), (3, True)):
        tx = begin(runtime, sequence, bar=1, realtime=True, deferred=True)
        n = tx.declare_scalar_v1("n", "var", lambda: None, "int")
        ticks = tx.declare_scalar_v1("ticks", "varip", lambda: None, "int")
        tx.write_scalar_v1("n", "var", n + 1, "int")
        tx.write_scalar_v1("ticks", "varip", ticks + 1, "int")
        tx.abort() if abort else tx.commit()
    saved = runtime.checkpoint().to_dict()
    clone = plain_session(version)
    clone.restore(saved)
    for current in (runtime, clone):
        assert current._last_published_bar == 0
        assert current.sequence == 2 and current._deferred_mode is True
        with pytest.raises(PineRuntimeError, match="published bar"):
            begin(current, 3, bar=0, deferred=True)
        tx = begin(current, 3, bar=1, realtime=True, deferred=True)
        assert tx.declare_scalar_v1("n", "var", lambda: None, "int") == 0
        assert tx.declare_scalar_v1("ticks", "varip", lambda: None, "int") == 2
        tx.commit()
        with pytest.raises(PineRuntimeError, match="provisional"):
            current.checkpoint()
        current.finalize_bar(1)
        assert current.checkpoint().schema_version == "1.1.0"
        assert "pending_abort" not in current.checkpoint().state
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_one_pass_retained_orphan_allocation_restores_without_a_second_rollback(version, compact):
    from pinelib.reference.array import array_new
    from pinelib.reference.registry import NominalTypeRegistry
    payload = registry(version).to_json()
    dtype = NODE + ":array-parent"
    payload["types"].append({"id": dtype, "kind": "udt", "fields": [
        {"name": "samples", "type": "array<int>", "varip": False}]})
    payload["types"].sort(key=lambda row: row["id"])
    admitted = NominalTypeRegistry.from_json(payload, pine_version=version, expected_source_hash=payload["source_hash"])
    def make():
        result = RuntimeSession(plain_session(version).language, nominal_registry=admitted)
        result.commit_full_identity = not compact
        return result
    runtime = make()
    tx = begin(runtime, 0)
    original = array_new(tx.references, "original", "int", 1, 0)
    parent = tx.new_udt_v1("parent", dtype, {"samples": original}, field_types={"samples": "array<int>"})
    tx.declare_reference_v1("parent", "varip", lambda: parent, dtype)
    tx.commit()
    tx = begin(runtime, 1, realtime=True)
    temporary = array_new(tx.references, "temporary", "int", 1, 9)
    tx.set_udt_field_v1(parent, "samples", temporary)
    tx.abort()
    assert udt_get(runtime.references, parent, "samples") == original
    assert {row["object_id"] for row in runtime.references.to_json()["objects"]} == {"parent", "original", "temporary"}
    clone = make()
    clone.restore(runtime.checkpoint().to_dict())
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()
    for current in (runtime, clone):
        tx = begin(current, 1, realtime=True)
        assert not current.references.contains("temporary")
        tx.commit()
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("parent_full", [False, True])
@pytest.mark.parametrize("child_full", [False, True])
def test_real_compiled_request_child_pending_abort_admits_and_rejects_atomically(version, parent_full, child_full):
    from tests.test_nominal_registry_request_restore import (
        fixture as request_fixture, checkpoint_with, reseal_state, assert_atomic_rejection, Child)
    runtime, children = request_fixture(version, full=parent_full)
    child = next(iter(children.values()))
    child.restore(reseal_state(child, deepcopy(child.checkpoint().state), full=child_full))
    tx = begin(child, child.sequence + 1, realtime=True)
    tx.declare_scalar_v1("ticks", "varip", lambda: 3, "int")
    tx.write_scalar_v1("ticks", "varip", 4, "int")
    tx.abort()
    saved = child.checkpoint().to_dict()
    assert saved["schema_version"] == "1.1.0"
    parent_saved = checkpoint_with(runtime, saved)
    calls, evaluations = runtime.requests.provider.calls, Child.evaluations
    runtime.restore(json.loads(json.dumps(parent_saved)))
    assert runtime.checkpoint().to_dict() == parent_saved
    assert (runtime.requests.provider.calls, Child.evaluations) == (calls, evaluations)
    forged = deepcopy(saved)
    forged["state"]["pending_abort"]["transcript_hash"] = "sha256:" + "0" * 64
    forged = reseal_pending(child, forged["state"])
    assert_atomic_rejection(runtime, checkpoint_with(runtime, forged), "pending abort")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("realtime", [False, True])
def test_no_effect_nondeferred_abort_rolls_back_transient_mode(version, compact, realtime):
    runtime = plain_session(version)
    runtime.commit_full_identity = not compact
    pristine = runtime.checkpoint().to_dict()
    begin(runtime, 0, bar=0, realtime=realtime).abort()
    saved = runtime.checkpoint().to_dict()
    assert saved["schema_version"] == "1.0.0"
    assert "pending_abort" not in saved["state"]
    assert runtime._deferred_mode is None
    if not compact:
        assert saved == pristine
    clone = plain_session(version)
    clone.restore(saved)
    for current in (runtime, clone):
        begin(current, 0, bar=0, deferred=True).commit()
        current.finalize_bar(0)
    assert runtime.checkpoint().to_dict() == clone.checkpoint().to_dict()
