"""Independent bar-window state and current-call estimate parameter contracts."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from pinelib.abi import ta
from pinelib.core.values import na
from pinelib.errors import PineRuntimeError, PL_RESOURCE_LIMIT
from pinelib.runtime import CallbackFrame
from pinelib.runtime.compact_transcript import CompactRuntimeTranscript
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from pinelib.runtime.semantic import semantic_state_digest
from pinelib.runtime.transcript import RuntimeTranscript
from pinelib.state.checkpoint import RuntimeCheckpoint, canonical_json, sha
from pinelib.state.slots import StateSlotRegistry
from tests.stage3_helpers import session

LEGACY = json.loads((Path(__file__).parent / "fixtures/rolling_state_v1_checkpoints.json").read_text())


def make(version, compact=False, limit=100_000):
    runtime = session(version, policies=RuntimePolicies(resource=ResourcePolicy(max_collection_elements=limit)))
    runtime.commit_full_identity = not compact
    return runtime


def call(runtime, name, value, length, *, sequence=None, bar=None, realtime=False, final=True, biased=None):
    sequence = runtime.sequence + 1 if sequence is None else sequence
    tx = runtime.begin(CallbackFrame("REALTIME_TICK" if realtime else "HISTORICAL_EVAL", sequence,
        bar_index=sequence if bar is None else bar, realtime=realtime, final_tick=final))
    args = [] if biased is None else [biased]
    result = getattr(ta, name + "_v1")(tx, "sample", value, length, *args)
    return tx, result


def reseal(runtime, saved):
    state = saved["state"]
    full = state["transcript"]["schema_id"] == "openpine.runtime_transcript.v1"
    digest = sha({k:v for k,v in state.items() if k != "transcript"}) if full else semantic_state_digest(
        runtime.identity_hash, state["sequence"], runtime.series, StateSlotRegistry.from_json(state["slots"]),
        runtime.references, runtime.visuals, runtime.alerts, runtime.requests)
    entries = deepcopy(state["transcript"]["entries"])
    entries[-1]["state_hash"] = digest
    transcript = RuntimeTranscript() if full else CompactRuntimeTranscript()
    for entry in entries: transcript.append(entry)
    state["transcript"] = transcript.to_dict()
    return RuntimeCheckpoint.seal(runtime.identity_hash, state, schema_version=saved["schema_version"]).to_dict()


def assert_atomic(runtime, saved, match):
    before = runtime.checkpoint().to_dict()
    names = ("series", "slots", "references", "visuals", "alerts", "requests", "transcript")
    segments = [getattr(runtime, key) for key in names]
    control = (runtime.sequence, runtime._deferred_mode, runtime._last_published_bar)
    with pytest.raises(PineRuntimeError, match=match): runtime.restore(saved)
    assert runtime.checkpoint().to_dict() == before
    assert all(getattr(runtime, name) is obj for name,obj in zip(names, segments, strict=True))
    assert (runtime.sequence, runtime._deferred_mode, runtime._last_published_bar) == control


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("name,values,expected", [
    ("highest", [9.0, na, 3.0, 1.0], [na, 9.0, 3.0, 3.0]),
    ("lowest", [1.0, na, 7.0, 9.0], [na, 1.0, 7.0, 7.0]),
])
def test_extrema_track_na_bars_and_roundtrip(version, compact, name, values, expected):
    runtime = make(version, compact)
    for value, want in zip(values, expected, strict=True):
        tx, observed = call(runtime, name, value, 2)
        assert observed is na if want is na else observed == want
        tx.commit()
        saved = runtime.checkpoint().to_dict()
        row = saved["state"]["slots"][0]
        assert row["schema_version"] == "ta." + name + ".state.v2"
        assert set(row["working"]) == {"kernel", "bars"}
        clone = make(version, compact)
        clone.restore(json.loads(json.dumps(saved)))
        assert clone.checkpoint().to_dict() == saved
        runtime = clone


@pytest.mark.parametrize("case", LEGACY["cases"], ids=lambda c:f"{c['version']}-{c['compact']}-{c['function']}")
def test_genuine_v1_checkpoint_boundary(case):
    runtime = make(case["version"], case["compact"])
    saved = case["checkpoint"]
    if case["function"] in ("highest", "lowest"):
        assert_atomic(runtime, saved, "replay.*original input")
    else:
        runtime.restore(saved)
        assert runtime.checkpoint().to_dict() == saved
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 3, bar_index=3))
        result = getattr(ta, case["function"] + "_v1")(tx, "legacy", 1.0, 2, False)
        assert result == pytest.approx(2.0 if case["function"] == "variance" else math.sqrt(2.0))
        tx.commit()
        clone = make(case["version"], case["compact"])
        clone.restore(runtime.checkpoint().to_dict())


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("name", ["highest", "lowest"])
@pytest.mark.parametrize("portion", ["working", "committed"])
@pytest.mark.parametrize("fault", ["extra", "kernel", "schema", "legacy", "bool", "int", "null", "marker", "varip", "owner", "initial"])
def test_fully_resealed_v2_slot_forgery_is_atomic(version, compact, name, portion, fault):
    runtime = make(version, compact)
    tx,_ = call(runtime, name, 9.0, 1); tx.commit()
    saved = deepcopy(runtime.checkpoint().to_dict())
    row = saved["state"]["slots"][0]
    if fault == "extra": row[portion]["extra"] = 1
    elif fault == "kernel": row[portion]["kernel"] = "ta.mode"
    elif fault == "schema": row["schema_version"] = "ta." + name + ".state.v99"
    elif fault == "legacy":
        row["schema_version"] = "ta." + name + ".state.v1"
        row["working"] = row["committed"] = {"kernel":"ta." + name, "values":[9.0]}
    elif fault == "varip": row["varip"] = True
    elif fault == "owner": row["owner"] = "ta.mode"
    elif fault == "initial": row["committed_exists"] = False
    else:
        row[portion]["bars"] = [{"bool":True, "int":9, "null":None, "marker":{"$unknown":"na"}}[fault]]
    assert_atomic(runtime, reseal(runtime, saved), "extrema")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("name", ["highest", "lowest"])
@pytest.mark.parametrize("revision", ["v99", "v2.extra"])
def test_unknown_extrema_schema_family_cannot_hide_behind_foreign_owner(version, compact, name, revision):
    runtime = make(version, compact)
    tx,_ = call(runtime, name, 9.0, 1); tx.commit()
    saved = deepcopy(runtime.checkpoint().to_dict())
    row = saved["state"]["slots"][0]
    row["owner"] = "custom.owner"
    row["schema_version"] = "ta." + name + ".state." + revision
    row["working"]["bars"] = [True]
    assert_atomic(runtime, reseal(runtime, saved), "extrema")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("schema", ["custom.state.v99", "ta.highestbars.state.v1", "ta.highest.stateful.v1"])
def test_extrema_schema_family_does_not_claim_unrelated_slot_namespaces(version, schema):
    from pinelib.ta.state import validate_extrema_slots
    validate_extrema_slots([{"owner":"custom.owner", "schema_version":schema}],
        pine_version=version, max_observations=1)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", ["variance", "stdev"])
@pytest.mark.parametrize("invalid", [na, None, 0, 1, "false", float("nan")])
def test_biased_requires_exact_abi_bool_before_state_access(version, name, invalid):
    runtime = make(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    before = runtime.slots.to_json()
    with pytest.raises(PineRuntimeError, match="biased"):
        getattr(ta, name + "_v1")(tx, "sample", 1.0, 1, invalid)
    assert runtime.slots.to_json() == before
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("name", ["highest", "lowest"])
def test_long_history_growing_length_exact_limit_and_atomic_overflow(version, compact, name):
    runtime = make(version, compact, limit=64)
    function = getattr(ta, name + "_v1")
    for i in range(64):
        length = 1 if i < 32 else i + 1
        tx, observed = call(runtime, name, float(i), length)
        assert observed == (float(i) if name == "highest" or length == 1 else 0.0)
        tx.commit()
    saved = runtime.checkpoint().to_dict()
    clone = make(version, compact, limit=64); clone.restore(saved)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 64, bar_index=64))
    before = runtime.slots.to_json()
    with pytest.raises(PineRuntimeError) as error: function(tx, "sample", 64.0, 1)
    assert error.value.code == PL_RESOURCE_LIMIT
    assert runtime.slots.to_json() == before
    tx.abort()
    assert runtime.checkpoint().to_dict() == saved


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", ["highest", "lowest"])
def test_request_above_retention_limit_does_not_create_slot(version, name):
    runtime = make(version, limit=2)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    with pytest.raises(PineRuntimeError) as error: getattr(ta, name + "_v1")(tx, "sample", 1.0, 3)
    assert error.value.code == PL_RESOURCE_LIMIT
    assert runtime.slots.to_json() == []
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("name", ["highest", "lowest"])
@pytest.mark.parametrize("portion", ["working", "committed"])
def test_resealed_history_over_resource_limit_rejects_at_restore(version, compact, name, portion):
    runtime = make(version, compact, limit=2)
    for value in (1.0, 2.0):
        tx,_ = call(runtime, name, value, 2); tx.commit()
    saved = deepcopy(runtime.checkpoint().to_dict())
    saved["state"]["slots"][0][portion]["bars"].append({"$pine":"na"})
    assert_atomic(runtime, reseal(runtime, saved), "history limit")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", ["highest", "lowest"])
@pytest.mark.parametrize("value", [None, True, "3", float("inf"), float("nan")])
def test_bad_extrema_source_does_not_create_state(version, name, value):
    runtime = make(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    with pytest.raises(PineRuntimeError): getattr(ta, name + "_v1")(tx, "sample", value, 1)
    assert runtime.slots.to_json() == []
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("name", ["highest", "lowest"])
@pytest.mark.parametrize("location", ["attempted", "successful", "post"])
def test_realtime_trial_abort_pending_restore_and_retry(version, compact, name, location):
    runtime = make(version, compact)
    tx,_ = call(runtime, name, 9.0, 2)
    tx.declare_scalar_v1("ticks", "varip", lambda: 0, "int")
    tx.commit()
    successful = runtime.transcript.to_dict()
    baseline_saved = runtime.checkpoint().to_dict()
    tx,result = call(runtime, name, 3.0, 2, bar=1, realtime=True, final=False)
    assert result == (9.0 if name == "highest" else 3.0)
    tx.write_scalar_v1("ticks", "varip", 1, "int")
    tx.abort()
    assert runtime.transcript.to_dict() == successful
    saved = runtime.checkpoint().to_dict()
    assert "pending_abort" in saved["state"]
    clone = make(version, compact); clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    forged = deepcopy(saved)
    record = forged["state"]["pending_abort"]
    segment = (record["attempts"][0]["attempted_state"] if location == "attempted" else
               record["successful_state"] if location == "successful" else forged["state"])
    row = next(row for row in segment["slots"] if row["owner"] == "ta." + name)
    row["schema_version"] = "ta." + name + ".state.v1"
    row["working"] = row["committed"] = {"kernel":"ta." + name,"values":[9.0]}
    if location == "successful":
        baseline = make(version, compact); baseline.restore(baseline_saved)
        changed = {**deepcopy(baseline_saved), "state":{**segment, "transcript":successful}}
        changed = reseal(baseline, changed)
        forged["state"]["transcript"] = changed["state"]["transcript"]
        record["transcript_hash"] = changed["state"]["transcript"]["content_hash"]
    from tests.test_varip_abort_checkpoint import reseal_pending
    bad = reseal_pending(runtime, forged["state"])
    assert_atomic(runtime, bad, "replay.*original input")
    for current in (runtime, clone):
        tx, value = call(current, name, na, 2, sequence=1, bar=1, realtime=True)
        assert value == 9.0
        tx.commit()
        tx, value = call(current, name, 3.0, 2, sequence=2, bar=2, realtime=True)
        assert value == 3.0
        tx.commit()
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("name", ["variance", "stdev"])
def test_estimate_mode_is_current_call_across_trial_abort_and_restore(version, compact, name):
    runtime = make(version, compact)
    for value in (1.0, 3.0):
        tx,_ = call(runtime, name, value, 2, biased=True); tx.commit()
    saved = runtime.checkpoint().to_dict()
    tx,value = call(runtime, name, 5.0, 2, bar=2, realtime=True, final=False, biased=False)
    assert value == pytest.approx(2.0 if name == "variance" else math.sqrt(2.0))
    tx.abort()
    assert runtime.checkpoint().to_dict() == saved
    clone = make(version, compact); clone.restore(saved)
    for current in (runtime, clone):
        tx,value = call(current, name, 5.0, 2, bar=2, realtime=True, biased=False)
        assert value == pytest.approx(2.0 if name == "variance" else math.sqrt(2.0))
        tx.commit()
        assert current.slots.to_json()[0]["working"]["parameters"] == {"biased":True}
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("name", ["highest", "lowest", "highestbars", "lowestbars"])
def test_earlier_versions_keep_existing_state_profile(version, name):
    runtime = make(version)
    tx,_ = call(runtime, name, 9.0, 1); tx.commit()
    saved = runtime.checkpoint().to_dict()
    assert saved["state"]["slots"][0]["schema_version"] == "ta." + name + ".state.v1"
    clone = make(version); clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", ["highestbars", "lowestbars"])
def test_extrema_offset_kernels_are_unchanged(version, name):
    runtime = make(version)
    tx,_ = call(runtime, name, 9.0, 1); tx.commit()
    assert runtime.slots.to_json()[0]["schema_version"] == "ta." + name + ".state.v1"


class ExtremaChild:
    evaluations = 0

    def __init__(self, runtime): self.runtime = runtime

    def value(self):
        ExtremaChild.evaluations += 1
        return ta.highest_v1(self.runtime, "sample", self.runtime.value_close, 2)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("fault", [None, "legacy", "bad_working", "bad_committed"])
def test_real_compiled_child_extrema_admission_without_callbacks(version, compact, fault):
    from pinelib.abi.compiled_request import CompiledRequestExpression, security_v1
    from pinelib.request import ResultShape
    from tests.test_compiled_requests import Provider, runtime as request_runtime, begin
    from tests.test_nominal_registry_request_restore import checkpoint_with

    parent = request_runtime(Provider(), version)
    parent.commit_full_identity = not compact
    tx = begin(parent, 0)
    expression = CompiledRequestExpression(tx, ExtremaChild, "value", "sha256:" + "7"*64, ResultShape.scalar("float"))
    security_v1(tx, "EX:S", "5", expression, "site")
    tx.commit()
    child = expression._runtime
    saved = child.checkpoint().to_dict()
    if fault is not None:
        row = saved["state"]["slots"][0]
        if fault == "legacy":
            row["schema_version"] = "ta.highest.state.v1"
            row["working"] = row["committed"] = {"kernel":"ta.highest", "values":[10.0,20.0,30.0]}
        else: row["working" if fault == "bad_working" else "committed"]["bars"] = [True]
        saved = reseal(child, saved)
    checkpoint = checkpoint_with(parent, saved)
    fetches, evaluations = parent.requests.provider.calls, ExtremaChild.evaluations
    if fault is None:
        parent.restore(checkpoint)
        assert parent.checkpoint().to_dict() == checkpoint
    else:
        assert_atomic(parent, checkpoint, "extrema")
    assert parent.requests.provider.calls == fetches
    assert ExtremaChild.evaluations == evaluations


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", ["variance", "stdev"])
def test_sample_unit_window_is_missing_population_unit_window_is_zero(version, name):
    runtime = make(version)
    tx,value = call(runtime, name, 3.0, 1, biased=False)
    assert value is na
    tx.commit()
    tx,value = call(runtime, name, 5.0, 1, biased=True)
    assert value == 0.0
    tx.commit()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_aggregate_checkpoint_budget_still_applies_to_v2_state(version, compact):
    policy = RuntimePolicies(resource=ResourcePolicy(max_checkpoint_bytes=8_000))
    runtime = session(version, policies=policy)
    runtime.commit_full_identity = not compact
    for i in range(40):
        tx,_ = call(runtime, "highest", float(i), 1); tx.commit()
    saved = RuntimeCheckpoint.seal(runtime.identity_hash,
        {**runtime._state_json(), "transcript":runtime.transcript.to_dict()}).to_dict()
    assert len(canonical_json(saved)) > policy.resource.max_checkpoint_bytes
    with pytest.raises(PineRuntimeError) as error: runtime.checkpoint()
    assert error.value.code == PL_RESOURCE_LIMIT
    clone = session(version, policies=policy)
    clone.commit_full_identity = not compact
    with pytest.raises(PineRuntimeError) as error: clone.restore(saved)
    assert error.value.code == PL_RESOURCE_LIMIT
    assert clone.sequence == -1 and clone.slots.to_json() == []


def test_estimate_target_signature_is_exact():
    from importlib.resources import files
    current = json.loads(files("pinelib.abi").joinpath("target_manifest.json").read_text())
    for name in ("ta.variance", "ta.stdev"):
        row = next(row for row in current["rows"] if row["name"] == name)
        assert row["parameters"][-1] == {"name":"biased", "type":"bool", "qualifier_max":"series", "required":False, "default":True}
        assert next(b for b in row["parameter_bindings"] if b["abi_parameter"] == "biased") == {
            "abi_parameter":"biased", "binding":"SOURCE_PARAMETER", "source":"biased"}
        assert row["version_availability"] == [5, 6]
        assert row["producer_overload_ids"] == ["pine:function:" + name + "#canonical"]
