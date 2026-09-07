"""Ordered abort witnesses and exact live checkpoint-resource admission."""

from copy import deepcopy
from dataclasses import replace

import pytest

from pinelib import RuntimeSession
from pinelib.errors import PL_RESOURCE_LIMIT, PineRuntimeError
from pinelib.reference.array import array_new
from pinelib.reference.registry import NominalTypeRegistry
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from pinelib.state.checkpoint import canonical_json
from tests.test_language_scopes_once import begin, session
from tests.test_nominal_registry_runtime import E, NODE, registry
from tests.test_varip_abort_checkpoint import fixture, reseal_pending


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_repeated_abort_collects_previous_provisional_temporary_reference(version, compact):
    payload = registry(version).to_json()
    dtype = NODE + ":repeated-orphan"
    payload["types"].append({"id": dtype, "kind": "udt", "fields": [
        {"name": "samples", "type": "array<int>", "varip": False}]})
    payload["types"].sort(key=lambda row: row["id"])
    admitted = NominalTypeRegistry.from_json(payload, pine_version=version, expected_source_hash=payload["source_hash"])
    def make():
        runtime = RuntimeSession(session(version).language, nominal_registry=admitted)
        runtime.commit_full_identity = not compact
        return runtime
    runtime = make()
    tx = begin(runtime, 0, bar=0)
    original = array_new(tx.references, "original", "int", 1, 0)
    parent = tx.new_udt_v1("parent", dtype, {"samples": original}, field_types={"samples": "array<int>"})
    tx.declare_reference_v1("parent", "varip", lambda: parent, dtype)
    tx.commit()
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    temporary = array_new(tx.references, "temporary", "int", 1, 9)
    tx.set_udt_field_v1(parent, "samples", temporary)
    tx.commit()
    successful = deepcopy(runtime.transcript.to_dict())
    for count in (1, 2, 3):
        begin(runtime, 2, bar=1, realtime=True).abort()
        assert not runtime.references.contains("temporary")
        assert runtime.transcript.to_dict() == successful
        saved = runtime.checkpoint().to_dict()
        assert len(saved["state"]["pending_abort"]["attempts"]) == count
        clone = make()
        clone.restore(saved)
        assert clone.checkpoint().to_dict() == saved
    for current in (runtime, clone):
        begin(current, 2, bar=1, realtime=True).commit()
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("corruption", ["empty", "null", "extra", "drop_first", "reorder",
    "extra_new_series", "missing_new_series", "duplicate_new_series", "invent_committed_slot",
    "change_committed_slot", "change_attempt_history"])
def test_resealed_ordered_witness_corruption_rejects_without_mutating_live_state(version, compact, corruption):
    runtime, handle, dtype, _ = fixture(version, compact, "varip")
    for index in (1, 2):
        tx = begin(runtime, 1, bar=1, realtime=True)
        tx.set_udt_field_v1(handle, "ticks", index)
        tx.declare_enum_v1("fresh-" + str(index), "varip", lambda: tx.enum_value_v1(E, "buy", 0), E)
        tx.abort()
    before = runtime.checkpoint().to_dict()
    state = deepcopy(before["state"])
    records = state["pending_abort"]["attempts"]
    if corruption == "empty": state["pending_abort"]["attempts"] = []
    elif corruption == "null": state["pending_abort"]["attempts"] = None
    elif corruption == "extra": records[0]["extra"] = True
    elif corruption == "drop_first": records.pop(0)
    elif corruption == "reorder": records.reverse()
    elif corruption == "extra_new_series": records[0]["new_series"].append("root")
    elif corruption == "missing_new_series": records[0]["new_series"] = []
    elif corruption == "duplicate_new_series": records[0]["new_series"] *= 2
    elif corruption == "invent_committed_slot":
        row = next(row for row in records[0]["attempted_state"]["slots"] if row["state_id"] == "enum-binding:fresh-1")
        row["committed_exists"] = True
    elif corruption == "change_committed_slot":
        row = next(row for row in records[0]["attempted_state"]["slots"] if row["state_id"] == "reference-binding:root")
        row["schema_version"] = "forged"
    elif corruption == "change_attempt_history":
        row = records[0]["attempted_state"]["series"]["root"]
        row["committed"].append(deepcopy(row["committed"][-1]))
        row["revision"] += 1
    with pytest.raises(PineRuntimeError):
        runtime.restore(reseal_pending(runtime, state))
    assert runtime.checkpoint().to_dict() == before


def resource_runtime(version, compact, limit=16 * 1024 * 1024):
    policies = RuntimePolicies(resource=replace(ResourcePolicy(), max_checkpoint_bytes=limit))
    runtime = session(version, policies)
    runtime.commit_full_identity = not compact
    tx = begin(runtime, 0, bar=0)
    tx.declare_scalar_v1("memory", "varip", lambda: "seed", "string")
    tx.commit()
    return runtime


def resource_attempt(runtime, index=1):
    tx = begin(runtime, 1, bar=1, realtime=True)
    tx.write_scalar_v1("memory", "varip", str(index) + ":" + "Ж" * 256, "string")
    array_new(tx.references, "new-uncommitted", "int", 1, index)
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_live_witness_budget_matches_exact_canonical_checkpoint_bytes(version, compact, delta):
    probe = resource_runtime(version, compact)
    resource_attempt(probe)
    required = len(canonical_json(probe.checkpoint().to_dict()))
    runtime = resource_runtime(version, compact, required + delta)
    before = runtime.checkpoint().to_dict()
    owners = tuple(getattr(runtime, key) for key in ("series", "slots", "references", "requests", "transcript"))
    if delta < 0:
        with pytest.raises(PineRuntimeError) as caught:
            resource_attempt(runtime)
        assert caught.value.code == PL_RESOURCE_LIMIT
        assert runtime.checkpoint().to_dict() == before
        assert all(owner is getattr(runtime, key) for owner, key in zip(owners,
            ("series", "slots", "references", "requests", "transcript"), strict=True))
        assert runtime._active is None and runtime.sequence == 0
        assert not runtime.references.contains("new-uncommitted")
        with pytest.raises(PineRuntimeError) as caught:
            runtime.restore(probe.checkpoint().to_dict())
        assert caught.value.code == PL_RESOURCE_LIMIT
        assert runtime.checkpoint().to_dict() == before
    else:
        resource_attempt(runtime)
        assert len(canonical_json(runtime.checkpoint().to_dict())) == required
    saved = runtime.checkpoint().to_dict()
    clone = resource_runtime(version, compact, required + delta)
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_repeated_resource_rejections_keep_previous_valid_pending_proof(version, compact):
    probe = resource_runtime(version, compact)
    resource_attempt(probe, 1)
    resource_attempt(probe, 2)
    limit = len(canonical_json(probe.checkpoint().to_dict()))
    runtime = resource_runtime(version, compact, limit)
    resource_attempt(runtime, 1)
    resource_attempt(runtime, 2)
    before = runtime.checkpoint().to_dict()
    byte_count = runtime._pending_abort_attempt_bytes
    for _ in range(5):
        with pytest.raises(PineRuntimeError) as caught:
            resource_attempt(runtime, 3)
        assert caught.value.code == PL_RESOURCE_LIMIT
        assert runtime.checkpoint().to_dict() == before
        assert runtime._pending_abort_attempt_bytes == byte_count
        assert runtime._deferred_mode is False and runtime.sequence == 0
    clone = resource_runtime(version, compact, limit)
    clone.restore(before)
    for current in (runtime, clone):
        tx = begin(current, 1, bar=1, realtime=True)
        assert tx.declare_scalar_v1("memory", "varip", lambda: None, "string").startswith("2:")
        tx.commit()
        assert current._pending_abort is None and current._pending_abort_attempt_bytes == 0
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


def test_append_does_not_reencode_prior_witnesses(monkeypatch):
    import pinelib.runtime.session as owner
    runtime = resource_runtime(6, True)
    resource_attempt(runtime, 1)
    old = runtime._pending_abort["attempts"][0]
    encode = owner.canonical_json
    def checked(value):
        pending = [value]
        while pending:
            row = pending.pop()
            assert row is not old, "previous witness was encoded again during append"
            if isinstance(row, dict): pending.extend(row.values())
            elif isinstance(row, list): pending.extend(row)
        return encode(value)
    monkeypatch.setattr(owner, "canonical_json", checked)
    resource_attempt(runtime, 2)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("provisional", [False, True])
def test_resource_rejection_restores_first_or_provisional_attempt_control(version, compact, provisional):
    def make(limit):
        result = session(version, RuntimePolicies(resource=replace(ResourcePolicy(), max_checkpoint_bytes=limit)))
        result.commit_full_identity = not compact
        if provisional:
            tx = begin(result, 0, bar=0, deferred=True)
            tx.declare_scalar_v1("memory", "varip", lambda: "seed", "string")
            tx.commit()
        return result
    def fail_attempt(runtime):
        tx = begin(runtime, 1 if provisional else 0, bar=0, realtime=not provisional, deferred=provisional)
        tx.declare_scalar_v1("memory", "varip", lambda: "seed", "string")
        tx.write_scalar_v1("memory", "varip", "Ж" * 256, "string")
        tx.abort()
    probe = make(16 * 1024 * 1024)
    fail_attempt(probe)
    limit = len(canonical_json(probe.checkpoint().to_dict())) - 1
    runtime = make(limit)
    before_state, before_transcript = deepcopy(runtime._state_json()), deepcopy(runtime.transcript.to_dict())
    pending, mode, machine = runtime._pending_bar_frame, runtime._deferred_mode, runtime.machine.state
    original = None if provisional else runtime.checkpoint().to_dict()
    with pytest.raises(PineRuntimeError) as caught:
        fail_attempt(runtime)
    assert caught.value.code == PL_RESOURCE_LIMIT
    assert runtime._state_json() == before_state and runtime.transcript.to_dict() == before_transcript
    assert runtime._pending_bar_frame is pending and runtime._deferred_mode is mode
    assert runtime.machine.state == machine and runtime._active is None
    if provisional:
        runtime.finalize_bar(0)
        assert runtime.series["memory"].working == "seed"
    else:
        assert runtime.checkpoint().to_dict() == original


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("parent_full", [False, True])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_parent_budget_counts_nested_child_witness_bytes(version, parent_full, delta):
    from tests.test_nominal_registry_request_restore import fixture as request_fixture, checkpoint_with, Child
    def make(limit):
        policies = RuntimePolicies(resource=replace(ResourcePolicy(), max_checkpoint_bytes=limit))
        parent, children = request_fixture(version, full=parent_full, policies=policies)
        child = next(iter(children.values()))
        tx = begin(child, child.sequence + 1, realtime=True)
        tx.declare_scalar_v1("memory", "varip", lambda: "Ж" * 128, "string")
        tx.abort()
        child_saved = child.checkpoint().to_dict()
        saved = checkpoint_with(parent, child_saved)
        return parent, saved, len(canonical_json(child_saved))
    _, probe, _ = make(16 * 1024 * 1024)
    required = len(canonical_json(probe))
    runtime, saved, child_size = make(required + delta)
    assert child_size < required + delta
    assert len(canonical_json(saved)) == required
    before = runtime.checkpoint().to_dict()
    calls, evaluations = runtime.requests.provider.calls, Child.evaluations
    if delta < 0:
        with pytest.raises(PineRuntimeError) as caught:
            runtime.restore(saved)
        assert caught.value.code == PL_RESOURCE_LIMIT
        assert runtime.checkpoint().to_dict() == before
    else:
        runtime.restore(saved)
        assert runtime.checkpoint().to_dict() == saved
    assert (runtime.requests.provider.calls, Child.evaluations) == (calls, evaluations)
