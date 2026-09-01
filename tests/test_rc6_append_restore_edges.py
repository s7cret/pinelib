from __future__ import annotations

import copy

import pytest

from pinelib import CallbackFrame, ResultShape
from pinelib.errors import PineRuntimeError
from pinelib.request import DataFinality, SnapshotMode
from pinelib.request.models import (
    EvaluatedBar,
    RequestChildContext,
    RequestDataset,
    RequestDatasetKey,
)
from pinelib.state.checkpoint import RuntimeCheckpoint, from_portable, sha
from tests.stage4_helpers import MemoryProvider, bars, query, request_session, snapshot

HOUR_MS = 60 * 60_000
FLOAT = ResultShape.scalar("float")


def expression(bar, _context):
    return bar.number("close")


def evaluate(runtime, request_query, sequence, opening, closing):
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


def evaluated(source_bar, value):
    return EvaluatedBar(
        source_bar.open_time_ms,
        source_bar.close_time_ms,
        source_bar.finality,
        source_bar.revision,
        FLOAT.validate(value),
    )


def dataset(runtime, request_query, sealed_snapshot, rows):
    key = RequestDatasetKey.create(request_query, sealed_snapshot.content_hash, FLOAT)
    child = RequestChildContext.seal(
        language_hash=sha(runtime.language.identity()),
        policy_hash=sha(runtime.policies.identity()),
        instrument_id=request_query.instrument_id,
        timeframe=request_query.timeframe,
        dataset_key_hash=key.key_hash,
        namespace=(
            f"{request_query.expression_context_id}:"
            f"{request_query.expression_id}:{key.key_hash}"
        ),
        parent_runtime_hash=runtime.identity_hash,
    )
    result = RequestDataset.ready(
        key=key,
        shape=FLOAT,
        snapshot=sealed_snapshot,
        evaluated_bars=rows,
        child_context=child,
        child_state={},
        lineage_hash=request_query.lineage_hash,
    )
    assert RequestDataset.from_dict(result.to_dict()).to_dict() == result.to_dict()
    return result


def forged_graph(case):
    base_query = query(
        snapshot_id="restore-edge-base", expression_id="expr:restore-edge"
    )
    append_query = query(
        snapshot_id="restore-edge-next", expression_id="expr:restore-edge"
    )
    valid_base = snapshot(
        base_query,
        bars(base_query, (1.0,), revision=1),
        revision=1,
    )
    valid_append = snapshot(
        append_query,
        bars(append_query, (2.0,), start_ms=HOUR_MS, revision=2),
        revision=2,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=valid_base.content_hash,
    )
    provider = MemoryProvider(
        {
            base_query.snapshot_id: valid_base,
            append_query.snapshot_id: valid_append,
        }
    )
    source = request_session(provider)
    evaluate(source, base_query, 0, 0, HOUR_MS)
    evaluate(source, append_query, 1, HOUR_MS, 2 * HOUR_MS)
    valid_state = from_portable(source.checkpoint().state)
    assert isinstance(valid_state, dict)
    valid_requests = source.requests.to_json()
    evaluator_by_discovery = {
        row["discovery_id"]: row["evaluator_identity"]
        for row in valid_requests["evaluators"]
    }

    parent_finality = (
        DataFinality.DEVELOPING
        if case == "parent_developing_tail"
        else DataFinality.FINAL
    )
    parent_bars = bars(
        base_query,
        (1.0,),
        revision=1,
        finalities=(parent_finality,),
    )
    parent_snapshot = snapshot(base_query, parent_bars, revision=1)
    child_revision = 1 if case == "child_revision_not_greater" else 2
    child_start = HOUR_MS // 2 if case == "child_overlaps_parent" else HOUR_MS
    child_values = (2.0, 3.0) if case == "child_nonfinal_interior" else (2.0,)
    child_finalities = (
        (DataFinality.DEVELOPING, DataFinality.FINAL)
        if case == "child_nonfinal_interior"
        else (DataFinality.FINAL,)
    )
    child_bars = bars(
        append_query,
        child_values,
        start_ms=child_start,
        revision=(1 if case == "child_bar_revision_mismatch" else child_revision),
        finalities=child_finalities,
    )
    child_snapshot = snapshot(
        append_query,
        child_bars,
        revision=child_revision,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=(
            sha({"missing_parent": True})
            if case == "parent_missing"
            else parent_snapshot.content_hash
        ),
    )
    parent_rows = (evaluated(parent_bars[0], 1.0),)
    delta_rows = tuple(
        evaluated(child_bar, value)
        for child_bar, value in zip(child_bars, child_values, strict=True)
    )
    child_rows = (
        (evaluated(parent_bars[0], 999.0), *delta_rows)
        if case == "child_prefix_differs"
        else (*parent_rows, *delta_rows)
    )
    parent_dataset = dataset(source, base_query, parent_snapshot, parent_rows)
    child_dataset = dataset(source, append_query, child_snapshot, child_rows)
    base_discovery = base_query.discovery_identity(FLOAT)
    append_discovery = append_query.discovery_identity(FLOAT)
    request_state = {
        "provider_identity": copy.deepcopy(valid_requests["provider_identity"]),
        "registry": {
            "datasets": [
                item.to_dict()
                for item in sorted(
                    (parent_dataset, child_dataset), key=lambda row: row.key.key_hash
                )
            ],
            "discovery": [
                {
                    "discovery_id": append_discovery,
                    "dataset_key_hash": child_dataset.key.key_hash,
                }
            ],
            "cursors": [],
        },
        "evaluators": [
            {
                "discovery_id": discovery_id,
                "evaluator_identity": (
                    sha({"mismatched_parent_evaluator": True})
                    if case == "evaluator_lineage_mismatch"
                    and discovery_id == base_discovery
                    else evaluator_by_discovery[discovery_id]
                ),
            }
            for discovery_id in sorted((base_discovery, append_discovery))
        ],
        "static_contexts": [],
    }
    state = copy.deepcopy(valid_state)
    state["requests"] = request_state
    state_without_transcript = {
        key: value for key, value in state.items() if key != "transcript"
    }
    state["transcript"]["entries"][-1]["state_hash"] = sha(state_without_transcript)
    state["transcript"]["content_hash"] = sha(
        {"entries": state["transcript"]["entries"]}
    )
    checkpoint = RuntimeCheckpoint.seal(source.identity_hash, state).to_dict()
    return checkpoint, provider


@pytest.mark.parametrize(
    "case",
    (
        "child_revision_not_greater",
        "child_bar_revision_mismatch",
        "child_nonfinal_interior",
        "parent_missing",
        "parent_developing_tail",
        "child_overlaps_parent",
        "child_prefix_differs",
        "evaluator_lineage_mismatch",
    ),
)
def test_restore_rejects_invalid_append_edge(case):
    checkpoint, provider = forged_graph(case)
    with pytest.raises(PineRuntimeError):
        request_session(provider).restore(checkpoint)


def test_restore_accepts_reachable_append_ancestor_without_discovery_root():
    checkpoint, provider = forged_graph("valid")
    restored = request_session(provider)
    restored.restore(checkpoint)
    assert restored.requests.registry.dataset_count == 2
    assert restored.requests.registry.discovery_count == 1


def test_registry_identity_accessors_and_parent_hash_guard_are_strict():
    request_query = query(snapshot_id="registry-identity-guards")
    provider = MemoryProvider(
        {
            request_query.snapshot_id: snapshot(
                request_query,
                bars(request_query, (1.0,)),
            )
        }
    )
    runtime = request_session(provider)
    evaluate(runtime, request_query, 0, 0, HOUR_MS)
    discovery_id = request_query.discovery_identity(FLOAT)
    registry = runtime.requests.registry
    assert registry.discovery_ids == (discovery_id,)
    assert registry.lookup_dataset_identity(discovery_id) is not None
    with pytest.raises(PineRuntimeError):
        registry.lookup_dataset_identity("not-a-canonical-hash")
    with pytest.raises(PineRuntimeError):
        registry.validate_parent_identity("not-a-canonical-hash")
