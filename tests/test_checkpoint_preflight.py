"""Public preparation retains the existing complete portable checkpoint owner."""

from copy import deepcopy
import json

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na, na
from pinelib.abi import load_target_manifest
from pinelib.errors import PineRuntimeError
from pinelib.state.checkpoint import RuntimeCheckpoint, sha


def runtime(compact=False):
    manifest = load_target_manifest()
    obj = RuntimeSession(
        RuntimeLanguageContext(
            6,
            "run02-preflight",
            "pine-v6",
            manifest["content_hash"],
            "compiler_annotation",
        )
    )
    obj.commit_full_identity = not compact
    return obj


def fill(obj):
    for i, value in enumerate((na, na, 3.0)):
        tx = obj.begin(CallbackFrame("HISTORICAL_EVAL", i, bar_index=i))
        tx.set_series("missing", value, "float")
        tx.commit()


def owned(obj):
    return (
        obj.series,
        obj.slots,
        obj.references,
        obj.visuals,
        obj.alerts,
        obj.requests,
        obj.transcript,
        obj.machine,
        obj.inputs,
        obj.nominal_registry,
    )


@pytest.mark.parametrize("compact", [False, True])
def test_prepared_runtime_preserves_live_state_and_portable_na(compact):
    obj = runtime(compact)
    fill(obj)
    wire = json.loads(json.dumps(obj.checkpoint().to_dict()))
    before, identities = obj.checkpoint().to_dict(), owned(obj)
    candidate = obj.prepare_restore(wire)
    assert (
        candidate is not obj
        and candidate.commit_full_identity == obj.commit_full_identity
    )
    assert candidate.checkpoint().to_dict() == wire
    assert is_na(candidate.series["missing"].committed[0])
    assert (
        candidate.state_hash == obj.state_hash
        and candidate.semantic_state_hash == obj.semantic_state_hash
    )
    assert obj.checkpoint().to_dict() == before
    assert all(a is b for a, b in zip(identities, owned(obj), strict=True))
    wire["state"]["series"]["missing"]["committed"][0] = 999
    assert candidate.checkpoint().to_dict() == before


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize(
    "fault",
    ["identity", "sequence", "series", "transcript", "requests", "pending-abort"],
)
def test_full_admission_failure_never_changes_live_runtime(compact, fault):
    obj = runtime(compact)
    fill(obj)
    saved, identities = obj.checkpoint().to_dict(), owned(obj)
    bad = deepcopy(saved)
    if fault == "identity":
        bad["identity_hash"] = sha("different context")
    else:
        if fault == "sequence":
            bad["state"]["sequence"] = 999
        elif fault == "series":
            bad["state"]["series"]["missing"]["dtype"] = "foreign"
        elif fault == "transcript":
            bad["state"]["transcript"]["entries"][-1]["state_hash"] = sha("forged")
        elif fault == "requests":
            bad["state"]["requests"]["late"] = 1
        else:
            bad["state"]["pending_abort"] = {"late": True}
        bad = RuntimeCheckpoint.seal(
            bad["identity_hash"], bad["state"], schema_version=bad["schema_version"]
        ).to_dict()
    with pytest.raises(PineRuntimeError):
        obj.prepare_restore(bad)
    assert obj.checkpoint().to_dict() == saved
    assert all(a is b for a, b in zip(identities, owned(obj), strict=True))


@pytest.mark.parametrize("fault", ["cycle", "deep", "nonfinite", "keys"])
def test_public_transport_preflight_is_bounded_and_pure(fault):
    obj = runtime()
    fill(obj)
    before, identities = obj.checkpoint().to_dict(), owned(obj)
    if fault == "cycle":
        data = {}
        data["cycle"] = data
    elif fault == "deep":
        data = 0
        for _ in range(140):
            data = [data]
    elif fault == "nonfinite":
        data = {"late": float("inf")}
    else:
        data = {1: "late"}
    with pytest.raises(PineRuntimeError):
        obj.validate_checkpoint_input(data)
    assert obj.checkpoint().to_dict() == before
    assert all(a is b for a, b in zip(identities, owned(obj), strict=True))


@pytest.mark.parametrize("phase", ["active", "provisional"])
def test_active_or_provisional_live_runtime_rejects_preparation(phase):
    obj = runtime()
    wire = obj.checkpoint().to_dict()
    tx = obj.begin(
        CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0, defer_bar_commit=True)
    )
    if phase == "provisional":
        tx.commit()
    identities = owned(obj)
    with pytest.raises(PineRuntimeError, match="active or provisional"):
        obj.prepare_restore(wire)
    assert all(a is b for a, b in zip(identities, owned(obj), strict=True))


@pytest.mark.parametrize("compact", [False, True])
def test_proved_pending_abort_and_nominal_refgraph_reuse_existing_admission(compact):
    from tests.test_varip_abort_checkpoint import fixture, attempt, values

    obj, handle, dtype, _ = fixture(6, compact, "varip")
    attempt(obj, handle, dtype, "varip")
    attempt(obj, handle, dtype, "varip", abort=True)
    saved, identities = obj.checkpoint().to_dict(), owned(obj)
    assert "pending_abort" in saved["state"]
    candidate = obj.prepare_restore(json.loads(json.dumps(saved)))
    assert candidate.checkpoint().to_dict() == saved
    assert values(candidate, handle) == [0, 2]
    assert candidate.nominal_registry is obj.nominal_registry
    assert all(a is b for a, b in zip(identities, owned(obj), strict=True))
    assert obj.checkpoint().to_dict() == saved


@pytest.mark.parametrize("forged_child", [False, True])
def test_compiled_child_admission_reuses_owner_without_provider_evaluation(
    forged_child,
):
    from tests.test_nominal_registry_request_restore import (
        fixture,
        checkpoint_with,
        Child,
    )

    obj, children = fixture(6, full=False)
    child = next(iter(children.values()))
    saved, identities = obj.checkpoint().to_dict(), owned(obj)
    calls, evaluations = obj.requests.provider.calls, Child.evaluations
    if forged_child:
        child_wire = deepcopy(child.checkpoint().to_dict())
        child_wire["state"]["transcript"]["entries"][-1]["state_hash"] = sha(
            "forged child"
        )
        child_wire = RuntimeCheckpoint.seal(
            child_wire["identity_hash"],
            child_wire["state"],
            schema_version=child_wire["schema_version"],
        ).to_dict()
        with pytest.raises(PineRuntimeError):
            obj.prepare_restore(checkpoint_with(obj, child_wire))
    else:
        candidate = obj.prepare_restore(json.loads(json.dumps(saved)))
        assert candidate.checkpoint().to_dict() == saved
    assert (obj.requests.provider.calls, Child.evaluations) == (calls, evaluations)
    assert obj.checkpoint().to_dict() == saved
    assert all(a is b for a, b in zip(identities, owned(obj), strict=True))
