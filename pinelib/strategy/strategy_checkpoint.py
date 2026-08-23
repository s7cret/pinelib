"""Checkpoint serialization and validation for :class:`StrategyContext`."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from pinelib.strategy.models import Order, RiskRule

if TYPE_CHECKING:
    from pinelib.strategy.context import StrategyContext


def export_strategy_state(strategy: StrategyContext) -> dict[str, object]:
    """Export broker-independent strategy and intent state for checkpointing."""

    return copy.deepcopy(
        {
            "state_version": "pinelib.strategy_context.state.v1",
            "declaration": strategy.declaration,
            "pending_orders": strategy.pending_orders,
            "risk_rules": strategy.risk_rules,
            "closedtrades": {
                "current": strategy._closedtrades._current,
                "history": strategy._closedtrades._history,
            },
            "intent_scope": {
                "phase": strategy._intent_phase,
                "recalc_iteration": strategy._intent_recalc_iteration,
            },
            "intent_tape": strategy.intent_tape.export_state(),
        }
    )


def restore_strategy_state(strategy: StrategyContext, state: object) -> None:
    """Atomically restore a compatible strategy checkpoint."""

    if not isinstance(state, dict):
        raise ValueError("StrategyContext restore_state() expects a dict snapshot")
    required = {
        "state_version",
        "declaration",
        "pending_orders",
        "risk_rules",
        "closedtrades",
        "intent_scope",
        "intent_tape",
    }
    if set(state) != required or state.get("state_version") != "pinelib.strategy_context.state.v1":
        raise ValueError("StrategyContext checkpoint schema mismatch")
    if state["declaration"] != strategy.declaration:
        raise ValueError("StrategyContext checkpoint declaration does not match")
    pending = state["pending_orders"]
    risks = state["risk_rules"]
    scalar = state["closedtrades"]
    intent_scope = state["intent_scope"]
    tape_state = state["intent_tape"]
    if not isinstance(pending, list) or not all(isinstance(item, Order) for item in pending):
        raise ValueError("StrategyContext checkpoint pending_orders is malformed")
    if not isinstance(risks, list) or not all(isinstance(item, RiskRule) for item in risks):
        raise ValueError("StrategyContext checkpoint risk_rules is malformed")
    if not isinstance(scalar, dict) or set(scalar) != {"current", "history"}:
        raise ValueError("StrategyContext checkpoint closedtrades is malformed")
    current = scalar["current"]
    history = scalar["history"]
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        raise ValueError("StrategyContext checkpoint closedtrades.current must be numeric")
    if not isinstance(history, list) or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) for item in history
    ):
        raise ValueError("StrategyContext checkpoint closedtrades.history must be numeric")
    if not isinstance(intent_scope, dict) or set(intent_scope) != {"phase", "recalc_iteration"}:
        raise ValueError("StrategyContext checkpoint intent_scope is malformed")
    phase = intent_scope["phase"]
    recalc_iteration = intent_scope["recalc_iteration"]
    if not isinstance(phase, str) or not phase.strip():
        raise ValueError("StrategyContext checkpoint intent_scope.phase must be nonempty")
    if (
        isinstance(recalc_iteration, bool)
        or not isinstance(recalc_iteration, int)
        or recalc_iteration < 0
    ):
        raise ValueError(
            "StrategyContext checkpoint intent_scope.recalc_iteration must be nonnegative"
        )
    tape_callback = tape_state.get("callback") if isinstance(tape_state, dict) else None
    if isinstance(tape_callback, dict) and (
        tape_callback.get("phase") != phase
        or tape_callback.get("recalc_iteration") != recalc_iteration
    ):
        raise ValueError(
            "StrategyContext checkpoint intent_scope must match IntentTape callback state"
        )
    try:
        validated = copy.deepcopy(state)
    except Exception as exc:
        raise ValueError(
            f"StrategyContext checkpoint cannot be detached: {type(exc).__name__}: {exc}"
        ) from exc

    # IntentTape validates and mutates atomically. Every other field has already
    # been validated and detached before this call.
    strategy.intent_tape.restore_state(tape_state)
    strategy.pending_orders = validated["pending_orders"]
    strategy.risk_rules = validated["risk_rules"]
    validated_scalar = validated["closedtrades"]
    strategy._closedtrades._current = validated_scalar["current"]
    strategy._closedtrades._history = validated_scalar["history"]
    validated_scope = validated["intent_scope"]
    strategy._intent_phase = validated_scope["phase"]
    strategy._intent_recalc_iteration = validated_scope["recalc_iteration"]
