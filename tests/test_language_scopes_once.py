"""Transactionality, evaluation clocks and bounded written-call scopes."""

import json

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na, na
from pinelib.abi.primitives import logical_lazy_v1
from pinelib.errors import PineRuntimeError
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from pinelib.state.series import SeriesStorage


def session(version=6, policies=None):
    return RuntimeSession(
        RuntimeLanguageContext(
            version,
            "stage2",
            f"pine-v{version}",
            "sha256:" + "a" * 64,
            "compiler_annotation",
        ),
        policies,
    )


def begin(s, sequence, *, bar=None, realtime=False, final=True, deferred=False):
    return s.begin(
        CallbackFrame(
            "REALTIME_TICK" if realtime else "HISTORICAL_EVAL",
            sequence,
            bar_index=sequence if bar is None else bar,
            realtime=realtime,
            final_tick=final,
            defer_bar_commit=deferred,
        )
    )


@pytest.mark.parametrize("version", range(1, 6))
def test_once_requires_exact_v6(version):
    s = session(version)
    t = begin(s, 0)
    with pytest.raises(PineRuntimeError, match="v6"):
        t.once_v1("written", lambda: True)
    t.abort()


@pytest.mark.parametrize("deferred", [False, True])
def test_once_loop_condition_not_repeated_after_committed_completion(deferred):
    s = session()
    calls = []
    for i in range(4):
        t = begin(s, s.sequence + 1, bar=i, deferred=deferred)
        for _ in range(3):
            if t.once_v1("written", lambda i=i: calls.append(i) or i >= 1):
                t.set_slot("body", i, owner="test")
        t.commit()
        if deferred:
            s.finalize_bar(i)
    # On the first bar false predicate is evaluated for each visit; on bar 1 it
    # succeeds once, then neither its body nor predicate are reevaluated.
    assert calls == [0, 0, 0, 1]
    t = begin(s, s.sequence + 1, bar=4, deferred=deferred)
    assert t.state("body", owner="test", schema_version="1", initial=None) == 1
    t.abort()


@pytest.mark.parametrize("closing_condition", [False, True])
def test_once_realtime_rollback_and_varip_do_not_share_lifetime(closing_condition):
    s = session()
    t = begin(s, 0)
    t.commit()
    for seq, condition, final in [(1, True, False), (2, closing_condition, True)]:
        t = begin(s, seq, bar=1, realtime=True, final=final)
        if t.once_v1("written", lambda condition=condition: condition):
            n = t.state(
                "count", owner="test", schema_version="1", initial=0, varip=True
            )
            t.set_slot("count", n + 1, owner="test", varip=True)
        t.commit()
    t = begin(s, 3, bar=2)
    assert t.once_v1("written", lambda: True) is (not closing_condition)
    count = t.state("count", owner="test", schema_version="1", initial=0, varip=True)
    assert count == (2 if closing_condition else 1)
    t.abort()


def test_once_abort_and_json_restore_are_exact():
    s = session()
    t = begin(s, 0)
    assert t.once_v1("once", lambda: True)
    t.abort()
    t = begin(s, 0)
    assert t.once_v1("once", lambda: True)
    t.commit()
    saved = json.loads(json.dumps(s.checkpoint().to_dict()))
    restored = session()
    restored.restore(saved)
    for obj in (s, restored):
        t = begin(obj, 1)
        assert not t.once_v1("once", lambda: 1 / 0)
        t.commit()
    assert s.state_hash == restored.state_hash
    assert s.semantic_state_hash == restored.semantic_state_hash


def test_call_scope_is_written_identity_not_loop_iteration_and_unwinds():
    s = session()
    t = begin(s, 0)

    def f():
        return t.scoped_id_v1("local")

    a = t.invoke_function_v1("A", f, {})
    assert t.invoke_function_v1("A", f, {}) == a
    assert t.invoke_function_v1("B", f, {}) != a

    def bad():
        raise ValueError("test")

    with pytest.raises(ValueError):
        t.invoke_function_v1("B", bad, {})
    assert t._function_path == () and t.scoped_id_v1("global") == "global"
    t.abort()


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize(
    "dtype,values", [("bool", [True, False]), ("float", [1.0, 4.0])]
)
def test_local_series_only_commits_executed_bars_and_restores(version, dtype, values):
    s = session(version)
    for i in range(4):
        t = begin(s, i)
        if i in (0, 3):
            t.set_series("local", values[i == 3], dtype, history_policy="on_evaluation")
        t.commit()
    assert list(s.series["local"].committed) == values
    checkpoint = json.loads(json.dumps(s.checkpoint().to_dict()))
    r = session(version)
    r.restore(checkpoint)
    t = begin(r, 4)
    assert t.op_series_history("local", 1) == values[-1]
    missing = t.op_series_history("local", 3)
    assert missing is False if version == 6 and dtype == "bool" else is_na(missing)
    t.abort()
    assert r.series["local"].history_policy == "on_evaluation"


def test_each_bar_series_keeps_legacy_portable_shape():
    series = SeriesStorage("x", "float")
    series.begin(1)
    series.commit()
    assert set(series.to_json()) == {
        "name",
        "dtype",
        "committed",
        "working",
        "initialized",
        "revision",
    }
    assert SeriesStorage.from_json(series.to_json()).to_json() == series.to_json()


@pytest.mark.parametrize("fault", ["policy", "flag", "missing_flag"])
def test_bad_local_series_snapshot_rejected(fault):
    s = SeriesStorage("x", "float", history_policy="on_evaluation")
    s.begin(1)
    d = s.to_json()
    if fault == "policy":
        d["history_policy"] = "whatever"
    elif fault == "flag":
        d["evaluated"] = 1
    else:
        d.pop("evaluated")
    with pytest.raises(PineRuntimeError):
        SeriesStorage.from_json(d)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("ascending", [False, True])
def test_range_bound_version_and_direction(version, ascending):
    s = session(version)
    t = begin(s, 0)
    bound = 1 if ascending else 2
    out = []
    def end():
        return bound  # Deliberately observe mutations between iterations.

    for i in t.range_v1(0 if ascending else 3, end):
        out.append(i)
        bound = 2 if ascending else 1
    assert (
        out == ([0, 1, 2] if ascending else [3, 2, 1])
        if version == 6
        else out == ([0, 1] if ascending else [3, 2])
    )
    t.abort()


@pytest.mark.parametrize("step", [0, -1, True, 1.1])
def test_bad_step_rejected(step):
    s = session()
    t = begin(s, 0)
    with pytest.raises(PineRuntimeError):
        list(t.range_v1(0, lambda: 1, step))
    t.abort()


def test_dynamic_loop_budget_is_enforced():
    s = session(
        policies=RuntimePolicies(resource=ResourcePolicy(max_loop_iterations=3))
    )
    t = begin(s, 0)
    with pytest.raises(PineRuntimeError, match="budget"):
        list(t.range_v1(0, lambda: 10))
    t.abort()


@pytest.mark.parametrize("op,left", [("and", False), ("or", True)])
def test_lazy_operators_do_not_evaluate_unneeded_branch(op, left):
    s = session()
    t = begin(s, 0)
    assert logical_lazy_v1(t, op, left, lambda: 1 / 0) is left
    t.abort()


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("value", [0, 1, na, None, "x"])
def test_boolean_condition_boundary_is_version_exact(version, value):
    s = session(version)
    t = begin(s, 0)
    if version == 6 or type(value) is str:
        with pytest.raises(PineRuntimeError):
            t.condition_v1(value)
    else:
        assert t.condition_v1(value) is (value == 1)
    t.abort()
