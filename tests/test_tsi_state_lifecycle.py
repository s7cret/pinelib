"""TSI slot revision is enforced at every existing scratch admission boundary."""

from copy import deepcopy
import json

import pytest

from pinelib import CallbackFrame
from pinelib.abi.compiled_request import CompiledRequestExpression, security_v1
from pinelib.request import ResultShape
from tests.test_compiled_requests import Provider, begin, runtime as request_runtime
from tests.test_nominal_registry_request_restore import checkpoint_with
from tests.test_rolling_statistics_state import assert_atomic, reseal
from tests.test_tsi_scale import BEFORE, commit, make, range_only, value
from tests.test_varip_abort_checkpoint import reseal_pending


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("location", ["attempted", "successful", "post"])
@pytest.mark.parametrize("fault", ["legacy", "profile", "wrong_type"])
def test_pending_every_portion_and_same_sequence_retry(version, compact, location, fault):
    runtime = make(version, compact)
    for source in [3.0, -1.0, 5.0, 2.0, -2.0, 4.0]:
        commit(runtime, source)
    baseline = runtime.checkpoint().to_dict()
    frame = CallbackFrame("REALTIME_TICK", 6, bar_index=6, realtime=True, final_tick=False)
    tx = runtime.begin(frame)
    tx.declare_scalar_v1("ticks", "varip", lambda: 0, "int")
    tx.write_scalar_v1("ticks", "varip", 1, "int")
    range_only(value(tx, 9.0))
    tx.abort()
    saved = runtime.checkpoint().to_dict()
    clone = make(version, compact)
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    forged = deepcopy(saved)
    record = forged["state"]["pending_abort"]
    segment = (
        record["attempts"][0]["attempted_state"]
        if location == "attempted"
        else record["successful_state"]
        if location == "successful"
        else forged["state"]
    )
    row = next(row for row in segment["slots"] if row["owner"] == "ta.tsi")
    if fault == "legacy":
        row["schema_version"] = "ta.tsi.state.v1"
    elif fault == "profile":
        row["working"]["profile"] = "percentage"
    else:
        row["working"]["change_long"]["value"] = True
    if location == "successful":
        base = make(version, compact)
        base.restore(baseline)
        changed = reseal(
            base,
            {
                **deepcopy(baseline),
                "state": {**segment, "transcript": baseline["state"]["transcript"]},
            },
        )
        forged["state"]["transcript"] = changed["state"]["transcript"]
        record["transcript_hash"] = changed["state"]["transcript"]["content_hash"]
    assert_atomic(runtime, reseal_pending(runtime, forged["state"]), "TSI|replay.*original input")
    for current in (runtime, clone):
        tx = current.begin(CallbackFrame("REALTIME_TICK", 6, bar_index=6, realtime=True))
        range_only(value(tx, 7.0))
        tx.commit()
        assert "pending_abort" not in current.checkpoint().state
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


class TsiChild:
    evaluations = 0

    def __init__(self, runtime):
        self.runtime = runtime

    def output(self):
        TsiChild.evaluations += 1
        return value(self.runtime, self.runtime.value_close)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("fault", [None, "legacy", "profile", "wrong_type"])
def test_actual_child_late_admission_and_no_execution(version, compact, pending, fault):
    parent = request_runtime(Provider(), version)
    parent.commit_full_identity = not compact
    tx = begin(parent, 0)
    children = {}
    for index in range(2):
        identity = "sha256:" + ("e" if index == 0 else "f") * 64
        expression = CompiledRequestExpression(
            tx, TsiChild, "output", identity, ResultShape.scalar("float")
        )
        security_v1(tx, "EX:S", "5", expression, "site-" + str(index))
        children[identity] = expression._runtime
    tx.commit()
    identity = parent.checkpoint().state["requests"]["registry"]["datasets"][-1]["key"]["query"][
        "expression_id"
    ]
    child = children[identity]
    if pending:
        tx = child.begin(
            CallbackFrame(
                "REALTIME_TICK", child.sequence + 1, bar_index=2, realtime=True, final_tick=False
            )
        )
        tx.declare_scalar_v1("ticks", "varip", lambda: 0, "int")
        tx.write_scalar_v1("ticks", "varip", 1, "int")
        value(tx, 99.0)
        tx.abort()
    saved = child.checkpoint().to_dict()
    if fault is not None:
        segment = (
            saved["state"]["pending_abort"]["attempts"][0]["attempted_state"]
            if pending
            else saved["state"]
        )
        row = next(row for row in segment["slots"] if row["owner"] == "ta.tsi")
        if fault == "legacy":
            row["schema_version"] = "ta.tsi.state.v1"
        elif fault == "profile":
            row["working"]["profile"] = "percentage"
        else:
            row["working"]["change_long"]["warmup"][0] = True
        saved = reseal_pending(child, saved["state"]) if pending else reseal(child, saved)
    checkpoint = checkpoint_with(parent, saved, identity=identity)
    calls, evaluations = parent.requests.provider.calls, TsiChild.evaluations
    if fault is None:
        parent.restore(json.loads(json.dumps(checkpoint)))
        assert parent.checkpoint().to_dict() == checkpoint
    else:
        assert_atomic(parent, checkpoint, "TSI|replay.*original input")
    assert parent.requests.provider.calls == calls
    assert TsiChild.evaluations == evaluations


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("stage", ["all_na", "seeded"])
def test_rename_only_of_old_schema_is_not_a_converter(version, compact, stage):
    runtime = make(version, compact)
    case = next(
        case
        for case in BEFORE["genuine_checkpoints"]
        if case["kind"] == "native"
        and case["version"] == version
        and case["compact"] == compact
        and case["stage"] == stage
    )
    saved = deepcopy(case["checkpoint"])
    saved["state"]["slots"][0]["schema_version"] = "ta.tsi.state.v2"
    assert_atomic(runtime, reseal(runtime, saved), "TSI")


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("compact", [False, True])
def test_earlier_versions_reject_new_revision(version, compact):
    runtime = make(version, compact)
    commit(runtime, 3.0)
    saved = runtime.checkpoint().to_dict()
    saved["state"]["slots"][0]["schema_version"] = "ta.tsi.state.v2"
    assert_atomic(runtime, reseal(runtime, saved), "revision differs from Pine version")
