from __future__ import annotations

import copy

import pytest

from pinelib import CallbackFrame
from pinelib.errors import PineRuntimeError
from pinelib.events import SourceSpan
from pinelib.reference import array as arrays
from pinelib.request import DataFinality, ResultShape, SnapshotMode
from pinelib.runtime import RuntimeLanguageContext, RuntimeSession
from pinelib.state.checkpoint import RuntimeCheckpoint, from_portable, sha
from tests.stage3_helpers import language
from tests.stage4_helpers import MemoryProvider, bars, query, request_session, snapshot

HOUR_MS = 60 * 60_000
FLOAT = ResultShape.scalar("float")


def evaluate(runtime, request_query, evaluator, sequence, opening, closing):
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", sequence))
    value = tx.requests.security(
        request_query,
        evaluator,
        FLOAT,
        chart_open_ms=opening,
        chart_close_ms=closing,
    )
    tx.commit()
    return value


def close_expression(bar, _context):
    return bar.number("close")


def checkpoint_state(runtime):
    state = from_portable(runtime.checkpoint().state)
    assert isinstance(state, dict)
    return state


def bind_final_transcript_state(state):
    runtime_state = {key: value for key, value in state.items() if key != "transcript"}
    entries = state["transcript"]["entries"]
    entries[-1]["state_hash"] = sha(runtime_state)
    state["transcript"]["content_hash"] = sha({"entries": entries})


def test_restore_rejects_non_contiguous_transcript_sequences():
    runtime = RuntimeSession(language())
    for sequence, value in enumerate((1, 2)):
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", sequence))
        tx.set_series("x", value)
        tx.commit()

    state = checkpoint_state(runtime)
    entries = state["transcript"]["entries"]
    entries[0]["sequence"] = 7
    state["transcript"]["content_hash"] = sha({"entries": entries})
    forged = RuntimeCheckpoint.seal(runtime.identity_hash, state)

    with pytest.raises(PineRuntimeError):
        RuntimeSession(language()).restore(forged.to_dict())


def test_aborted_callback_does_not_consume_sequence_and_checkpoint_restores():
    runtime = RuntimeSession(language())
    runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0)).abort()

    assert runtime.sequence == -1
    runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0)).commit()

    restored = RuntimeSession(language())
    restored.restore(runtime.checkpoint().to_dict())
    assert restored.sequence == 0
    assert [entry["sequence"] for entry in restored.transcript.entries] == [0]


def test_restore_rejects_missing_v5_static_callsite_binding():
    btc = query(
        version=5,
        snapshot_id="static-btc",
        expression_context_id="call:static",
    )
    provider = MemoryProvider({btc.snapshot_id: snapshot(btc, bars(btc, (1.0,)))})
    runtime = request_session(provider, version=5)
    assert evaluate(runtime, btc, close_expression, 0, 0, HOUR_MS) == 1.0

    state = checkpoint_state(runtime)
    state["requests"]["static_contexts"] = []
    forged = RuntimeCheckpoint.seal(runtime.identity_hash, state)

    with pytest.raises(PineRuntimeError):
        request_session(provider, version=5).restore(forged.to_dict())


def test_restore_rejects_orphan_committed_request_dataset():
    request_query = query(snapshot_id="orphan", version=5)
    provider = MemoryProvider(
        {
            request_query.snapshot_id: snapshot(
                request_query, bars(request_query, (1.0,))
            )
        }
    )
    runtime = request_session(provider, version=5)
    assert evaluate(runtime, request_query, close_expression, 0, 0, 2 * HOUR_MS) == 1.0

    state = copy.deepcopy(checkpoint_state(runtime))
    request_state = state["requests"]
    request_state["registry"]["discovery"] = []
    request_state["registry"]["cursors"] = []
    request_state["evaluators"] = []
    request_state["static_contexts"] = []
    forged = RuntimeCheckpoint.seal(runtime.identity_hash, state)

    with pytest.raises(PineRuntimeError):
        request_session(provider, version=5).restore(forged.to_dict())


def test_restore_accepts_reachable_append_ancestor_without_discovery_root():
    base_query = query(snapshot_id="reachable-base", expression_id="expr:reachable")
    append_query = query(snapshot_id="reachable-next", expression_id="expr:reachable")
    base = snapshot(
        base_query,
        bars(base_query, (1.0,), revision=1),
        revision=1,
    )
    appended = snapshot(
        append_query,
        bars(append_query, (2.0,), start_ms=HOUR_MS, revision=2),
        revision=2,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=base.content_hash,
    )
    provider = MemoryProvider(
        {base_query.snapshot_id: base, append_query.snapshot_id: appended}
    )
    runtime = request_session(provider)
    assert evaluate(runtime, base_query, close_expression, 0, 0, HOUR_MS) == 1.0
    assert (
        evaluate(
            runtime,
            append_query,
            close_expression,
            1,
            HOUR_MS,
            2 * HOUR_MS,
        )
        == 2.0
    )

    state = copy.deepcopy(checkpoint_state(runtime))
    registry = state["requests"]["registry"]
    base_identity = base_query.discovery_identity(FLOAT)
    registry["discovery"] = [
        row for row in registry["discovery"] if row["discovery_id"] != base_identity
    ]
    registry["cursors"] = [
        row for row in registry["cursors"] if row["discovery_id"] != base_identity
    ]
    bind_final_transcript_state(state)
    forged = RuntimeCheckpoint.seal(runtime.identity_hash, state)

    restored = request_session(provider)
    restored.restore(forged.to_dict())
    assert restored.requests.registry.dataset_count == 2
    assert restored.requests.registry.discovery_count == 1


def test_restore_rejects_integer_payload_for_float_result_shape():
    request_query = query(snapshot_id="shape")
    provider = MemoryProvider(
        {
            request_query.snapshot_id: snapshot(
                request_query,
                bars(request_query, (1.0,)),
            )
        }
    )
    runtime = request_session(provider)
    assert evaluate(runtime, request_query, close_expression, 0, 0, HOUR_MS) == 1.0

    state = checkpoint_state(runtime)
    dataset = state["requests"]["registry"]["datasets"][0]
    dataset["evaluated_bars"][0]["value"] = 1
    body = {key: value for key, value in dataset.items() if key != "content_hash"}
    dataset["content_hash"] = sha(body)
    forged = RuntimeCheckpoint.seal(runtime.identity_hash, state)

    with pytest.raises(PineRuntimeError):
        request_session(provider).restore(forged.to_dict())


def test_restore_rejects_negative_reference_revisions():
    runtime = RuntimeSession(language())
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    arrays.array_new(
        runtime.references,
        "array:negative-revision",
        "array<int>",
        1,
        1,
    )
    tx.commit()

    state = checkpoint_state(runtime)
    row = state["references"]["objects"][0]
    row["committed_revision"] = -1
    row["working_revision"] = -1
    forged = RuntimeCheckpoint.seal(runtime.identity_hash, state)

    with pytest.raises(PineRuntimeError):
        RuntimeSession(language()).restore(forged.to_dict())


def test_append_requires_strictly_increasing_revision():
    base_query = query(snapshot_id="rev-base", expression_id="expr:rev")
    append_query = query(snapshot_id="rev-append", expression_id="expr:rev")
    base = snapshot(
        base_query,
        bars(base_query, (1.0,), revision=1),
        revision=1,
    )
    same_revision = snapshot(
        append_query,
        bars(append_query, (2.0,), start_ms=HOUR_MS, revision=1),
        revision=1,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=base.content_hash,
    )
    provider = MemoryProvider(
        {base_query.snapshot_id: base, append_query.snapshot_id: same_revision}
    )
    runtime = request_session(provider)
    evaluate(runtime, base_query, close_expression, 0, 0, HOUR_MS)

    with pytest.raises(PineRuntimeError):
        evaluate(
            runtime,
            append_query,
            close_expression,
            1,
            HOUR_MS,
            2 * HOUR_MS,
        )


def test_append_rejects_non_final_interior_bar():
    base_query = query(snapshot_id="fin-base", expression_id="expr:fin")
    append_query = query(snapshot_id="fin-append", expression_id="expr:fin")
    base = snapshot(
        base_query,
        bars(base_query, (1.0,), revision=1),
        revision=1,
    )
    delta = bars(
        append_query,
        (2.0, 3.0),
        start_ms=HOUR_MS,
        finalities=(DataFinality.DEVELOPING, DataFinality.FINAL),
        revision=2,
    )
    invalid_append = snapshot(
        append_query,
        delta,
        revision=2,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=base.content_hash,
    )
    provider = MemoryProvider(
        {base_query.snapshot_id: base, append_query.snapshot_id: invalid_append}
    )
    runtime = request_session(provider)
    evaluate(runtime, base_query, close_expression, 0, 0, HOUR_MS)

    with pytest.raises(PineRuntimeError):
        evaluate(
            runtime,
            append_query,
            close_expression,
            1,
            2 * HOUR_MS,
            3 * HOUR_MS,
        )


def test_append_rejects_changed_mutable_evaluator_closure():
    base_query = query(snapshot_id="eval-base", expression_id="expr:mutable")
    append_query = query(snapshot_id="eval-append", expression_id="expr:mutable")
    base = snapshot(
        base_query,
        bars(base_query, (10.0,), revision=1),
        revision=1,
    )
    appended = snapshot(
        append_query,
        bars(append_query, (20.0,), start_ms=HOUR_MS, revision=2),
        revision=2,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=base.content_hash,
    )
    provider = MemoryProvider(
        {base_query.snapshot_id: base, append_query.snapshot_id: appended}
    )
    captured = {"value": 1.0}

    def mutable_evaluator(_bar, _context):
        return captured["value"]

    runtime = request_session(provider)
    assert evaluate(runtime, base_query, mutable_evaluator, 0, 0, HOUR_MS) == 1.0
    captured["value"] = 999.0

    with pytest.raises(PineRuntimeError):
        evaluate(
            runtime,
            append_query,
            mutable_evaluator,
            1,
            HOUR_MS,
            2 * HOUR_MS,
        )


def test_callback_frame_rejects_non_boolean_final_tick_without_mutation():
    runtime = RuntimeSession(language())

    with pytest.raises(PineRuntimeError):
        CallbackFrame("HISTORICAL_EVAL", 0, False, 1)  # type: ignore[arg-type]

    assert runtime._active is None
    assert "x" not in runtime.series
    assert runtime.transcript.entries == []


def test_context_and_source_span_reject_noncanonical_sha256():
    pseudo_digest = "sha256:" + "g" * 64

    with pytest.raises(PineRuntimeError):
        RuntimeLanguageContext(
            6,
            "rev",
            "profile",
            pseudo_digest,
            "compiler_annotation",
        )
    with pytest.raises(PineRuntimeError):
        SourceSpan(pseudo_digest, "f", 0, 0, 0, 1)
