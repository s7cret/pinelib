"""Independent expression contexts, transactionality and portable checkpoint tests."""

import json
from dataclasses import replace

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na
from pinelib.abi.compiled_request import (
    CompiledRequestExpression,
    security_lower_tf_v1,
    security_v1,
)
from pinelib.abi.ta import sma_v1
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_values
from pinelib.request import CanonicalBar, DataFinality, ResultShape
from pinelib.request.snapshots import RequestSource, SnapshotRequestProvider
from pinelib.runtime.metadata import BarValues, InstrumentContext, TimeframeContext
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies

INSTRUMENT = InstrumentContext("S", "EX:S", "EX", "USD", "S", "UTC", "stock", 0.01)


class Provider(SnapshotRequestProvider):
    def __init__(self, values=(10, 20, 30), period="5"):
        self.calls = 0
        step = int(period) * 60000
        bars = tuple(
            CanonicalBar(
                "stock:S",
                period,
                i * step,
                (i + 1) * step,
                str(v),
                str(v + 1),
                str(v - 1),
                str(v),
                "1",
                DataFinality.FINAL,
                0,
            )
            for i, v in enumerate(values)
        )
        super().__init__(
            (RequestSource("stock:S", INSTRUMENT, "stock", period, bars, "sha256:" + "d" * 64),)
        )

    def fetch(self, q):
        self.calls += 1
        return super().fetch(q)


class Script:
    evaluations = 0

    def __init__(self, runtime):
        self.runtime = runtime

    def average(self):
        Script.evaluations += 1
        return sma_v1(self.runtime, "sma", self.runtime.value_close, 2)

    def close(self):
        return self.runtime.value_close

    def pair(self):
        return (self.runtime.value_close, self.runtime.value_open)

    def boolean(self):
        return self.runtime.value_close > 0


def runtime(provider, version=6, period="1", policies=None):
    r = RuntimeSession(
        RuntimeLanguageContext(
            version,
            "test",
            f"pine-v{version}",
            "sha256:" + "a" * 64,
            "compiler_annotation",
        ),
        policies,
        instrument=INSTRUMENT,
        timeframe=TimeframeContext.parse(period),
        request_provider=provider,
    )
    r.commit_full_identity = False
    return r


def begin(r, i, *, period=60000, realtime=False):
    return r.begin(
        CallbackFrame(
            "REALTIME_TICK" if realtime else "HISTORICAL_EVAL",
            i,
            bar_index=i,
            last_bar_index=14,
            realtime=realtime,
        ),
        values=BarValues(100, 101, 99, 100, 1, i * period, (i + 1) * period - 1),
    )


def expression(tx, method="average", shape=None):
    return CompiledRequestExpression(
        tx,
        Script,
        method,
        "sha256:"
        + {"average": "1", "close": "2", "pair": "3", "boolean": "4"}[method] * 64,
        shape or ResultShape.scalar("float"),
    )


def evaluate(r, i, **kwargs):
    tx = begin(r, i)
    value = security_v1(tx, "EX:S", "5", expression(tx), "site", **kwargs)
    tx.commit()
    return value


def test_child_ta_cache_and_checkpoint_resume_match_uninterrupted_hashes():
    Script.evaluations = 0
    provider = Provider()
    whole = runtime(provider)
    output = [evaluate(whole, i) for i in range(15)]
    assert is_na(output[8]) and output[9] == 15 and output[14] == 25
    assert Script.evaluations == 3 and provider.calls == 1
    split = runtime(Provider())
    for i in range(7):
        evaluate(split, i)
    saved = json.loads(json.dumps(split.checkpoint().to_dict()))
    resumed_provider = Provider()
    restored = runtime(resumed_provider)
    restored.restore(saved)
    before = Script.evaluations
    suffix = [evaluate(restored, i) for i in range(7, 15)]
    assert suffix == output[7:]
    assert Script.evaluations == before and resumed_provider.calls == 0
    assert restored.state_hash == whole.state_hash
    assert restored.semantic_state_hash == whole.semantic_state_hash
    assert restored.transcript.content_hash == whole.transcript.content_hash


def test_abort_does_not_publish_requested_state():
    p = Provider()
    r = runtime(p)
    tx = begin(r, 0)
    security_v1(tx, "EX:S", "5", expression(tx), "site")
    tx.abort()
    assert r.requests.registry.dataset_count == 0 and r.sequence == -1
    evaluate(r, 0)
    assert r.requests.registry.dataset_count == 1 and p.calls == 2


@pytest.mark.parametrize("tuple_result", [False, True])
def test_lower_arrays_preserve_previous_handles_and_checkpoint_values(tuple_result):
    r = runtime(Provider(tuple(range(15)), "1"), period="5")
    method = "pair" if tuple_result else "close"
    shape = (
        ResultShape.tuple_of(ResultShape.scalar("float"), ResultShape.scalar("float"))
        if tuple_result
        else ResultShape.scalar("float")
    )
    prior = []
    for i in range(3):
        tx = begin(r, i, period=300000)
        handle = security_lower_tf_v1(
            tx, "EX:S", "1", expression(tx, method, shape), "site"
        )
        another = security_lower_tf_v1(
            tx, "EX:S", "1", expression(tx, method, shape), "site"
        )
        assert handle != another
        tx.commit()
        handles = handle if tuple_result else (handle,)
        assert all(
            array_values(r.references, h)
            == tuple(map(float, range(i * 5, (i + 1) * 5)))
            for h in handles
        )
        prior.extend((h, array_values(r.references, h)) for h in handles)
    restored = runtime(Provider(tuple(range(15)), "1"), period="5")
    restored.restore(json.loads(json.dumps(r.checkpoint().to_dict())))
    assert all(array_values(restored.references, h) == v for h, v in prior)
    assert r.state_hash == restored.state_hash


@pytest.mark.parametrize("version", [5, 6])
def test_bool_gap_obeys_version_rules(version):
    r = runtime(Provider(), version=version)
    tx = begin(r, 0)
    value = security_v1(
        tx, "EX:S", "5", expression(tx, "boolean", ResultShape.scalar("bool")), "site"
    )
    assert (value is False) if version == 6 else is_na(value)
    tx.commit()


def test_snapshot_identity_includes_values_and_metadata():
    p = Provider()
    source = p.source("EX:S", "5")
    other = replace(source, instrument=replace(INSTRUMENT, pointvalue=10))
    assert source.content_hash != other.content_hash
    assert (
        p.descriptor.provider_id
        != SnapshotRequestProvider((other,)).descriptor.provider_id
    )
    with pytest.raises(PineRuntimeError, match="identity"):
        runtime(Provider((11, 21, 31))).restore(runtime(p).checkpoint().to_dict())


def test_missing_preload_is_not_an_invalid_symbol():
    r = runtime(Provider())
    tx = begin(r, 0)
    with pytest.raises(PineRuntimeError, match="not preloaded"):
        security_v1(
            tx, "MISSING", "5", expression(tx), "site", ignore_invalid_symbol=True
        )
    tx.abort()


def test_no_live_future_values_from_historical_final_preloads():
    r = runtime(Provider())
    evaluate(r, 0)
    tx = begin(r, 1, realtime=True)
    with pytest.raises(PineRuntimeError, match="live revisions"):
        security_v1(tx, "EX:S", "5", expression(tx), "site")
    tx.abort()


def test_intrabar_budget_enforced_before_array_publication():
    r = runtime(
        Provider(tuple(range(15)), "1"),
        period="5",
        policies=RuntimePolicies(resource=ResourcePolicy(max_intrabars_per_bar=3)),
    )
    tx = begin(r, 0, period=300000)
    with pytest.raises(PineRuntimeError, match="intrabar limit"):
        security_lower_tf_v1(tx, "EX:S", "1", expression(tx, "close"), "site")
    tx.abort()
    assert r.requests.registry.dataset_count == 0


@pytest.mark.parametrize("count", [True, 0, -1, 1.5, 250001])
def test_bad_calc_bars_count_does_not_evaluate(count):
    p = Provider()
    r = runtime(p)
    tx = begin(r, 0)
    with pytest.raises(PineRuntimeError):
        security_v1(tx, "EX:S", "5", expression(tx), "site", calc_bars_count=count)
    tx.abort()
    assert p.calls == 0


def test_calc_bars_count_limits_child_history():
    r = runtime(Provider())
    values = [evaluate(r, i, calc_bars_count=2) for i in range(15)]
    assert is_na(values[9]) and values[14] == 25
    dataset = r.requests.registry.committed_datasets[0]
    assert len(dataset.evaluated_bars) == 2
    assert dataset.child_state["compiled-runtime"]["state"]["sequence"] == 1


@pytest.mark.parametrize("tuple_result", [False, True])
def test_invalid_lower_tf_is_na_not_valid_empty_array(tuple_result):
    r = runtime(Provider())
    tx = begin(r, 0)
    shape = (
        ResultShape.tuple_of(ResultShape.scalar("float"), ResultShape.scalar("float"))
        if tuple_result
        else ResultShape.scalar("float")
    )
    value = security_lower_tf_v1(
        tx,
        "EX:S",
        "5",
        expression(tx, "pair" if tuple_result else "close", shape),
        "invalid",
        ignore_invalid_timeframe=True,
    )
    assert all(is_na(v) for v in value) if tuple_result else is_na(value)
    tx.commit()
    assert r.requests.registry.dataset_count == 0


def test_missing_intrabars_are_empty_array():
    r = runtime(Provider((), "1"), period="5")
    tx = begin(r, 0, period=300000)
    handle = security_lower_tf_v1(tx, "EX:S", "1", expression(tx, "close"), "empty")
    tx.commit()
    assert not is_na(handle) and array_values(r.references, handle) == ()
