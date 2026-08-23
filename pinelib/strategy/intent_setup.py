"""Resolve StrategyContext intent identity from an admitted execution context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pinelib.execution_context import ExecutionContext


@dataclass(frozen=True, slots=True)
class IntentSetup:
    run_id: str
    strategy_id: str
    series_id: str
    instrument_id: str
    timeframe: str
    producer_commit: object | None
    strict_production: bool
    stack_id: str | None
    execution_context: ExecutionContext | None


def pop_intent_setup(kwargs: dict[str, Any]) -> IntentSetup:
    raw_context = kwargs.pop("intent_execution_context", None)
    context = None if raw_context is None else ExecutionContext.coerce(raw_context)

    def identity(field: str, compatibility_default: str) -> str:
        return str(
            kwargs.pop(
                f"intent_{field}",
                compatibility_default if context is None else context[field],
            )
        )

    raw_stack_id = kwargs.pop("intent_stack_id", None)
    stack_id = (
        (None if context is None else str(context["stack_id"]))
        if raw_stack_id is None
        else str(raw_stack_id)
    )
    return IntentSetup(
        run_id=identity("run_id", "run"),
        strategy_id=identity("strategy_id", "strategy"),
        series_id=identity("series_id", "series"),
        instrument_id=identity("instrument_id", "instrument"),
        timeframe=identity("timeframe", "unspecified"),
        producer_commit=kwargs.pop(
            "intent_producer_commit",
            None if context is None else context.pinelib_commit,
        ),
        strict_production=bool(kwargs.pop("intent_strict_production", False)),
        stack_id=stack_id,
        execution_context=context,
    )
