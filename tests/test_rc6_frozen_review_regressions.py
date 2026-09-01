from __future__ import annotations

import pytest

from pinelib import CallbackFrame, ResultShape
from pinelib.errors import PineRuntimeError
from pinelib.reference import array as arrays
from pinelib.request import SnapshotMode
from pinelib.runtime import RuntimeLanguageContext, RuntimeSession
from pinelib.state.checkpoint import RuntimeCheckpoint, from_portable, sha
from tests.stage4_helpers import MemoryProvider, bars, query, request_session, snapshot

HOUR_MS = 60 * 60_000
FLOAT = ResultShape.scalar("float")


class MutableClassGlobal:
    value = 1.0


class OtherMutableClassGlobal:
    value = 1.0


def class_global_expression(_bar, _context):
    return MutableClassGlobal.value


def other_class_global_expression(_bar, _context):
    return OtherMutableClassGlobal.value


def evaluate(runtime, request_query, expression, sequence, opening, closing):
    transaction = runtime.begin(
        CallbackFrame("HISTORICAL_EVAL", sequence, bar_index=sequence)
    )
    value = transaction.requests.security(
        request_query,
        expression,
        FLOAT,
        chart_open_ms=opening,
        chart_close_ms=closing,
    )
    transaction.commit()
    return value


def test_append_rejects_changed_mutable_class_global_state():
    MutableClassGlobal.value = 1.0
    base_query = query(
        snapshot_id="class-global-base", expression_id="expr:class-global"
    )
    append_query = query(
        snapshot_id="class-global-append", expression_id="expr:class-global"
    )
    base_snapshot = snapshot(
        base_query,
        bars(base_query, (10.0,), revision=1),
        revision=1,
    )
    append_snapshot = snapshot(
        append_query,
        bars(append_query, (20.0,), start_ms=HOUR_MS, revision=2),
        revision=2,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=base_snapshot.content_hash,
    )
    provider = MemoryProvider(
        {
            base_query.snapshot_id: base_snapshot,
            append_query.snapshot_id: append_snapshot,
        }
    )
    runtime = request_session(provider)
    evaluate(runtime, base_query, class_global_expression, 0, 0, HOUR_MS)
    checkpoint = runtime.checkpoint().to_dict()
    MutableClassGlobal.value = 999.0
    resumed = request_session(provider)
    resumed.restore(checkpoint)

    try:
        with pytest.raises(PineRuntimeError):
            evaluate(
                resumed,
                append_query,
                class_global_expression,
                1,
                HOUR_MS,
                2 * HOUR_MS,
            )
    finally:
        MutableClassGlobal.value = 1.0


def test_semantically_equivalent_class_globals_have_equal_identity():
    base_query = query(
        snapshot_id="class-equivalent-base", expression_id="expr:class-equivalent"
    )
    append_query = query(
        snapshot_id="class-equivalent-append", expression_id="expr:class-equivalent"
    )
    base_snapshot = snapshot(
        base_query,
        bars(base_query, (10.0,), revision=1),
        revision=1,
    )
    append_snapshot = snapshot(
        append_query,
        bars(append_query, (20.0,), start_ms=HOUR_MS, revision=2),
        revision=2,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=base_snapshot.content_hash,
    )
    provider = MemoryProvider(
        {
            base_query.snapshot_id: base_snapshot,
            append_query.snapshot_id: append_snapshot,
        }
    )
    runtime = request_session(provider)
    evaluate(runtime, base_query, class_global_expression, 0, 0, HOUR_MS)
    resumed = request_session(provider)
    resumed.restore(runtime.checkpoint().to_dict())

    assert evaluate(
        resumed,
        append_query,
        other_class_global_expression,
        1,
        HOUR_MS,
        2 * HOUR_MS,
    ) == pytest.approx(1.0)


def language(source: str) -> RuntimeLanguageContext:
    return RuntimeLanguageContext(6, "test", "default", sha({"source": source}), "test")


def test_restore_rejects_transcript_state_hash_not_bound_to_checkpoint_state():
    runtime_language = language("transcript-state")
    source = RuntimeSession(runtime_language)
    transaction = source.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    transaction.set_series("x", 1.0)
    transaction.commit()
    state = from_portable(source.checkpoint().state)
    assert isinstance(state, dict)
    state["transcript"]["entries"][-1]["state_hash"] = sha(
        {"forged_transcript_state": True}
    )
    state["transcript"]["content_hash"] = sha(
        {"entries": state["transcript"]["entries"]}
    )
    forged = RuntimeCheckpoint.seal(source.identity_hash, state).to_dict()

    with pytest.raises(PineRuntimeError):
        RuntimeSession(runtime_language).restore(forged)


def test_restore_rejects_dangling_reference_handle_graph():
    runtime_language = language("reference-graph")
    source = RuntimeSession(runtime_language)
    transaction = source.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    child = arrays.array_new(
        transaction.references,
        "array:child",
        "array<int>",
        1,
        7,
    )
    arrays.array_new(
        transaction.references,
        "array:root",
        "array<array<int>>",
        1,
        child,
    )
    transaction.commit()
    state = from_portable(source.checkpoint().state)
    assert isinstance(state, dict)
    state["references"]["objects"] = [
        row
        for row in state["references"]["objects"]
        if row["object_id"] != "array:child"
    ]
    without_transcript = {
        key: value for key, value in state.items() if key != "transcript"
    }
    state["transcript"]["entries"][-1]["state_hash"] = sha(without_transcript)
    state["transcript"]["content_hash"] = sha(
        {"entries": state["transcript"]["entries"]}
    )
    forged = RuntimeCheckpoint.seal(source.identity_hash, state).to_dict()

    with pytest.raises(PineRuntimeError):
        RuntimeSession(runtime_language).restore(forged)
