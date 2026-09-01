from __future__ import annotations

import copy
from collections.abc import Callable
from types import ModuleType

import pytest

from pinelib import CallbackFrame, ResultShape
from pinelib.errors import PineRuntimeError
from pinelib.request import SnapshotMode
from pinelib.request.models import (
    CanonicalBar,
    DataCoverage,
    DataSnapshot,
    EvaluatedBar,
    RequestChildContext,
    RequestDatasetKey,
    RequestQuery,
)
from pinelib.request.models import ResultShape as RequestResultShape
from pinelib.state.checkpoint import RuntimeCheckpoint, from_portable, sha
from tests.stage4_helpers import MemoryProvider, bars, query, request_session, snapshot

HOUR_MS = 60 * 60_000
FLOAT = ResultShape.scalar("float")
GLOBAL_EVALUATOR_STATE = {"value": 1.0}
GLOBAL_EVALUATOR_MODULE = ModuleType("pinelib_test_evaluator_module")
GLOBAL_EVALUATOR_MODULE.state = {"value": 1.0}
GLOBAL_NONSTRING_MAPPING = {1: "value"}
GLOBAL_UNSUPPORTED_SET = {1}
GLOBAL_BYTES = b"pinelib"
GLOBAL_LEN = len


class BoundEvaluator:
    def __init__(self, value: float) -> None:
        self.value = value

    def identity(self) -> dict[str, float]:
        return {"value": self.value}

    def evaluate(self, _bar, _context):
        return self.value


def close_expression(bar, _context):
    return bar.number("close")


def global_expression(_bar, _context):
    return GLOBAL_EVALUATOR_STATE["value"]


def module_global_expression(_bar, _context):
    return GLOBAL_EVALUATOR_MODULE.state["value"]


def direct_module_expression(_bar, _context):
    return GLOBAL_EVALUATOR_MODULE


def missing_module_attribute_expression(_bar, _context):
    return GLOBAL_EVALUATOR_MODULE.missing


def nonstring_mapping_expression(_bar, _context):
    return GLOBAL_NONSTRING_MAPPING[1]


def unsupported_set_expression(_bar, _context):
    return len(GLOBAL_UNSUPPORTED_SET)


def portable_global_expression(_bar, _context):
    return float(GLOBAL_LEN(GLOBAL_BYTES))


def cyclic_helper(bar, context):
    if context.state("cycle", False):
        return cyclic_expression(bar, context)
    return bar.number("close")


def cyclic_expression(bar, context):
    return cyclic_helper(bar, context)


def evaluate(
    runtime,
    request_query,
    expression: Callable[..., object],
    sequence: int,
    opening: int,
    closing: int,
):
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


def single_evaluation(expression: Callable[..., object], snapshot_id: str):
    request_query = query(snapshot_id=snapshot_id)
    provider = MemoryProvider(
        {
            request_query.snapshot_id: snapshot(
                request_query,
                bars(request_query, (1.0,)),
            )
        }
    )
    return evaluate(
        request_session(provider),
        request_query,
        expression,
        0,
        0,
        HOUR_MS,
    )


@pytest.mark.parametrize(
    "expression",
    (
        direct_module_expression,
        missing_module_attribute_expression,
        nonstring_mapping_expression,
        unsupported_set_expression,
    ),
)
def test_implicit_evaluator_rejects_unstable_global_graph(expression):
    with pytest.raises(PineRuntimeError):
        single_evaluation(expression, f"unstable:{expression.__name__}")


def test_implicit_evaluator_supports_portable_and_recursive_globals():
    assert single_evaluation(portable_global_expression, "portable-globals") == 7.0
    assert single_evaluation(cyclic_expression, "recursive-globals") == 1.0


def test_restore_rejects_integer_for_request_query_boolean():
    request_query = query(snapshot_id="bool-int-type-confusion")
    provider = MemoryProvider(
        {
            request_query.snapshot_id: snapshot(
                request_query,
                bars(request_query, (1.0,)),
            )
        }
    )
    source = request_session(provider)
    evaluate(source, request_query, close_expression, 0, 0, HOUR_MS)
    state = from_portable(source.checkpoint().state)
    assert isinstance(state, dict)
    query_payload = state["requests"]["registry"]["datasets"][0]["key"]["query"]
    assert type(query_payload["dynamic"]) is bool
    query_payload["dynamic"] = int(query_payload["dynamic"])
    assert type(query_payload["dynamic"]) is int
    without_transcript = {
        key: value for key, value in state.items() if key != "transcript"
    }
    state["transcript"]["entries"][-1]["state_hash"] = sha(without_transcript)
    state["transcript"]["content_hash"] = sha(
        {"entries": state["transcript"]["entries"]}
    )
    forged = RuntimeCheckpoint.seal(source.identity_hash, state).to_dict()

    with pytest.raises(PineRuntimeError):
        request_session(provider).restore(forged)


def test_append_rejects_changed_module_global_evaluator_state():
    GLOBAL_EVALUATOR_STATE["value"] = 1.0
    base_query = query(snapshot_id="global-evaluator-base", expression_id="expr:global")
    append_query = query(
        snapshot_id="global-evaluator-append", expression_id="expr:global"
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
    source = request_session(provider)
    evaluate(source, base_query, global_expression, 0, 0, HOUR_MS)
    checkpoint = source.checkpoint().to_dict()
    GLOBAL_EVALUATOR_STATE["value"] = 999.0
    resumed = request_session(provider)
    resumed.restore(checkpoint)

    try:
        with pytest.raises(PineRuntimeError):
            evaluate(
                resumed,
                append_query,
                global_expression,
                1,
                HOUR_MS,
                2 * HOUR_MS,
            )
    finally:
        GLOBAL_EVALUATOR_STATE["value"] = 1.0


def test_append_rejects_changed_bound_evaluator_state():
    evaluator = BoundEvaluator(1.0)
    base_query = query(snapshot_id="bound-evaluator-base", expression_id="expr:bound")
    append_query = query(
        snapshot_id="bound-evaluator-append", expression_id="expr:bound"
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
    source = request_session(provider)
    evaluate(source, base_query, evaluator.evaluate, 0, 0, HOUR_MS)
    checkpoint = source.checkpoint().to_dict()
    evaluator.value = 999.0
    resumed = request_session(provider)
    resumed.restore(checkpoint)

    with pytest.raises(PineRuntimeError):
        evaluate(
            resumed,
            append_query,
            evaluator.evaluate,
            1,
            HOUR_MS,
            2 * HOUR_MS,
        )


def test_append_rejects_changed_module_attribute_evaluator_state():
    GLOBAL_EVALUATOR_MODULE.state["value"] = 1.0
    base_query = query(
        snapshot_id="module-evaluator-base", expression_id="expr:module-global"
    )
    append_query = query(
        snapshot_id="module-evaluator-append", expression_id="expr:module-global"
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
    source = request_session(provider)
    evaluate(source, base_query, module_global_expression, 0, 0, HOUR_MS)
    checkpoint = source.checkpoint().to_dict()
    GLOBAL_EVALUATOR_MODULE.state["value"] = 999.0
    resumed = request_session(provider)
    resumed.restore(checkpoint)

    try:
        with pytest.raises(PineRuntimeError):
            evaluate(
                resumed,
                append_query,
                module_global_expression,
                1,
                HOUR_MS,
                2 * HOUR_MS,
            )
    finally:
        GLOBAL_EVALUATOR_MODULE.state["value"] = 1.0


def test_child_context_from_dict_rejects_numeric_namespace_normalization():
    context = RequestChildContext.seal(
        language_hash=sha({"language": True}),
        policy_hash=sha({"policy": True}),
        instrument_id="instrument:test",
        timeframe="60",
        dataset_key_hash=sha({"dataset": True}),
        namespace="1",
        parent_runtime_hash=sha({"runtime": True}),
    )
    payload = context.to_dict()
    payload["namespace"] = 1
    with pytest.raises(PineRuntimeError):
        RequestChildContext.from_dict(payload)


def test_result_shape_from_dict_rejects_numeric_field_name_normalization():
    shape = RequestResultShape.udt("strict-shape", {"1": FLOAT})
    payload = shape.identity()
    payload["fields"][0]["name"] = 1
    with pytest.raises(PineRuntimeError):
        RequestResultShape.from_dict(payload)


@pytest.mark.parametrize(
    "case",
    (
        "query_dynamic",
        "bar_open",
        "bar_open_time",
        "bar_revision",
        "coverage_bars_available",
        "snapshot_revision",
        "key_invalid_symbol",
        "evaluated_open_time",
        "evaluated_revision",
        "shape_nullable",
    ),
)
def test_request_model_from_dict_rejects_noncanonical_exact_types(case):
    request_query = query(snapshot_id="strict-model-types")
    source_bar = bars(request_query, (1.0,), revision=1)[0]
    sealed_snapshot = snapshot(
        request_query,
        (source_bar,),
        revision=1,
    )
    key = RequestDatasetKey.create(
        request_query,
        sealed_snapshot.content_hash,
        FLOAT,
    )
    evaluated_bar = EvaluatedBar(
        source_bar.open_time_ms,
        source_bar.close_time_ms,
        source_bar.finality,
        source_bar.revision,
        FLOAT.validate(1.0),
    )
    model_cases = {
        "query_dynamic": (
            RequestQuery.from_dict,
            request_query.identity(),
            "dynamic",
            0,
        ),
        "bar_open": (CanonicalBar.from_dict, source_bar.identity(), "open", 1),
        "bar_open_time": (
            CanonicalBar.from_dict,
            source_bar.identity(),
            "open_time_ms",
            False,
        ),
        "bar_revision": (
            CanonicalBar.from_dict,
            source_bar.identity(),
            "revision",
            True,
        ),
        "coverage_bars_available": (
            DataCoverage.from_dict,
            sealed_snapshot.coverage.identity(),
            "bars_available",
            True,
        ),
        "snapshot_revision": (
            DataSnapshot.from_dict,
            sealed_snapshot.to_dict(),
            "revision",
            True,
        ),
        "key_invalid_symbol": (
            RequestDatasetKey.from_dict,
            key.to_dict(),
            "invalid_symbol",
            0,
        ),
        "evaluated_open_time": (
            EvaluatedBar.from_dict,
            evaluated_bar.to_dict(),
            "open_time_ms",
            False,
        ),
        "evaluated_revision": (
            EvaluatedBar.from_dict,
            evaluated_bar.to_dict(),
            "revision",
            True,
        ),
        "shape_nullable": (
            RequestResultShape.from_dict,
            FLOAT.identity(),
            "nullable",
            1,
        ),
    }
    parser, original, field, replacement = model_cases[case]
    payload = copy.deepcopy(original)
    payload[field] = replacement
    with pytest.raises(PineRuntimeError):
        parser(payload)
