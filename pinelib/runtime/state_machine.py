from __future__ import annotations

from enum import StrEnum

from pinelib.errors import PL_RUNTIME_STATE_TRANSITION, PineRuntimeError


class RuntimeState(StrEnum):
    CREATED = "CREATED"
    ADMITTED = "ADMITTED"
    INITIALIZED = "INITIALIZED"
    HISTORICAL_CALLBACK = "HISTORICAL_CALLBACK"
    REALTIME_CALLBACK = "REALTIME_CALLBACK"
    FILL_RECALC = "FILL_RECALC"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    FINALIZED = "FINALIZED"
    ABORTED = "ABORTED"


_ALLOWED = {
    RuntimeState.CREATED: {RuntimeState.ADMITTED},
    RuntimeState.ADMITTED: {RuntimeState.INITIALIZED},
    RuntimeState.INITIALIZED: {
        RuntimeState.HISTORICAL_CALLBACK,
        RuntimeState.REALTIME_CALLBACK,
        RuntimeState.FILL_RECALC,
        RuntimeState.FINALIZED,
    },
    RuntimeState.HISTORICAL_CALLBACK: {RuntimeState.COMMITTING, RuntimeState.ABORTED},
    RuntimeState.REALTIME_CALLBACK: {
        RuntimeState.COMMITTING,
        RuntimeState.ABORTED,
        RuntimeState.REALTIME_CALLBACK,
    },
    RuntimeState.FILL_RECALC: {
        RuntimeState.COMMITTING,
        RuntimeState.ABORTED,
        RuntimeState.FILL_RECALC,
    },
    RuntimeState.COMMITTING: {RuntimeState.COMMITTED, RuntimeState.ABORTED},
    RuntimeState.COMMITTED: {
        RuntimeState.HISTORICAL_CALLBACK,
        RuntimeState.REALTIME_CALLBACK,
        RuntimeState.FILL_RECALC,
        RuntimeState.FINALIZED,
    },
    RuntimeState.ABORTED: {
        RuntimeState.HISTORICAL_CALLBACK,
        RuntimeState.REALTIME_CALLBACK,
        RuntimeState.FILL_RECALC,
        RuntimeState.FINALIZED,
    },
    RuntimeState.FINALIZED: set(),
}


class RuntimeStateMachine:
    def __init__(self) -> None:
        self.state = RuntimeState.CREATED

    def transition(self, target: RuntimeState) -> None:
        if target not in _ALLOWED[self.state]:
            raise PineRuntimeError(
                f"invalid runtime transition {self.state}->{target}",
                code=PL_RUNTIME_STATE_TRANSITION,
            )
        self.state = target
