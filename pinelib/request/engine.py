from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dis import get_instructions
from types import (
    BuiltinFunctionType,
    BuiltinMethodType,
    CodeType,
    FunctionType,
    ModuleType,
)
from typing import Protocol

from pinelib.errors import (
    PL_REQUEST_DATA,
    PL_REQUEST_DISCOVERY,
    PL_REQUEST_IDENTITY,
    PL_REQUEST_NESTED,
    PL_REQUEST_POLICY,
    PL_REQUEST_PROVIDER,
    PL_REQUEST_RESULT_SHAPE,
    PL_RESOURCE_LIMIT,
    PineRuntimeError,
)
from pinelib.request.alignment import align_lower_timeframe, align_security
from pinelib.request.models import (
    CanonicalBar,
    CoverageMode,
    DataFinality,
    DatasetStatus,
    DataSnapshot,
    EvaluatedBar,
    RequestChildContext,
    RequestDataset,
    RequestDatasetKey,
    RequestKind,
    RequestQuery,
    ResultShape,
    SnapshotMode,
)
from pinelib.request.provider import (
    ProviderErrorKind,
    RequestDataProvider,
    RequestProviderError,
    fetch_snapshot,
    validate_provider,
)
from pinelib.request.registry import RequestDatasetRegistry
from pinelib.runtime.context import RuntimeLanguageContext
from pinelib.runtime.policies import RuntimePolicies
from pinelib.state.checkpoint import (
    canonical_json,
    from_portable,
    is_canonical_sha256,
    sha,
    to_portable,
)


def _callable_reference(value: object) -> dict[str, str]:
    return {
        "module": str(getattr(value, "__module__", "")),
        "qualname": str(getattr(value, "__qualname__", getattr(value, "__name__", ""))),
    }


def _global_attribute_paths(code: CodeType) -> dict[str, set[tuple[str, ...]]]:
    instructions = tuple(get_instructions(code))
    paths: dict[str, set[tuple[str, ...]]] = {}
    for index, instruction in enumerate(instructions):
        if instruction.opname not in {"LOAD_GLOBAL", "LOAD_NAME"}:
            continue
        name = instruction.argval
        if type(name) is not str:
            continue
        attributes: list[str] = []
        cursor = index + 1
        while cursor < len(instructions) and instructions[cursor].opname in {
            "LOAD_ATTR",
            "LOAD_METHOD",
        }:
            attribute = instructions[cursor].argval
            if type(attribute) is not str:
                break
            attributes.append(attribute)
            cursor += 1
        paths.setdefault(name, set()).add(tuple(attributes))
    return paths


def _fingerprint_static_attributes(
    owner: object,
    paths: set[tuple[str, ...]],
    active_callables: set[object],
    *,
    owner_kind: str,
) -> object:
    if not paths or () in paths:
        raise PineRuntimeError(
            f"implicit evaluator {owner_kind} access requires an explicit stable identity",
            code=PL_REQUEST_IDENTITY,
        )
    attributes: dict[str, object] = {}
    for path in sorted(paths):
        value = owner
        try:
            for attribute in path:
                value = getattr(value, attribute)
        except AttributeError as error:
            raise PineRuntimeError(
                f"implicit evaluator {owner_kind} attribute is unavailable",
                code=PL_REQUEST_IDENTITY,
            ) from error
        attributes[".".join(path)] = _fingerprint_value(value, active_callables)
    return {f"{owner_kind}_attributes": attributes}


def _semantic_code_names(code: CodeType) -> list[str]:
    global_names = {
        instruction.argval
        for instruction in get_instructions(code)
        if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}
        and type(instruction.argval) is str
    }
    return ["<global>" if name in global_names else name for name in code.co_names]


def _fingerprint_function(
    token: object,
    active_callables: set[object],
) -> object:
    code = getattr(token, "__code__", None)
    if not isinstance(code, CodeType):
        raise PineRuntimeError(
            "request evaluator requires an explicit stable identity",
            code=PL_REQUEST_IDENTITY,
        )
    if token in active_callables:
        return {"recursive_callable": True}
    active_callables.add(token)
    try:
        closure_values: list[object] = []
        for cell in getattr(token, "__closure__", None) or ():
            try:
                captured = cell.cell_contents
                closure_values.append(
                    {"self_reference": True}
                    if captured is token
                    else _fingerprint_value(captured, active_callables)
                )
            except ValueError as error:
                raise PineRuntimeError(
                    "request evaluator has an empty closure cell",
                    code=PL_REQUEST_IDENTITY,
                ) from error
        global_values: list[object] = []
        globals_namespace = getattr(token, "__globals__", None)
        if isinstance(globals_namespace, dict):
            for name, paths in _global_attribute_paths(code).items():
                if name not in globals_namespace:
                    continue
                value = globals_namespace[name]
                if value is token:
                    global_values.append({"self_reference": True})
                elif isinstance(value, ModuleType):
                    global_values.append(
                        _fingerprint_static_attributes(
                            value,
                            paths,
                            active_callables,
                            owner_kind="module",
                        )
                    )
                elif isinstance(value, type):
                    global_values.append(
                        _fingerprint_static_attributes(
                            value,
                            paths,
                            active_callables,
                            owner_kind="class",
                        )
                    )
                else:
                    global_values.append(_fingerprint_value(value, active_callables))
        return {
            "code": _fingerprint_value(code, active_callables),
            "defaults": _fingerprint_value(
                getattr(token, "__defaults__", None), active_callables
            ),
            "kwdefaults": _fingerprint_value(
                getattr(token, "__kwdefaults__", None), active_callables
            ),
            "closure": closure_values,
            "globals": global_values,
        }
    finally:
        active_callables.remove(token)


def _fingerprint_value(
    value: object,
    active_callables: set[object] | None = None,
) -> object:
    """Return a deterministic representation for evaluator code identity."""

    active = active_callables if active_callables is not None else set()
    callable_token = getattr(value, "__func__", value)
    if isinstance(callable_token, FunctionType):
        fingerprint: dict[str, object] = {
            "function": _fingerprint_function(callable_token, active)
        }
        bound_self = getattr(value, "__self__", None)
        if bound_self is not None:
            fingerprint["bound_self"] = _fingerprint_value(bound_self, active)
        return fingerprint
    if isinstance(value, (BuiltinFunctionType, BuiltinMethodType)):
        return {"builtin_callable": _callable_reference(value)}
    if isinstance(value, ModuleType):
        raise PineRuntimeError(
            "implicit evaluator module access requires an explicit stable identity",
            code=PL_REQUEST_IDENTITY,
        )
    if isinstance(value, type):
        return {"type": _callable_reference(value)}
    if isinstance(value, CodeType):
        return {
            "argcount": value.co_argcount,
            "posonlyargcount": value.co_posonlyargcount,
            "kwonlyargcount": value.co_kwonlyargcount,
            "flags": value.co_flags,
            "bytecode": value.co_code.hex(),
            "constants": [_fingerprint_value(item, active) for item in value.co_consts],
            "names": _semantic_code_names(value),
            "local_count": value.co_nlocals,
            "freevar_count": len(value.co_freevars),
            "cellvar_count": len(value.co_cellvars),
        }
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, (tuple, list)):
        return [_fingerprint_value(item, active) for item in value]
    if isinstance(value, dict):
        if not all(type(key) is str for key in value):
            raise PineRuntimeError(
                "implicit evaluator closure keys must be strings",
                code=PL_REQUEST_IDENTITY,
            )
        return {
            key: _fingerprint_value(item, active) for key, item in sorted(value.items())
        }
    identity = getattr(value, "identity", None)
    if callable(identity):
        return {"identity": _fingerprint_value(identity(), active)}
    try:
        return to_portable(value)
    except PineRuntimeError as error:
        raise PineRuntimeError(
            "request evaluator requires an explicit stable identity",
            code=PL_REQUEST_IDENTITY,
        ) from error


def _implicit_evaluator_identity(expression: RequestExpression) -> str:
    return sha(
        {
            "contract": "request.implicit_evaluator_code.v2",
            "callable": _fingerprint_value(expression, set()),
        }
    )


class RequestExpression(Protocol):
    def __call__(
        self, bar: CanonicalBar, context: RequestExpressionContext
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class RequestEngineIdentity:
    provider: dict[str, object] | None
    provider_hash: str | None

    def to_dict(self) -> dict[str, object]:
        return {"provider": self.provider, "provider_hash": self.provider_hash}


class RequestExpressionContext:
    """State-isolated child context used while evaluating a sealed dataset."""

    __slots__ = (
        "_bar",
        "_depth",
        "_engine",
        "_stack",
        "_state",
        "child",
    )

    def __init__(
        self,
        engine: RequestEngine,
        child: RequestChildContext,
        state: Mapping[str, object],
        *,
        depth: int,
        stack: tuple[str, ...],
    ) -> None:
        self._engine = engine
        self.child = child
        portable = to_portable(dict(state))
        if not isinstance(portable, dict):
            raise PineRuntimeError(
                "request child state must be an object", code=PL_REQUEST_DATA
            )
        self._state = portable
        self._bar: CanonicalBar | None = None
        self._depth = depth
        self._stack = stack

    @property
    def bar(self) -> CanonicalBar:
        if self._bar is None:
            raise PineRuntimeError(
                "request expression bar is not bound", code=PL_REQUEST_DATA
            )
        return self._bar

    def _bind(self, bar: CanonicalBar) -> None:
        self._bar = bar

    def state(self, state_id: str, initial: object) -> object:
        if not state_id or state_id.strip() != state_id or state_id.startswith("0:"):
            raise PineRuntimeError(
                "request state_id is invalid", code=PL_REQUEST_IDENTITY
            )
        if state_id not in self._state:
            self.set_state(state_id, initial)
        return from_portable(to_portable(self._state[state_id]))

    def set_state(self, state_id: str, value: object) -> None:
        if not state_id or state_id.strip() != state_id or state_id.startswith("0:"):
            raise PineRuntimeError(
                "request state_id is invalid", code=PL_REQUEST_IDENTITY
            )
        encoded = to_portable(value)
        before = self._state.get(state_id, None)
        self._state[state_id] = encoded
        if (
            len(canonical_json(self._state))
            > self._engine.policies.resource.max_request_state_bytes
        ):
            if before is None:
                self._state.pop(state_id, None)
            else:
                self._state[state_id] = before
            raise PineRuntimeError(
                "request child state limit exceeded", code=PL_RESOURCE_LIMIT
            )

    def state_snapshot(self) -> dict[str, object]:
        snapshot = to_portable(self._state)
        if not isinstance(snapshot, dict):
            raise PineRuntimeError(
                "request child state is invalid", code=PL_REQUEST_RESULT_SHAPE
            )
        return snapshot

    def nested_security(
        self,
        query: RequestQuery,
        expression: RequestExpression,
        shape: ResultShape,
        *,
        ignore_invalid_symbol: bool = False,
    ) -> object:
        bound = self._bind_parent(query)
        return self._engine.security(
            bound,
            expression,
            shape,
            chart_open_ms=self.bar.open_time_ms,
            chart_close_ms=self.bar.close_time_ms,
            ignore_invalid_symbol=ignore_invalid_symbol,
            _depth=self._depth + 1,
            _stack=self._stack,
            _expected_parent_hash=self.child.content_hash,
        )

    def nested_lower_timeframe(
        self,
        query: RequestQuery,
        expression: RequestExpression,
        shape: ResultShape,
        *,
        ignore_invalid_symbol: bool = False,
    ) -> tuple[object, ...]:
        bound = self._bind_parent(query)
        return self._engine.security_lower_tf(
            bound,
            expression,
            shape,
            chart_open_ms=self.bar.open_time_ms,
            chart_close_ms=self.bar.close_time_ms,
            ignore_invalid_symbol=ignore_invalid_symbol,
            _depth=self._depth + 1,
            _stack=self._stack,
            _expected_parent_hash=self.child.content_hash,
        )

    def _bind_parent(self, query: RequestQuery) -> RequestQuery:
        if query.parent_context_hash not in {None, self.child.content_hash}:
            raise PineRuntimeError(
                "nested request parent identity mismatch", code=PL_REQUEST_NESTED
            )
        return query.with_parent(self.child.content_hash)


class RequestEngine:
    """Canonical request engine over immutable provider snapshots."""

    def __init__(
        self,
        language: RuntimeLanguageContext,
        policies: RuntimePolicies,
        provider: RequestDataProvider | None = None,
    ) -> None:
        if not policies.request.require_historical_discovery:
            raise PineRuntimeError(
                "realtime request discovery cannot be disabled",
                code=PL_REQUEST_POLICY,
            )
        self.language = language
        self.policies = policies
        self._admitted_provider = provider
        self.provider_descriptor = validate_provider(provider)
        self.registry = RequestDatasetRegistry(
            max_datasets=policies.resource.max_request_datasets,
            max_bars=policies.resource.max_request_bars,
            max_cache_bytes=policies.resource.max_request_cache_bytes,
        )
        self._realtime = False
        self._sequence = -1
        self._evaluations = 0
        self._parent_runtime_hash: str | None = None
        self._committed_evaluators: dict[str, str] = {}
        self._working_evaluators: dict[str, str] = {}
        self._committed_static_contexts: dict[str, str] = {}
        self._working_static_contexts: dict[str, str] = {}
        self._committed_callables: dict[str, object] = {}
        self._working_callables: dict[str, object] = {}

    @property
    def identity(self) -> RequestEngineIdentity:
        descriptor = self.provider_descriptor
        return RequestEngineIdentity(
            None if descriptor is None else descriptor.identity(),
            None if descriptor is None else descriptor.content_hash,
        )

    @property
    def provider(self) -> RequestDataProvider | None:
        return self._admitted_provider

    @provider.setter
    def provider(self, value: RequestDataProvider | None) -> None:
        if value is not self._admitted_provider:
            raise PineRuntimeError(
                "request provider cannot change after admission",
                code=PL_REQUEST_PROVIDER,
            )

    def bind_parent_identity(self, identity_hash: str) -> None:
        if not is_canonical_sha256(identity_hash):
            raise PineRuntimeError(
                "runtime identity is invalid", code=PL_REQUEST_IDENTITY
            )
        if self._parent_runtime_hash not in {None, identity_hash}:
            raise PineRuntimeError(
                "request engine runtime identity changed", code=PL_REQUEST_IDENTITY
            )
        self._parent_runtime_hash = identity_hash

    @property
    def active(self) -> bool:
        return self.registry.active

    @property
    def state_hash(self) -> str:
        return sha(self.to_json())

    def begin(self, *, realtime: bool, sequence: int) -> None:
        if type(realtime) is not bool or type(sequence) is not int or sequence < 0:
            raise PineRuntimeError(
                "request callback identity is invalid", code=PL_REQUEST_IDENTITY
            )
        if self._parent_runtime_hash is None:
            raise PineRuntimeError(
                "request engine is not bound to a runtime", code=PL_REQUEST_IDENTITY
            )
        self.registry.begin()
        self._working_evaluators = dict(self._committed_evaluators)
        self._working_static_contexts = dict(self._committed_static_contexts)
        self._working_callables = dict(self._committed_callables)
        self._realtime = realtime
        self._sequence = sequence
        self._evaluations = 0

    def finish(self, *, persist: bool) -> None:
        if not self.registry.active:
            raise PineRuntimeError(
                "request transaction is not active", code=PL_REQUEST_DATA
            )
        if persist:
            self.registry.commit()
            self._committed_evaluators = dict(self._working_evaluators)
            self._committed_static_contexts = dict(self._working_static_contexts)
            self._committed_callables = dict(self._working_callables)
        else:
            self.registry.rollback()
        self._working_evaluators = {}
        self._working_static_contexts = {}
        self._working_callables = {}
        self._sequence = -1
        self._evaluations = 0

    def security(
        self,
        query: RequestQuery,
        expression: RequestExpression,
        shape: ResultShape,
        *,
        chart_open_ms: int,
        chart_close_ms: int,
        ignore_invalid_symbol: bool = False,
        _depth: int = 0,
        _stack: tuple[str, ...] = (),
        _expected_parent_hash: str | None = None,
    ) -> object:
        if type(ignore_invalid_symbol) is not bool:
            raise PineRuntimeError(
                "ignore_invalid_symbol must be a bool", code=PL_REQUEST_DATA
            )
        if query.kind != RequestKind.SECURITY:
            raise PineRuntimeError(
                "request kind mismatch for security", code=PL_REQUEST_DATA
            )
        savepoint = self.registry.savepoint()
        evaluations = self._evaluations
        evaluators = dict(self._working_evaluators)
        static_contexts = dict(self._working_static_contexts)
        callables = dict(self._working_callables)
        try:
            dataset, discovery_id = self._dataset(
                query,
                expression,
                shape,
                ignore_invalid_symbol=ignore_invalid_symbol,
                depth=_depth,
                stack=_stack,
                expected_parent_hash=_expected_parent_hash,
            )
            value, cursor = align_security(
                dataset,
                chart_open_ms=chart_open_ms,
                chart_close_ms=chart_close_ms,
                realtime=self._realtime,
                allow_developing_realtime=self.policies.request.allow_developing_realtime,
            )
            self.registry.update_cursor(discovery_id, cursor)
            return value
        except Exception:
            self.registry.restore_savepoint(savepoint)
            self._evaluations = evaluations
            self._working_evaluators = evaluators
            self._working_static_contexts = static_contexts
            self._working_callables = callables
            raise

    def security_lower_tf(
        self,
        query: RequestQuery,
        expression: RequestExpression,
        shape: ResultShape,
        *,
        chart_open_ms: int,
        chart_close_ms: int,
        ignore_invalid_symbol: bool = False,
        _depth: int = 0,
        _stack: tuple[str, ...] = (),
        _expected_parent_hash: str | None = None,
    ) -> tuple[object, ...]:
        if type(ignore_invalid_symbol) is not bool:
            raise PineRuntimeError(
                "ignore_invalid_symbol must be a bool", code=PL_REQUEST_DATA
            )
        if query.kind != RequestKind.SECURITY_LOWER_TF:
            raise PineRuntimeError(
                "request kind mismatch for lower TF", code=PL_REQUEST_DATA
            )
        if query.timeframe_seconds * 1000 > chart_close_ms - chart_open_ms:
            raise PineRuntimeError(
                "request.security_lower_tf timeframe exceeds the chart timeframe",
                code=PL_REQUEST_DATA,
            )
        savepoint = self.registry.savepoint()
        evaluations = self._evaluations
        evaluators = dict(self._working_evaluators)
        static_contexts = dict(self._working_static_contexts)
        callables = dict(self._working_callables)
        try:
            dataset, discovery_id = self._dataset(
                query,
                expression,
                shape,
                ignore_invalid_symbol=ignore_invalid_symbol,
                depth=_depth,
                stack=_stack,
                expected_parent_hash=_expected_parent_hash,
            )
            values, cursor = align_lower_timeframe(
                dataset,
                chart_open_ms=chart_open_ms,
                chart_close_ms=chart_close_ms,
                realtime=self._realtime,
                allow_developing_realtime=self.policies.request.allow_developing_realtime,
                max_intrabars=self.policies.resource.max_intrabars_per_bar,
            )
            self.registry.update_cursor(discovery_id, cursor)
            return values
        except Exception:
            self.registry.restore_savepoint(savepoint)
            self._evaluations = evaluations
            self._working_evaluators = evaluators
            self._working_static_contexts = static_contexts
            self._working_callables = callables
            raise

    def _dataset(
        self,
        query: RequestQuery,
        expression: RequestExpression,
        shape: ResultShape,
        *,
        ignore_invalid_symbol: bool,
        depth: int,
        stack: tuple[str, ...],
        expected_parent_hash: str | None,
    ) -> tuple[RequestDataset, str]:
        if not self.registry.active:
            raise PineRuntimeError(
                "request call requires an active callback", code=PL_REQUEST_DATA
            )
        savepoint = self.registry.savepoint()
        evaluations = self._evaluations
        evaluators = dict(self._working_evaluators)
        static_contexts = dict(self._working_static_contexts)
        callables = dict(self._working_callables)
        try:
            self._validate_query(
                query, depth=depth, expected_parent_hash=expected_parent_hash
            )
            discovery_id = query.discovery_identity(shape)
            evaluator_identity = self._bind_evaluator(discovery_id, query, expression)
            cycle_body = query.identity()
            cycle_body["parent_context_hash"] = None
            cycle_id = sha({"query": cycle_body, "shape": shape.identity()})
            if cycle_id in stack:
                raise PineRuntimeError(
                    "nested request cycle detected", code=PL_REQUEST_NESTED
                )
            stack = (*stack, cycle_id)

            dataset = self.registry.lookup(discovery_id, committed_only=self._realtime)
            if dataset is not None:
                self._raise_if_invalid(dataset, ignore_invalid_symbol)
                return dataset, discovery_id
            if self._realtime:
                raise PineRuntimeError(
                    "request context was not discovered during history",
                    code=PL_REQUEST_DISCOVERY,
                    details={"discovery_id": discovery_id},
                )

            snapshot = self._fetch(query, shape, discovery_id, ignore_invalid_symbol)
            if isinstance(snapshot, RequestDataset):
                dataset = snapshot
            else:
                parent = self._validate_snapshot(
                    query,
                    snapshot,
                    shape,
                    evaluator_identity,
                )
                dataset = self._evaluate_dataset(
                    query,
                    snapshot,
                    expression,
                    shape,
                    depth,
                    stack,
                    parent,
                )
            registered = self.registry.register(discovery_id, dataset)
            self._raise_if_invalid(registered, ignore_invalid_symbol)
            return registered, discovery_id
        except Exception:
            self.registry.restore_savepoint(savepoint)
            self._evaluations = evaluations
            self._working_evaluators = evaluators
            self._working_static_contexts = static_contexts
            self._working_callables = callables
            raise

    def _bind_evaluator(
        self,
        discovery_id: str,
        query: RequestQuery,
        expression: RequestExpression,
    ) -> str:
        if not callable(expression):
            raise PineRuntimeError(
                "request expression is not callable", code=PL_REQUEST_RESULT_SHAPE
            )
        callable_token = getattr(expression, "__func__", expression)
        explicit = getattr(expression, "__pinelib_expression_identity__", None)
        if explicit is None:
            evaluator_identity = _implicit_evaluator_identity(expression)
        else:
            if (
                type(explicit) is not str
                or not explicit
                or explicit.strip() != explicit
            ):
                raise PineRuntimeError(
                    "explicit request evaluator identity is invalid",
                    code=PL_REQUEST_IDENTITY,
                )
            evaluator_identity = sha(
                {
                    "contract": "request.explicit_evaluator_identity.v1",
                    "identity": explicit,
                }
            )
        admitted = self._working_evaluators.get(discovery_id)
        if admitted is not None and admitted != evaluator_identity:
            raise PineRuntimeError(
                "request evaluator identity changed for a cached expression",
                code=PL_REQUEST_IDENTITY,
            )
        admitted_callable = self._working_callables.get(discovery_id)
        if (
            explicit is None
            and admitted_callable is not None
            and admitted_callable is not callable_token
        ):
            raise PineRuntimeError(
                "request evaluator changed without an explicit identity",
                code=PL_REQUEST_IDENTITY,
            )
        self._working_evaluators[discovery_id] = evaluator_identity
        self._working_callables[discovery_id] = callable_token
        return evaluator_identity

    def _fetch(
        self,
        query: RequestQuery,
        shape: ResultShape,
        discovery_id: str,
        ignore_invalid_symbol: bool,
    ) -> DataSnapshot | RequestDataset:
        if self.provider is None or self.provider is not self._admitted_provider:
            raise PineRuntimeError(
                "request provider changed after admission", code=PL_REQUEST_PROVIDER
            )
        current_descriptor = validate_provider(self.provider)
        if current_descriptor != self.provider_descriptor:
            raise PineRuntimeError(
                "request provider descriptor changed after admission",
                code=PL_REQUEST_PROVIDER,
            )
        try:
            return fetch_snapshot(self.provider, query)
        except RequestProviderError as error:
            if (
                error.kind != ProviderErrorKind.INVALID_SYMBOL
                or not ignore_invalid_symbol
            ):
                raise
            return RequestDataset.invalid_symbol(query, shape)

    def _validate_query(
        self,
        query: RequestQuery,
        *,
        depth: int,
        expected_parent_hash: str | None,
    ) -> None:
        if query.pine_version != self.language.pine_version:
            raise PineRuntimeError(
                "request Pine version mismatch", code=PL_REQUEST_IDENTITY
            )
        descriptor = self.provider_descriptor
        if descriptor is None or query.provider_id != descriptor.provider_id:
            raise PineRuntimeError(
                "request provider identity mismatch", code=PL_REQUEST_PROVIDER
            )
        descriptor.require(query.kind.value)
        self._bind_static_context(query)
        if query.calc_bars_count is not None and (
            query.calc_bars_count > descriptor.max_bars_per_query
            or query.calc_bars_count > self.policies.resource.max_request_bars
        ):
            raise PineRuntimeError(
                "calc_bars_count exceeds admitted limits", code=PL_RESOURCE_LIMIT
            )
        if query.dynamic:
            if not self.policies.request.dynamic_enabled(self.language.pine_version):
                raise PineRuntimeError(
                    "dynamic requests are disabled", code=PL_REQUEST_POLICY
                )
            descriptor.require("request.dynamic")
        if depth < 0 or depth > self.policies.resource.max_request_depth:
            raise PineRuntimeError(
                "nested request depth exceeded", code=PL_REQUEST_NESTED
            )
        if depth == 0:
            if (
                query.parent_context_hash is not None
                or expected_parent_hash is not None
            ):
                raise PineRuntimeError(
                    "top-level request has a parent identity", code=PL_REQUEST_NESTED
                )
        else:
            if not self.policies.request.dynamic_enabled(self.language.pine_version):
                raise PineRuntimeError(
                    "nested requests require dynamic requests",
                    code=PL_REQUEST_POLICY,
                )
            if not self.policies.request.nested_enabled:
                raise PineRuntimeError(
                    "nested requests are disabled", code=PL_REQUEST_NESTED
                )
            descriptor.require("request.nested")
            if query.parent_context_hash != expected_parent_hash:
                raise PineRuntimeError(
                    "nested request parent identity mismatch", code=PL_REQUEST_NESTED
                )

    def _bind_static_context(self, query: RequestQuery) -> None:
        if self.language.pine_version > 5 or query.dynamic:
            return
        context_hash = self._static_context_hash(query)
        admitted = self._working_static_contexts.get(query.expression_context_id)
        if admitted is not None and admitted != context_hash:
            raise PineRuntimeError(
                "non-dynamic request callsite context changed",
                code=PL_REQUEST_POLICY,
            )
        self._working_static_contexts[query.expression_context_id] = context_hash

    @staticmethod
    def _static_context_hash(query: RequestQuery) -> str:
        return sha(
            {
                "kind": query.kind.value,
                "instrument_id": query.instrument_id,
                "symbol": query.symbol,
                "exchange": query.exchange,
                "market": query.market,
                "timeframe": query.timeframe,
                "currency": query.currency,
                "provider_id": query.provider_id,
            }
        )

    def _validate_snapshot(
        self,
        query: RequestQuery,
        snapshot: DataSnapshot,
        shape: ResultShape,
        evaluator_identity: str,
    ) -> RequestDataset | None:
        descriptor = self.provider_descriptor
        assert descriptor is not None
        if (
            snapshot.provider_id != descriptor.provider_id
            or snapshot.provider_id != query.provider_id
        ):
            raise RequestProviderError(
                ProviderErrorKind.SCHEMA, "snapshot provider identity mismatch"
            )
        if snapshot.snapshot_id != query.snapshot_id:
            raise RequestProviderError(
                ProviderErrorKind.REVISION, "snapshot identity mismatch"
            )
        if snapshot.query_hash != query.content_hash:
            raise RequestProviderError(
                ProviderErrorKind.REVISION, "snapshot query hash mismatch"
            )
        if (
            query.coverage_mode == CoverageMode.REQUIRE_COMPLETE
            and not snapshot.coverage.complete
        ):
            raise RequestProviderError(
                ProviderErrorKind.INCOMPLETE_COVERAGE, "snapshot coverage is incomplete"
            )
        if (
            len(snapshot.bars) > descriptor.max_bars_per_query
            or len(snapshot.bars) > self.policies.resource.max_request_bars
        ):
            raise PineRuntimeError(
                "provider snapshot exceeds request bar limits", code=PL_RESOURCE_LIMIT
            )
        if (
            query.calc_bars_count is not None
            and len(snapshot.bars) > query.calc_bars_count
        ):
            raise RequestProviderError(
                ProviderErrorKind.SCHEMA, "provider ignored calc_bars_count"
            )
        for bar in snapshot.bars:
            if (
                bar.instrument_id != query.instrument_id
                or bar.timeframe != query.timeframe
            ):
                raise RequestProviderError(
                    ProviderErrorKind.SCHEMA, "snapshot bar context mismatch"
                )
            if bar.revision > snapshot.revision:
                raise RequestProviderError(
                    ProviderErrorKind.REVISION, "bar revision exceeds snapshot revision"
                )
        if snapshot.mode != SnapshotMode.APPEND:
            return None

        parent = self.registry.find_by_snapshot_hash(
            snapshot.parent_snapshot_hash or "",
            query=query,
            result_shape=shape,
            language_hash=sha(self.language.identity()),
            policy_hash=sha(self.policies.identity()),
            parent_runtime_hash=self._parent_runtime_hash or "",
        )
        if (
            parent is None
            or parent.status != DatasetStatus.READY
            or parent.snapshot is None
        ):
            raise RequestProviderError(
                ProviderErrorKind.REVISION, "append snapshot parent is unavailable"
            )
        parent_discovery = parent.key.query.discovery_identity(parent.result_shape)
        if self._working_evaluators.get(parent_discovery) != evaluator_identity:
            raise RequestProviderError(
                ProviderErrorKind.REVISION,
                "append snapshot evaluator lineage mismatch",
            )
        if snapshot.revision <= parent.snapshot.revision:
            raise RequestProviderError(
                ProviderErrorKind.REVISION,
                "append snapshot revision did not strictly increase",
            )
        if any(bar.revision != snapshot.revision for bar in snapshot.bars):
            raise RequestProviderError(
                ProviderErrorKind.REVISION,
                "append bar revision does not match snapshot revision",
            )
        if any(bar.finality != DataFinality.FINAL for bar in snapshot.bars[:-1]):
            raise RequestProviderError(
                ProviderErrorKind.REVISION,
                "append snapshot contains a non-final interior bar",
            )
        if (
            parent.evaluated_bars
            and parent.evaluated_bars[-1].finality != DataFinality.FINAL
        ):
            raise RequestProviderError(
                ProviderErrorKind.REVISION,
                "append snapshot cannot extend an unresolved developing tail",
            )
        if (
            snapshot.bars
            and parent.evaluated_bars
            and snapshot.bars[0].open_time_ms < parent.evaluated_bars[-1].close_time_ms
        ):
            raise RequestProviderError(
                ProviderErrorKind.REVISION, "append snapshot overlaps parent history"
            )
        return parent

    def _evaluate_dataset(
        self,
        query: RequestQuery,
        snapshot: DataSnapshot,
        expression: RequestExpression,
        shape: ResultShape,
        depth: int,
        stack: tuple[str, ...],
        previous: RequestDataset | None,
    ) -> RequestDataset:
        key = RequestDatasetKey.create(query, snapshot.content_hash, shape)
        child = RequestChildContext.seal(
            language_hash=sha(self.language.identity()),
            policy_hash=sha(self.policies.identity()),
            instrument_id=query.instrument_id,
            timeframe=query.timeframe,
            dataset_key_hash=key.key_hash,
            namespace=f"{query.expression_context_id}:{query.expression_id}:{key.key_hash}",
            parent_runtime_hash=self._parent_runtime_hash or "",
        )
        evaluated: list[EvaluatedBar] = []
        state: dict[str, object] = {}
        if snapshot.mode == SnapshotMode.APPEND:
            assert previous is not None
            evaluated.extend(previous.evaluated_bars)
            restored_state = from_portable(previous.child_state)
            if not isinstance(restored_state, dict):
                raise PineRuntimeError(
                    "request child state is invalid", code=PL_REQUEST_RESULT_SHAPE
                )
            state = restored_state
        context = RequestExpressionContext(self, child, state, depth=depth, stack=stack)
        for bar in snapshot.bars:
            self._evaluations += 1
            if (
                self._evaluations
                > self.policies.resource.max_request_evaluations_per_callback
            ):
                raise PineRuntimeError(
                    "request evaluation budget exceeded", code=PL_RESOURCE_LIMIT
                )
            context._bind(bar)
            value = expression(bar, context)
            encoded = shape.validate(value)
            evaluated.append(
                EvaluatedBar(
                    bar.open_time_ms,
                    bar.close_time_ms,
                    bar.finality,
                    bar.revision,
                    encoded,
                )
            )
        child_state = context.state_snapshot()
        if (
            len(canonical_json(child_state))
            > self.policies.resource.max_request_state_bytes
        ):
            raise PineRuntimeError(
                "request child state limit exceeded", code=PL_RESOURCE_LIMIT
            )
        return RequestDataset.ready(
            key=key,
            shape=shape,
            snapshot=snapshot,
            evaluated_bars=evaluated,
            child_context=child,
            child_state=child_state,
            lineage_hash=query.lineage_hash,
        )

    @staticmethod
    def _raise_if_invalid(dataset: RequestDataset, ignore_invalid_symbol: bool) -> None:
        if dataset.status == DatasetStatus.INVALID_SYMBOL and not ignore_invalid_symbol:
            raise RequestProviderError(
                ProviderErrorKind.INVALID_SYMBOL, "invalid symbol"
            )

    def to_json(self) -> dict[str, object]:
        return {
            "provider_identity": self.identity.to_dict(),
            "registry": self.registry.to_json(),
            "evaluators": [
                {
                    "discovery_id": discovery_id,
                    "evaluator_identity": evaluator_identity,
                }
                for discovery_id, evaluator_identity in sorted(
                    self._committed_evaluators.items()
                )
            ],
            "static_contexts": [
                {
                    "expression_context_id": expression_context_id,
                    "context_hash": context_hash,
                }
                for expression_context_id, context_hash in sorted(
                    self._committed_static_contexts.items()
                )
            ],
        }

    def restore(self, data: object) -> None:
        if self.registry.active:
            raise PineRuntimeError(
                "cannot restore active request engine", code=PL_REQUEST_DATA
            )
        if not isinstance(data, dict) or set(data) != {
            "provider_identity",
            "registry",
            "evaluators",
            "static_contexts",
        }:
            raise PineRuntimeError(
                "request engine checkpoint schema mismatch", code=PL_REQUEST_DATA
            )
        expected = self.identity.to_dict()
        if data["provider_identity"] != expected:
            raise PineRuntimeError(
                "request provider checkpoint identity mismatch",
                code=PL_REQUEST_IDENTITY,
            )
        if not isinstance(data["evaluators"], list) or not isinstance(
            data["static_contexts"], list
        ):
            raise PineRuntimeError(
                "request identity bindings must be lists", code=PL_REQUEST_IDENTITY
            )
        new_registry = RequestDatasetRegistry.from_json(
            data["registry"],
            max_datasets=self.policies.resource.max_request_datasets,
            max_bars=self.policies.resource.max_request_bars,
            max_cache_bytes=self.policies.resource.max_request_cache_bytes,
        )
        if self._parent_runtime_hash is None:
            raise PineRuntimeError(
                "request engine is not bound to a runtime", code=PL_REQUEST_IDENTITY
            )
        new_registry.validate_parent_identity(self._parent_runtime_hash)

        evaluators: dict[str, str] = {}
        for row in data["evaluators"]:
            if not isinstance(row, dict) or set(row) != {
                "discovery_id",
                "evaluator_identity",
            }:
                raise PineRuntimeError(
                    "request evaluator binding schema mismatch",
                    code=PL_REQUEST_IDENTITY,
                )
            discovery_id = row["discovery_id"]
            evaluator_identity = row["evaluator_identity"]
            if (
                not is_canonical_sha256(discovery_id)
                or not is_canonical_sha256(evaluator_identity)
                or discovery_id in evaluators
                or new_registry.lookup_dataset_identity(discovery_id) is None
            ):
                raise PineRuntimeError(
                    "request evaluator binding is invalid",
                    code=PL_REQUEST_IDENTITY,
                )
            evaluators[discovery_id] = evaluator_identity
        if set(evaluators) != set(new_registry.dataset_identity_ids):
            raise PineRuntimeError(
                "request evaluator bindings are incomplete",
                code=PL_REQUEST_IDENTITY,
            )
        new_registry.validate_evaluator_lineage(evaluators)

        static_contexts: dict[str, str] = {}
        for row in data["static_contexts"]:
            if not isinstance(row, dict) or set(row) != {
                "expression_context_id",
                "context_hash",
            }:
                raise PineRuntimeError(
                    "static request context binding schema mismatch",
                    code=PL_REQUEST_IDENTITY,
                )
            expression_context_id = row["expression_context_id"]
            context_hash = row["context_hash"]
            if (
                type(expression_context_id) is not str
                or not expression_context_id
                or expression_context_id.strip() != expression_context_id
                or not is_canonical_sha256(context_hash)
                or expression_context_id in static_contexts
            ):
                raise PineRuntimeError(
                    "static request context binding is invalid",
                    code=PL_REQUEST_IDENTITY,
                )
            static_contexts[expression_context_id] = context_hash

        expected_static_contexts: dict[str, str] = {}
        for dataset in new_registry.committed_datasets:
            query = dataset.key.query
            if query.pine_version > 5 or query.dynamic:
                continue
            context_hash = self._static_context_hash(query)
            admitted = expected_static_contexts.get(query.expression_context_id)
            if admitted is not None and admitted != context_hash:
                raise PineRuntimeError(
                    "restored static request contexts conflict",
                    code=PL_REQUEST_IDENTITY,
                )
            expected_static_contexts[query.expression_context_id] = context_hash
        if static_contexts != expected_static_contexts:
            raise PineRuntimeError(
                "static request context bindings are incomplete",
                code=PL_REQUEST_IDENTITY,
            )

        self.registry = new_registry
        self._committed_evaluators = evaluators
        self._committed_static_contexts = static_contexts
        self._committed_callables = {}
