from __future__ import annotations

import copy
from dataclasses import replace
from types import MappingProxyType

import pytest

from pinelib import (
    CallbackFrame,
    RequestPolicy,
    ResourcePolicy,
    RuntimePolicies,
    is_na,
    na,
)
from pinelib.errors import PineRuntimeError
from pinelib.request import (
    CanonicalBar,
    CoverageMode,
    DataCoverage,
    DataFinality,
    DatasetStatus,
    DataSnapshot,
    GapsMode,
    LookaheadMode,
    MergeCursor,
    ProviderDescriptor,
    ProviderErrorKind,
    RequestChildContext,
    RequestDataset,
    RequestDatasetKey,
    RequestDatasetRegistry,
    RequestEngine,
    RequestKind,
    RequestProviderError,
    RequestQuery,
    ResultKind,
    ResultShape,
    RevisionPolicy,
    SnapshotMode,
)
from pinelib.request.alignment import align_lower_timeframe, align_security
from pinelib.request.models import EvaluatedBar
from pinelib.request.provider import fetch_snapshot, validate_provider
from pinelib.state.checkpoint import sha
from tests.stage3_helpers import language
from tests.stage4_helpers import (
    bars,
    provider_for,
    query,
    request_session,
    snapshot,
)


def raises(callable_value, *args, **kwargs):
    with pytest.raises((PineRuntimeError, ValueError, TypeError)):
        callable_value(*args, **kwargs)


def close_expression(bar, _context):
    return bar.number("close")


def committed_dataset(request_query=None):
    request_query = (
        query(snapshot_id="contract-dataset")
        if request_query is None
        else request_query
    )
    provider = provider_for(request_query, bars(request_query, (1.0, 2.0)))
    runtime = request_session(provider)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    request_call = (
        tx.requests.security_lower_tf
        if request_query.kind == RequestKind.SECURITY_LOWER_TF
        else tx.requests.security
    )
    request_call(
        request_query,
        close_expression,
        ResultShape.scalar("float"),
        chart_open_ms=0,
        chart_close_ms=120 * 60_000,
    )
    tx.commit()
    dataset = runtime.requests.registry.lookup(
        request_query.discovery_identity(ResultShape.scalar("float")),
        committed_only=True,
    )
    assert dataset is not None
    return runtime, dataset


def test_result_shape_factories_roundtrip_and_map_immutability():
    scalar = ResultShape.scalar("float")
    tuple_shape = ResultShape.tuple_of(scalar, ResultShape.scalar("bool"))
    array_shape = ResultShape.array_of(scalar)
    udt_shape = ResultShape.udt(
        "Point", {"x": scalar, "name": ResultShape.scalar("string")}
    )
    map_shape = ResultShape.map_of(ResultShape.scalar("string"), scalar)
    for shape in (scalar, tuple_shape, array_shape, udt_shape, map_shape):
        assert ResultShape.from_dict(shape.identity()) == shape
        assert shape.content_hash.startswith("sha256:")
    restored = map_shape.restore(map_shape.validate({"b": 2, "a": 1}))
    assert isinstance(restored, MappingProxyType)
    assert dict(restored) == {"a": 1.0, "b": 2.0}
    with pytest.raises(TypeError):
        restored["c"] = 3  # type: ignore[index]
    assert is_na(scalar.restore(scalar.validate(na)))


def test_result_shape_constructor_rejects_invalid_descriptors():
    raises(ResultShape, "unknown", "x")
    raises(ResultShape, ResultKind.SCALAR, "float", (ResultShape.scalar(),))
    raises(ResultShape, ResultKind.TUPLE, "tuple")
    raises(ResultShape, ResultKind.ARRAY, "array")
    raises(ResultShape, ResultKind.UDT, "Point")
    raises(
        ResultShape,
        ResultKind.UDT,
        "Point",
        (),
        (("x", ResultShape.scalar()), ("x", ResultShape.scalar())),
    )
    raises(ResultShape, ResultKind.UDT, "Point", (), (("", ResultShape.scalar()),))
    raises(ResultShape, ResultKind.MAP, "map", (ResultShape.scalar(),))
    raises(ResultShape.scalar, "")


def test_result_shape_rejects_shape_and_scalar_mismatches():
    nonnullable = ResultShape.scalar("float", nullable=False)
    raises(nonnullable.validate, na)
    raises(nonnullable.validate, None)
    raises(ResultShape.tuple_of(ResultShape.scalar()).validate, (1, 2))
    raises(ResultShape.array_of(ResultShape.scalar()).validate, "not-array")
    udt = ResultShape.udt("P", {"x": ResultShape.scalar("int")})
    raises(udt.validate, 1)
    raises(udt.validate, {"y": 1})
    mapping = ResultShape.map_of(
        ResultShape.scalar("string"), ResultShape.scalar("int")
    )
    raises(mapping.validate, [("a", 1)])
    raises(mapping.restore, {"not": "encoded-list"})
    for shape, value in (
        (ResultShape.scalar("float"), "x"),
        (ResultShape.scalar("int"), True),
        (ResultShape.scalar("bool"), 1),
        (ResultShape.scalar("string"), 1),
    ):
        raises(shape.validate, value)
    assert ResultShape.scalar("object").validate({"x": 1}) == {"x": 1}
    assert ResultShape.scalar("custom").validate(1) == 1


def test_result_shape_parser_rejects_bad_schema():
    raises(ResultShape.from_dict, [])
    raises(ResultShape.from_dict, {"kind": "scalar"})
    shape = ResultShape.udt("P", {"x": ResultShape.scalar()}).identity()
    shape["fields"] = [{"name": "x"}]
    raises(ResultShape.from_dict, shape)


def test_request_query_identity_roundtrip_and_semantic_key_sensitivity():
    base = query(snapshot_id="identity")
    assert RequestQuery.from_dict(base.identity()) == base
    assert base.with_parent("sha256:" + "a" * 64).parent_context_hash is not None
    shape = ResultShape.scalar("float")
    hashes = {base.discovery_identity(shape)}
    mutations = {
        "instrument_id": "instrument:ETH",
        "symbol": "ETHUSDT",
        "exchange": "BYBIT",
        "market": "linear",
        "timeframe": "30",
        "expression_context_id": "call:other",
        "expression_id": "expr:other",
        "currency": "USD",
        "gaps": GapsMode.ON,
        "lookahead": LookaheadMode.ON,
        "calc_bars_count": 10,
        "provider_id": "provider:other",
        "snapshot_id": "snapshot:other",
        "revision_policy": RevisionPolicy.EXACT,
        "coverage_mode": CoverageMode.ALLOW_PARTIAL,
        "pine_version": 5,
        "dynamic": True,
        "parent_context_hash": "sha256:" + "b" * 64,
    }
    for field, value in mutations.items():
        candidate = replace(base, **{field: value})
        hashes.add(candidate.discovery_identity(shape))
    # revision_policy has one admitted value and therefore intentionally cannot
    # create a second hash; every other semantic input does.
    assert len(hashes) == len(mutations)
    assert base.lineage_hash != replace(base, timeframe="30").lineage_hash
    assert base.timeframe_seconds == 3600


def test_request_query_rejects_missing_identity_and_bad_values():
    base = query()
    for field in (
        "instrument_id",
        "symbol",
        "exchange",
        "market",
        "timeframe",
        "expression_context_id",
        "expression_id",
        "provider_id",
        "snapshot_id",
    ):
        raises(replace, base, **{field: ""})
    raises(replace, base, currency=" ")
    raises(replace, base, pine_version=7)
    raises(replace, base, calc_bars_count=-1)
    raises(replace, base, parent_context_hash="bad")
    raises(replace, base, kind="bad")
    raises(replace, base, gaps="bad")
    raises(replace, base, lookahead="bad")
    raises(replace, base, revision_policy="bad")
    raises(replace, base, coverage_mode="bad")
    monthly = replace(base, timeframe="1M")
    raises(lambda: monthly.timeframe_seconds)
    raises(RequestQuery.from_dict, [])
    malformed = base.identity()
    malformed.pop("symbol")
    raises(RequestQuery.from_dict, malformed)


def test_canonical_bar_normalizes_decimals_and_roundtrips():
    bar = CanonicalBar(
        "instrument:X",
        "1",
        0,
        60_000,
        "1.00",
        "2e0",
        "-0.0",
        "1.5000",
        None,
        DataFinality.FINAL,
        0,
        "session:X",
    )
    assert (bar.open, bar.high, bar.low, bar.close) == ("1", "2", "-0", "1.5")
    assert bar.number("close") == 1.5
    assert CanonicalBar.from_dict(bar.identity()) == bar
    assert bar.content_hash.startswith("sha256:")
    raises(bar.number, "unknown")
    raises(bar.number, "volume")


def test_canonical_bar_rejects_noncanonical_payloads():
    base = bars(query(timeframe="1"), (1.0,))[0]
    values = base.identity()
    for field, value in (
        ("instrument_id", ""),
        ("timeframe", "bad"),
        ("close_time_ms", 0),
        ("revision", -1),
        ("finality", "bad"),
        ("open", " "),
        ("open", "abc"),
        ("open", "NaN"),
        ("session_id", ""),
    ):
        row = dict(values)
        row[field] = value
        raises(CanonicalBar.from_dict, row)
    row = dict(values)
    row.update({"high": "0", "low": "2"})
    raises(CanonicalBar.from_dict, row)
    raises(CanonicalBar.from_dict, [])
    row = dict(values)
    row.pop("open")
    raises(CanonicalBar.from_dict, row)


def test_coverage_contract_empty_and_invalid_cases():
    empty = DataCoverage(None, None, True, 0)
    assert DataCoverage.from_dict(empty.identity()) == empty
    raises(DataCoverage, 0, 1, True, -1)
    raises(DataCoverage, 0, 1, True, 0)
    raises(DataCoverage, None, None, True, 1)
    raises(DataCoverage, 1, 1, True, 1)
    raises(DataCoverage.from_dict, [])
    raises(DataCoverage.from_dict, {"complete": True})


def test_snapshot_contract_roundtrip_empty_and_append_modes():
    q = query(snapshot_id="snap-contract")
    source = bars(q, (1.0, 2.0))
    sealed = snapshot(q, source)
    assert DataSnapshot.from_dict(sealed.to_dict()) == sealed
    empty = snapshot(q, ())
    assert empty.coverage.bars_available == 0
    append_q = query(snapshot_id="snap-append")
    append = snapshot(
        append_q,
        bars(append_q, (3.0,), start_ms=2 * 60 * 60_000),
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=sealed.content_hash,
    )
    assert append.mode == SnapshotMode.APPEND


def test_snapshot_rejects_schema_revision_order_coverage_and_hash_mutations():
    q = query(snapshot_id="snap-errors")
    source = bars(q, (1.0, 2.0))
    sealed = snapshot(q, source)
    data = sealed.to_dict()
    mutations = [
        {**data, "schema_id": "wrong"},
        {**data, "schema_version": "1"},
        {**data, "revision": -1},
        {**data, "finality": "bad"},
        {**data, "mode": "bad"},
        {**data, "content_hash": "bad"},
    ]
    for row in mutations:
        raises(DataSnapshot.from_dict, row)
    raises(
        DataSnapshot.seal,
        provider_id=q.provider_id,
        snapshot_id=q.snapshot_id,
        query=q,
        revision=0,
        finality=DataFinality.FINAL,
        coverage=DataCoverage(0, 2 * 60 * 60_000, True, 2),
        bars=source,
        mode=SnapshotMode.FULL,
        parent_snapshot_hash=sealed.content_hash,
    )
    raises(
        DataSnapshot.seal,
        provider_id=q.provider_id,
        snapshot_id=q.snapshot_id,
        query=q,
        revision=0,
        finality=DataFinality.FINAL,
        coverage=DataCoverage(0, 2 * 60 * 60_000, True, 2),
        bars=source,
        mode=SnapshotMode.APPEND,
    )
    bad_coverage = DataCoverage(0, 2 * 60 * 60_000, True, 1)
    raises(
        DataSnapshot.seal,
        provider_id=q.provider_id,
        snapshot_id=q.snapshot_id,
        query=q,
        revision=0,
        finality=DataFinality.FINAL,
        coverage=bad_coverage,
        bars=source,
    )
    overlapping = (
        source[0],
        replace(source[1], open_time_ms=source[0].close_time_ms - 1),
    )
    raises(
        DataSnapshot.seal,
        provider_id=q.provider_id,
        snapshot_id=q.snapshot_id,
        query=q,
        revision=0,
        finality=DataFinality.FINAL,
        coverage=DataCoverage(0, source[1].close_time_ms, True, 2),
        bars=overlapping,
    )
    developing = (replace(source[0], finality=DataFinality.DEVELOPING),)
    raises(
        DataSnapshot.seal,
        provider_id=q.provider_id,
        snapshot_id=q.snapshot_id,
        query=q,
        revision=0,
        finality=DataFinality.FINAL,
        coverage=DataCoverage(0, source[0].close_time_ms, True, 1),
        bars=developing,
    )
    raises(DataSnapshot.from_dict, [])
    malformed = data.copy()
    malformed.pop("bars")
    raises(DataSnapshot.from_dict, malformed)


def test_dataset_key_child_context_and_evaluated_bar_contracts():
    q = query(snapshot_id="key")
    shape = ResultShape.scalar("float")
    snap = snapshot(q, bars(q, (1.0,)))
    key = RequestDatasetKey.create(q, snap.content_hash, shape)
    assert RequestDatasetKey.from_dict(key.to_dict()) == key
    invalid = RequestDatasetKey.invalid(q, shape)
    assert invalid.invalid_symbol
    raises(RequestDatasetKey.from_dict, {})
    raises(RequestDatasetKey, q, "bad", shape.content_hash, False, "bad")

    child = RequestChildContext.seal(
        language_hash=sha(language().identity()),
        policy_hash=sha(RuntimePolicies().identity()),
        instrument_id=q.instrument_id,
        timeframe=q.timeframe,
        dataset_key_hash=key.key_hash,
        namespace="namespace:key",
        parent_runtime_hash="sha256:" + "1" * 64,
    )
    assert RequestChildContext.from_dict(child.to_dict()) == child
    raises(RequestChildContext.from_dict, {})
    raises(replace, child, content_hash="sha256:" + "0" * 64)

    evaluated = EvaluatedBar(0, 1, DataFinality.FINAL, 0, 1.0)
    assert EvaluatedBar.from_dict(evaluated.to_dict()) == evaluated
    raises(EvaluatedBar, 0, 0, DataFinality.FINAL, 0, 1)
    raises(EvaluatedBar, 0, 1, DataFinality.FINAL, -1, 1)
    raises(EvaluatedBar, 0, 1, "bad", 0, 1)
    raises(EvaluatedBar.from_dict, {})


def test_request_dataset_roundtrip_invalid_symbol_and_mutations():
    _runtime, dataset = committed_dataset()
    assert RequestDataset.from_dict(dataset.to_dict()) == dataset
    assert dataset.value(0) == 1.0
    raises(dataset.value, 99)
    invalid = RequestDataset.invalid_symbol(dataset.key.query, dataset.result_shape)
    assert invalid.status == DatasetStatus.INVALID_SYMBOL
    assert RequestDataset.from_dict(invalid.to_dict()) == invalid
    raises(RequestDataset.from_dict, [])
    malformed = dataset.to_dict()
    malformed.pop("status")
    raises(RequestDataset.from_dict, malformed)
    raises(replace, dataset, content_hash="sha256:" + "0" * 64)
    raises(replace, invalid, snapshot=dataset.snapshot)
    raises(replace, dataset, snapshot=None)
    raises(replace, dataset, evaluated_bars=())
    bad_bar = replace(
        dataset.evaluated_bars[0],
        close_time_ms=dataset.evaluated_bars[0].close_time_ms + 1,
    )
    raises(replace, dataset, evaluated_bars=(bad_bar, *dataset.evaluated_bars[1:]))


def test_provider_descriptor_protocol_and_typed_errors():
    descriptor = ProviderDescriptor(
        "provider:x",
        "openpine.marketdata.v2",
        ("request.security", "request.security", "request.dynamic"),
        10,
    )
    assert descriptor.capabilities == ("request.dynamic", "request.security")
    assert descriptor.content_hash.startswith("sha256:")
    descriptor.require("request.security")
    raises(descriptor.require, "request.missing")
    raises(ProviderDescriptor, "", "openpine.marketdata.v2", ("x",), 1)
    raises(ProviderDescriptor, "p", "wrong", ("x",), 1)
    raises(ProviderDescriptor, "p", "openpine.marketdata.v2", (), 1)
    raises(ProviderDescriptor, "p", "openpine.marketdata.v2", ("",), 1)
    raises(ProviderDescriptor, "p", "openpine.marketdata.v2", ("x",), 0)
    raises(RequestProviderError, "bad", "x")
    assert validate_provider(None) is None
    raises(validate_provider, object())


def test_fetch_snapshot_wraps_transport_and_rejects_noncanonical_result():
    q = query(snapshot_id="provider-errors")

    class Boom:
        descriptor = ProviderDescriptor(
            "provider:test", "openpine.marketdata.v2", ("request.security",), 10
        )

        def fetch(self, query):
            raise OSError("down")

    with pytest.raises(RequestProviderError) as caught:
        fetch_snapshot(Boom(), q)
    assert caught.value.kind == ProviderErrorKind.TRANSPORT

    class Bad(Boom):
        def fetch(self, query):
            return {"legacy": "bar"}

    with pytest.raises(RequestProviderError) as caught:
        fetch_snapshot(Bad(), q)
    assert caught.value.kind == ProviderErrorKind.SCHEMA


def test_request_policy_and_resource_policy_validate_and_hash():
    assert RequestPolicy().dynamic_enabled(6)
    assert not RequestPolicy().dynamic_enabled(5)
    assert RequestPolicy(dynamic_requests="enabled").dynamic_enabled(5)
    assert not RequestPolicy(dynamic_requests="disabled").dynamic_enabled(6)
    assert RequestPolicy(nested_requests="enabled").nested_enabled
    assert not RequestPolicy().nested_enabled
    raises(RequestPolicy, dynamic_requests="bad")
    raises(RequestPolicy, nested_requests="bad")
    raises(ResourcePolicy, max_request_depth=0)
    policies = RuntimePolicies()
    assert "max_request_datasets" in policies.identity()["resource"]


def test_merge_cursor_contract_and_registry_basic_transaction_roundtrip():
    runtime, dataset = committed_dataset()
    discovery = dataset.key.query.discovery_identity(dataset.result_shape)
    cursor = MergeCursor("security", dataset.key.key_hash, 0, 1, 0, 0)
    assert MergeCursor.from_dict(cursor.to_dict()) == cursor
    raises(MergeCursor, "bad", dataset.key.key_hash, 0, 1, 0, 0)
    raises(MergeCursor, "security", "bad", 0, 1, 0, 0)
    raises(MergeCursor, "security", dataset.key.key_hash, 1, 1, 0, 0)
    raises(MergeCursor, "security", dataset.key.key_hash, 0, 1, -2, 0)
    raises(MergeCursor.from_dict, {})

    data = runtime.requests.registry.to_json()
    restored = RequestDatasetRegistry.from_json(
        data,
        max_datasets=64,
        max_bars=100,
        max_cache_bytes=10_000_000,
    )
    assert restored.lookup(discovery, committed_only=True) == dataset
    assert restored.content_hash == runtime.requests.registry.content_hash
    assert restored.cache_bytes > 0


def test_registry_guards_savepoint_rollback_cursor_and_limits():
    _runtime, dataset = committed_dataset()
    discovery = dataset.key.query.discovery_identity(dataset.result_shape)
    registry = RequestDatasetRegistry(
        max_datasets=1, max_bars=2, max_cache_bytes=10_000_000
    )
    raises(RequestDatasetRegistry, max_datasets=0, max_bars=1, max_cache_bytes=1)
    raises(registry.register, discovery, dataset)
    raises(registry.lookup, "bad")
    registry.begin()
    raises(registry.begin)
    savepoint = registry.savepoint()
    registry.register(discovery, dataset)
    assert registry.lookup(discovery) == dataset
    registry.update_cursor(
        discovery, MergeCursor("security", dataset.key.key_hash, 0, 1, 0, 0)
    )
    assert registry.cursor(discovery) is not None
    registry.restore_savepoint(savepoint)
    assert registry.lookup(discovery) is None
    registry.rollback()
    raises(registry.rollback)

    registry.begin()
    registry.register(discovery, dataset)
    registry.commit()
    assert registry.dataset_count == 1
    assert registry.discovery_count == 1
    registry.begin()
    assert registry.register(discovery, dataset) == dataset
    wrong_cursor = MergeCursor("security", "sha256:" + "0" * 64, 0, 1, 0, 0)
    raises(registry.update_cursor, discovery, wrong_cursor)
    registry.rollback()

    other_q = query(snapshot_id="other-dataset")
    _other_runtime, other = committed_dataset(other_q)
    registry.begin()
    raises(registry.register, other_q.discovery_identity(other.result_shape), other)
    registry.rollback()


def test_registry_restore_rejects_malformed_relationships_and_limits():
    runtime, _ = committed_dataset()
    data = runtime.requests.registry.to_json()
    raises(
        RequestDatasetRegistry.from_json,
        {},
        max_datasets=64,
        max_bars=100,
        max_cache_bytes=1_000_000,
    )
    malformed = copy.deepcopy(data)
    malformed["datasets"] = {}
    raises(
        RequestDatasetRegistry.from_json,
        malformed,
        max_datasets=64,
        max_bars=100,
        max_cache_bytes=1_000_000,
    )
    duplicate = copy.deepcopy(data)
    duplicate["datasets"].append(copy.deepcopy(duplicate["datasets"][0]))
    raises(
        RequestDatasetRegistry.from_json,
        duplicate,
        max_datasets=64,
        max_bars=100,
        max_cache_bytes=1_000_000,
    )
    bad_discovery = copy.deepcopy(data)
    bad_discovery["discovery"][0]["dataset_key_hash"] = "sha256:" + "0" * 64
    raises(
        RequestDatasetRegistry.from_json,
        bad_discovery,
        max_datasets=64,
        max_bars=100,
        max_cache_bytes=1_000_000,
    )
    bad_row = copy.deepcopy(data)
    bad_row["discovery"] = [{}]
    raises(
        RequestDatasetRegistry.from_json,
        bad_row,
        max_datasets=64,
        max_bars=100,
        max_cache_bytes=1_000_000,
    )
    bad_cursor = copy.deepcopy(data)
    bad_cursor["cursors"] = [{"discovery_id": "x", "cursor": {}}]
    raises(
        RequestDatasetRegistry.from_json,
        bad_cursor,
        max_datasets=64,
        max_bars=100,
        max_cache_bytes=1_000_000,
    )
    raises(
        RequestDatasetRegistry.from_json,
        data,
        max_datasets=0,
        max_bars=100,
        max_cache_bytes=1_000_000,
    )
    raises(
        RequestDatasetRegistry.from_json,
        data,
        max_datasets=64,
        max_bars=1,
        max_cache_bytes=1_000_000,
    )
    raises(
        RequestDatasetRegistry.from_json,
        data,
        max_datasets=64,
        max_bars=100,
        max_cache_bytes=1,
    )


def test_alignment_rejects_wrong_dataset_kind_and_boundaries():
    _runtime, dataset = committed_dataset()
    raises(
        align_security,
        dataset,
        chart_open_ms=1,
        chart_close_ms=1,
        realtime=False,
        allow_developing_realtime=True,
    )
    lower_q = query(
        kind=RequestKind.SECURITY_LOWER_TF, timeframe="5", snapshot_id="lower-contract"
    )
    _lower_runtime, lower_dataset = committed_dataset(lower_q)
    raises(
        align_security,
        lower_dataset,
        chart_open_ms=0,
        chart_close_ms=15 * 60_000,
        realtime=False,
        allow_developing_realtime=True,
    )
    raises(
        align_lower_timeframe,
        dataset,
        chart_open_ms=0,
        chart_close_ms=60 * 60_000,
        realtime=False,
        allow_developing_realtime=True,
        max_intrabars=10,
    )


def test_request_engine_admission_binding_finish_and_restore_guards():
    q = query(snapshot_id="engine-guards")
    provider = provider_for(q, bars(q, (1.0,)))
    raises(
        RequestEngine,
        language(),
        RuntimePolicies(request=RequestPolicy(require_historical_discovery=False)),
        provider,
    )
    engine = RequestEngine(language(), RuntimePolicies(), provider)
    raises(engine.bind_parent_identity, "bad")
    engine.bind_parent_identity("sha256:" + "1" * 64)
    raises(engine.bind_parent_identity, "sha256:" + "2" * 64)
    raises(engine.begin, realtime=False, sequence=-1)
    engine.begin(realtime=False, sequence=0)
    raises(engine.begin, realtime=False, sequence=1)
    raises(engine.restore, {})
    engine.finish(persist=False)
    raises(engine.finish, persist=False)
    state = engine.to_json()
    wrong = copy.deepcopy(state)
    wrong["provider_identity"] = {"provider": None, "provider_hash": None}
    raises(engine.restore, wrong)
    engine.restore(state)


def test_request_expression_state_identity_and_budget_guards():
    q = query(snapshot_id="state-guards")
    provider = provider_for(q, bars(q, (1.0,)))
    defaults = ResourcePolicy()
    kwargs = {name: getattr(defaults, name) for name in defaults.__dataclass_fields__}
    kwargs["max_request_state_bytes"] = 32
    runtime = request_session(provider, resource_policy=ResourcePolicy(**kwargs))

    def bad_state(_bar, context):
        raises(context.state, "", 0)
        raises(context.set_state, "0:compat", 1)
        context.set_state("ok", 1)
        assert context.state("ok", 0) == 1
        context.set_state("ok", 2)
        assert context.state("ok", 0) == 2
        context.set_state("huge", "x" * 100)
        return 1.0

    bad_state.__pinelib_expression_identity__ = "test:state-guards"
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError) as caught:
        tx.requests.security(
            q,
            bad_state,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
        )
    assert caught.value.code == "PL1900"
    tx.abort()
