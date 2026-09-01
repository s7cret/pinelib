from __future__ import annotations

import copy

import pytest

from pinelib import (
    CallbackFrame,
    CoverageMode,
    DataFinality,
    GapsMode,
    LookaheadMode,
    RequestKind,
    RequestPolicy,
    ResourcePolicy,
    ResultShape,
    is_na,
)
from pinelib.abi import request as request_abi
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_values
from pinelib.request import ProviderErrorKind, RequestProviderError, SnapshotMode
from tests.stage4_helpers import (
    MemoryProvider,
    bars,
    provider_for,
    query,
    request_session,
    snapshot,
)


def close_expression(bar, _context):
    return bar.number("close")


def _call(
    runtime,
    request_query,
    chart_open,
    chart_close,
    *,
    sequence,
    realtime=False,
    final=True,
    expression=close_expression,
    shape=None,
    ignore=False,
):
    tx = runtime.begin(
        CallbackFrame(
            "REALTIME_TICK" if realtime else "HISTORICAL_EVAL",
            sequence,
            realtime=realtime,
            final_tick=final,
            bar_index=sequence,
        )
    )
    value = tx.requests.security(
        request_query,
        expression,
        ResultShape.scalar("float") if shape is None else shape,
        chart_open_ms=chart_open,
        chart_close_ms=chart_close,
        ignore_invalid_symbol=ignore,
    )
    tx.commit()
    return value


def test_historical_htf_gaps_and_lookahead_matrix():
    minute = 60_000
    queries = [
        query(snapshot_id="off-gapoff", gaps=GapsMode.OFF, lookahead=LookaheadMode.OFF),
        query(snapshot_id="off-gapon", gaps=GapsMode.ON, lookahead=LookaheadMode.OFF),
        query(snapshot_id="on-gapoff", gaps=GapsMode.OFF, lookahead=LookaheadMode.ON),
        query(snapshot_id="on-gapon", gaps=GapsMode.ON, lookahead=LookaheadMode.ON),
    ]
    snapshots = {
        item.snapshot_id: snapshot(item, bars(item, (10.0, 20.0))) for item in queries
    }
    provider = MemoryProvider(snapshots)
    runtime = request_session(provider)

    assert is_na(_call(runtime, queries[0], 0, 15 * minute, sequence=0))
    assert _call(runtime, queries[0], 45 * minute, 60 * minute, sequence=1) == 10.0
    assert _call(runtime, queries[0], 60 * minute, 75 * minute, sequence=2) == 10.0

    assert _call(runtime, queries[1], 45 * minute, 60 * minute, sequence=3) == 10.0
    assert is_na(_call(runtime, queries[1], 60 * minute, 75 * minute, sequence=4))

    assert _call(runtime, queries[2], 0, 15 * minute, sequence=5) == 10.0
    assert _call(runtime, queries[2], 15 * minute, 30 * minute, sequence=6) == 10.0
    assert _call(runtime, queries[3], 0, 15 * minute, sequence=7) == 10.0
    assert is_na(_call(runtime, queries[3], 15 * minute, 30 * minute, sequence=8))
    assert len(provider.calls) == 4


def test_realtime_requires_historical_discovery_and_never_fetches_unseen():
    q = query(snapshot_id="unseen")
    provider = provider_for(q, bars(q, (1.0,)))
    runtime = request_session(provider)
    tx = runtime.begin(
        CallbackFrame("REALTIME_TICK", 0, realtime=True, final_tick=False)
    )
    with pytest.raises(PineRuntimeError) as caught:
        tx.requests.security(
            q,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=15 * 60_000,
        )
    assert caught.value.code == "PL1503"
    assert provider.calls == []
    tx.abort()


def test_realtime_uses_admitted_developing_value_without_refetch():
    q = query(snapshot_id="developing")
    source = bars(
        q,
        (10.0, 21.0),
        finalities=(DataFinality.FINAL, DataFinality.DEVELOPING),
    )
    provider = provider_for(q, source, complete=False)
    # Developing tail is explicit and partial coverage is explicit.
    q = query(snapshot_id="developing", coverage_mode=CoverageMode.ALLOW_PARTIAL)
    source = bars(
        q, (10.0, 21.0), finalities=(DataFinality.FINAL, DataFinality.DEVELOPING)
    )
    provider = provider_for(q, source, complete=False)
    runtime = request_session(provider)
    assert _call(runtime, q, 0, 60 * 60_000, sequence=0) == 10.0
    assert (
        _call(
            runtime,
            q,
            60 * 60_000,
            75 * 60_000,
            sequence=1,
            realtime=True,
            final=False,
        )
        == 21.0
    )
    assert len(provider.calls) == 1


def test_dynamic_request_policy_is_version_exact():
    q5 = query(snapshot_id="v5", version=5, dynamic=True)
    p5 = provider_for(q5, bars(q5, (1.0,)))
    runtime5 = request_session(p5, version=5)
    tx = runtime5.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError) as caught:
        tx.requests.security(
            q5,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
        )
    assert caught.value.code == "PL1504"
    tx.abort()

    enabled = RequestPolicy(dynamic_requests="enabled")
    runtime5_enabled = request_session(p5, version=5, request_policy=enabled)
    assert _call(runtime5_enabled, q5, 0, 60 * 60_000, sequence=0) == 1.0

    q6 = query(snapshot_id="v6", version=6, dynamic=True)
    p6 = provider_for(q6, bars(q6, (2.0,)))
    assert _call(request_session(p6), q6, 0, 60 * 60_000, sequence=0) == 2.0

    disabled = RequestPolicy(dynamic_requests="disabled")
    runtime6_disabled = request_session(p6, request_policy=disabled)
    tx = runtime6_disabled.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError):
        tx.requests.security(
            q6,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
        )
    tx.abort()


def test_security_lower_tf_returns_ordered_values_and_abi_array():
    minute = 60_000
    q = query(kind=RequestKind.SECURITY_LOWER_TF, timeframe="5", snapshot_id="ltf")
    provider = provider_for(q, bars(q, (1.0, 2.0, 3.0)))
    runtime = request_session(provider)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    values = tx.requests.security_lower_tf(
        q,
        close_expression,
        ResultShape.scalar("float"),
        chart_open_ms=0,
        chart_close_ms=15 * minute,
    )
    assert values == (1.0, 2.0, 3.0)
    tx.commit()

    # A second call uses the exact ABI and creates a proper PineArray handle.
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    handle = request_abi.security_lower_tf_v1(
        tx,
        q,
        close_expression,
        ResultShape.scalar("float"),
        0,
        15 * minute,
        "request-array:1",
    )
    assert array_values(tx.references, handle) == (1.0, 2.0, 3.0)
    tx.commit()
    assert len(provider.calls) == 1


def test_lower_tf_allows_equal_rejects_higher_and_enforces_limit():
    q = query(kind=RequestKind.SECURITY_LOWER_TF, timeframe="15", snapshot_id="same-tf")
    provider = provider_for(q, bars(q, (1.0,)))
    runtime = request_session(provider)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    assert tx.requests.security_lower_tf(
        q,
        close_expression,
        ResultShape.scalar("float"),
        chart_open_ms=0,
        chart_close_ms=15 * 60_000,
    ) == (1.0,)
    tx.abort()

    higher = query(
        kind=RequestKind.SECURITY_LOWER_TF,
        timeframe="30",
        snapshot_id="higher-tf",
    )
    higher_provider = provider_for(higher, bars(higher, (1.0,)))
    higher_runtime = request_session(higher_provider)
    tx = higher_runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError):
        tx.requests.security_lower_tf(
            higher,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=15 * 60_000,
        )
    tx.abort()

    q2 = query(kind=RequestKind.SECURITY_LOWER_TF, timeframe="5", snapshot_id="limit")
    provider2 = provider_for(q2, bars(q2, (1.0, 2.0, 3.0)))
    defaults = ResourcePolicy()
    kwargs = {name: getattr(defaults, name) for name in defaults.__dataclass_fields__}
    kwargs["max_intrabars_per_bar"] = 2
    runtime2 = request_session(provider2, resource_policy=ResourcePolicy(**kwargs))
    tx = runtime2.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError) as caught:
        tx.requests.security_lower_tf(
            q2,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=15 * 60_000,
        )
    assert caught.value.code == "PL1900"
    tx.abort()


def test_ignore_invalid_symbol_only_masks_that_exact_taxonomy():
    q = query(snapshot_id="invalid")
    invalid = RequestProviderError(ProviderErrorKind.INVALID_SYMBOL, "bad symbol")
    provider = MemoryProvider({q.snapshot_id: invalid})
    runtime = request_session(provider)
    assert is_na(_call(runtime, q, 0, 60 * 60_000, sequence=0, ignore=True))
    # The ignored tombstone is admitted and reused on realtime without provider I/O.
    assert is_na(
        _call(
            runtime,
            q,
            0,
            15 * 60_000,
            sequence=1,
            realtime=True,
            final=False,
            ignore=True,
        )
    )
    assert len(provider.calls) == 1

    runtime2 = request_session(provider)
    tx = runtime2.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(RequestProviderError) as caught:
        tx.requests.security(
            q,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
        )
    assert caught.value.kind == ProviderErrorKind.INVALID_SYMBOL
    tx.abort()

    transport_q = query(snapshot_id="transport")
    transport = RequestProviderError(ProviderErrorKind.TRANSPORT, "network")
    transport_provider = MemoryProvider({transport_q.snapshot_id: transport})
    runtime3 = request_session(transport_provider)
    tx = runtime3.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(RequestProviderError) as caught:
        tx.requests.security(
            transport_q,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
            ignore_invalid_symbol=True,
        )
    assert caught.value.kind == ProviderErrorKind.TRANSPORT
    tx.abort()


def test_incomplete_coverage_and_calc_bars_are_fail_closed():
    q = query(snapshot_id="partial")
    provider = provider_for(q, bars(q, (1.0,)), complete=False)
    runtime = request_session(provider)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(RequestProviderError) as caught:
        tx.requests.security(
            q,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
        )
    assert caught.value.kind == ProviderErrorKind.INCOMPLETE_COVERAGE
    tx.abort()

    limited_q = query(snapshot_id="calc", calc_bars_count=1)
    bad_snapshot = snapshot(limited_q, bars(limited_q, (1.0, 2.0)))
    limited_provider = MemoryProvider({limited_q.snapshot_id: bad_snapshot})
    limited_runtime = request_session(limited_provider)
    tx = limited_runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(RequestProviderError) as caught:
        tx.requests.security(
            limited_q,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=120 * 60_000,
        )
    assert caught.value.kind == ProviderErrorKind.SCHEMA
    tx.abort()


def test_tuple_array_and_udt_results_preserve_shape():
    q_tuple = query(snapshot_id="tuple", expression_id="expr:tuple")
    q_udt = query(snapshot_id="udt", expression_id="expr:udt")
    q_array = query(snapshot_id="array", expression_id="expr:array")
    provider = MemoryProvider(
        {
            q_tuple.snapshot_id: snapshot(q_tuple, bars(q_tuple, (2.0,))),
            q_udt.snapshot_id: snapshot(q_udt, bars(q_udt, (3.0,))),
            q_array.snapshot_id: snapshot(q_array, bars(q_array, (4.0,))),
        }
    )
    runtime = request_session(provider)
    tuple_shape = ResultShape.tuple_of(
        ResultShape.scalar("float"), ResultShape.scalar("bool")
    )
    assert _call(
        runtime,
        q_tuple,
        0,
        60 * 60_000,
        sequence=0,
        expression=lambda bar, ctx: (bar.number("close"), True),
        shape=tuple_shape,
    ) == (2.0, True)
    udt_shape = ResultShape.udt(
        "Point",
        {"x": ResultShape.scalar("float"), "name": ResultShape.scalar("string")},
    )
    udt = _call(
        runtime,
        q_udt,
        0,
        60 * 60_000,
        sequence=1,
        expression=lambda bar, ctx: {"x": bar.number("close"), "name": "p"},
        shape=udt_shape,
    )
    assert dict(udt) == {"x": 3.0, "name": "p"}
    array_shape = ResultShape.array_of(ResultShape.scalar("float"))
    assert _call(
        runtime,
        q_array,
        0,
        60 * 60_000,
        sequence=2,
        expression=lambda bar, ctx: [bar.number("close"), 5],
        shape=array_shape,
    ) == (4.0, 5.0)


def test_dataset_cache_reuses_snapshot_and_expression_state_is_isolated():
    q1 = query(snapshot_id="state-a", expression_context_id="same-call")
    q2 = query(
        snapshot_id="state-b",
        expression_context_id="same-call",
        instrument_id="instrument:ETHUSDT",
    )
    source1 = bars(q1, (10.0, 20.0))
    source2 = bars(q2, (30.0, 40.0))
    provider = MemoryProvider(
        {
            q1.snapshot_id: snapshot(q1, source1),
            q2.snapshot_id: snapshot(q2, source2),
        }
    )
    calls = {"count": 0}

    def counter(_bar, context):
        calls["count"] += 1
        value = context.state("counter", 0) + 1
        context.set_state("counter", value)
        return value

    counter.__pinelib_expression_identity__ = "test:stateful-cache-counter"

    runtime = request_session(provider)
    assert (
        _call(runtime, q1, 60 * 60_000, 120 * 60_000, sequence=0, expression=counter)
        == 2.0
    )
    assert (
        _call(runtime, q1, 60 * 60_000, 120 * 60_000, sequence=1, expression=counter)
        == 2.0
    )
    assert (
        _call(runtime, q2, 60 * 60_000, 120 * 60_000, sequence=2, expression=counter)
        == 2.0
    )
    assert calls["count"] == 4
    assert len(provider.calls) == 2


def test_append_snapshot_evaluates_only_delta_and_preserves_child_state():
    q1 = query(snapshot_id="base", expression_id="expr:counter")
    base_snapshot = snapshot(q1, bars(q1, (1.0, 2.0)))
    q2 = query(snapshot_id="append", expression_id="expr:counter")
    delta_bars = bars(q2, (3.0,), start_ms=2 * 60 * 60_000, revision=1)
    append_snapshot = snapshot(
        q2,
        delta_bars,
        revision=1,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=base_snapshot.content_hash,
    )
    provider = MemoryProvider({"base": base_snapshot, "append": append_snapshot})
    evaluations = []

    def counter(_bar, context):
        value = context.state("n", 0) + 1
        context.set_state("n", value)
        evaluations.append(value)
        return value

    counter.__pinelib_expression_identity__ = "test:append-state-counter"

    runtime = request_session(provider)
    assert (
        _call(runtime, q1, 60 * 60_000, 120 * 60_000, sequence=0, expression=counter)
        == 2.0
    )
    assert (
        _call(runtime, q2, 120 * 60_000, 180 * 60_000, sequence=1, expression=counter)
        == 3.0
    )
    assert evaluations == [1, 2, 3]
    dataset = runtime.requests.registry.lookup(
        q2.discovery_identity(ResultShape.scalar("float")), committed_only=True
    )
    assert dataset is not None
    assert [dataset.value(i) for i in range(3)] == [1.0, 2.0, 3.0]


def test_checkpoint_restores_request_registry_without_refetch():
    q = query(snapshot_id="checkpoint")
    provider = provider_for(q, bars(q, (7.0,)))
    runtime = request_session(provider)
    assert _call(runtime, q, 0, 60 * 60_000, sequence=0) == 7.0
    checkpoint = runtime.checkpoint().to_dict()

    restored = request_session(provider)
    restored.restore(checkpoint)
    before = len(provider.calls)
    assert _call(restored, q, 0, 60 * 60_000, sequence=1) == 7.0
    assert len(provider.calls) == before
    assert restored.requests.registry.dataset_count == 1


def test_request_cache_is_transactional_on_expression_failure_and_abort():
    q = query(snapshot_id="fault")
    provider = provider_for(q, bars(q, (1.0, 2.0)))
    runtime = request_session(provider)

    def fault(bar, context):
        context.set_state("seen", bar.number("close"))
        if bar.number("close") == 2.0:
            raise ValueError("injected")
        return bar.number("close")

    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(ValueError):
        tx.requests.security(
            q,
            fault,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=120 * 60_000,
        )
    assert (
        tx.requests.registry.lookup(q.discovery_identity(ResultShape.scalar("float")))
        is None
    )
    tx.abort()
    assert runtime.requests.registry.dataset_count == 0


def test_nested_request_policy_parent_identity_and_cycle_detection():
    outer = query(snapshot_id="outer", expression_id="expr:outer")
    inner = query(
        snapshot_id="inner",
        timeframe="15",
        expression_context_id="call:inner",
        expression_id="expr:inner",
    )

    def make_snapshot(request_query):
        value = 10.0 if request_query.snapshot_id == "outer" else 5.0
        return snapshot(request_query, bars(request_query, (value,)))

    provider = MemoryProvider({"outer": make_snapshot, "inner": make_snapshot})
    enabled = RequestPolicy(nested_requests="enabled")
    runtime = request_session(provider, request_policy=enabled)

    def outer_expression(_bar, context):
        return context.nested_security(
            inner, close_expression, ResultShape.scalar("float")
        )

    # Inner 15-minute close is not available at the beginning of the outer 60m bar;
    # lookahead_on makes the intended historical semantics explicit for this vector.
    inner_lookahead = query(
        snapshot_id="inner",
        timeframe="15",
        expression_context_id="call:inner",
        expression_id="expr:inner",
        lookahead=LookaheadMode.ON,
    )

    def outer_expression2(_bar, context):
        return context.nested_security(
            inner_lookahead, close_expression, ResultShape.scalar("float")
        )

    assert (
        _call(runtime, outer, 0, 60 * 60_000, sequence=0, expression=outer_expression2)
        == 5.0
    )
    assert runtime.requests.registry.dataset_count == 2

    disabled_runtime = request_session(provider)
    tx = disabled_runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError) as caught:
        tx.requests.security(
            outer,
            outer_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
        )
    assert caught.value.code == "PL1512"
    tx.abort()

    cycle_runtime = request_session(provider, request_policy=enabled)

    def recursive(_bar, context):
        return context.nested_security(outer, recursive, ResultShape.scalar("float"))

    tx = cycle_runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError) as caught:
        tx.requests.security(
            outer,
            recursive,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
        )
    assert caught.value.code == "PL1512"
    tx.abort()


def test_provider_identity_capabilities_and_snapshot_mutations_fail_closed():
    q = query(snapshot_id="cap")
    source = bars(q, (1.0,))
    sealed = snapshot(q, source)
    provider = MemoryProvider(
        {q.snapshot_id: sealed}, capabilities=("request.security_lower_tf",)
    )
    runtime = request_session(provider)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError) as caught:
        tx.requests.security(
            q,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
        )
    assert caught.value.code == "PL1500"
    tx.abort()

    wrong = copy.deepcopy(sealed.to_dict())
    wrong["snapshot_id"] = "other"
    # Re-seal hash so the model is valid but the query binding is wrong.
    body = {key: wrong[key] for key in wrong if key != "content_hash"}
    from pinelib.state.checkpoint import sha

    wrong["content_hash"] = sha(body)
    from pinelib.request import DataSnapshot

    wrong_snapshot = DataSnapshot.from_dict(wrong)
    provider2 = MemoryProvider({q.snapshot_id: wrong_snapshot})
    runtime2 = request_session(provider2)
    tx = runtime2.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(RequestProviderError) as caught:
        tx.requests.security(
            q,
            close_expression,
            ResultShape.scalar("float"),
            chart_open_ms=0,
            chart_close_ms=60 * 60_000,
        )
    assert caught.value.kind == ProviderErrorKind.REVISION
    tx.abort()
