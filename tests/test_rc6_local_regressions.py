from __future__ import annotations

import copy

import pytest

from pinelib import CallbackFrame, RuntimePolicies
from pinelib.errors import PineRuntimeError
from pinelib.request import DataFinality, ResultShape, SnapshotMode
from pinelib.runtime import InstrumentContext, RuntimeSession
from pinelib.state.checkpoint import RuntimeCheckpoint, from_portable
from tests.stage3_helpers import language
from tests.stage4_helpers import (
    MemoryProvider,
    bars,
    query,
    replace_query,
    request_session,
    snapshot,
)

FLOAT = ResultShape.scalar("float")
HOUR_MS = 60 * 60_000


def equivalent_close_a(bar, _context):
    return bar.number("close")


def equivalent_close_b(bar, _context):
    return bar.number("close")


def evaluator_five(_bar, _context):
    return 5.0


def evaluator_nine_ninety_nine(_bar, _context):
    return 999.0


def _evaluate(
    runtime,
    request_query,
    expression,
    sequence: int,
    *,
    chart_open_ms: int,
    chart_close_ms: int,
):
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", sequence))
    value = tx.requests.security(
        request_query,
        expression,
        FLOAT,
        chart_open_ms=chart_open_ms,
        chart_close_ms=chart_close_ms,
    )
    tx.commit()
    return value


def _instrument(symbol: str) -> InstrumentContext:
    return InstrumentContext(
        symbol,
        f"BINANCE:{symbol}",
        "BINANCE",
        "USDT",
        symbol.removesuffix("USDT"),
        "UTC",
        "crypto",
        0.01,
    )


def test_append_resume_accepts_equivalent_evaluator_and_matches_uninterrupted() -> None:
    base_query = query(snapshot_id="append-base")
    append_query = query(snapshot_id="append-next")
    base_snapshot = snapshot(
        base_query,
        bars(base_query, (1.0,), revision=1),
        revision=1,
    )
    append_snapshot = snapshot(
        append_query,
        bars(
            append_query,
            (2.0,),
            start_ms=HOUR_MS,
            finalities=(DataFinality.FINAL,),
            revision=2,
        ),
        revision=2,
        mode=SnapshotMode.APPEND,
        parent_snapshot_hash=base_snapshot.content_hash,
    )

    def make_provider() -> MemoryProvider:
        return MemoryProvider(
            {
                base_query.snapshot_id: base_snapshot,
                append_query.snapshot_id: append_snapshot,
            }
        )

    uninterrupted = request_session(make_provider())
    assert (
        _evaluate(
            uninterrupted,
            base_query,
            equivalent_close_a,
            0,
            chart_open_ms=0,
            chart_close_ms=HOUR_MS,
        )
        == 1.0
    )
    assert (
        _evaluate(
            uninterrupted,
            append_query,
            equivalent_close_a,
            1,
            chart_open_ms=HOUR_MS,
            chart_close_ms=2 * HOUR_MS,
        )
        == 2.0
    )

    before_resume = request_session(make_provider())
    _evaluate(
        before_resume,
        base_query,
        equivalent_close_a,
        0,
        chart_open_ms=0,
        chart_close_ms=HOUR_MS,
    )
    checkpoint = before_resume.checkpoint().to_dict()

    resumed = request_session(make_provider())
    resumed.restore(checkpoint)
    assert (
        _evaluate(
            resumed,
            append_query,
            equivalent_close_b,
            1,
            chart_open_ms=HOUR_MS,
            chart_close_ms=2 * HOUR_MS,
        )
        == 2.0
    )
    assert resumed.checkpoint().to_dict() == uninterrupted.checkpoint().to_dict()


def test_provider_replacement_is_rejected_at_assignment_boundary() -> None:
    request_query = query(snapshot_id="provider-admission")
    original = MemoryProvider(
        {
            request_query.snapshot_id: snapshot(
                request_query, bars(request_query, (1.0,))
            )
        }
    )
    replacement = MemoryProvider(
        {
            request_query.snapshot_id: snapshot(
                request_query, bars(request_query, (9.0,))
            )
        }
    )
    runtime = request_session(original)

    with pytest.raises(PineRuntimeError):
        runtime.requests.provider = replacement

    assert runtime.requests.provider is original


def test_restore_rejects_request_registry_from_different_parent_runtime() -> None:
    request_query = query(snapshot_id="runtime-parent")
    sealed = snapshot(request_query, bars(request_query, (1.0,)))
    provider = MemoryProvider({request_query.snapshot_id: sealed})

    runtime_a = RuntimeSession(
        language(6),
        RuntimePolicies(),
        instrument=_instrument("BTCUSDT"),
        request_provider=provider,
    )
    _evaluate(
        runtime_a,
        request_query,
        equivalent_close_a,
        0,
        chart_open_ms=0,
        chart_close_ms=HOUR_MS,
    )
    state_a = from_portable(runtime_a.checkpoint().state)
    assert isinstance(state_a, dict)

    runtime_b = RuntimeSession(
        language(6),
        RuntimePolicies(),
        instrument=_instrument("ETHUSDT"),
        request_provider=provider,
    )
    state_b = from_portable(runtime_b.checkpoint().state)
    assert isinstance(state_b, dict)
    grafted = copy.deepcopy(state_b)
    grafted["requests"] = copy.deepcopy(state_a["requests"])
    resealed = RuntimeCheckpoint.seal(runtime_b.identity_hash, grafted)

    with pytest.raises(PineRuntimeError):
        runtime_b.restore(resealed.to_dict())


def test_security_alignment_failure_rolls_back_registration_state_and_budget() -> None:
    request_query = query(snapshot_id="security-rollback")
    provider = MemoryProvider(
        {
            request_query.snapshot_id: snapshot(
                request_query, bars(request_query, (1.0,))
            )
        }
    )
    runtime = request_session(provider)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))

    def stateful_expression(bar, context):
        context.set_state("state:seen", True)
        return bar.number("close")

    with pytest.raises(PineRuntimeError):
        tx.requests.security(
            request_query,
            stateful_expression,
            FLOAT,
            chart_open_ms=HOUR_MS,
            chart_close_ms=0,
        )

    discovery_id = request_query.discovery_identity(FLOAT)
    assert tx.requests.registry.lookup(discovery_id) is None
    assert tx.requests._evaluations == 0
    assert tx.requests._working_evaluators == {}
    assert tx.requests._working_static_contexts == {}
    assert tx.requests._working_callables == {}
    tx.abort()


def test_restore_rejects_changed_implicit_evaluator_for_cached_request() -> None:
    request_query = query(snapshot_id="evaluator-resume")
    sealed = snapshot(request_query, bars(request_query, (1.0,)))

    runtime = request_session(MemoryProvider({request_query.snapshot_id: sealed}))
    assert (
        _evaluate(
            runtime,
            request_query,
            evaluator_five,
            0,
            chart_open_ms=0,
            chart_close_ms=HOUR_MS,
        )
        == 5.0
    )
    checkpoint = runtime.checkpoint().to_dict()

    resumed = request_session(MemoryProvider({request_query.snapshot_id: sealed}))
    resumed.restore(checkpoint)
    tx = resumed.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    with pytest.raises(PineRuntimeError):
        tx.requests.security(
            request_query,
            evaluator_nine_ninety_nine,
            FLOAT,
            chart_open_ms=0,
            chart_close_ms=HOUR_MS,
        )
    tx.abort()


def test_v5_static_context_binding_survives_checkpoint_restore() -> None:
    btc = query(
        version=5,
        dynamic=False,
        snapshot_id="static-btc",
        expression_context_id="call:static",
    )
    eth = replace_query(
        btc,
        instrument_id="instrument:ETHUSDT",
        symbol="ETHUSDT",
        snapshot_id="static-eth",
    )
    provider = MemoryProvider(
        {
            btc.snapshot_id: snapshot(btc, bars(btc, (1.0,))),
            eth.snapshot_id: snapshot(eth, bars(eth, (2.0,))),
        }
    )
    runtime = request_session(provider, version=5)
    _evaluate(
        runtime,
        btc,
        equivalent_close_a,
        0,
        chart_open_ms=0,
        chart_close_ms=HOUR_MS,
    )

    resumed = request_session(provider, version=5)
    resumed.restore(runtime.checkpoint().to_dict())
    tx = resumed.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    with pytest.raises(PineRuntimeError):
        tx.requests.security(
            eth,
            equivalent_close_a,
            FLOAT,
            chart_open_ms=0,
            chart_close_ms=HOUR_MS,
        )
    tx.abort()
