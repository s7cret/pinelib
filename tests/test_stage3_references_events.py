from __future__ import annotations

import pytest

from pinelib.abi import alert, string, visual
from pinelib.abi import reference as ref
from pinelib.core import is_na, na
from pinelib.errors import PineRuntimeError
from pinelib.runtime import CallbackFrame
from tests.stage3_helpers import session, span


def rollback_sensitive_state(runtime):
    return {
        key: value
        for key, value in runtime.checkpoint().state.items()
        if key not in {"sequence", "transcript"}
    }


def test_array_alias_copy_shift_bounds_and_versioned_negative_indexes():
    runtime = session(6)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    handle = ref.array_new_v1(tx, "array:source", "array<int>", 0, na)
    for value in (1, 2, 3):
        ref.array_push_v1(tx, handle, value)
    alias = handle
    assert ref.array_shift_v1(tx, handle) == 1
    assert ref.array_get_v1(tx, alias, -1) == 3
    copied = ref.array_copy_v1(tx, handle, "array:copy")
    ref.array_set_v1(tx, copied, 0, 99)
    assert ref.array_get_v1(tx, handle, 0) == 2
    assert ref.array_get_v1(tx, copied, 0) == 99
    with pytest.raises(PineRuntimeError):
        ref.array_get_v1(tx, handle, 99)
    tx.commit()

    runtime5 = session(5)
    tx5 = runtime5.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    handle5 = ref.array_new_v1(tx5, "array:v5", "array<int>", 1, 1)
    with pytest.raises(PineRuntimeError):
        ref.array_get_v1(tx5, handle5, -1)
    tx5.abort()


def test_maps_matrices_udt_enum_and_checkpoint_roundtrip():
    runtime = session()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    mapping = ref.map_new_v1(tx, "map:1", "map<string,int>")
    assert is_na(ref.map_put_v1(tx, mapping, "a", 1))
    assert ref.map_put_v1(tx, mapping, "a", 2) == 1
    ref.map_put_v1(tx, mapping, "b", 3)
    assert ref.map_keys_v1(tx, mapping) == ("a", "b")
    assert ref.map_values_v1(tx, mapping) == (2, 3)
    matrix = ref.matrix_new_v1(tx, "matrix:1", "matrix<int>", 2, 2, 0)
    ref.matrix_set_v1(tx, matrix, 1, 1, 7)
    assert ref.matrix_get_v1(tx, matrix, 1, 1) == 7
    point = ref.udt_new_v1(tx, "udt:1", "Point", {"x": 1, "y": 2})
    ref.udt_set_v1(tx, point, "x", 5)
    assert ref.udt_get_v1(tx, point, "x") == 5
    assert ref.enum_value_v1("Side", "long", 0) == ref.enum_value_v1("Side", "long", 0)
    tx.commit()
    checkpoint = runtime.checkpoint().to_dict()
    restored = session()
    restored.restore(checkpoint)
    assert restored.state_hash == runtime.state_hash


def test_reference_heap_rolls_back_created_and_mutated_objects():
    runtime = session()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    handle = ref.array_new_v1(tx, "array:1", "array<int>", 1, 1)
    tx.commit()
    before = rollback_sensitive_state(runtime)
    before_transcript = runtime.transcript.to_dict()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    ref.array_set_v1(tx, handle, 0, 9)
    ref.array_new_v1(tx, "array:transient", "array<int>", 1, 2)
    tx.abort()
    assert rollback_sensitive_state(runtime) == before
    assert runtime.sequence == 0
    assert runtime.transcript.to_dict() == before_transcript
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 2))
    assert ref.array_get_v1(tx, handle, 0) == 1
    with pytest.raises(PineRuntimeError):
        ref.array_get_v1(tx, type(handle)("array:transient", "array"), 0)
    tx.abort()


def test_str_split_returns_heap_array():
    runtime = session()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    handle = string.split_v1(tx, "split:1", "a,b,c", ",")
    assert ref.array_values_v1(tx, handle) == ("a", "b", "c")
    tx.commit()


def test_visual_and_alert_tapes_commit_abort_and_do_not_render_or_notify():
    runtime = session()
    sp = span()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    plot = visual.plot_v1(tx, "plot:1", sp, 10, title="x")
    notice = alert.alert_v1(tx, "alert:1", sp, "hello")
    result = tx.commit()
    assert len(runtime.visuals.committed) == 1
    assert len(runtime.alerts.committed) == 1
    assert result.visual_batch_hash and result.alert_batch_hash
    assert plot.delivery_id != notice.delivery_id

    before = rollback_sensitive_state(runtime)
    before_transcript = runtime.transcript.to_dict()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    visual.bgcolor_v1(tx, "bg:1", sp, "red")
    alert.alertcondition_v1(tx, "cond:1", sp, True, "x", "y")
    tx.abort()
    assert rollback_sensitive_state(runtime) == before
    assert runtime.sequence == 0
    assert runtime.transcript.to_dict() == before_transcript
    assert len(runtime.visuals.committed) == 1
    assert len(runtime.alerts.committed) == 1


def test_visual_object_identity_mutation_and_deterministic_replay():
    def run():
        runtime = session()
        sp = span()
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
        line = visual.line_new_v1(tx, "line:new", sp, "line:1", 0, 1, 2, 3)
        visual.line_set_xy1_v1(tx, "line:set1", sp, line, 4, 5)
        label = visual.label_new_v1(tx, "label:new", sp, "label:1", 1, 2, "A")
        visual.label_set_text_v1(tx, "label:set", sp, label, "B")
        result = tx.commit()
        return (
            runtime.state_hash,
            result.visual_batch_hash,
            runtime.checkpoint().content_hash,
        )

    assert run() == run()


def test_nonfinal_realtime_events_are_returned_but_not_committed():
    runtime = session()
    tx = runtime.begin(
        CallbackFrame("REALTIME_TICK", 0, True, False, bar_index=0, tick_index=0)
    )
    visual.plot_v1(tx, "plot:1", span(), 1)
    result = tx.commit()
    assert result.committed
    assert not runtime.visuals.committed
    tx = runtime.begin(
        CallbackFrame("REALTIME_TICK", 1, True, True, bar_index=0, tick_index=1)
    )
    visual.plot_v1(tx, "plot:1", span(), 2)
    tx.commit()
    assert len(runtime.visuals.committed) == 1
