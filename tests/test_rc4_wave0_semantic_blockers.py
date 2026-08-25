from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from openpine_contracts import IntentKind, seal_content_hash, validate_payload

from pinelib import (
    Bar,
    PineRuntime,
    PineRuntimeError,
    StrategyContext,
    SymbolInfo,
    TimeframeInfo,
)
from pinelib.strategy.intent_tape import IntentTape

COMMIT = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
HASH_A = "sha256:" + ("a" * 64)
HASH_B = "sha256:" + ("b" * 64)
HASH_C = "sha256:" + ("c" * 64)
HASH_D = "sha256:" + ("d" * 64)
STACK_COMPONENTS = (
    "openpine-contracts",
    "marketdata-provider",
    "pinelib",
    "pine2ast",
    "ast2python",
    "backtest_engine",
    "optimizer",
    "openpine",
)
LINE_ONE_SPAN = {
    "known": True,
    "source_hash": HASH_C,
    "start_offset": 0,
    "end_offset": 12,
    "start_line": 1,
    "start_col": 0,
    "end_line": 1,
    "end_col": 12,
}
UNKNOWN_SPAN = {
    "known": False,
    "source_hash": None,
    "start_offset": None,
    "end_offset": None,
    "start_line": None,
    "start_col": None,
    "end_line": None,
    "end_col": None,
}


def _execution_context(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_id": "openpine.execution_context.v1",
        "schema_version": "1.0.0",
        "producer": "pinelib-tests",
        "producer_version": "5.0.0-rc.5",
        "producer_commit": COMMIT,
        "stack_id": HASH_D,
        "created_at_utc_ms": 0,
        "serializer_id": "openpine.canonical.json.v1",
        "content_hash_alg": "sha256",
        "run_id": "run-rc4-wave0",
        "strategy_id": "strategy-rc4-wave0",
        "session_id": "session-rc4-wave0",
        "stack_manifest_hash": HASH_D,
        "wheel_identities": [
            {"name": name, "version": "5.0.0rc5", "content_hash": HASH_B}
            for name in STACK_COMPONENTS
        ],
        "schema_hashes": {
            "openpine.intent.v2": HASH_B,
            "openpine.execution_context.v1": HASH_C,
            "openpine.worker.protocol.v2": HASH_B,
            "openpine.checkpoint.v1": HASH_C,
            "openpine.checkpoint.proof.v1": HASH_D,
        },
        "generated_artifact_hash": HASH_B,
        "source_hash": HASH_C,
        "emitted_module_hash": HASH_D,
        "data_snapshot_hash": HASH_A,
        "series_id": "series-rc4-wave0",
        "instrument_id": "NASDAQ:AAPL",
        "exchange": "NASDAQ",
        "market": "stock",
        "symbol": "AAPL",
        "timeframe": "1",
        "timezone": "America/New_York",
        "currency": "USD",
        "mintick": "0.01",
        "pointvalue": "1",
        "session_policy": "regular",
        "semantic_profile": "strict_5x",
        "finality_policy": "CLOSED_BAR_ONLY",
        "warmup_policy": "CALC_ONLY",
        "score_policy": "ALL_BARS",
        "end_policy": "LIQUIDATE_ON_LAST_BAR",
        "capabilities": ["closed_bar", "deterministic_clock", "checkpoint_v1"],
        "producer_commits": {name: COMMIT for name in STACK_COMPONENTS},
        "policy_registry_version": "openpine.policies.rc4.v1",
        "schema_registry_version": "openpine.schemas.rc4.v1",
        "capability_registry_version": "openpine.capabilities.rc4.v1",
    }
    payload.update(overrides)
    sealed = seal_content_hash(payload, schema_id="openpine.execution_context.v1")
    validate_payload("openpine.execution_context.v1", sealed)
    return sealed


def _strict_tape(**overrides: Any) -> IntentTape:
    identity: dict[str, Any] = {
        "run_id": "run-rc4-wave0",
        "strategy_id": "strategy-rc4-wave0",
        "series_id": "series-rc4-wave0",
        "instrument_id": "NASDAQ:AAPL",
        "timeframe": "1",
        "producer_commit": COMMIT,
        "stack_id": HASH_D,
        "strict_production": True,
        "execution_context": _execution_context(),
    }
    identity.update(overrides)
    return IntentTape(**identity)


def _strict_strategy(**overrides: Any) -> StrategyContext:
    identity: dict[str, Any] = {
        "intent_run_id": "run-rc4-wave0",
        "intent_strategy_id": "strategy-rc4-wave0",
        "intent_series_id": "series-rc4-wave0",
        "intent_instrument_id": "NASDAQ:AAPL",
        "intent_timeframe": "1",
        "intent_producer_commit": COMMIT,
        "intent_stack_id": HASH_D,
        "intent_strict_production": True,
        "intent_execution_context": _execution_context(),
    }
    identity.update(overrides)
    return StrategyContext(**identity)


def test_strict_intent_tape_and_strategy_context_require_execution_context() -> None:
    with pytest.raises(ValueError, match="execution_context"):
        IntentTape(
            run_id="run-rc4-wave0",
            strategy_id="strategy-rc4-wave0",
            series_id="series-rc4-wave0",
            instrument_id="NASDAQ:AAPL",
            timeframe="1",
            producer_commit=COMMIT,
            stack_id=HASH_D,
            strict_production=True,
        )
    with pytest.raises(ValueError, match="execution_context"):
        StrategyContext(
            intent_run_id="run-rc4-wave0",
            intent_strategy_id="strategy-rc4-wave0",
            intent_series_id="series-rc4-wave0",
            intent_instrument_id="NASDAQ:AAPL",
            intent_timeframe="1",
            intent_producer_commit=COMMIT,
            intent_stack_id=HASH_D,
            intent_strict_production=True,
        )


@pytest.mark.parametrize(
    ("field", "sentinel"),
    [
        pytest.param("run_id", "run", id="run"),
        pytest.param("strategy_id", "strategy", id="strategy"),
        pytest.param("series_id", "series", id="series"),
        pytest.param("instrument_id", "instrument", id="instrument"),
        pytest.param("timeframe", "unspecified", id="unspecified"),
        pytest.param("producer_commit", "development", id="development"),
        pytest.param("producer_commit", "0" * 40, id="zero-commit"),
        pytest.param("stack_id", "sha256:" + ("0" * 64), id="zero-stack"),
    ],
)
def test_strict_production_rejects_identity_mismatch_before_recording(
    field: str, sentinel: str
) -> None:
    with pytest.raises(ValueError):
        _strict_tape(**{field: sentinel})


def test_strict_strategy_context_rejects_execution_context_identity_mismatch() -> None:
    with pytest.raises(ValueError, match="strategy_id"):
        _strict_strategy(intent_strategy_id="other-strategy")


def test_execution_context_content_hash_is_verified() -> None:
    tampered = _execution_context()
    tampered["session_id"] = "tampered"
    with pytest.raises(ValueError, match="content_hash"):
        _strict_tape(execution_context=tampered)


def test_execution_context_requires_running_pinelib_wheel_version() -> None:
    context = _execution_context()
    context["wheel_identities"] = [
        {**identity, "version": "5.0.0rc4"} if identity["name"] == "pinelib" else identity
        for identity in context["wheel_identities"]
    ]
    context = seal_content_hash(context, schema_id="openpine.execution_context.v1")
    with pytest.raises(ValueError, match="wheel version"):
        _strict_tape(execution_context=context)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"producer": "other"}, "producer must be", id="producer"),
        pytest.param(
            {"producer_version": "99.0.0"},
            "producer_version",
            id="producer-version",
        ),
    ],
)
def test_strict_intent_rejects_producer_spoof(overrides: dict[str, str], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _strict_tape(**overrides)


def test_artifact_or_manifest_identity_changes_intent_event_identity() -> None:
    first_context = _execution_context()
    second_context = _execution_context(generated_artifact_hash=HASH_A)
    first = _strict_tape(execution_context=first_context).record(
        IntentKind.CANCEL_ALL,
        command_id="same-command",
        source_span=LINE_ONE_SPAN,
    )
    second = _strict_tape(execution_context=second_context).record(
        IntentKind.CANCEL_ALL,
        command_id="same-command",
        source_span=LINE_ONE_SPAN,
    )
    assert first["event_id"] != second["event_id"]
    assert first["idempotency_key"] != second["idempotency_key"]
    assert first["content_hash"] != second["content_hash"]


def test_execution_context_builds_symbol_info_and_rejects_fake_runtime_identity() -> None:
    strategy = _strict_strategy()
    context = strategy.intent_tape.execution_context
    assert context is not None
    symbol = context.to_symbol_info()
    assert symbol.tickerid == "NASDAQ:AAPL"
    assert symbol.exchange == "NASDAQ"
    assert symbol.currency == "USD"
    assert symbol.mintick == 0.01
    assert symbol.pointvalue == 1.0

    fake_runtime = PineRuntime(SymbolInfo("S"), TimeframeInfo.from_string("1"))
    with pytest.raises(ValueError, match="instrument identity"):
        strategy.attach_runtime(fake_runtime)


def test_intent_v22_uses_exact_kind_payload_and_canonical_direction() -> None:
    event = _strict_tape().record(
        IntentKind.ENTRY,
        command_id="source:entry:line-1",
        order_id="L",
        direction="long",
        qty=1,
        limit=10,
        source_span=LINE_ONE_SPAN,
    )

    validate_payload("openpine.intent.v2", event)
    assert event["schema_version"] == "2.2.0"
    assert event["producer_version"] == "5.0.0-rc.5"
    assert event["direction"] == "LONG"
    assert "price" not in event
    assert "origin_command_kind" not in event


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("profit", 10, id="entry-profit"),
        pytest.param("risk_rule", "max_drawdown", id="entry-risk"),
        pytest.param("from_entry", "L", id="entry-from-entry"),
    ],
)
def test_intent_v22_rejects_unrelated_kind_fields(field: str, value: object) -> None:
    kwargs: dict[str, Any] = {
        "order_id": "L",
        "direction": "long",
        "qty": 1,
        "source_span": LINE_ONE_SPAN,
        field: value,
    }
    with pytest.raises(ValueError, match="unrelated"):
        _strict_tape().record(IntentKind.ENTRY, command_id="L", **kwargs)


def test_non_strict_omitted_source_is_explicitly_unknown() -> None:
    tape = IntentTape(run_id="compat-run", strategy_id="compat-strategy")
    event = tape.record(IntentKind.CANCEL_ALL, command_id="programmatic")
    assert dict(event["source_span"]) == UNKNOWN_SPAN


def test_strict_direct_tape_rejects_omitted_source_span() -> None:
    with pytest.raises(ValueError, match="source_span"):
        _strict_tape().record(IntentKind.CANCEL_ALL, command_id="source:missing-span")


def test_strict_strategy_programmatic_call_uses_explicit_unknown_source() -> None:
    strategy = _strict_strategy()
    strategy.cancel_all()
    assert dict(strategy.intent_tape.events[0]["source_span"]) == UNKNOWN_SPAN


def test_strict_source_hash_must_match_execution_context() -> None:
    with pytest.raises(ValueError, match="source_hash"):
        _strict_tape().record(
            IntentKind.CANCEL_ALL,
            command_id="source:mismatch",
            source_span={**LINE_ONE_SPAN, "source_hash": HASH_B},
        )


def test_strict_intent_preserves_complete_line_one_source_span() -> None:
    event = _strict_tape().record(
        IntentKind.CANCEL_ALL,
        command_id="source:line-one",
        source_span=LINE_ONE_SPAN,
    )
    assert dict(event["source_span"]) == LINE_ONE_SPAN


def test_intent_tape_checkpoint_restores_sequence_and_committed_bars() -> None:
    tape = _strict_tape()
    tape.begin_callback(
        bar_index=0,
        bar_open_time_utc_ms=1_700_000_000_000,
        phase="BAR_COMMIT",
    )
    tape.record(
        IntentKind.CANCEL_ALL,
        command_id="source:cancel-all:line-1",
        source_span=LINE_ONE_SPAN,
    )
    tape.commit_bar(bar_index=0, bar_open_time_utc_ms=1_700_000_000_000)
    checkpoint = tape.export_state()

    tape.begin_callback(
        bar_index=1,
        bar_open_time_utc_ms=1_700_000_060_000,
        phase="BAR_COMMIT",
    )
    tape.record(
        IntentKind.CANCEL_ALL,
        command_id="source:cancel-all:line-2",
        source_span={
            **LINE_ONE_SPAN,
            "start_offset": 13,
            "end_offset": 25,
            "start_line": 2,
            "end_line": 2,
        },
    )
    tape.restore_state(checkpoint)

    assert [event["sequence"] for event in tape.events] == [0]
    tape.begin_callback(
        bar_index=0,
        bar_open_time_utc_ms=1_700_000_000_000,
        phase="BAR_COMMIT",
    )
    with pytest.raises(RuntimeError, match="already committed"):
        tape.record(
            IntentKind.CANCEL_ALL,
            command_id="source:cancel-all:line-1",
            source_span=LINE_ONE_SPAN,
        )

    tape.begin_callback(
        bar_index=1,
        bar_open_time_utc_ms=1_700_000_060_000,
        phase="BAR_COMMIT",
    )
    resumed = tape.record(
        IntentKind.CANCEL_ALL,
        command_id="source:cancel-all:line-2",
        source_span={
            **LINE_ONE_SPAN,
            "start_offset": 13,
            "end_offset": 25,
            "start_line": 2,
            "end_line": 2,
        },
    )
    assert resumed["sequence"] == 1


def test_intent_tape_checkpoint_restores_callback_recalc_and_invocation_state() -> None:
    tape = _strict_tape()
    tape.begin_callback(
        bar_index=3,
        bar_open_time_utc_ms=1_700_000_180_000,
        phase="INTRABAR",
        recalc_iteration=2,
    )
    first = tape.record(
        IntentKind.CANCEL_ALL,
        command_id="same-command",
        source_span=LINE_ONE_SPAN,
    )
    checkpoint = tape.export_state()
    tape.record(IntentKind.CANCEL_ALL, command_id="discarded", source_span=LINE_ONE_SPAN)

    tape.restore_state(checkpoint)
    second = tape.record(
        IntentKind.CANCEL_ALL,
        command_id="same-command",
        source_span=LINE_ONE_SPAN,
    )

    assert first["sequence"] == 0
    assert second["sequence"] == 1
    assert second["bar_index"] == 3
    assert second["phase"] == "INTRABAR"
    assert second["recalc_iteration"] == 2
    assert second["idempotency_key"] != first["idempotency_key"]


def test_intent_tape_checkpoint_rejects_identity_mismatch_atomically() -> None:
    checkpoint = _strict_tape().export_state()
    other_context = _execution_context(run_id="other-run")
    other = _strict_tape(run_id="other-run", execution_context=other_context)
    before = other.export_state()

    with pytest.raises(ValueError, match="identity"):
        other.restore_state(checkpoint)

    assert other.export_state() == before


def test_intent_tape_checkpoint_rejects_foreign_or_forged_events() -> None:
    tape = _strict_tape()
    tape.record(
        IntentKind.CANCEL_ALL,
        command_id="same",
        source_span=LINE_ONE_SPAN,
        invocation_ordinal=7,
    )

    foreign = tape.export_state()
    foreign["events"][0]["run_id"] = "foreign-run"
    foreign["events"][0] = seal_content_hash(
        foreign["events"][0],
        schema_id="openpine.intent.v2",
    )
    with pytest.raises(ValueError, match="run_id"):
        tape.restore_state(foreign)

    forged = tape.export_state()
    old_key = forged["events"][0]["idempotency_key"]
    forged["events"][0]["event_id"] = "caller-chosen-event-id"
    forged["events"][0]["idempotency_key"] = "caller-chosen-key"
    forged["events"][0] = seal_content_hash(
        forged["events"][0],
        schema_id="openpine.intent.v2",
    )
    forged["idempotency_map"] = {"caller-chosen-key": forged["idempotency_map"][old_key]}
    with pytest.raises(ValueError, match="delivery identity"):
        tape.restore_state(forged)


def test_rejected_intent_append_does_not_mutate_invocation_state() -> None:
    tape = _strict_tape()
    before = tape.export_state()
    with pytest.raises(ValueError, match="unrelated"):
        tape.record(
            IntentKind.CANCEL_ALL,
            command_id="same",
            profit=1,
            source_span=LINE_ONE_SPAN,
        )
    assert tape.export_state() == before


def test_strategy_context_checkpoint_restores_strategy_state() -> None:
    strategy = _strict_strategy()
    strategy.begin_intent_callback(phase="INTRABAR", recalc_iteration=3)
    strategy.order("kept", "long", qty=1, source_map=LINE_ONE_SPAN)
    strategy.risk_max_position_size(3)
    strategy.closedtrades = 2
    strategy.commit_scalar_history()
    checkpoint = strategy.export_state()

    strategy.order("discarded", "short", qty=2, source_map=LINE_ONE_SPAN)
    strategy.risk_max_drawdown(10, "percent")
    strategy.closedtrades = 9
    strategy.commit_scalar_history()
    strategy.restore_state(checkpoint)

    assert [order.id for order in strategy.pending_orders] == ["kept"]
    assert strategy.risk_rules == [strategy.risk_rules[0]]
    assert strategy.risk_rules[0].name == "max_position_size"
    assert strategy.closedtrades.current == 2
    assert strategy.closedtrades.committed_length == 1
    assert [event["sequence"] for event in strategy.intent_tape.events] == [0, 1]
    assert strategy._intent_phase == "INTRABAR"
    assert strategy._intent_recalc_iteration == 3


def test_strategy_context_checkpoint_is_detached() -> None:
    strategy = _strict_strategy()
    strategy.order("kept", "long", qty=1, source_map=LINE_ONE_SPAN)
    checkpoint = strategy.export_state()
    mutated = deepcopy(checkpoint)
    mutated["pending_orders"][0].id = "tampered"
    assert strategy.pending_orders[0].id == "kept"


def test_runtime_checkpoint_restores_series_execution_state() -> None:
    runtime = PineRuntime(SymbolInfo("NASDAQ:AAPL"), TimeframeInfo.from_string("1"))
    runtime.begin_bar(Bar(time=0, open=10, high=10, low=10, close=10, volume=1, time_close=59_999))
    runtime.end_bar()
    runtime.begin_bar(
        Bar(
            time=60_000,
            open=20,
            high=20,
            low=20,
            close=20,
            volume=1,
            time_close=119_999,
        )
    )
    prior_close_during_bar = runtime.close[1]
    assert runtime.close._between_bars is False
    checkpoint = runtime.export_state()

    runtime.end_bar()
    assert runtime.close._between_bars is True
    runtime.restore_state(checkpoint)

    assert runtime.close._between_bars is False
    assert runtime.close[1] == prior_close_during_bar
    assert runtime.visual.config is runtime.config


def test_runtime_checkpoint_restores_dynamic_series_into_fresh_runtime() -> None:
    original = PineRuntime(SymbolInfo("NASDAQ:AAPL"), TimeframeInfo.from_string("1"))
    dynamic = original.series("generated_recursive_state", "float", initial=0.0)
    original.begin_bar(Bar(time=0, open=10, high=10, low=10, close=10, volume=1, time_close=59_999))
    dynamic.set_current(42.5)
    original.end_bar()
    checkpoint = original.export_state()

    restored = PineRuntime(SymbolInfo("NASDAQ:AAPL"), TimeframeInfo.from_string("1"))
    assert "generated_recursive_state" not in restored.series_registry
    restored.restore_state(checkpoint)

    recreated = restored.series_registry["generated_recursive_state"]
    assert recreated.current == 42.5
    assert recreated._history == [42.5]
    assert restored.commit_order == original.commit_order


def test_runtime_checkpoint_rejects_cross_instrument_or_timeframe_restore() -> None:
    source = PineRuntime(SymbolInfo("NASDAQ:AAPL"), TimeframeInfo.from_string("1"))
    checkpoint = source.export_state()
    target = PineRuntime(SymbolInfo("OTHER:BBB"), TimeframeInfo.from_string("5"))

    with pytest.raises(PineRuntimeError, match="identity"):
        target.restore_state(checkpoint)

    assert target.syminfo.tickerid == "OTHER:BBB"
    assert target.timeframe.value == "5"
    assert target.bar_index == -1
    assert target.current_bar is None
    assert all(not series._history for series in target.series_registry.values())
    assert target.visual.events == []


@pytest.mark.parametrize("tickerid", ["binance:spot:BTCUSDT", "binance/spot/BTCUSDT"])
def test_symbol_ticker_uses_last_component_of_canonical_instrument_id(
    tickerid: str,
) -> None:
    symbol = SymbolInfo(tickerid=tickerid)
    assert symbol.ticker == "BTCUSDT"
