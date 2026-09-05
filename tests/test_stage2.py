import copy
import json

import pytest

from pinelib import *
from pinelib.errors import PineRuntimeError


def ctx(v=6):
    return RuntimeLanguageContext(
        v, "2026-08-29", f"pine-v{v}", "sha256:" + "1" * 64, "compiler_annotation"
    )


def test_versions_1_6():
    for v in range(1, 7):
        assert ctx(v).pine_version == v
    with pytest.raises(PineRuntimeError):
        RuntimeLanguageContext(7, "x", "x", "sha256:" + "1" * 64, "compiler_annotation")


def test_state_machine_invalid():
    m = RuntimeStateMachine()
    with pytest.raises(PineRuntimeError):
        m.transition(RuntimeState.COMMITTED)


def test_historical_commit_and_abort():
    s = RuntimeSession(ctx())
    t = s.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    t.set_series("x", 10)
    t.set_slot("a", 1)
    r = t.commit()
    assert r.committed
    assert s.series["x"].read(1) == 10
    before = s.state_hash
    t = s.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    t.set_series("x", 99)
    t.set_slot("a", 9)
    t.abort()
    assert s.state_hash == before or s.series["x"].working == 10
    assert s.slots._slots["a"].working == 1


def test_realtime_nonfinal_does_not_commit_history_but_varip_survives():
    s = RuntimeSession(ctx())
    t = s.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    t.set_series("x", 1)
    t.set_slot("normal", 1)
    t.set_slot("vip", 1, varip=True)
    t.commit()
    t = s.begin(CallbackFrame("REALTIME_TICK", 1, True, False))
    t.set_series("x", 2)
    t.set_slot("normal", 2)
    t.set_slot("vip", 2, varip=True)
    t.commit()
    assert s.series["x"].committed == [1]
    t = s.begin(CallbackFrame("REALTIME_TICK", 2, True, False))
    assert s.slots._slots["normal"].working == 1
    assert s.slots._slots["vip"].working == 2
    t.abort()


def test_final_realtime_commits():
    s = RuntimeSession(ctx())
    t = s.begin(CallbackFrame("REALTIME_TICK", 0, True, True))
    t.set_series("x", 2)
    t.commit()
    assert s.series["x"].committed == [2]


def test_bool_version_semantics():
    assert pine_bool(1, ctx(5)) is True
    with pytest.raises(PineRuntimeError):
        pine_bool(1, ctx(6))
    assert is_na(pine_bool(na, ctx(5)))
    with pytest.raises(PineRuntimeError):
        pine_bool(na, ctx(6))


def test_div_version_semantics():
    assert pine_div_const_int(5, 2, ctx(5)) == 2
    assert pine_div_const_int(5, 2, ctx(6)) == 2.5
    assert pine_div(5, 2, ctx(6)) == 2.5


def test_slot_identity_conflict():
    r = StateSlotRegistry()
    r.register("x", "a", "1")
    with pytest.raises(PineRuntimeError):
        r.register("x", "b", "1")


def test_checkpoint_json_roundtrip_atomic_reject():
    s = RuntimeSession(ctx())
    t = s.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    t.set_series("x", 10)
    t.set_slot("a", 3)
    t.commit()
    cp = s.checkpoint().to_dict()
    json.dumps(cp, allow_nan=False)
    s2 = RuntimeSession(ctx())
    s2.restore(cp)
    assert s2.state_hash == s.state_hash
    bad = copy.deepcopy(cp)
    bad["state"]["sequence"] = 999
    before = s2.state_hash
    with pytest.raises(PineRuntimeError):
        s2.restore(bad)
    assert s2.state_hash == before


def test_checkpoint_identity_rejected():
    s = RuntimeSession(ctx(6))
    cp = s.checkpoint().to_dict()
    s5 = RuntimeSession(ctx(5))
    with pytest.raises(PineRuntimeError):
        s5.restore(cp)


def test_transcript_deterministic_replay():
    def run():
        s = RuntimeSession(ctx())
        for i, v in enumerate((1, 2, 3)):
            t = s.begin(CallbackFrame("HISTORICAL_EVAL", i))
            t.set_series("x", v)
            t.commit()
        return s.state_hash, s.transcript.to_dict(), s.checkpoint().content_hash

    assert run() == run()


def test_fill_recalc_is_explicit_phase():
    s = RuntimeSession(ctx())
    t = s.begin(
        CallbackFrame("ORDER_FILL_RECALC", 0, False, True, "sha256:" + "2" * 64)
    )
    t.set_slot("a", 1)
    t.commit()
    assert s.transcript.entries[-1]["phase"] == "ORDER_FILL_RECALC"


def test_finalize():
    s = RuntimeSession(ctx())
    s.finalize()
    assert s.machine.state == RuntimeState.FINALIZED


def test_more_value_and_context_edges():
    with pytest.raises(PineRuntimeError):
        RuntimeLanguageContext(6, "", "x", "sha256:" + "1" * 64, "compiler_annotation")
    with pytest.raises(PineRuntimeError):
        RuntimeLanguageContext(6, "x", "x", "bad", "compiler_annotation")
    with pytest.raises(PineRuntimeError):
        pine_div_const_int(1, 0, ctx())
    with pytest.raises(PineRuntimeError):
        pine_div(1, 0, ctx())
    assert is_na(pine_div(na, 2, ctx()))


def test_series_edges_and_slot_limit():
    s = SeriesStorage("x", "float")
    with pytest.raises(PineRuntimeError):
        s.set(1)
    with pytest.raises(PineRuntimeError):
        s.read(-1)
    s.begin(1)
    assert s.read(5) is None
    s.commit()
    s.begin()
    s.rollback()
    assert s.working == 1
    r = StateSlotRegistry(limit=1)
    r.register("x", "a", "1")
    with pytest.raises(PineRuntimeError):
        r.register("y", "a", "1")


def test_transaction_closed_and_resource_checkpoint_limit():
    policies = RuntimePolicies(resource=ResourcePolicy(max_checkpoint_bytes=10))
    s = RuntimeSession(ctx(), policies)
    t = s.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    t.commit()
    with pytest.raises(PineRuntimeError):
        t.commit()
    with pytest.raises(PineRuntimeError):
        s.checkpoint()


def test_commit_identity_can_skip_full_state_json() -> None:
    session = RuntimeSession(ctx())
    session.commit_full_identity = False
    calls = {"n": 0}
    original = session._state_json

    def counted() -> dict[str, object]:
        calls["n"] += 1
        return original()

    session._state_json = counted  # type: ignore[method-assign]
    for index in range(8):
        transaction = session.begin(CallbackFrame("HISTORICAL_EVAL", index))
        transaction.set_series("close", float(index))
        transaction.commit()
    assert calls["n"] == 0
    assert len(session.transcript.entries) == 8
    assert session.transcript.to_dict()["schema_id"] == "openpine.runtime_transcript.v2"
