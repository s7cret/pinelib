"""Reference identity follows evaluations; persistence follows owning Pine slots."""

import json

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import (
    array_get,
    array_new,
    array_push,
    array_set,
    array_size,
)
from pinelib.reference.heap import ReferenceHandle
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies


def runtime(policies=None):
    return RuntimeSession(
        RuntimeLanguageContext(
            6,
            "reference-language",
            "pine-v6",
            "sha256:" + "a" * 64,
            "compiler_annotation",
        ),
        policies,
    )


def begin(s, seq, bar=None, *, realtime=False, final=True):
    return s.begin(
        CallbackFrame(
            "REALTIME_TICK" if realtime else "HISTORICAL_EVAL",
            seq,
            bar_index=seq if bar is None else bar,
            realtime=realtime,
            final_tick=final,
        )
    )


def create(t, value=0.0, source="create"):
    return array_new(t.references, t.new_reference_id_v1(source), "float", 1, value)


@pytest.mark.parametrize("mode", ["default", "var", "varip"])
def test_per_bar_allocation_history_and_persistent_reference(mode):
    s = runtime()
    handles = []
    for i in range(3):
        t = begin(s, i)
        h = t.declare_reference_v1(
            "a", mode, lambda t=t, i=i: create(t, float(i)), "array<float>"
        )
        handles.append(h)
        if i:
            prior = t.op_series_history("a", 1)
            assert isinstance(prior, ReferenceHandle)
            assert prior == handles[i - 1]
        else:
            assert is_na(t.op_series_history("a", 1))
        assert array_get(t.references, h, 0) == (i if mode == "default" else 0)
        t.commit()
    assert len(set(handles)) == (3 if mode == "default" else 1)
    saved = json.loads(json.dumps(s.checkpoint().to_dict()))
    r = runtime()
    r.restore(saved)
    t = begin(r, 3)
    assert t.op_series_history("a", 1) == handles[-1]
    assert array_get(t.references, handles[0], 0) == 0
    t.abort()
    assert r.state_hash == s.state_hash


@pytest.mark.parametrize("mode,expected", [("var", [1, 1, 1]), ("varip", [1, 2, 3])])
def test_varip_reference_mutations_survive_intrabar_not_normal_var(mode, expected):
    s = runtime()
    t = begin(s, 0)
    h = t.declare_reference_v1("a", mode, lambda: create(t, 0.0), "array<float>")
    t.commit()
    for seq in (1, 2, 3):
        t = begin(s, seq, bar=1, realtime=True, final=seq == 3)
        actual = t.declare_reference_v1("a", mode, lambda: 1 / 0, "array<float>")
        assert actual == h
        array_set(t.references, actual, 0, array_get(t.references, actual, 0) + 1)
        assert array_get(t.references, h, 0) == expected[seq - 1]
        t.commit()
    assert array_get(s.references, h, 0) == expected[-1]


def test_new_varip_object_survives_abort_and_same_callback_retry_without_collision():
    s = runtime()
    t = begin(s, 0, bar=0, realtime=True, final=False)
    first = t.declare_reference_v1("a", "varip", lambda: create(t, 7.0), "array<float>")
    scratch = create(t, 99.0)
    t.abort()
    t = begin(s, 0, bar=0, realtime=True, final=True)
    retained = t.declare_reference_v1("a", "varip", lambda: 1 / 0, "array<float>")
    assert retained == first
    assert array_get(t.references, retained, 0) == 7
    second = create(t, 2.0)
    assert second != first
    # Unrooted object is rolled back, so its identity may safely be reused.
    assert second == scratch
    t.commit()


def test_ordinary_aborted_allocations_replay_deterministically():
    s = runtime()
    t = begin(s, 0)
    expected = [create(t, float(i)) for i in range(3)]
    t.abort()
    t = begin(s, 0)
    actual = [create(t, float(i)) for i in range(3)]
    assert expected == actual and len(set(actual)) == 3
    t.commit()


def test_written_function_calls_and_loop_allocations_have_independent_ids():
    s = runtime()
    t = begin(s, 0)

    def function():
        return create(t)

    a = [t.invoke_function_v1("site-A", function, {}) for _ in range(3)]
    b = t.invoke_function_v1("site-B", function, {})
    assert len({*a, b}) == 4
    t.commit()


@pytest.mark.parametrize(
    "fault", ["wrong_kind", "wrong_element", "foreign", "bad_marker", "plain_payload"]
)
def test_declared_reference_identity_and_type_must_be_valid(fault):
    s = runtime()
    t = begin(s, 0)
    value = create(t)
    dtype = "array<float>"
    if fault == "wrong_kind":
        dtype = "matrix<float>"
    elif fault == "wrong_element":
        dtype = "array<int>"
    elif fault == "foreign":
        value = ReferenceHandle("foreign", "array")
    elif fault == "bad_marker":
        value = {"$pinelib_ref": {"object_id": value.object_id}}
    else:
        value = [1.0]
    with pytest.raises(PineRuntimeError):
        t.declare_reference_v1("a", "default", lambda: value, dtype)
    t.abort()


def test_reference_reassignment_preserves_alias_and_distinct_history():
    s = runtime()
    t = begin(s, 0)
    a = t.declare_reference_v1("a", "var", lambda: create(t, 3.0), "array<float>")
    t.declare_reference_v1("b", "default", lambda: a, "array<float>")
    t.commit()
    t = begin(s, 1)
    b = t.op_series_history("b", 1)
    a2 = create(t, 5.0)
    t.write_reference_v1("a", "var", a2, "array<float>")
    array_set(t.references, b, 0, 9.0)
    assert t.op_series_history("a", 1) == a
    assert array_get(t.references, a, 0) == 9 and array_get(t.references, a2, 0) == 5
    t.commit()


def test_iterator_reads_live_reference_and_dynamic_length_not_copied_payload():
    s = runtime()
    t = begin(s, 0)
    a = create(t, 1.0)
    seen = []
    for index, value in t.array_iterator_v1(a, indexed=True):
        seen.append((index, value))
        if index == 0:
            array_push(t.references, a, 2.0)
        elif index == 1:
            array_push(t.references, a, 3.0)
    assert seen == [(0, 1), (1, 2), (2, 3)] and array_size(t.references, a) == 3
    t.abort()


def test_growing_array_iteration_obeys_resource_limit():
    s = runtime(RuntimePolicies(resource=ResourcePolicy(max_loop_iterations=3)))
    t = begin(s, 0)
    a = create(t)
    with pytest.raises(PineRuntimeError, match="budget"):
        for value in t.array_iterator_v1(a):
            array_push(t.references, a, value)
    t.abort()


def test_checkpoint_continuation_reuses_no_objects_and_preserves_semantic_hashes():
    def advance(s, start, end):
        result = []
        for seq in range(start, end):
            t = begin(s, seq)
            a = t.declare_reference_v1(
                "a",
                "default",
                lambda t=t, seq=seq: create(t, float(seq)),
                "array<float>",
            )
            result.append(a)
            t.commit()
        return result

    whole = runtime()
    expected = advance(whole, 0, 8)
    split = runtime()
    first = advance(split, 0, 3)
    restored = runtime()
    restored.restore(json.loads(json.dumps(split.checkpoint().to_dict())))
    remaining = advance(restored, 3, 8)
    assert first + remaining == expected
    assert restored.state_hash == whole.state_hash
    assert restored.semantic_state_hash == whole.semantic_state_hash
    assert restored.checkpoint().to_dict() == whole.checkpoint().to_dict()
