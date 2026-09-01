from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pinelib.errors import (
    PL_DELEGATED_HANDLER_FAILURE,
    PL_DELEGATED_INVOCATION,
    PL_DELEGATED_TARGET,
    PineRuntimeError,
)
from pinelib.events import SourceSpan
from pinelib.state.checkpoint import clone_runtime_value, sha

DelegatedHandler = Callable[["DelegatedInvocation"], object]
DelegatedTarget = tuple[str, str, str]


def _freeze_runtime_value(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_runtime_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_runtime_value(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class DelegatedInvocation:
    """Exact, identity-bound request passed to a host capability handler."""

    owner: str
    schema_id: str
    capability_id: str
    symbol_id: str
    overload_id: str
    arguments: object
    call_site_id: str
    source_span: SourceSpan
    sequence: int
    phase: str
    realtime: bool
    final_tick: bool
    projection_hash: str | None
    bar_index: int
    tick_index: int
    ordinal: int
    invocation_id: str = field(init=False)

    def __post_init__(self) -> None:
        string_fields = (
            self.owner,
            self.schema_id,
            self.capability_id,
            self.symbol_id,
            self.overload_id,
            self.call_site_id,
            self.phase,
        )
        if any(type(value) is not str or not value for value in string_fields):
            raise PineRuntimeError(
                "delegated invocation identity is incomplete",
                code=PL_DELEGATED_INVOCATION,
            )
        if not isinstance(self.source_span, SourceSpan):
            raise PineRuntimeError(
                "delegated invocation source span is invalid",
                code=PL_DELEGATED_INVOCATION,
            )
        if (
            type(self.sequence) is not int
            or self.sequence < 0
            or type(self.bar_index) is not int
            or self.bar_index < 0
            or type(self.tick_index) is not int
            or self.tick_index < 0
            or type(self.ordinal) is not int
            or self.ordinal < 0
            or type(self.realtime) is not bool
            or type(self.final_tick) is not bool
        ):
            raise PineRuntimeError(
                "delegated invocation frame identity is invalid",
                code=PL_DELEGATED_INVOCATION,
            )
        try:
            detached_arguments = _freeze_runtime_value(
                clone_runtime_value(self.arguments)
            )
        except PineRuntimeError as error:
            raise PineRuntimeError(
                "delegated invocation arguments are invalid",
                code=PL_DELEGATED_INVOCATION,
            ) from error
        object.__setattr__(self, "arguments", detached_arguments)
        object.__setattr__(self, "invocation_id", sha(self._identity_body()))

    @property
    def source_identity(self) -> dict[str, object]:
        return {
            "call_site_id": self.call_site_id,
            "source_span": self.source_span.identity(),
        }

    def _identity_body(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "schema_id": self.schema_id,
            "capability_id": self.capability_id,
            "symbol_id": self.symbol_id,
            "overload_id": self.overload_id,
            "arguments": self.arguments,
            "source_identity": self.source_identity,
            "frame": {
                "sequence": self.sequence,
                "phase": self.phase,
                "realtime": self.realtime,
                "final_tick": self.final_tick,
                "projection_hash": self.projection_hash,
                "bar_index": self.bar_index,
                "tick_index": self.tick_index,
            },
            "ordinal": self.ordinal,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_body(), "invocation_id": self.invocation_id}


@dataclass(frozen=True, slots=True)
class DelegatedOutput:
    """A handler result paired with the invocation that produced it."""

    invocation: DelegatedInvocation
    value: object


class DelegatedCapabilityDispatcher:
    """Exact owner/schema/capability dispatcher supplied by the runtime host."""

    def __init__(
        self,
        handlers: Mapping[DelegatedTarget, DelegatedHandler],
        *,
        values: Mapping[DelegatedTarget, object] | None = None,
    ) -> None:
        copied: dict[DelegatedTarget, DelegatedHandler] = {}
        for target, handler in handlers.items():
            if (
                not isinstance(target, tuple)
                or len(target) != 3
                or any(type(part) is not str or not part for part in target)
                or not callable(handler)
            ):
                raise PineRuntimeError(
                    "delegated capability registration is invalid",
                    code=PL_DELEGATED_TARGET,
                )
            copied[target] = handler
        self._handlers: Mapping[DelegatedTarget, DelegatedHandler] = MappingProxyType(
            copied
        )
        copied_values: dict[DelegatedTarget, object] = {}
        for target, value in (values or {}).items():
            if (
                not isinstance(target, tuple)
                or len(target) != 3
                or any(type(part) is not str or not part for part in target)
            ):
                raise PineRuntimeError(
                    "delegated value registration is invalid",
                    code=PL_DELEGATED_TARGET,
                )
            try:
                copied_values[target] = _freeze_runtime_value(
                    clone_runtime_value(value)
                )
            except PineRuntimeError as error:
                raise PineRuntimeError(
                    "delegated value registration is invalid",
                    code=PL_DELEGATED_TARGET,
                ) from error
        self._values: Mapping[DelegatedTarget, object] = MappingProxyType(
            copied_values
        )

    def resolve_value(self, owner: str, schema_id: str, capability_id: str) -> object:
        target = (owner, schema_id, capability_id)
        if any(type(part) is not str or not part for part in target):
            raise PineRuntimeError(
                "delegated value target is invalid",
                code=PL_DELEGATED_TARGET,
            )
        if target not in self._values:
            raise PineRuntimeError(
                "delegated value target is unavailable",
                code=PL_DELEGATED_TARGET,
                details={
                    "owner": owner,
                    "schema_id": schema_id,
                    "capability_id": capability_id,
                },
            )
        return self._values[target]

    def _handler_for(self, invocation: DelegatedInvocation) -> DelegatedHandler:
        target = (
            invocation.owner,
            invocation.schema_id,
            invocation.capability_id,
        )
        handler = self._handlers.get(target)
        if handler is None:
            raise PineRuntimeError(
                "delegated capability target is unavailable",
                code=PL_DELEGATED_TARGET,
                details={
                    "owner": invocation.owner,
                    "schema_id": invocation.schema_id,
                    "capability_id": invocation.capability_id,
                },
            )
        return handler

    def validate_capability(self, invocation: DelegatedInvocation) -> None:
        """Fail closed before staging an invocation for deferred dispatch."""

        self._handler_for(invocation)

    def dispatch_capability(self, invocation: DelegatedInvocation) -> object:
        handler = self._handler_for(invocation)
        try:
            value = handler(invocation)
        except PineRuntimeError:
            raise
        except Exception as error:
            raise PineRuntimeError(
                "delegated capability handler failed",
                code=PL_DELEGATED_HANDLER_FAILURE,
                details={
                    "owner": invocation.owner,
                    "schema_id": invocation.schema_id,
                    "capability_id": invocation.capability_id,
                    "exception_type": type(error).__name__,
                },
            ) from error
        try:
            return _freeze_runtime_value(clone_runtime_value(value))
        except Exception as error:
            raise PineRuntimeError(
                "delegated capability handler returned an invalid output",
                code=PL_DELEGATED_HANDLER_FAILURE,
                details={
                    "owner": invocation.owner,
                    "schema_id": invocation.schema_id,
                    "capability_id": invocation.capability_id,
                    "output_type": type(value).__name__,
                },
            ) from error
