from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from openpine_contracts import IntentKind, seal_content_hash

from pinelib import ExecutionContext, PineRuntime, StrategyContext, SymbolInfo, TimeframeInfo
from pinelib.core.runtime import PineRuntimeError
from pinelib.strategy.intent_tape import (
    IntentTape,
    _direction,
    _source_span,
)
from tests.rc4_fixtures import (
    HASH_A,
    HASH_C,
    execution_context,
    known_source_span,
)


def _strict_tape(**overrides: Any) -> IntentTape:
    context = overrides.pop("execution_context", execution_context())
    values: dict[str, Any] = {
        "run_id": context["run_id"],
        "strategy_id": context["strategy_id"],
        "series_id": context["series_id"],
        "instrument_id": context["instrument_id"],
        "timeframe": context["timeframe"],
        "producer_commit": context["producer_commits"]["pinelib"],
        "stack_id": context["stack_id"],
        "strict_production": True,
        "execution_context": context,
    }
    values.update(overrides)
    return IntentTape(**values)


def _checkpoint_tape() -> IntentTape:
    tape = _strict_tape()
    tape.begin_callback(bar_index=2, bar_open_time_utc_ms=120_000, phase="INTRABAR")
    tape.record(IntentKind.CANCEL_ALL, command_id="all", source_span=known_source_span())
    tape.commit_bar(bar_index=2, bar_open_time_utc_ms=120_000)
    return tape


def _strict_strategy() -> StrategyContext:
    return StrategyContext(
        intent_strict_production=True,
        intent_execution_context=execution_context(),
    )


def test_execution_context_wrapper_defensive_surface_and_type_errors() -> None:
    with pytest.raises(TypeError, match="mapping"):
        ExecutionContext(1)  # type: ignore[arg-type]

    context = ExecutionContext(execution_context())
    assert len(context) == len(list(iter(context)))
    assert context["run_id"] == "run-1"
    detached = context.to_dict()
    detached["run_id"] = "tampered"
    assert context["run_id"] == "run-1"
    assert ExecutionContext.coerce(context) is context


def test_execution_context_reports_every_runtime_identity_mismatch() -> None:
    context = ExecutionContext(execution_context())
    wrong = SymbolInfo(
        "OTHER:WRONG",
        timezone="Europe/London",
        session="other",
        mintick=0.5,
        exchange="OTHER",
        type="crypto",
        currency="EUR",
        pointvalue=2,
    )
    with pytest.raises(ValueError, match="mintick.*pointvalue.*symbol.*timeframe"):
        context.assert_runtime_identity(wrong, TimeframeInfo.from_string("1"))


def test_runtime_checkpoint_rejects_non_boolean_between_bars() -> None:
    runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60"))
    state = runtime.export_state()
    state["series"]["close"]["between_bars"] = 1  # type: ignore[index]
    with pytest.raises(PineRuntimeError, match="between_bars"):
        runtime.restore_state(state)


def test_runtime_checkpoint_rejects_runtime_identity_mismatch() -> None:
    runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60"))
    state = runtime.export_state()
    state["runtime_identity"]["bar_index_offset"] = 99  # type: ignore[index]
    with pytest.raises(PineRuntimeError, match="identity"):
        runtime.restore_state(state)


@pytest.mark.parametrize(
    ("policy", "remove_varip", "match"),
    [
        pytest.param("invalid", False, "varip_policy is invalid", id="invalid"),
        pytest.param("included", True, "presence", id="missing-varip"),
        pytest.param("preserve_existing", False, "presence", id="unexpected-varip"),
    ],
)
def test_runtime_checkpoint_rejects_inconsistent_varip_policy(
    policy: str,
    remove_varip: bool,
    match: str,
) -> None:
    runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60"))
    state = runtime.export_state()
    state["varip_policy"] = policy
    if remove_varip:
        state.pop("varip_state")
    with pytest.raises(PineRuntimeError, match=match):
        runtime.restore_state(state)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        pytest.param("commit_order", [], "commit_order", id="commit-order"),
        pytest.param("input_metadata", {"x": object()}, "input_metadata", id="inputs"),
        pytest.param("config_diagnostics", [1], "config_diagnostics", id="diagnostics"),
    ],
)
def test_runtime_checkpoint_rejects_malformed_extended_state(
    field: str,
    value: object,
    match: str,
) -> None:
    runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60"))
    state = runtime.export_state()
    state[field] = value
    with pytest.raises(PineRuntimeError, match=match):
        runtime.restore_state(state)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        pytest.param("dtype", "", "dtype must be nonempty", id="dtype"),
        pytest.param("type_info", object(), "type_info is malformed", id="type-info"),
        pytest.param("initial", 999, "metadata does not match", id="metadata"),
    ],
)
def test_runtime_checkpoint_rejects_malformed_series_metadata(
    field: str,
    value: object,
    match: str,
) -> None:
    runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60"))
    state = runtime.export_state()
    state["series"]["close"][field] = value  # type: ignore[index]
    with pytest.raises(PineRuntimeError, match=match):
        runtime.restore_state(state)


def test_source_provenance_negative_edges() -> None:
    with pytest.raises(ValueError, match="direction"):
        _direction("sideways")
    with pytest.raises(TypeError, match="mapping"):
        _source_span(1)
    with pytest.raises(ValueError, match="known=false"):
        _source_span({"known": False})
    with pytest.raises(TypeError, match="start_line"):
        _source_span({"start_line": True})
    assert _source_span({"start_line": 1})["known"] is False
    with pytest.raises(ValueError, match="explicitly declare"):
        _source_span(
            {"start_line": 1},
            strict_production=True,
            expected_source_hash=HASH_C,
        )
    with pytest.raises(ValueError, match="complete RC4"):
        _source_span({"known": True, "source_hash": HASH_C})
    with pytest.raises(ValueError, match="nonzero sha256"):
        _source_span({**known_source_span(), "source_hash": "sha256:" + ("0" * 64)})
    with pytest.raises(TypeError, match="start_line"):
        _source_span({**known_source_span(), "start_line": True})


def test_strict_generic_identity_and_series_rebinding_fail_closed() -> None:
    generic_context = execution_context(run_id="run")
    with pytest.raises(ValueError, match="generic identity"):
        _strict_tape(execution_context=generic_context)

    tape = _strict_tape()
    with pytest.raises(ValueError, match="series identity"):
        tape.set_series_identity(
            series_id="other",
            instrument_id=tape.instrument_id,
            timeframe=tape.timeframe,
            semantic_profile=tape.semantic_profile,
        )


def test_removed_intent_fields_and_unknown_kind_fail_closed() -> None:
    tape = _strict_tape()
    common = {"command_id": "all", "source_span": known_source_span()}
    with pytest.raises(ValueError, match="price"):
        tape.record(IntentKind.CANCEL_ALL, price=1, **common)
    with pytest.raises(ValueError, match="origin_command_kind"):
        tape.record(IntentKind.CANCEL_ALL, origin_command_kind="legacy", **common)
    with pytest.raises(ValueError, match="unsupported intent kind"):
        tape.record("unknown", **common)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda state: state.update(state_version="bad"), "schema mismatch"),
        (lambda state: state.update(events="bad"), "events must be a list"),
        (lambda state: state.update(event_ordinals=[]), "event_ordinals"),
        (lambda state: state.update(event_ordinals=[True]), "event_ordinals"),
        (lambda state: state.update(events=[1]), "contain mappings"),
        (
            lambda state: state["events"][0].update(content_hash=HASH_A),
            "content_hash is invalid",
        ),
        (
            lambda state: state["events"].__setitem__(
                0,
                seal_content_hash(
                    {**state["events"][0], "sequence": 1},
                    schema_id="openpine.intent.v2",
                ),
            ),
            "sequences must be contiguous",
        ),
        (lambda state: state.update(idempotency_map={}), "idempotency map"),
        (lambda state: state.update(committed_bars="bad"), "committed_bars must be a list"),
        (lambda state: state.update(committed_bars=[[1]]), "bar identity is malformed"),
        (
            lambda state: state.update(committed_bars=[[2, 120_000], [2, 120_000]]),
            "committed bars must be unique",
        ),
        (lambda state: state.update(callback={}), "callback state is malformed"),
        (lambda state: state.update(invocation_counts="bad"), "invocation_counts must be a list"),
        (lambda state: state.update(invocation_counts=[{}]), "invocation count is malformed"),
        (
            lambda state: state.update(
                invocation_counts=[{"kind": "cancel_all", "command_id": "all", "count": True}]
            ),
            "count must be nonnegative",
        ),
        (
            lambda state: state.update(
                invocation_counts=[
                    {"kind": "cancel_all", "command_id": "all", "count": 1},
                    {"kind": "cancel_all", "command_id": "all", "count": 2},
                ]
            ),
            "counts must be unique",
        ),
    ],
)
def test_intent_checkpoint_rejects_malformed_state_atomically(
    mutation: Any,
    match: str,
) -> None:
    tape = _checkpoint_tape()
    before = tape.export_state()
    state = deepcopy(before)
    mutation(state)
    with pytest.raises(ValueError, match=match):
        tape.restore_state(state)
    assert tape.export_state() == before


def test_intent_checkpoint_rejects_duplicate_event_idempotency_key() -> None:
    tape = _checkpoint_tape()
    state = tape.export_state()
    duplicate = seal_content_hash(
        {**state["events"][0], "sequence": 1},
        schema_id="openpine.intent.v2",
    )
    state["events"].append(duplicate)
    state["event_ordinals"].append(0)
    with pytest.raises(ValueError, match="idempotency keys"):
        tape.restore_state(state)


def test_intent_checkpoint_requires_dict() -> None:
    with pytest.raises(ValueError, match="dict snapshot"):
        _strict_tape().restore_state(None)


class _Uncopyable:
    def __deepcopy__(self, _memo: object) -> object:
        raise RuntimeError("cannot-copy")


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda state: state.update(state_version="bad"), "schema mismatch"),
        (
            lambda state: state.update(declaration=StrategyContext(pyramiding=2).declaration),
            "declaration",
        ),
        (lambda state: state.update(pending_orders="bad"), "pending_orders"),
        (lambda state: state.update(risk_rules="bad"), "risk_rules"),
        (lambda state: state.update(closedtrades={}), "closedtrades is malformed"),
        (
            lambda state: state["closedtrades"].update(current=True),
            "current must be numeric",
        ),
        (
            lambda state: state["closedtrades"].update(history=[True]),
            "history must be numeric",
        ),
        (lambda state: state.update(intent_scope={}), "intent_scope is malformed"),
        (
            lambda state: state["intent_scope"].update(phase=""),
            "phase must be nonempty",
        ),
        (
            lambda state: state["intent_scope"].update(recalc_iteration=True),
            "recalc_iteration must be nonnegative",
        ),
        (
            lambda state: state["intent_scope"].update(phase="MISMATCH"),
            "must match IntentTape",
        ),
    ],
)
def test_strategy_checkpoint_rejects_malformed_state(
    mutation: Any,
    match: str,
) -> None:
    strategy = _strict_strategy()
    state = strategy.export_state()
    mutation(state)
    with pytest.raises(ValueError, match=match):
        strategy.restore_state(state)


def test_strategy_checkpoint_requires_dict_and_reports_detach_failure() -> None:
    strategy = _strict_strategy()
    with pytest.raises(ValueError, match="dict snapshot"):
        strategy.restore_state(None)

    strategy.order("L", "long", qty=1, source_map=known_source_span())
    state = strategy.export_state()
    state["pending_orders"][0].comment = _Uncopyable()
    with pytest.raises(ValueError, match="cannot be detached"):
        strategy.restore_state(state)
