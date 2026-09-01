from __future__ import annotations

from dataclasses import dataclass

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
from pinelib.runtime.context import RuntimeLanguageContext
from pinelib.runtime.delegated import (
    DelegatedCapabilityDispatcher,
    DelegatedInvocation,
    DelegatedOutput,
)
from pinelib.runtime.metadata import (
    BarStateView,
    BarValues,
    InstrumentContext,
    TimeframeContext,
)
from pinelib.runtime.policies import RuntimePolicies
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


class RuntimeTransaction:
    def __init__(self, session: RuntimeSession, frame: CallbackFrame) -> None:
        self.session = session
        self.frame = frame
        self.closed = False
        self._new_series: set[str] = set()
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

    def set_series(self, name: str, value: object, dtype: str = "float") -> None:
        self._check()
        if name not in self.session.series:
            if len(self.session.series) >= self.session.policies.resource.max_series:
                raise PineRuntimeError("series limit exceeded", code=PL_RESOURCE_LIMIT)
            self.session.series[name] = SeriesStorage(name, dtype)
            self._new_series.add(name)
        storage = self.session.series[name]
        if storage.dtype != dtype:
            raise PineRuntimeError("series type descriptor changed for the same name")
        if not storage.initialized:
            storage.begin(value)
        else:
            storage.set(value)

    def read_series(self, name: str, offset: int = 0) -> object:
        self._check()
        try:
            return self.session.series[name].read(offset)
        except KeyError as error:
            raise PineRuntimeError(f"unknown series: {name}") from error

    def op_operator_binary(self, operator: str, left: object, right: object) -> object:
        """Ast2Python ``operator.binary`` ABI."""

        self._check()
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
            value = base.read(offset)
        elif isinstance(base, str) and base in self.session.series:
            value = self.session.series[base].read(offset)
        else:
            raise PineRuntimeError(
                "history base must be declared series storage",
                code=PL_SERIES_HISTORY,
            )
        return na if value is None else value

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
        return self.session.slots.get_working(
            state_id,
            owner,
            schema_version,
            varip=varip,
            initial=initial,
        )

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
            self.closed = True
            self.session._finish(self, False)
            raise
        self.closed = True
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
    ) -> None:
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
        )
        self.visuals = VisualTape(policies.resource.max_visual_events)
        self.alerts = AlertTape(policies.resource.max_alert_events)
        self.requests = RequestEngine(language, policies, request_provider)
        self.delegated_dispatcher = delegated_dispatcher
        self.transcript = RuntimeTranscript()
        self.sequence = -1
        self._active: RuntimeTransaction | None = None
        self.machine.transition(RuntimeState.ADMITTED)
        self.machine.transition(RuntimeState.INITIALIZED)
        self.requests.bind_parent_identity(self.identity_hash)

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
            }
        )

    def begin(
        self, frame: CallbackFrame, *, values: BarValues | None = None
    ) -> RuntimeTransaction:
        if self._active is not None:
            raise PineRuntimeError(
                "another callback transaction is active",
                code=PL_RUNTIME_TRANSACTION_ACTIVE,
            )
        if frame.sequence <= self.sequence:
            raise PineRuntimeError(
                "callback sequence must be monotonic", code=PL_RUNTIME_SEQUENCE
            )
        if frame.phase == "ORDER_FILL_RECALC":
            target = RuntimeState.FILL_RECALC
        elif frame.realtime:
            target = RuntimeState.REALTIME_CALLBACK
        else:
            target = RuntimeState.HISTORICAL_CALLBACK
        self.machine.transition(target)
        self.sequence = frame.sequence
        for storage in self.series.values():
            storage.begin()
        self.slots.begin(preserve_varip=frame.realtime)
        self.references.begin()
        self.visuals.begin()
        self.alerts.begin()
        self.requests.begin(realtime=frame.realtime, sequence=frame.sequence)
        transaction = RuntimeTransaction(self, frame)
        self._active = transaction
        if values is not None:
            for name in ("open", "high", "low", "close", "volume"):
                transaction.set_series(name, getattr(values, name), "float")
            transaction.set_series("time", values.time, "int")
            transaction.set_series("time_close", values.time_close, "int")
        return transaction

    def _finish(self, transaction: RuntimeTransaction, commit: bool) -> CallbackResult:
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
            self.machine.transition(RuntimeState.COMMITTING)
            if not frame.realtime or frame.final_tick:
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
        else:
            for name in transaction._new_series:
                self.series.pop(name, None)
            for storage in self.series.values():
                storage.rollback()
            self.slots.rollback(preserve_varip=frame.realtime)
            self.references.rollback()
            self.visuals.rollback()
            self.alerts.rollback()
            self.requests.finish(persist=False)
            self.machine.transition(RuntimeState.ABORTED)
        self._active = None
        state_hash = self.state_hash
        self.transcript.append(
            {
                "sequence": frame.sequence,
                "phase": frame.phase,
                "realtime": frame.realtime,
                "final_tick": frame.final_tick,
                "projection_hash": frame.projection_hash,
                "bar_index": frame.bar_index,
                "tick_index": frame.tick_index,
                "committed": commit,
                "state_hash": state_hash,
                "visual_batch_hash": visual_hash,
                "alert_batch_hash": alert_hash,
            }
        )
        return CallbackResult(
            commit,
            not commit,
            state_hash,
            self.transcript.content_hash,
            visual_hash,
            alert_hash,
            delegated_outputs,
        )

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
        if self._active is not None:
            raise PineRuntimeError("cannot checkpoint an active transaction")
        checkpoint_state = {
            **self._state_json(),
            "transcript": self.transcript.to_dict(),
        }
        checkpoint = RuntimeCheckpoint.seal(self.identity_hash, checkpoint_state)
        if (
            len(canonical_json(checkpoint.to_dict()))
            > self.policies.resource.max_checkpoint_bytes
        ):
            raise PineRuntimeError("checkpoint too large", code=PL_RESOURCE_LIMIT)
        return checkpoint

    def restore(self, data: dict[str, object]) -> None:
        if self._active is not None:
            raise PineRuntimeError("cannot restore an active transaction")
        checkpoint = RuntimeCheckpoint.parse(data, self.identity_hash)
        state = from_portable(checkpoint.state)
        if not isinstance(state, dict):
            raise PineRuntimeError("checkpoint state must decode to an object")
        required_state = {
            "sequence",
            "series",
            "slots",
            "references",
            "visuals",
            "alerts",
            "requests",
            "transcript",
        }
        if set(state) != required_state:
            raise PineRuntimeError(
                "checkpoint runtime schema mismatch", code=PL_CHECKPOINT_INVALID
            )
        if type(state["sequence"]) is not int or state["sequence"] < -1:
            raise PineRuntimeError(
                "checkpoint sequence is invalid", code=PL_CHECKPOINT_INVALID
            )
        series_data = state["series"]
        slots_data = state["slots"]
        references_data = state["references"]
        visuals_data = state["visuals"]
        alerts_data = state["alerts"]
        requests_data = state["requests"]
        transcript_data = state["transcript"]
        if not isinstance(series_data, dict) or not isinstance(slots_data, list):
            raise PineRuntimeError("checkpoint runtime segments are invalid")
        if not all(
            isinstance(segment, dict)
            for segment in (
                references_data,
                visuals_data,
                alerts_data,
                requests_data,
                transcript_data,
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
        new_references = RuntimeReferenceHeap.from_json(
            references_data,
            self.language,
            max_objects=self.policies.resource.max_reference_objects,
            max_elements=self.policies.resource.max_collection_elements,
        )
        new_visuals = VisualTape.from_json(
            visuals_data, self.policies.resource.max_visual_events
        )
        new_alerts = AlertTape.from_json(
            alerts_data, self.policies.resource.max_alert_events
        )
        new_transcript = RuntimeTranscript.from_dict(transcript_data)
        if (not new_transcript.entries and state["sequence"] != -1) or (
            new_transcript.entries
            and new_transcript.entries[-1]["sequence"] != state["sequence"]
        ):
            raise PineRuntimeError(
                "runtime transcript does not end at checkpoint sequence",
                code=PL_CHECKPOINT_INVALID,
            )
        new_requests = RequestEngine(
            self.language, self.policies, self.requests.provider
        )
        new_requests.bind_parent_identity(self.identity_hash)
        new_requests.restore(requests_data)
        new_sequence = state["sequence"]
        normalized_state = {
            "sequence": new_sequence,
            "series": {
                key: value.to_json() for key, value in sorted(new_series.items())
            },
            "slots": new_slots.to_json(),
            "references": new_references.to_json(),
            "visuals": new_visuals.to_json(),
            "alerts": new_alerts.to_json(),
            "requests": new_requests.to_json(),
            "transcript": new_transcript.to_dict(),
        }
        normalized_runtime_state = {
            key: value for key, value in normalized_state.items() if key != "transcript"
        }
        if new_transcript.entries and new_transcript.entries[-1]["state_hash"] != sha(
            normalized_runtime_state
        ):
            raise PineRuntimeError(
                "runtime transcript state hash does not match checkpoint state",
                code=PL_CHECKPOINT_INVALID,
            )
        if to_portable(normalized_state) != checkpoint.state:
            raise PineRuntimeError(
                "checkpoint is not round-trip stable", code=PL_CHECKPOINT_INVALID
            )
        # Atomic replacement only after every segment has validated.
        self.series = new_series
        self.slots = new_slots
        self.references = new_references
        self.visuals = new_visuals
        self.alerts = new_alerts
        self.requests = new_requests
        self.transcript = new_transcript
        self.sequence = new_sequence

    def finalize(self) -> None:
        if self._active is not None:
            raise PineRuntimeError("cannot finalize an active transaction")
        self.machine.transition(RuntimeState.FINALIZED)
