from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, replace

from pinelib.core.values import na, pine_binary, pine_unary
from pinelib.errors import (
    PL_CHECKPOINT_INVALID,
    PL_DELEGATED_HANDLER_UNAVAILABLE,
    PL_RESOURCE_LIMIT,
    PL_RUNTIME_CONTEXT_REQUIRED,
    PL_RUNTIME_SEQUENCE,
    PL_RUNTIME_TRANSACTION_ACTIVE,
    PL_RUNTIME_TRANSACTION_CLOSED,
    PL_SERIES_HISTORY,
    PineRuntimeError,
)
from pinelib.events import AlertEvent, AlertTape, SourceSpan, VisualEvent, VisualTape
from pinelib.input import InputRegistry
from pinelib.reference import RuntimeReferenceHeap
from pinelib.request import RequestDataProvider, RequestEngine
from pinelib.runtime.compact_transcript import CompactRuntimeTranscript
from pinelib.runtime.context import RuntimeLanguageContext
from pinelib.runtime.delegated import (
    DelegatedCapabilityDispatcher,
    DelegatedInvocation,
    DelegatedOutput,
)
from pinelib.runtime.language import LanguageExecutionMixin
from pinelib.runtime.metadata import (
    BarStateView,
    BarValues,
    InstrumentContext,
    TimeframeContext,
)
from pinelib.runtime.policies import RuntimePolicies
from pinelib.runtime.pending_abort import AbortBaseline, validate_abort_attempt
from pinelib.runtime.semantic import ALGORITHM, semantic_state_digest
from pinelib.runtime.state_machine import RuntimeState, RuntimeStateMachine
from pinelib.runtime.transcript import RuntimeTranscript
from pinelib.state.checkpoint import (
    RuntimeCheckpoint,
    canonical_json,
    from_portable,
    is_canonical_sha256,
    sha,
    to_portable,
)
from pinelib.state.series import SeriesStorage
from pinelib.state.slots import StateSlotRegistry


@dataclass(frozen=True, slots=True)
class CallbackFrame:
    phase: str
    sequence: int
    realtime: bool = False
    final_tick: bool = True
    projection_hash: str | None = None
    bar_index: int = 0
    tick_index: int = 0
    is_last_bar: bool = False
    is_last_confirmed_history: bool = False
    last_bar_index: int | None = None
    defer_bar_commit: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.phase) is not str
            or not self.phase
            or type(self.sequence) is not int
            or self.sequence < 0
            or type(self.realtime) is not bool
            or type(self.final_tick) is not bool
            or type(self.bar_index) is not int
            or self.bar_index < 0
            or type(self.tick_index) is not int
            or self.tick_index < 0
            or type(self.defer_bar_commit) is not bool
            or type(self.is_last_bar) is not bool
            or type(self.is_last_confirmed_history) is not bool
            or (
                self.last_bar_index is not None
                and (type(self.last_bar_index) is not int or self.last_bar_index < 0)
            )
            or (
                self.projection_hash is not None
                and not is_canonical_sha256(self.projection_hash)
            )
        ):
            raise PineRuntimeError("callback frame identity is invalid")


@dataclass(frozen=True, slots=True)
class CallbackResult:
    committed: bool
    aborted: bool
    state_hash: str
    transcript_hash: str
    visual_batch_hash: str
    alert_batch_hash: str
    delegated_outputs: tuple[DelegatedOutput, ...] = ()
    state_hash_algorithm: str = "pinelib.snapshot-json.v1"
    revision_fingerprint: str | None = None


class RuntimeTransaction(LanguageExecutionMixin):
    def __init__(self, session: RuntimeSession, frame: CallbackFrame) -> None:
        self.session = session
        self.frame = frame
        self.closed = False
        self._new_series: set[str] = set()
        self._function_path: tuple[str, ...] = ()
        self._request_allocations = 0
        self._delegated_invocations: list[DelegatedInvocation] = []
        self._delegated_outputs: list[DelegatedOutput] = []

    def _check(self) -> None:
        if self.closed:
            raise PineRuntimeError(
                "transaction is closed", code=PL_RUNTIME_TRANSACTION_CLOSED
            )
        if self.session._active is not self:
            raise PineRuntimeError(
                "transaction is not active", code=PL_RUNTIME_TRANSACTION_CLOSED
            )

    def set_series(
        self,
        name: str,
        value: object,
        dtype: str = "float",
        *,
        history_policy: str = "each_bar",
    ) -> None:
        self._check()
        from pinelib.reference.nominal import validate_field_value
        decoded = self.references._decode_value(value)
        if self.references._has_nominal_value(decoded) or (type(dtype) is str and ("udt:" in dtype or "enum:" in dtype)):
            validate_field_value(self.references, value, dtype)
        if name not in self.session.series:
            if len(self.session.series) >= self.session.policies.resource.max_series:
                raise PineRuntimeError("series limit exceeded", code=PL_RESOURCE_LIMIT)
            self.session.series[name] = SeriesStorage(
                name, dtype, history_policy=history_policy
            )
            self._new_series.add(name)
        storage = self.session.series[name]
        if storage.dtype != dtype or storage.history_policy != history_policy:
            raise PineRuntimeError("series type descriptor changed for the same name")
        if not storage.initialized:
            storage.begin(value)
        else:
            storage.set(value)
        storage.evaluated = True

    def read_series(self, name: str, offset: int = 0) -> object:
        self._check()
        try:
            return self._read_typed_series(self.session.series[name], offset)
        except KeyError as error:
            raise PineRuntimeError(f"unknown series: {name}") from error

    def op_operator_binary(self, operator: str, left: object, right: object) -> object:
        """Ast2Python ``operator.binary`` ABI."""

        self._check()
        self.references._decode_value(left)
        self.references._decode_value(right)
        return pine_binary(operator, left, right, self.session.language)

    def op_operator_unary(self, operator: str, operand: object) -> object:
        """Ast2Python ``operator.unary`` ABI."""

        self._check()
        return pine_unary(operator, operand, self.session.language)

    def op_series_history(self, base: object, offset: object) -> object:
        """Ast2Python ``series.history`` ABI over declared series storage."""

        self._check()
        if type(offset) is not int:
            raise PineRuntimeError(
                "history offset must be an int", code=PL_SERIES_HISTORY
            )
        if isinstance(base, SeriesStorage):
            storage = base
        elif isinstance(base, str) and base in self.session.series:
            storage = self.session.series[base]
        else:
            raise PineRuntimeError(
                "history base must be declared series storage",
                code=PL_SERIES_HISTORY,
            )
        value = self._read_typed_series(storage, offset)
        return na if value is None else value

    def _read_typed_series(self, storage: SeriesStorage, offset: int) -> object:
        if type(offset) is not int:
            raise PineRuntimeError(
                "history offset must be an int", code=PL_SERIES_HISTORY
            )
        if "udt:" in storage.dtype or "enum:" in storage.dtype:
            from pinelib.reference.nominal import validate_field_type
            validate_field_type(storage.dtype, self.session.language.pine_version, self.session.nominal_registry)
        if (
            offset > 0
            and storage.dtype.startswith("array<")
            and self.session.language.pine_version < 5
        ):
            raise PineRuntimeError(
                "array instance history requires Pine v5 or later",
                code=PL_SERIES_HISTORY,
            )
        value = storage.read(offset)
        if value is not None and storage.dtype.startswith(
            ("array<", "map<", "matrix<", "udt:")
        ):
            return self._check_reference_binding(value, storage.dtype)
        if value is not None and storage.dtype.startswith("enum:"):
            return self.enum_coerce_v1(value, storage.dtype)
        if (
            offset > 0
            and value is None
            and storage.dtype == "bool"
            and self.session.language.pine_version >= 6
        ):
            return False
        return value

    def _required_series_value(self, name: str) -> object:
        try:
            return self.read_series(name)
        except PineRuntimeError as error:
            raise PineRuntimeError(
                f"bar value {name} was not injected",
                code=PL_RUNTIME_CONTEXT_REQUIRED,
            ) from error

    def _instrument(self) -> InstrumentContext:
        if self.session.instrument is None:
            raise PineRuntimeError(
                "InstrumentContext is required", code=PL_RUNTIME_CONTEXT_REQUIRED
            )
        return self.session.instrument

    def _timeframe(self) -> TimeframeContext:
        if self.session.timeframe is None:
            raise PineRuntimeError(
                "TimeframeContext is required", code=PL_RUNTIME_CONTEXT_REQUIRED
            )
        return self.session.timeframe

    @property
    def value_na(self) -> object:
        self._check()
        return na

    @property
    def value_open(self) -> object:
        return self._required_series_value("open")

    @property
    def value_high(self) -> object:
        return self._required_series_value("high")

    @property
    def value_low(self) -> object:
        return self._required_series_value("low")

    @property
    def value_close(self) -> object:
        return self._required_series_value("close")

    @property
    def value_volume(self) -> object:
        return self._required_series_value("volume")

    @property
    def value_time(self) -> object:
        return self._required_series_value("time")

    @property
    def value_time_close(self) -> object:
        return self._required_series_value("time_close")

    @property
    def value_bar_index(self) -> int:
        self._check()
        return self.frame.bar_index

    @property
    def value_last_bar_index(self) -> int:
        self._check()
        if self.frame.last_bar_index is None:
            raise PineRuntimeError(
                "last_bar_index was not injected", code=PL_RUNTIME_CONTEXT_REQUIRED
            )
        return self.frame.last_bar_index

    @property
    def value_syminfo_ticker(self) -> str:
        return self._instrument().ticker

    @property
    def value_syminfo_tickerid(self) -> str:
        return self._instrument().tickerid

    @property
    def value_syminfo_prefix(self) -> str:
        return self._instrument().prefix

    @property
    def value_syminfo_currency(self) -> str:
        return self._instrument().currency

    @property
    def value_syminfo_basecurrency(self) -> str:
        return self._instrument().basecurrency

    @property
    def value_syminfo_timezone(self) -> str:
        return self._instrument().timezone

    @property
    def value_syminfo_type(self) -> str:
        return self._instrument().instrument_type

    @property
    def value_syminfo_mintick(self) -> float:
        return self._instrument().mintick

    @property
    def value_syminfo_pointvalue(self) -> float:
        return self._instrument().pointvalue

    @property
    def value_syminfo_mincontract(self) -> float:
        return self._instrument().mincontract

    @property
    def value_timeframe_period(self) -> str:
        return self._timeframe().period_for(self.session.language)

    @property
    def value_timeframe_multiplier(self) -> int:
        return self._timeframe().multiplier

    @property
    def value_timeframe_in_seconds(self) -> object:
        return self._timeframe().seconds

    @property
    def value_timeframe_isintraday(self) -> bool:
        return self._timeframe().unit in {"tick", "second", "minute"}

    @property
    def value_timeframe_isdaily(self) -> bool:
        return self._timeframe().unit == "day"

    @property
    def value_timeframe_isweekly(self) -> bool:
        return self._timeframe().unit == "week"

    @property
    def value_timeframe_ismonthly(self) -> bool:
        return self._timeframe().unit == "month"

    @property
    def value_barstate_isfirst(self) -> bool:
        return self.session.barstate(self.frame).isfirst

    @property
    def value_barstate_islast(self) -> bool:
        return self.session.barstate(self.frame).islast

    @property
    def value_barstate_ishistory(self) -> bool:
        return self.session.barstate(self.frame).ishistory

    @property
    def value_barstate_isrealtime(self) -> bool:
        return self.session.barstate(self.frame).isrealtime

    @property
    def value_barstate_isnew(self) -> bool:
        return self.session.barstate(self.frame).isnew

    @property
    def value_barstate_isconfirmed(self) -> bool:
        return self.session.barstate(self.frame).isconfirmed

    @property
    def value_barstate_islastconfirmedhistory(self) -> bool:
        return self.session.barstate(self.frame).islastconfirmedhistory

    def declare_scalar_v1(
        self,
        series_id: str,
        mode: str,
        initializer: Callable[[], object],
        dtype: str,
        *,
        history_policy: str = "each_bar",
    ) -> object:
        """Initialize a scalar lazily and bind its final callback value to history."""
        self._check()
        if mode not in {"default", "var", "varip"} or dtype not in {
            "bool",
            "color",
            "float",
            "int",
            "string",
        }:
            raise PineRuntimeError("unsupported scalar declaration")
        if mode == "default":
            value = initializer()
        else:
            state_id = "scalar:" + series_id
            if not self.session.slots.contains(state_id):
                self.set_slot(
                    state_id,
                    initializer(),
                    owner="ast2python.scalar.v1",
                    varip=mode == "varip",
                )
            value = self.state(
                state_id,
                owner="ast2python.scalar.v1",
                schema_version="1",
                initial=None,
                varip=mode == "varip",
            )
        self.set_series(series_id, value, dtype, history_policy=history_policy)
        return value

    def write_scalar_v1(
        self,
        series_id: str,
        mode: str,
        value: object,
        dtype: str,
        *,
        history_policy: str = "each_bar",
    ) -> None:
        """A reassignment updates the declared series, not just a Python local."""
        self._check()
        if mode not in {"default", "var", "varip"} or dtype not in {
            "bool",
            "color",
            "float",
            "int",
            "string",
        }:
            raise PineRuntimeError("unsupported scalar reassignment")
        if mode != "default":
            self.set_slot(
                "scalar:" + series_id,
                value,
                owner="ast2python.scalar.v1",
                varip=mode == "varip",
            )
        self.set_series(series_id, value, dtype, history_policy=history_policy)

    def set_slot(
        self,
        state_id: str,
        value: object,
        *,
        owner: str = "generated",
        schema_version: str = "1",
        varip: bool = False,
    ) -> None:
        self._check()
        self.references._decode_value(value)
        slot = self.session.slots.register(state_id, owner, schema_version, varip=varip)
        slot.working = value

    def state(
        self,
        state_id: str,
        *,
        owner: str,
        schema_version: str,
        initial: object,
        varip: bool = False,
    ) -> object:
        self._check()
        self.references._decode_value(initial)
        value = self.session.slots.get_working(
            state_id,
            owner,
            schema_version,
            varip=varip,
            initial=initial,
        )
        self.references._decode_value(value)
        return value

    @property
    def references(self) -> RuntimeReferenceHeap:
        self._check()
        return self.session.references

    @property
    def requests(self) -> RequestEngine:
        self._check()
        return self.session.requests

    def visual(
        self,
        *,
        kind: str,
        call_site_id: str,
        payload: dict[str, object],
        source_span: SourceSpan,
    ) -> VisualEvent:
        self._check()
        return self.session.visuals.record(
            kind=kind,
            call_site_id=call_site_id,
            sequence=self.frame.sequence,
            phase=self.frame.phase,
            payload=payload,
            source_span=source_span,
        )

    def alert(
        self,
        *,
        kind: str,
        call_site_id: str,
        payload: dict[str, object],
        source_span: SourceSpan,
    ) -> AlertEvent:
        self._check()
        return self.session.alerts.record(
            kind=kind,
            call_site_id=call_site_id,
            sequence=self.frame.sequence,
            phase=self.frame.phase,
            payload=payload,
            source_span=source_span,
        )

    def dispatch_delegated(
        self,
        *,
        owner: str,
        schema_id: str,
        capability_id: str,
        symbol_id: str,
        overload_id: str,
        arguments: object,
        call_site_id: str,
        source_span: SourceSpan,
    ) -> str:
        """Stage one exact host capability and return its immutable receipt id.

        The handler runs only during ``commit()``; ``abort()`` discards the staged
        invocation without exposing it to host code.
        """

        self._check()
        dispatcher = self.session.delegated_dispatcher
        if dispatcher is None:
            raise PineRuntimeError(
                "delegated capability dispatcher is not configured",
                code=PL_DELEGATED_HANDLER_UNAVAILABLE,
                details={
                    "owner": owner,
                    "schema_id": schema_id,
                    "capability_id": capability_id,
                },
            )
        frame = self.frame
        invocation = DelegatedInvocation(
            owner=owner,
            schema_id=schema_id,
            capability_id=capability_id,
            symbol_id=symbol_id,
            overload_id=overload_id,
            arguments=arguments,
            call_site_id=call_site_id,
            source_span=source_span,
            sequence=frame.sequence,
            phase=frame.phase,
            realtime=frame.realtime,
            final_tick=frame.final_tick,
            projection_hash=frame.projection_hash,
            bar_index=frame.bar_index,
            tick_index=frame.tick_index,
            ordinal=len(self._delegated_invocations),
        )
        dispatcher.validate_capability(invocation)
        self._delegated_invocations.append(invocation)
        return invocation.invocation_id

    def resolve_delegated_value(
        self, *, owner: str, schema_id: str, capability_id: str
    ) -> object:
        """Resolve an immutable host-provided value without invoking host code."""

        self._check()
        dispatcher = self.session.delegated_dispatcher
        if dispatcher is None:
            raise PineRuntimeError(
                "delegated capability dispatcher is not configured",
                code=PL_DELEGATED_HANDLER_UNAVAILABLE,
                details={
                    "owner": owner,
                    "schema_id": schema_id,
                    "capability_id": capability_id,
                },
            )
        return dispatcher.resolve_value(owner, schema_id, capability_id)

    def commit(self) -> CallbackResult:
        self._check()
        # Prevent delegated preparation code from re-entering or mutating the
        # transaction while commit is being resolved.
        self.closed = True
        dispatcher = self.session.delegated_dispatcher
        try:
            if self._delegated_invocations and dispatcher is None:
                raise PineRuntimeError(
                    "delegated capability dispatcher is not configured",
                    code=PL_DELEGATED_HANDLER_UNAVAILABLE,
                )
            if dispatcher is not None:
                self._delegated_outputs.extend(
                    DelegatedOutput(
                        invocation,
                        dispatcher.dispatch_capability(invocation),
                    )
                    for invocation in self._delegated_invocations
                )
        except Exception:
            self.session._finish(self, False)
            raise
        return self.session._finish(self, True)

    def abort(self) -> CallbackResult:
        self._check()
        self.closed = True
        return self.session._finish(self, False)


class RuntimeSession:
    def __init__(
        self,
        language: RuntimeLanguageContext,
        policies: RuntimePolicies | None = None,
        *,
        inputs: InputRegistry | None = None,
        instrument: InstrumentContext | None = None,
        timeframe: TimeframeContext | None = None,
        request_provider: RequestDataProvider | None = None,
        delegated_dispatcher: DelegatedCapabilityDispatcher | None = None,
        nominal_registry=None,
    ) -> None:
        from pinelib.reference.registry import NominalTypeRegistry
        if nominal_registry is not None and (
            type(nominal_registry) is not NominalTypeRegistry
            or nominal_registry.pine_version != language.pine_version
        ):
            raise PineRuntimeError("nominal registry differs from runtime language")
        self._nominal_registry = nominal_registry
        self.language = language
        self.policies = policies if policies is not None else RuntimePolicies()
        policies = self.policies
        self.inputs = inputs if inputs is not None else InputRegistry()
        self.instrument = instrument
        self.timeframe = timeframe
        self.machine = RuntimeStateMachine()
        self.series: dict[str, SeriesStorage[object]] = {}
        self.slots = StateSlotRegistry(policies.resource.max_state_slots)
        self.references = RuntimeReferenceHeap(
            language,
            max_objects=policies.resource.max_reference_objects,
            max_elements=policies.resource.max_collection_elements,
            nominal_registry=nominal_registry,
        )
        self.visuals = VisualTape(policies.resource.max_visual_events)
        self.alerts = AlertTape(policies.resource.max_alert_events)
        self.requests = RequestEngine(language, policies, request_provider)
        self.delegated_dispatcher = delegated_dispatcher
        self.transcript = RuntimeTranscript()
        self.sequence = -1
        self.commit_full_identity = True
        self._identity_mode: bool | None = None
        self._active: RuntimeTransaction | None = None
        self._pending_bar_frame: CallbackFrame | None = None
        self._last_published_bar: int | None = None
        self._deferred_mode: bool | None = None
        self._pending_abort: dict[str, object] | None = None
        self._pending_abort_attempt_bytes = 0
        self._abort_baseline: AbortBaseline | None = None
        self.machine.transition(RuntimeState.ADMITTED)
        self.machine.transition(RuntimeState.INITIALIZED)
        self.requests.bind_parent_identity(self.identity_hash)

    @property
    def nominal_registry(self):
        return self._nominal_registry

    @property
    def identity_hash(self) -> str:
        return sha(
            {
                "language": self.language.identity(),
                "policies": self.policies.identity(),
                "inputs": self.inputs.identity(),
                "instrument": (
                    None if self.instrument is None else self.instrument.identity()
                ),
                "timeframe": (
                    None if self.timeframe is None else self.timeframe.identity()
                ),
                "request_engine": self.requests.identity.to_dict(),
                **({"nominal_registry_hash": self.nominal_registry.content_hash}
                   if self.nominal_registry is not None else {}),
            }
        )

    def begin(
        self, frame: CallbackFrame, *, values: BarValues | None = None
    ) -> RuntimeTransaction:
        preattempt = AbortBaseline(self)
        if type(self.commit_full_identity) is not bool:
            raise PineRuntimeError("commit_full_identity must be boolean")
        if self._identity_mode is None:
            self._identity_mode = self.commit_full_identity
            if not self.commit_full_identity:
                self.transcript = CompactRuntimeTranscript()
        elif self._identity_mode != self.commit_full_identity:
            raise PineRuntimeError(
                "identity mode is immutable during a run; use state_hash for checkpoint snapshots"
            )
        if self._active is not None:
            raise PineRuntimeError(
                "another callback transaction is active",
                code=PL_RUNTIME_TRANSACTION_ACTIVE,
            )
        if frame.sequence <= self.sequence:
            raise PineRuntimeError(
                "callback sequence must be monotonic", code=PL_RUNTIME_SEQUENCE
            )
        if (
            self._deferred_mode is not None
            and self._deferred_mode != frame.defer_bar_commit
        ):
            raise PineRuntimeError(
                "bar commit mode cannot change during a run", code=PL_RUNTIME_SEQUENCE
            )
        if frame.defer_bar_commit:
            if (
                self._last_published_bar is not None
                and frame.bar_index <= self._last_published_bar
            ):
                raise PineRuntimeError(
                    "cannot execute an already published bar", code=PL_RUNTIME_SEQUENCE
                )
            if self._pending_bar_frame is not None:
                if frame.bar_index != self._pending_bar_frame.bar_index:
                    raise PineRuntimeError(
                        "previous bar has not been published", code=PL_RUNTIME_SEQUENCE
                    )
                # Roll back the provisional child request transaction just like
                # normal variables; no past chart-bar history was committed.
                self.requests.finish(persist=False)
                self._pending_bar_frame = None
        # Preserve mutable successful values before begin rolls them back. Growing
        # append-only histories are serialized only if the attempt aborts.
        self._abort_baseline = preattempt
        self._deferred_mode = frame.defer_bar_commit
        if frame.phase == "ORDER_FILL_RECALC":
            target = RuntimeState.FILL_RECALC
        elif frame.realtime:
            target = RuntimeState.REALTIME_CALLBACK
        else:
            target = RuntimeState.HISTORICAL_CALLBACK
        self.machine.transition(target)
        self._begin_segments(frame)
        transaction = RuntimeTransaction(self, frame)
        self._active = transaction
        if values is not None:
            for name in ("open", "high", "low", "close", "volume"):
                transaction.set_series(name, getattr(values, name), "float")
            transaction.set_series("time", values.time, "int")
            transaction.set_series("time_close", values.time_close, "int")
        return transaction

    def _begin_segments(self, frame):
        """Shared begin projection; it never executes an evaluator or callback."""
        for storage in self.series.values():
            storage.begin()
        self.slots.begin(preserve_varip=frame.realtime or frame.defer_bar_commit)
        self.references.begin(preserve_varip=frame.realtime or frame.defer_bar_commit)
        self.visuals.begin()
        self.alerts.begin()
        self.requests.begin(realtime=frame.realtime, sequence=frame.sequence)

    def _rollback_segments(self, frame, new_series):
        """The actual abort projection, shared with scratch proof replay."""
        preserve_varip = frame.realtime or frame.defer_bar_commit
        retained_declarations = set()
        if preserve_varip:
            for row in self.slots.to_json():
                prefix = ("reference-binding:" if row["owner"] == "ast2python.reference.v1"
                          else "enum-binding:" if row["owner"] == "ast2python.enum.v1" else None)
                if prefix and row["varip"] and row["state_id"].startswith(prefix):
                    retained_declarations.add(row["state_id"][len(prefix):])
        for name in set(new_series) - retained_declarations:
            self.series.pop(name, None)
        for storage in self.series.values():
            storage.rollback()
        self.slots.rollback(preserve_varip=preserve_varip)
        self.references.rollback(preserve_varip=preserve_varip)
        self.visuals.rollback()
        self.alerts.rollback()
        self.requests.finish(persist=False)

    def _finish(self, transaction: RuntimeTransaction, commit: bool, *, publish_bar: bool = False) -> CallbackResult:
        if self._active is not transaction:
            raise PineRuntimeError(
                "transaction is not active", code=PL_RUNTIME_TRANSACTION_CLOSED
            )
        frame = transaction.frame
        delegated_outputs = tuple(transaction._delegated_outputs) if commit else ()
        transaction._delegated_outputs.clear()
        transaction._delegated_invocations.clear()
        visual_hash = self.visuals.working_hash
        alert_hash = self.alerts.working_hash
        if commit:
            self._pending_abort = None
            self._pending_abort_attempt_bytes = 0
            self.machine.transition(RuntimeState.COMMITTING)
            if frame.defer_bar_commit:
                # Leave working values available for BAR_COMMIT. The next
                # callback rolls them back, except the intrabar-persistent slots.
                self._pending_bar_frame = frame
            elif not frame.realtime or frame.final_tick:
                for storage in self.series.values():
                    storage.commit()
                self.slots.commit()
                self.references.commit()
                self.visuals.commit()
                self.alerts.commit()
                self.requests.finish(persist=True)
            else:
                self.requests.finish(persist=False)
            self.machine.transition(RuntimeState.COMMITTED)
            self.sequence = frame.sequence
        else:
            attempted_state = self._state_json()
            successful_state = (self._pending_abort["successful_state"] if self._pending_abort is not None
                                else self._abort_baseline.materialize(self))
            previous_attempts = self._pending_abort["attempts"] if self._pending_abort is not None else []
            self._rollback_segments(frame, transaction._new_series)
            self.machine.transition(RuntimeState.ABORTED)
        self._active = None
        state_hash = (
            self.state_hash if self.commit_full_identity else self.semantic_state_hash
        )
        if not commit:
            successful_state["requests"] = self.requests.to_json()
            control_changed = (frame.defer_bar_commit and
                               (self._abort_baseline.deferred_mode is None or self._abort_baseline.pending_bar_frame is not None))
            needs_abort_evidence = (control_changed or self._pending_abort is not None
                                    or self._state_json() != successful_state)
            record = {
                "schema_id": "pinelib.pending_abort.v1",
                "transcript_hash": self.transcript.content_hash,
                "state_hash_algorithm": "pinelib.snapshot-json.v1" if self.commit_full_identity else ALGORITHM,
                "state_hash": state_hash,
                "successful_state": successful_state,
                "attempts": [],
            }
            if needs_abort_evidence:
                witness = {"frame": asdict(frame), "attempted_state": attempted_state,
                           "new_series": sorted(transaction._new_series)}
                attempt_bytes = self._pending_abort_attempt_bytes + len(canonical_json(witness))
                # Hash strings have a fixed canonical width. Count the complete
                # envelope with an empty attempts list, then add exact witness
                # bytes and separators. Previous witnesses are not re-encoded.
                skeleton = {"schema_id": "openpine.runtime_checkpoint.v1", "schema_version": "1.1.0",
                    "identity_hash": self.identity_hash,
                    "state": {**self._state_json(), "transcript": self.transcript.to_dict(), "pending_abort": record},
                    "content_hash": "sha256:" + "0" * 64}
                size = len(canonical_json(skeleton)) + attempt_bytes + len(previous_attempts)
                if size > self.policies.resource.max_checkpoint_bytes:
                    self._abort_baseline.restore_rejected_attempt(self)
                    self._abort_baseline = None
                    raise PineRuntimeError("pending abort witness exceeds checkpoint byte budget", code=PL_RESOURCE_LIMIT)
                record["attempts"] = [*previous_attempts, witness]
                self._pending_abort = record
                self._pending_abort_attempt_bytes = attempt_bytes
            else:
                self._pending_abort = None
                self._pending_abort_attempt_bytes = 0
            if not needs_abort_evidence:
                # A transaction with no persistent effect cannot establish a new
                # control mode. Its ordinary checkpoint remains byte-compatible.
                self._deferred_mode = self._abort_baseline.deferred_mode
        self._abort_baseline = None
        revision_fingerprint = sha(
            {
                "algorithm": "pinelib.revision-fingerprint.v1",
                "sequence": self.sequence,
                "revisions": {
                    key: value.revision for key, value in sorted(self.series.items())
                },
            }
        )
        if commit:
            self.transcript.append(
                {
                    "sequence": frame.sequence,
                    "phase": frame.phase,
                    "realtime": frame.realtime,
                    "final_tick": frame.final_tick,
                    "projection_hash": frame.projection_hash,
                    "bar_index": frame.bar_index,
                    "tick_index": frame.tick_index,
                    "committed": True,
                    "state_hash": state_hash,
                    "visual_batch_hash": visual_hash,
                    "alert_batch_hash": alert_hash,
                    "control": {"bar_commit_mode": "deferred" if self._deferred_mode else "callback",
                                "boundary": "bar_commit" if publish_bar else "callback"},
                }
            )
        transcript_hash = self.transcript.content_hash
        return CallbackResult(
            commit,
            not commit,
            state_hash,
            transcript_hash,
            visual_hash,
            alert_hash,
            delegated_outputs,
            "pinelib.snapshot-json.v1" if self.commit_full_identity else ALGORITHM,
            revision_fingerprint,
        )

    def finalize_bar(self, bar_index: int) -> CallbackResult:
        """Publish the last successful callback once at the host's bar boundary.

        A callback commit releases intents, but history/var/requests/visuals
        become the prior-bar baseline only here. Checkpoints between these two
        boundaries are intentionally rejected.
        """
        if self._active is not None:
            raise PineRuntimeError(
                "cannot publish an active transaction",
                code=PL_RUNTIME_TRANSACTION_ACTIVE,
            )
        pending = self._pending_bar_frame
        if (
            type(bar_index) is not int
            or pending is None
            or pending.bar_index != bar_index
        ):
            raise PineRuntimeError(
                "no matching provisional bar to publish", code=PL_RUNTIME_SEQUENCE
            )
        if pending.realtime and not pending.final_tick:
            raise PineRuntimeError(
                "cannot publish an unconfirmed realtime bar", code=PL_RUNTIME_SEQUENCE
            )
        frame = replace(
            pending,
            phase="BAR_COMMIT",
            sequence=self.sequence + 1,
            defer_bar_commit=False,
        )
        transaction = RuntimeTransaction(self, frame)
        transaction.closed = True
        self._active = transaction
        # Enter the normal transaction state before promoting the working data.
        self.machine.transition(
            RuntimeState.REALTIME_CALLBACK
            if frame.realtime
            else RuntimeState.HISTORICAL_CALLBACK
        )
        result = self._finish(transaction, True, publish_bar=True)
        self._pending_bar_frame = None
        self._last_published_bar = bar_index
        return result

    def barstate(self, frame: CallbackFrame) -> BarStateView:
        return BarStateView(
            isfirst=frame.bar_index == 0,
            islast=frame.is_last_bar,
            ishistory=not frame.realtime,
            isrealtime=frame.realtime,
            isnew=not frame.realtime or frame.tick_index == 0,
            isconfirmed=not frame.realtime or frame.final_tick,
            islastconfirmedhistory=frame.is_last_confirmed_history,
        )

    @property
    def semantic_state_hash(self) -> str:
        return semantic_state_digest(
            self.identity_hash,
            self.sequence,
            self.series,
            self.slots,
            self.references,
            self.visuals,
            self.alerts,
            self.requests,
        )

    @property
    def state_hash(self) -> str:
        return sha(self._state_json())

    def _state_json(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "series": {
                key: value.to_json() for key, value in sorted(self.series.items())
            },
            "slots": self.slots.to_json(),
            "references": self.references.to_json(),
            "visuals": self.visuals.to_json(),
            "alerts": self.alerts.to_json(),
            "requests": self.requests.to_json(),
        }

    def checkpoint(self) -> RuntimeCheckpoint:
        if self._active is not None or self._pending_bar_frame is not None:
            raise PineRuntimeError("cannot checkpoint an active or provisional bar")
        checkpoint_state = {
            **self._state_json(),
            "transcript": self.transcript.to_dict(),
        }
        if self._pending_abort is not None:
            checkpoint_state["pending_abort"] = self._pending_abort
        checkpoint = RuntimeCheckpoint.seal(self.identity_hash, checkpoint_state)
        if (
            len(canonical_json(checkpoint.to_dict()))
            > self.policies.resource.max_checkpoint_bytes
        ):
            raise PineRuntimeError("checkpoint too large", code=PL_RESOURCE_LIMIT)
        return checkpoint

    def restore(self, data: dict[str, object]) -> None:
        self._preflight_checkpoint_input(data)
        self._restore_checkpoint(data, validate_children=True)

    def _preflight_checkpoint_input(self, data):
        """Bound portable input before recursive canonical codecs inspect it."""
        limit = self.policies.resource.max_checkpoint_bytes
        pending = [(data, 0, False)]
        active = []
        nodes = chars = 0
        while pending:
            value, depth, leaving = pending.pop()
            if leaving:
                active.pop()
                continue
            nodes += 1
            # A fixed transport bound also applies when request-depth budgets
            # are configured above the safe depth of the canonical JSON codec.
            if nodes > limit or depth > 128:
                raise PineRuntimeError("checkpoint JSON structure exceeds limits", code=PL_RESOURCE_LIMIT)
            if type(value) in (dict, list, tuple):
                if any(value is ancestor for ancestor in active):
                    raise PineRuntimeError("checkpoint JSON contains a cycle", code=PL_CHECKPOINT_INVALID)
                if len(value) > limit - nodes:
                    raise PineRuntimeError("checkpoint JSON container exceeds limits", code=PL_RESOURCE_LIMIT)
                active.append(value)
                pending.append((value, depth, True))
                if type(value) is dict:
                    if any(type(key) is not str for key in value):
                        raise PineRuntimeError("checkpoint JSON keys must be strings", code=PL_CHECKPOINT_INVALID)
                    chars += sum(len(key) for key in value)
                    pending.extend((child, depth + 1, False) for child in value.values())
                else:
                    pending.extend((child, depth + 1, False) for child in value)
            elif isinstance(value, str):
                chars += len(value)
            elif value is not None and value is not na and not isinstance(value, (bool, int, float)):
                # Preserve the existing portable value owner (enum/reference
                # protocols, mappings and sequences) rather than inventing a
                # narrower cast table at this admission boundary.
                try:
                    portable = to_portable(value)
                except (ValueError, UnicodeError, RecursionError) as error:
                    raise PineRuntimeError("checkpoint JSON is not canonical", code=PL_CHECKPOINT_INVALID) from error
                pending.append((portable, depth, False))
            if chars > limit:
                raise PineRuntimeError("checkpoint exceeds byte limit", code=PL_RESOURCE_LIMIT)
        try:
            encoded_size = len(canonical_json(data))
        except (ValueError, UnicodeError, RecursionError) as error:
            raise PineRuntimeError("checkpoint JSON is not canonical", code=PL_CHECKPOINT_INVALID) from error
        if encoded_size > limit:
            raise PineRuntimeError("checkpoint exceeds byte limit", code=PL_RESOURCE_LIMIT)

    def _new_compiled_request_runtime(self, instrument, timeframe):
        """One child identity owner for live evaluation and checkpoint admission."""
        child = RuntimeSession(
            self.language,
            self.policies,
            inputs=self.inputs,
            instrument=instrument,
            timeframe=TimeframeContext.parse(timeframe),
            request_provider=self.requests.provider,
            nominal_registry=self.nominal_registry,
        )
        child.commit_full_identity = False
        return child

    def _validate_compiled_request_checkpoints(self, requests):
        """Validate saved children without executing generated code or fetching bars.

        Scratch children use the ordinary segment decoder. An explicit work list
        keeps one cumulative budget and avoids recursive restore calls. Only the
        reserved compiled-runtime slot has runtime checkpoint semantics; ordinary
        request expression state remains owned by the request engine.
        """
        from pinelib.request.snapshots import SnapshotRequestProvider

        limits = self.policies.resource
        pending = [(self, requests, 0)]
        count = total_bytes = 0
        while pending:
            parent, engine, depth = pending.pop()
            for dataset in engine.registry.committed_datasets:
                if "compiled-runtime" not in dataset.child_state:
                    continue
                count += 1
                saved = dataset.child_state["compiled-runtime"]
                size = len(canonical_json(saved))
                total_bytes += size
                if (depth > limits.max_request_depth
                        or count > limits.max_request_datasets
                        or size > limits.max_request_state_bytes
                        or total_bytes > limits.max_request_cache_bytes):
                    raise PineRuntimeError(
                        "compiled request checkpoint validation exceeds limits", code=PL_RESOURCE_LIMIT
                    )
                provider = engine.provider
                if not isinstance(provider, SnapshotRequestProvider):
                    raise PineRuntimeError(
                        "compiled request checkpoint requires admitted snapshot metadata", code=PL_CHECKPOINT_INVALID
                    )
                query = dataset.key.query
                source = provider.source(query.instrument_id, query.timeframe)
                context = dataset.child_context
                if (source.content_hash != query.snapshot_id
                        or source.instrument_id != query.instrument_id
                        or source.timeframe != query.timeframe
                        or provider.descriptor.provider_id != query.provider_id
                        or source.instrument.ticker != query.symbol
                        or source.instrument.prefix != query.exchange
                        or source.market != query.market
                        or query.currency not in (None, source.instrument.currency)
                        or query.pine_version != parent.language.pine_version
                        or context is None
                        or context.language_hash != sha(parent.language.identity())
                        or context.policy_hash != sha(parent.policies.identity())):
                    raise PineRuntimeError(
                        "compiled request checkpoint source identity mismatch", code=PL_CHECKPOINT_INVALID
                    )
                child = parent._new_compiled_request_runtime(source.instrument, source.timeframe)
                child._restore_checkpoint(saved, validate_children=False)
                pending.append((child, child.requests, depth + 1))

    def _restore_scratch(self):
        return RuntimeSession(self.language, self.policies, inputs=self.inputs,
            instrument=self.instrument, timeframe=self.timeframe, request_provider=self.requests.provider,
            nominal_registry=self.nominal_registry)

    def _admit_pending_abort(self, record, candidate, transcript, expected_state_hash):
        required = {"schema_id", "transcript_hash", "state_hash_algorithm", "state_hash", "successful_state", "attempts"}
        runtime_fields = {"sequence", "series", "slots", "references", "visuals", "alerts", "requests"}
        if (type(record) is not dict or set(record) != required
                or record["schema_id"] != "pinelib.pending_abort.v1"
                or type(record["successful_state"]) is not dict
                or set(record["successful_state"]) != runtime_fields
                or type(record["attempts"]) is not list or not record["attempts"]):
            raise PineRuntimeError("pending abort schema mismatch", code=PL_CHECKPOINT_INVALID)
        algorithm = ALGORITHM if isinstance(transcript, CompactRuntimeTranscript) else "pinelib.snapshot-json.v1"
        if (record["transcript_hash"] != transcript.content_hash
                or record["state_hash_algorithm"] != algorithm
                or record["state_hash"] != expected_state_hash):
            raise PineRuntimeError("pending abort anchor mismatch", code=PL_CHECKPOINT_INVALID)
        baseline = self._restore_scratch()
        if not transcript.entries and record["successful_state"] != baseline._state_json():
            raise PineRuntimeError("pending abort initial state is not empty", code=PL_CHECKPOINT_INVALID)
        saved_baseline = RuntimeCheckpoint.seal(self.identity_hash,
            {**record["successful_state"], "transcript": transcript.to_dict()})
        baseline._restore_checkpoint(saved_baseline.to_dict(), validate_children=False)
        established_mode = baseline._deferred_mode
        initial_mode = established_mode
        published_bar = baseline._last_published_bar
        previous = baseline
        last = transcript.entries[-1] if transcript.entries else None
        provisional_bar = (last["bar_index"] if last is not None and last.get("control") ==
                           {"bar_commit_mode": "deferred", "boundary": "callback"} else None)
        for index, witness in enumerate(record["attempts"]):
            if (type(witness) is not dict or set(witness) != {"frame", "attempted_state", "new_series"}
                    or type(witness["frame"]) is not dict
                    or set(witness["frame"]) != {field.name for field in fields(CallbackFrame)}):
                raise PineRuntimeError("pending abort attempt schema mismatch", code=PL_CHECKPOINT_INVALID)
            try:
                frame = CallbackFrame(**witness["frame"])
            except (TypeError, PineRuntimeError) as error:
                raise PineRuntimeError("pending abort frame is invalid", code=PL_CHECKPOINT_INVALID) from error
            if (frame.sequence <= candidate.sequence
                    or (established_mode is not None and frame.defer_bar_commit != established_mode)
                    or (frame.defer_bar_commit and published_bar is not None and frame.bar_index <= published_bar)
                    or (index == 0 and provisional_bar is not None and frame.bar_index != provisional_bar)):
                raise PineRuntimeError("pending abort frame differs from bound control", code=PL_CHECKPOINT_INVALID)
            established_mode = frame.defer_bar_commit
            previous._begin_segments(frame)
            attempted = self._decode_runtime_state(witness["attempted_state"], attempted=True)
            validate_abort_attempt(previous, attempted, witness["new_series"], frame)
            # Request witnesses contain committed state only. Open its scratch
            # transaction so the same rollback owner can discard that attempt.
            attempted.requests.begin(realtime=frame.realtime, sequence=frame.sequence)
            attempted._rollback_segments(frame, witness["new_series"])
            control_changed = frame.defer_bar_commit and (initial_mode is None or provisional_bar is not None)
            if index == 0 and not control_changed and attempted._state_json() == record["successful_state"]:
                raise PineRuntimeError("pending abort witness has no retained effect", code=PL_CHECKPOINT_INVALID)
            previous = attempted
        if previous._state_json() != candidate._state_json():
            raise PineRuntimeError("pending abort state differs from replayed rollback", code=PL_CHECKPOINT_INVALID)
        return frame, baseline

    def _decode_runtime_state(self, state, *, attempted=False):
        """Decode closed runtime segments into scratch owners, without a transcript.

        This private owner is shared by ordinary checkpoint admission and bounded
        abort witnesses. Only their enclosing proof admits the decoded state.
        """
        required = {"sequence", "series", "slots", "references", "visuals", "alerts", "requests"}
        if type(state) is not dict or set(state) != required:
            raise PineRuntimeError("checkpoint runtime segment schema mismatch", code=PL_CHECKPOINT_INVALID)
        if type(state["sequence"]) is not int or state["sequence"] < -1:
            raise PineRuntimeError("checkpoint sequence is invalid", code=PL_CHECKPOINT_INVALID)
        series_data = state["series"]
        slots_data = state["slots"]
        references_data = state["references"]
        visuals_data = state["visuals"]
        alerts_data = state["alerts"]
        requests_data = state["requests"]
        if not isinstance(series_data, dict) or not isinstance(slots_data, list):
            raise PineRuntimeError("checkpoint runtime segments are invalid")
        if not all(
            isinstance(segment, dict)
            for segment in (
                references_data,
                visuals_data,
                alerts_data,
                requests_data,
            )
        ):
            raise PineRuntimeError("checkpoint Stage 4 segments are invalid")
        new_series = {
            str(key): SeriesStorage.from_json(value)
            for key, value in series_data.items()
            if isinstance(value, dict)
        }
        if len(new_series) != len(series_data):
            raise PineRuntimeError("checkpoint series row is invalid")
        if any(key != storage.name for key, storage in new_series.items()):
            raise PineRuntimeError(
                "checkpoint series key/name mismatch", code=PL_CHECKPOINT_INVALID
            )
        new_slots = StateSlotRegistry.from_json(
            slots_data, self.policies.resource.max_state_slots
        )
        from pinelib.ta.state import validate_extrema_slots
        validate_extrema_slots(slots_data, pine_version=self.language.pine_version,
                               max_observations=self.policies.resource.max_collection_elements)
        reference_decoder = (RuntimeReferenceHeap._from_abort_witness_json if attempted else RuntimeReferenceHeap.from_json)
        new_references = reference_decoder(
            references_data,
            self.language,
            max_objects=self.policies.resource.max_reference_objects,
            max_elements=self.policies.resource.max_collection_elements,
            nominal_registry=self.nominal_registry,
        )
        # Nominal identities remain typed across serialized series and slots;
        # accepting a JSON-shaped enum or a foreign UDT here would defer a corrupt
        # checkpoint error until the next generated callback.
        from pinelib.reference.nominal import validate_field_type, validate_field_value
        for storage in new_series.values():
            if "udt:" in storage.dtype or "enum:" in storage.dtype:
                validate_field_type(storage.dtype, self.language.pine_version, self.nominal_registry)
            for value in [*storage.committed, storage.working]:
                decoded = new_references._decode_value(value)
                if new_references._has_nominal_value(decoded):
                    validate_field_value(new_references, value, storage.dtype)
            if storage.dtype.startswith(("udt:", "enum:", "array<", "map<", "matrix<")):
                for value in [*storage.committed, storage.working]:
                    if value is not None:
                        validate_field_value(new_references, value, storage.dtype)
        for row in new_slots.to_json():
            new_references._decode_value(from_portable(row["working"]))
            new_references._decode_value(from_portable(row["committed"]))
            prefix = ("enum-binding:" if row["owner"] == "ast2python.enum.v1"
                      else "reference-binding:" if row["owner"] == "ast2python.reference.v1" else None)
            if prefix is not None and row["state_id"].startswith(prefix):
                storage = new_series.get(row["state_id"][len(prefix):])
                if storage is None:
                    raise PineRuntimeError("typed binding checkpoint lacks declared series", code=PL_CHECKPOINT_INVALID)
                if storage.dtype.startswith(("udt:", "enum:", "array<", "map<", "matrix<")):
                    validate_field_value(new_references, from_portable(row["working"]), storage.dtype)
                    if row["committed_exists"]:
                        validate_field_value(new_references, from_portable(row["committed"]), storage.dtype)
        # A rehashed checkpoint must not preserve only the binding while rolling
        # back its object. Validate both segments together before replacing either.
        for row in new_slots.to_json():
            if row["owner"] == "ast2python.reference.v1" and row["varip"]:
                new_references.validate_intrabar_binding(from_portable(row["working"]))
                if row["committed_exists"]:
                    new_references.validate_intrabar_binding(from_portable(row["committed"]), committed=True)
        new_visuals = VisualTape.from_json(
            visuals_data, self.policies.resource.max_visual_events
        )
        new_alerts = AlertTape.from_json(
            alerts_data, self.policies.resource.max_alert_events
        )
        new_requests = RequestEngine(
            self.language, self.policies, self.requests.provider
        )
        new_requests.bind_parent_identity(self.identity_hash)
        new_requests.restore(requests_data)
        candidate = self._restore_scratch()
        candidate.sequence = state["sequence"]
        candidate.series, candidate.slots, candidate.references = new_series, new_slots, new_references
        candidate.visuals, candidate.alerts, candidate.requests = new_visuals, new_alerts, new_requests
        if candidate._state_json() != state:
            raise PineRuntimeError("checkpoint segments are not round-trip stable", code=PL_CHECKPOINT_INVALID)
        return candidate

    def _restore_checkpoint(self, data, *, validate_children):
        if self._active is not None or self._pending_bar_frame is not None:
            raise PineRuntimeError("cannot restore an active or provisional bar")
        checkpoint = RuntimeCheckpoint.parse(data, self.identity_hash)
        state = checkpoint.state
        required = {"sequence", "series", "slots", "references", "visuals", "alerts", "requests", "transcript"}
        has_pending = "pending_abort" in state
        if has_pending:
            required.add("pending_abort")
        if set(state) != required:
            raise PineRuntimeError("checkpoint runtime schema mismatch", code=PL_CHECKPOINT_INVALID)
        new_transcript = RuntimeTranscript.from_dict(state["transcript"])
        required_version = "1.1.0" if has_pending or new_transcript.control_mode is not None else "1.0.0"
        if checkpoint.schema_version != required_version:
            raise PineRuntimeError("checkpoint version differs from its state profile", code=PL_CHECKPOINT_INVALID)
        candidate = self._decode_runtime_state({key: value for key, value in state.items()
            if key not in ("transcript", "pending_abort")})
        new_sequence = candidate.sequence
        if (not new_transcript.entries and new_sequence != -1) or (
                new_transcript.entries and new_transcript.entries[-1]["sequence"] != new_sequence):
            raise PineRuntimeError("runtime transcript does not end at checkpoint sequence", code=PL_CHECKPOINT_INVALID)
        new_series, new_slots, new_references = candidate.series, candidate.slots, candidate.references
        new_visuals, new_alerts, new_requests = candidate.visuals, candidate.alerts, candidate.requests
        normalized_state = {**candidate._state_json(), "transcript": new_transcript.to_dict()}
        expected_state_hash = (candidate.semantic_state_hash if isinstance(new_transcript, CompactRuntimeTranscript)
                               else candidate.state_hash)
        abort_record = state.get("pending_abort")
        abort_frame = successful_runtime = None
        if has_pending:
            abort_frame, successful_runtime = self._admit_pending_abort(
                abort_record, candidate, new_transcript, expected_state_hash)
            normalized_state["pending_abort"] = abort_record
        elif (
            new_transcript.entries
            and new_transcript.entries[-1]["state_hash"] != expected_state_hash
        ):
            raise PineRuntimeError(
                "runtime transcript state hash does not match checkpoint state",
                code=PL_CHECKPOINT_INVALID,
            )
        if to_portable(normalized_state) != checkpoint.state:
            raise PineRuntimeError(
                "checkpoint is not round-trip stable", code=PL_CHECKPOINT_INVALID
            )
        if validate_children:
            # The abort transition requires byte-equal committed requests in its
            # successful evidence. This one traversal validates both copies and
            # does not charge the same child twice against request-count limits.
            self._validate_compiled_request_checkpoints(new_requests)
        # Atomic replacement only after every segment has validated.
        self.series = new_series
        self.slots = new_slots
        self.references = new_references
        self.visuals = new_visuals
        self.alerts = new_alerts
        self.requests = new_requests
        self.transcript = new_transcript
        self.sequence = new_sequence
        last = new_transcript.entries[-1] if new_transcript.entries else None
        self._pending_bar_frame = None
        self._pending_abort = abort_record
        self._pending_abort_attempt_bytes = (sum(len(canonical_json(witness)) for witness in abort_record["attempts"])
                                             if abort_record is not None else 0)
        self._abort_baseline = None
        self._deferred_mode = (abort_frame.defer_bar_commit if abort_frame is not None
                               else new_transcript.control_mode == "deferred" if new_transcript.control_mode is not None
                               else None if last is None else last["phase"] == "BAR_COMMIT")
        published = [entry for entry in new_transcript.entries if new_transcript.is_publication(entry)]
        self._last_published_bar = (
            published[-1]["bar_index"]
            if published
            else None
        )
        self.commit_full_identity = not isinstance(
            new_transcript, CompactRuntimeTranscript
        )
        self._identity_mode = self.commit_full_identity

    def finalize(self) -> None:
        if self._active is not None:
            raise PineRuntimeError("cannot finalize an active transaction")
        self.machine.transition(RuntimeState.FINALIZED)
