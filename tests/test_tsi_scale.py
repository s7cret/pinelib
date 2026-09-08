"""Primary range predicates are separate from compatibility/exception observations."""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import pytest

from pinelib import CallbackFrame, na
from pinelib.abi.ta import tsi_v1
from pinelib.errors import PL_RESOURCE_LIMIT, PineRuntimeError
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from pinelib.state.checkpoint import RuntimeCheckpoint, canonical_json
from tests.stage3_helpers import session
from tests.test_rolling_statistics_state import assert_atomic, reseal

FIXTURES = Path(__file__).parent / "fixtures"
RANGE_RAW = (FIXTURES / "tsi_range_expected.json").read_bytes()
BEFORE_RAW = (FIXTURES / "tsi_scale_before.json").read_bytes()
assert (
    hashlib.sha256(RANGE_RAW).hexdigest()
    == "5a76aacd6df1b88faf414b2a6bba389b0f859234b2c2e6f2748dea13357ef420"
)
assert (
    hashlib.sha256(BEFORE_RAW).hexdigest()
    == "382242c74460d4849383b3cbaf5fce5438427b1e71d50e1730b104c536a808cd"
)
RANGE, BEFORE = json.loads(RANGE_RAW), json.loads(BEFORE_RAW)


def make(version, compact, limit=None):
    policies = (
        RuntimePolicies(resource=ResourcePolicy(max_collection_elements=limit)) if limit else None
    )
    runtime = session(version, policies=policies)
    runtime.commit_full_identity = not compact
    return runtime


def value(tx, number, short=2, long=3):
    return tsi_v1(tx, "sample", number, short, long)


def commit(runtime, number, short=2, long=3):
    index = runtime.sequence + 1
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
    actual = value(tx, number, short, long)
    tx.commit()
    return actual


def range_only(actual):
    if actual is na:
        return "NA_timing_UNVERIFIED"
    assert type(actual) is float and math.isfinite(actual)
    assert (
        RANGE["predicate"]["finite_float"]["lower_inclusive"]
        <= actual
        <= RANGE["predicate"]["finite_float"]["upper_inclusive"]
    )
    return "finite_range_only"


def normalization_neutral_slots(rows):
    rows = deepcopy(rows)
    for row in rows:
        if row["owner"] == "ta.tsi":
            row["schema_version"] = "comparison-of-unscaled-numerical-state"
            for part in ("committed", "working"):
                row[part].pop("profile", None)
    return rows


@pytest.mark.parametrize(
    "case", RANGE["cases"], ids=lambda c: c["manual_row_id"] + "-v" + str(c["version"])
)
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("route", ["historical", "realtime", "deferred_fill"])
def test_complete_observation_denominator_range_and_lifecycle(case, compact, route):
    runtime = make(case["version"], compact)
    deferred = route == "deferred_fill"
    sequence = 0
    observed = []
    for bar, source in enumerate(case["source"]):
        number = na if source == "na" else float(source)

        def start(final, phase=None):
            return runtime.begin(
                CallbackFrame(
                    phase or ("REALTIME_TICK" if route == "realtime" else "HISTORICAL_EVAL"),
                    sequence,
                    bar_index=bar,
                    realtime=route == "realtime",
                    final_tick=final,
                    defer_bar_commit=deferred,
                )
            )

        args = case["parameters"]["short"], case["parameters"]["long"]
        if route != "historical":
            tx = start(False)
            value(tx, 99.0, *args)
            tx.commit()
            sequence += 1
            tx = start(False, "ORDER_FILL_RECALC" if deferred else None)
            range_only(value(tx, number, *args))
            tx.abort()
        tx = start(True, "ORDER_FILL_RECALC" if deferred else None)
        observed.append(range_only(value(tx, number, *args)))
        tx.commit()
        sequence += 1
        if deferred:
            runtime.finalize_bar(bar)
            sequence = runtime.sequence + 1
        saved = runtime.checkpoint().to_dict()
        assert saved["state"]["slots"][0]["schema_version"] == "ta.tsi.state.v2"
        clone = make(case["version"], compact)
        clone.restore(json.loads(json.dumps(saved)))
        assert clone.checkpoint().to_dict() == saved
        runtime = clone
    assert len(observed) == len(case["source"])
    assert case["complete_trajectory_authority"] == "UNVERIFIED"


def test_range_fixture_keeps_all_events_and_no_complete_assignment():
    assert len(RANGE["cases"]) == 16
    assert sum(len(c["source"]) for c in RANGE["cases"]) == RANGE["total_events"] == 90
    assert RANGE["complete_direct_assignments"] == [] and not RANGE["full_stage2_accepted"]


@pytest.mark.parametrize(
    "case",
    BEFORE["genuine_checkpoints"],
    ids=lambda c: f"{c['kind']}-{c.get('stage', '')}-{c['version']}-{c['compact']}",
)
def test_genuine_old_tsi_checkpoint_boundary(case):
    if case["kind"] == "request":
        from tests.test_compiled_requests import Provider, runtime as request_runtime

        runtime = request_runtime(Provider(), case["version"])
        runtime.commit_full_identity = not case["compact"]
        calls = runtime.requests.provider.calls
    else:
        runtime = make(case["version"], case["compact"])
    if case["version"] >= 5:
        assert_atomic(runtime, case["checkpoint"], "replay.*original input")
    else:
        runtime.restore(case["checkpoint"])
        assert runtime.checkpoint().to_dict() == case["checkpoint"]
        commit(runtime, 7.0)
        assert runtime.slots.to_json()[0]["schema_version"] == "ta.tsi.state.v1"
        clone = make(case["version"], case["compact"])
        clone.restore(runtime.checkpoint().to_dict())
        assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()
    if case["kind"] == "request":
        assert runtime.requests.provider.calls == calls


SPECS = {
    "invalid_bool": ([], True, 2, 3),
    "invalid_none": ([], None, 2, 3),
    "invalid_string": ([], "bad", 2, 3),
    "invalid_infinity": ([], math.inf, 2, 3),
    "change_overflow": ([-1e308], 1e308, 2, 3),
    "signed_seed_overflow": ([-9e307, 0.0], 9e307, 2, 2),
    "absolute_seed_overflow": ([0.0, 8e307], -8e307, 2, 2),
    "percentage_result_overflow": ([0.0], 1e308, 1, 1),
    "resource_length": ([], 3.0, 3, 3),
}


@pytest.mark.parametrize(
    "case",
    BEFORE["exception_witnesses"],
    ids=lambda c: f"{c['case']}-{c['version']}-{c['compact']}",
)
@pytest.mark.parametrize("finish", ["abort", "caught_commit"])
def test_actual_failure_state_compatibility_and_roundtrip(case, finish):
    label = case["case"]
    runtime = make(case["version"], case["compact"], 2 if label == "resource_length" else None)
    sources, source, short, long = SPECS[label]
    if not sources:
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
        tx.commit()
    for number in sources:
        commit(runtime, number, short, long)
    tx = runtime.begin(
        CallbackFrame(
            "REALTIME_TICK",
            runtime.sequence + 1,
            bar_index=runtime.sequence + 1,
            realtime=True,
            final_tick=False,
        )
    )
    tx.declare_scalar_v1("ticks", "varip", lambda: 0, "int")
    tx.write_scalar_v1("ticks", "varip", 1, "int")
    before_call = runtime.slots.to_json()
    if label == "resource_length":
        with pytest.raises(PineRuntimeError) as raised:
            value(tx, source, short, long)
        assert raised.value.code == PL_RESOURCE_LIMIT
        assert runtime.slots.to_json() == before_call
    elif label == "percentage_result_overflow":
        assert case["outcome"] == {"returned": {"nonfinite": "inf"}}
        range_only(value(tx, source, short, long))
    else:
        with pytest.raises((PineRuntimeError, OverflowError)) as raised:
            value(tx, source, short, long)
        assert type(raised.value).__name__ == case["outcome"]["exception_type"]
        assert str(raised.value) == case["outcome"]["message"]
    if label != "resource_length":
        # This is preserved implementation state, expressly not a Pine output oracle.
        assert normalization_neutral_slots(runtime.slots.to_json()) == normalization_neutral_slots(
            case["attempted_slots"]
        )
    if finish == "abort":
        tx.abort()
        if label != "resource_length":
            assert normalization_neutral_slots(
                runtime.slots.to_json()
            ) == normalization_neutral_slots(case["post_abort"]["state"]["slots"])
    else:
        tx.commit()
    saved = runtime.checkpoint().to_dict()
    clone = make(case["version"], case["compact"], 2 if label == "resource_length" else None)
    clone.restore(json.loads(json.dumps(saved)))
    assert clone.checkpoint().to_dict() == saved


FAULTS = [
    "extra",
    "kernel",
    "profile",
    "missing_profile",
    "owner",
    "schema",
    "owner_schema",
    "varip",
    "parameter_bool",
    "parameter_zero",
    "parameter_extra",
    "previous_bool",
    "previous_int",
    "previous_none",
    "missing_previous",
    "missing_stage",
    "stage_list",
    "stage_extra",
    "warmup_empty",
    "warmup_long",
    "warmup_bool",
    "warmup_int",
    "warmup_na",
    "value_bool",
    "value_int",
    "value_none",
    "value_without_warmup",
    "seed_short_warmup",
    "absolute_negative",
]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("part", ["working", "committed"])
@pytest.mark.parametrize("fault", FAULTS)
def test_closed_local_shapes_reject_forgery_atomically(version, compact, part, fault):
    runtime = make(version, compact)
    for number in [3.0, -1.0, 5.0, 2.0, -2.0, 4.0]:
        commit(runtime, number)
    saved = runtime.checkpoint().to_dict()
    row = saved["state"]["slots"][0]
    state = row[part]
    stage = state["change_long"]
    if fault == "extra":
        state["extra"] = 1
    elif fault == "kernel":
        state["kernel"] = "ta.ema"
    elif fault == "profile":
        state["profile"] = "percentage"
    elif fault == "missing_profile":
        state.pop("profile")
    elif fault == "owner":
        row["owner"] = "custom"
    elif fault == "schema":
        row["schema_version"] = "ta.tsi.state.v99"
    elif fault == "owner_schema":
        row["owner"], row["schema_version"] = "custom", "ta.tsi.state.v99"
    elif fault == "varip":
        row["varip"] = True
    elif fault == "parameter_bool":
        state["parameters"]["short_length"] = True
    elif fault == "parameter_zero":
        state["parameters"]["short_length"] = 0
    elif fault == "parameter_extra":
        state["parameters"]["extra"] = 1
    elif fault == "previous_bool":
        state["previous"] = True
    elif fault == "previous_int":
        state["previous"] = 1
    elif fault == "previous_none":
        state["previous"] = None
    elif fault == "missing_previous":
        state.pop("previous")
    elif fault == "missing_stage":
        state.pop("absolute_short")
    elif fault == "stage_list":
        state["change_long"] = []
    elif fault == "stage_extra":
        stage["extra"] = 1
    elif fault == "warmup_empty":
        stage["warmup"] = []
    elif fault == "warmup_long":
        stage["warmup"].append(1.0)
    elif fault == "warmup_bool":
        stage["warmup"][0] = True
    elif fault == "warmup_int":
        stage["warmup"][0] = 1
    elif fault == "warmup_na":
        stage["warmup"][0] = {"$pine": "na"}
    elif fault == "value_bool":
        stage["value"] = True
    elif fault == "value_int":
        stage["value"] = 1
    elif fault == "value_none":
        stage["value"] = None
    elif fault == "value_without_warmup":
        stage.pop("warmup")
    elif fault == "seed_short_warmup":
        stage["warmup"].pop()
    elif fault == "absolute_negative":
        state["absolute_long"]["value"] = -1.0
    assert_atomic(runtime, reseal(runtime, saved), "TSI")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("parameter", ["short", "long"])
@pytest.mark.parametrize("length", [1, 2, 3])
def test_resource_boundary_before_state_mutation_and_on_restore(
    version, compact, parameter, length
):
    runtime = make(version, compact, 2)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    args = {"short": 2, "long": 2, parameter: length}
    if length > 2:
        with pytest.raises(PineRuntimeError) as raised:
            value(tx, 3.0, **args)
        assert raised.value.code == PL_RESOURCE_LIMIT
        assert runtime.slots.to_json() == []
        tx.abort()
    else:
        value(tx, 3.0, **args)
        tx.commit()
        saved = runtime.checkpoint().to_dict()
        clone = make(version, compact, 2)
        clone.restore(saved)
        assert clone.checkpoint().to_dict() == saved
        for part in ["working", "committed"]:
            saved["state"]["slots"][0][part]["parameters"][parameter + "_length"] = 3
        assert_atomic(runtime, reseal(runtime, saved), "resource limit")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_long_valid_warmup_under_resource_bound(version, compact):
    runtime = make(version, compact, 64)
    for index in range(132):
        range_only(commit(runtime, float(index % 11 - 5), 64, 64))
    saved = runtime.checkpoint().to_dict()
    clone = make(version, compact, 64)
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_seed_zero_survives_restore_and_cannot_disappear(version, compact):
    runtime = make(version, compact)
    for _ in range(5):
        commit(runtime, 3.0)
    saved = runtime.checkpoint().to_dict()
    assert saved["state"]["slots"][0]["working"]["change_long"]["value"] == 0.0
    clone = make(version, compact)
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    saved["state"]["slots"][0]["working"]["change_long"].pop("value")
    assert_atomic(runtime, reseal(runtime, saved), "lost a committed seed")


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("compact", [False, True])
def test_legacy_percentage_and_resource_policy_compatibility(version, compact):
    runtime = make(version, compact, 2)
    # Prior native behavior, not a newly established historical Pine oracle.
    commit(runtime, 3.0, 3, 3)
    assert runtime.slots.to_json()[0]["schema_version"] == "ta.tsi.state.v1"
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 1, bar_index=1))
    assert tsi_v1(tx, "unit", 0.0, 1, 1) is na
    assert tsi_v1(tx, "unit", 1.0, 1, 1) == 100.0
    tx.commit()
    saved = runtime.checkpoint().to_dict()
    clone = make(version, compact, 2)
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_total_checkpoint_budget_remains_enforced(version, compact):
    policies = RuntimePolicies(resource=ResourcePolicy(max_checkpoint_bytes=8000))
    runtime = session(version, policies=policies)
    runtime.commit_full_identity = not compact
    for number in range(70):
        commit(runtime, float(number % 11), 8, 8)
    saved = RuntimeCheckpoint.seal(
        runtime.identity_hash, {**runtime._state_json(), "transcript": runtime.transcript.to_dict()}
    ).to_dict()
    assert len(canonical_json(saved)) > 8000
    with pytest.raises(PineRuntimeError) as raised:
        runtime.checkpoint()
    assert raised.value.code == PL_RESOURCE_LIMIT
    clone = session(version, policies=policies)
    clone.commit_full_identity = not compact
    with pytest.raises(PineRuntimeError) as raised:
        clone.restore(saved)
    assert raised.value.code == PL_RESOURCE_LIMIT
    assert clone.sequence == -1 and clone.slots.to_json() == []
