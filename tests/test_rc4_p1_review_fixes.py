from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest
from openpine_contracts import IntentKind, seal_content_hash, validate_payload

from pinelib import StrategyContext
from pinelib.strategy.intent_tape import IntentTape
from tests.rc4_fixtures import HASH_A, execution_context, known_source_span

EventMutation = Callable[[dict[str, Any]], None]
StrategyCall = Callable[[StrategyContext], None]


def _strict_tape() -> IntentTape:
    context = execution_context()
    return IntentTape(
        run_id=context["run_id"],
        strategy_id=context["strategy_id"],
        series_id=context["series_id"],
        instrument_id=context["instrument_id"],
        timeframe=context["timeframe"],
        producer_commit=context["producer_commits"]["pinelib"],
        stack_id=context["stack_id"],
        strict_production=True,
        execution_context=context,
    )


def _strict_strategy() -> StrategyContext:
    return StrategyContext(
        intent_strict_production=True,
        intent_execution_context=execution_context(),
    )


def _record_event(
    tape: IntentTape,
    kind: IntentKind,
    command_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    return dict(
        tape.record(
            kind,
            command_id=command_id,
            source_span=known_source_span(),
            **fields,
        )
    )


SEMANTIC_EVENT_CASES = [
    pytest.param(
        IntentKind.ENTRY,
        "entry",
        {"order_id": "E", "direction": "long", "qty": 1},
        {"qty": 2},
        lambda event: event.update(qty="2"),
        id="qty",
    ),
    pytest.param(
        IntentKind.ORDER,
        "order",
        {"order_id": "O", "direction": "long", "qty": 1},
        {"direction": "short"},
        lambda event: event.update(direction="SHORT"),
        id="direction",
    ),
    pytest.param(
        IntentKind.CANCEL_ALL,
        "cancel-all-source",
        {},
        {
            "source_span": known_source_span(
                start_offset=21,
                end_offset=30,
                start_line=3,
                start_col=1,
                end_line=3,
                end_col=10,
            )
        },
        lambda event: event.update(
            source_span=known_source_span(
                start_offset=21,
                end_offset=30,
                start_line=3,
                start_col=1,
                end_line=3,
                end_col=10,
            )
        ),
        id="source-span",
    ),
    pytest.param(
        IntentKind.EXIT,
        "exit",
        {"order_id": "X", "from_entry": "E", "qty": 1, "profit": 5},
        {"from_entry": "OTHER"},
        lambda event: event.update(from_entry="OTHER"),
        id="exit-from-entry",
    ),
    pytest.param(
        IntentKind.CLOSE,
        "close:E",
        {"from_entry": "E", "qty": 1, "immediately": False},
        {"immediately": True},
        lambda event: event.update(immediately=True),
        id="close-immediately",
    ),
    pytest.param(
        IntentKind.CLOSE_ALL,
        "close-all",
        {"immediately": False, "comment": "base"},
        {"comment": "changed"},
        lambda event: event.update(comment="changed"),
        id="close-all-comment",
    ),
    pytest.param(
        IntentKind.CANCEL,
        "cancel",
        {"order_id": "E"},
        {"order_id": "OTHER"},
        lambda event: event.update(order_id="OTHER"),
        id="cancel-order-id",
    ),
    pytest.param(
        IntentKind.RISK,
        "max_position_size",
        {
            "risk_rule": "max_position_size",
            "risk_value": 1,
            "risk_unit": "fixed",
            "risk_scope": "strategy",
        },
        {"risk_value": 2},
        lambda event: event.update(risk_value="2"),
        id="risk-value",
    ),
]


@pytest.mark.parametrize(
    ("kind", "command_id", "base_fields", "changed_fields", "_mutation"),
    SEMANTIC_EVENT_CASES,
)
def test_event_id_binds_complete_semantic_event_content(
    kind: IntentKind,
    command_id: str,
    base_fields: dict[str, Any],
    changed_fields: dict[str, Any],
    _mutation: EventMutation,
) -> None:
    first = _record_event(_strict_tape(), kind, command_id, base_fields)
    second_fields = {**base_fields, **changed_fields}
    if "source_span" in second_fields:
        second_source = second_fields.pop("source_span")
        second = dict(
            _strict_tape().record(
                kind,
                command_id=command_id,
                source_span=second_source,
                **second_fields,
            )
        )
    else:
        second = _record_event(_strict_tape(), kind, command_id, second_fields)

    assert first["idempotency_key"] == second["idempotency_key"]
    assert first["event_id"] != second["event_id"]
    assert first["content_hash"] != second["content_hash"]


@pytest.mark.parametrize(
    ("kind", "command_id", "base_fields", "_changed_fields", "mutation"),
    SEMANTIC_EVENT_CASES,
)
def test_checkpoint_rejects_resealed_semantic_event_mutation_atomically(
    kind: IntentKind,
    command_id: str,
    base_fields: dict[str, Any],
    _changed_fields: dict[str, Any],
    mutation: EventMutation,
) -> None:
    tape = _strict_tape()
    _record_event(tape, kind, command_id, base_fields)
    before = tape.export_state()
    forged = deepcopy(before)
    event = forged["events"][0]
    stale_event_id = event["event_id"]
    mutation(event)
    forged["events"][0] = seal_content_hash(event, schema_id="openpine.intent.v2")
    validate_payload("openpine.intent.v2", forged["events"][0])
    assert forged["events"][0]["event_id"] == stale_event_id

    with pytest.raises(ValueError, match="semantic identity"):
        tape.restore_state(forged)

    assert tape.export_state() == before


def _seed_cancellable_order(strategy: StrategyContext) -> None:
    strategy.entry("seed", "long", qty=1, source_map=known_source_span())


BAD_SOURCE = {**known_source_span(), "source_hash": HASH_A}


REJECTED_STRATEGY_CALLS = [
    pytest.param(
        False,
        lambda strategy: strategy.entry("E", "long", qty=1, source_map=BAD_SOURCE),
        ValueError,
        "source_hash",
        id="entry-source",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.order("O", "sideways", qty=1, source_map=known_source_span()),
        ValueError,
        "direction",
        id="order-direction",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.exit(
            "X", from_entry=None, profit=5, source_map=known_source_span()
        ),
        ValueError,
        "from_entry",
        id="exit-required-field",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.close("E", qty=True, source_map=known_source_span()),
        TypeError,
        "decimal",
        id="close-decimal",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.close_all(source_map=BAD_SOURCE),
        ValueError,
        "source_hash",
        id="close-all-source",
    ),
    pytest.param(
        True,
        lambda strategy: strategy.cancel("seed", source_map=BAD_SOURCE),
        ValueError,
        "source_hash",
        id="cancel-source",
    ),
    pytest.param(
        True,
        lambda strategy: strategy.cancel_all(source_map=BAD_SOURCE),
        ValueError,
        "source_hash",
        id="cancel-all-source",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.risk_max_position_size(float("inf")),
        ValueError,
        "finite",
        id="risk-decimal",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.risk_max_drawdown(1, ""),
        ValueError,
        "nonempty",
        id="risk-required-field",
    ),
]


@pytest.mark.parametrize(
    ("seed_order", "invoke", "error", "match"),
    REJECTED_STRATEGY_CALLS,
)
def test_rejected_strict_strategy_command_leaves_export_state_unchanged(
    seed_order: bool,
    invoke: StrategyCall,
    error: type[Exception],
    match: str,
) -> None:
    strategy = _strict_strategy()
    if seed_order:
        _seed_cancellable_order(strategy)
    before = strategy.export_state()

    with pytest.raises(error, match=match):
        invoke(strategy)

    assert strategy.export_state() == before


COMMITTED_BAR_CALLS = [
    pytest.param(
        False,
        lambda strategy: strategy.entry("E", "long", qty=1, source_map=known_source_span()),
        id="entry",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.order("O", "short", qty=1, source_map=known_source_span()),
        id="order",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.exit(
            "X", from_entry="seed", profit=5, source_map=known_source_span()
        ),
        id="exit",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.close("seed", qty=1, source_map=known_source_span()),
        id="close",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.close_all(source_map=known_source_span()),
        id="close-all",
    ),
    pytest.param(
        True,
        lambda strategy: strategy.cancel("seed", source_map=known_source_span()),
        id="cancel",
    ),
    pytest.param(
        True,
        lambda strategy: strategy.cancel_all(source_map=known_source_span()),
        id="cancel-all",
    ),
    pytest.param(
        False,
        lambda strategy: strategy.risk_max_position_size(1),
        id="risk",
    ),
]


@pytest.mark.parametrize(("seed_order", "invoke"), COMMITTED_BAR_CALLS)
def test_committed_bar_rejection_is_atomic_for_every_strategy_command(
    seed_order: bool,
    invoke: StrategyCall,
) -> None:
    strategy = _strict_strategy()
    if seed_order:
        _seed_cancellable_order(strategy)
    strategy.commit_intents_for_current_bar()
    before = strategy.export_state()

    with pytest.raises(RuntimeError, match="already committed"):
        invoke(strategy)

    assert strategy.export_state() == before
