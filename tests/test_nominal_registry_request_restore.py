"""Parent admission validates fully resealed compiled request checkpoints.

These fixtures execute actual CompiledRequestExpression children. Recomputed
digests are integrity controls, not authority to declare enum members or schemas.
"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from pinelib import RuntimeSession, is_na, na
from pinelib.abi.compiled_request import CompiledRequestExpression, security_v1
from pinelib.errors import PineRuntimeError
from pinelib.reference.heap import PineEnumValue
from pinelib.request import RequestEngine, ResultShape
from pinelib.request.engine import RequestExpressionContext
from pinelib.runtime.compact_transcript import CompactRuntimeTranscript
from pinelib.runtime.metadata import TimeframeContext
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from pinelib.runtime.semantic import semantic_state_digest
from pinelib.runtime.transcript import RuntimeTranscript
from pinelib.state.checkpoint import RuntimeCheckpoint, canonical_json, from_portable, sha
from tests.test_compiled_requests import INSTRUMENT, Provider, begin
from tests.test_language_scopes_once import session as plain_session
from tests.test_nominal_registry_runtime import E, registry


class Child:
    evaluations = 0

    def __init__(self, runtime):
        self.runtime = runtime

    def value(self):
        Child.evaluations += 1
        self.runtime.declare_enum_v1("side", "var", lambda: self.runtime.enum_value_v1(E, "buy", 0), E)
        self.runtime.declare_scalar_v1("missing", "var", lambda: na, "float")
        return self.runtime.value_close


def evaluate(runtime, *, count=1):
    tx = begin(runtime, 0)
    children = {}
    for index in range(count):
        identity = "sha256:" + ("e" if index == 0 else "f") * 64
        expression = CompiledRequestExpression(tx, Child, "value", identity, ResultShape.scalar("float"))
        security_v1(tx, "EX:S", "5", expression, "site-" + str(index))
        children[identity] = expression._runtime
    tx.commit()
    return children


def fixture(version=6, *, full=True, count=1, policies=None, provider=None):
    runtime = RuntimeSession(
        plain_session(version).language, policies,
        instrument=INSTRUMENT, timeframe=TimeframeContext.parse("1"),
        request_provider=provider or Provider(), nominal_registry=registry(version),
    )
    runtime.commit_full_identity = full
    return runtime, evaluate(runtime, count=count)


def reseal_state(runtime, state, *, full=None):
    if full is None:
        full = state["transcript"]["schema_id"] == "openpine.runtime_transcript.v1"
    requests = RequestEngine(runtime.language, runtime.policies, runtime.requests.provider)
    requests.bind_parent_identity(runtime.identity_hash)
    requests.restore(state["requests"])
    digest = (sha({key: value for key, value in state.items() if key != "transcript"}) if full else
              semantic_state_digest(runtime.identity_hash, state["sequence"], runtime.series,
                                    runtime.slots, runtime.references, runtime.visuals, runtime.alerts, requests))
    entries = deepcopy(state["transcript"]["entries"])
    if entries:
        entries[-1]["state_hash"] = digest
    transcript = RuntimeTranscript() if full else CompactRuntimeTranscript()
    for entry in entries:
        transcript.append(entry)
    state["transcript"] = transcript.to_dict()
    return RuntimeCheckpoint.seal(runtime.identity_hash, state).to_dict()


def checkpoint_with(runtime, saved_child, *, identity=None):
    state = deepcopy(runtime.checkpoint().state)
    datasets = state["requests"]["registry"]["datasets"]
    dataset = next(row for row in datasets if identity is None or row["key"]["query"]["expression_id"] == identity)
    dataset["child_state"]["compiled-runtime"] = deepcopy(saved_child)
    dataset["content_hash"] = sha({key: value for key, value in dataset.items() if key != "content_hash"})
    return reseal_state(runtime, state)


def assert_atomic_rejection(runtime, checkpoint, match):
    original = runtime.checkpoint().to_dict()
    segments = tuple(getattr(runtime, key) for key in ("series", "slots", "references", "requests", "transcript"))
    calls, evaluations = runtime.requests.provider.calls, Child.evaluations
    with pytest.raises(PineRuntimeError, match=match):
        runtime.restore(checkpoint)
    assert runtime.checkpoint().to_dict() == original
    assert all(before is getattr(runtime, key) for before, key in zip(
        segments, ("series", "slots", "references", "requests", "transcript"), strict=True))
    assert runtime.requests.provider.calls == calls
    assert Child.evaluations == evaluations


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("parent_full", [False, True])
@pytest.mark.parametrize("child_full", [False, True])
def test_parent_admits_real_child_without_fetch_or_evaluation(version, parent_full, child_full):
    runtime, children = fixture(version, full=parent_full)
    child = next(iter(children.values()))
    saved = reseal_state(child, deepcopy(child.checkpoint().state), full=child_full)
    checkpoint = checkpoint_with(runtime, saved)
    calls, evaluations = runtime.requests.provider.calls, Child.evaluations
    runtime.restore(json.loads(json.dumps(checkpoint)))
    assert runtime.checkpoint().to_dict() == checkpoint
    assert runtime.requests.provider.calls == calls
    assert Child.evaluations == evaluations
    assert runtime.references.nominal_registry is runtime.nominal_registry


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("parent_full", [False, True])
@pytest.mark.parametrize("child_full", [False, True])
@pytest.mark.parametrize("member,ordinal", [("not_declared", 0), ("buy", 123), ("sell", 0)])
def test_fully_resealed_child_enum_forgery_rejects_before_parent_swap(version, parent_full, child_full, member, ordinal):
    runtime, children = fixture(version, full=parent_full)
    identity, child = next(iter(children.items()))
    child.series["side"].working = PineEnumValue(E, member, ordinal)
    saved = reseal_state(child, deepcopy(child.checkpoint().state), full=child_full)
    assert_atomic_rejection(runtime, checkpoint_with(runtime, saved, identity=identity), "enum")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("corruption", ["null", "wrong_identity", "wrong_source_metadata"])
def test_child_checkpoint_requires_exact_runtime_and_provider_metadata(version, corruption):
    runtime, children = fixture(version)
    child = next(iter(children.values()))
    saved = child.checkpoint().to_dict()
    if corruption == "null":
        saved = None
    elif corruption == "wrong_identity":
        saved = RuntimeCheckpoint.seal(runtime.identity_hash, saved["state"]).to_dict()
    else:
        # Identical data provider, different requested instrument metadata.
        forged = RuntimeSession(child.language, child.policies, inputs=child.inputs,
                                instrument=replace(child.instrument, mintick=0.5), timeframe=child.timeframe,
                                request_provider=child.requests.provider, nominal_registry=child.nominal_registry)
        saved = RuntimeCheckpoint.seal(forged.identity_hash, saved["state"]).to_dict()
    assert_atomic_rejection(runtime, checkpoint_with(runtime, saved), "checkpoint")


@pytest.mark.parametrize("version", [5, 6])
def test_late_second_child_failure_preserves_every_live_parent_segment(version):
    runtime, children = fixture(version, count=2)
    datasets = runtime.requests.registry.committed_datasets
    identity = datasets[-1].key.query.expression_id
    child = children[identity]
    child.series["side"].working = PineEnumValue(E, "forged", 0)
    saved = reseal_state(child, deepcopy(child.checkpoint().state))
    assert_atomic_rejection(runtime, checkpoint_with(runtime, saved, identity=identity), "enum")


def nested_fixture(version=6, *, wrappers=1, resource=None, forged=False):
    policies = RuntimePolicies(resource=resource or ResourcePolicy())
    runtime, children = fixture(version, policies=policies)
    leaf = next(iter(children.values()))
    if forged:
        leaf.series["side"].working = PineEnumValue(E, "forged", 0)
    saved = reseal_state(leaf, deepcopy(leaf.checkpoint().state))
    # Every wrapper is a real session with a real compiled request dataset.
    wrapper = runtime._new_compiled_request_runtime(INSTRUMENT, "5")
    wrapper.commit_full_identity = True
    evaluate(wrapper)
    for _ in range(wrappers):
        saved = checkpoint_with(wrapper, saved)
    return runtime, checkpoint_with(runtime, saved)


@pytest.mark.parametrize("version", [5, 6])
def test_recursive_child_checkpoint_is_validated_before_parent_swap(version):
    runtime, checkpoint = nested_fixture(version, wrappers=2, forged=True)
    assert_atomic_rejection(runtime, checkpoint, "enum")


@pytest.mark.parametrize("version", [5, 6])
def test_recursive_child_checkpoint_depth_boundary_and_cumulative_count(version):
    runtime, checkpoint = nested_fixture(version, wrappers=1, resource=ResourcePolicy(max_request_depth=1))
    runtime.restore(checkpoint)  # First child depth 0, second child depth 1.
    runtime, checkpoint = nested_fixture(version, wrappers=2, resource=ResourcePolicy(max_request_depth=1))
    assert_atomic_rejection(runtime, checkpoint, "limits")
    runtime, checkpoint = nested_fixture(version, wrappers=2, resource=ResourcePolicy(max_request_datasets=2))
    assert_atomic_rejection(runtime, checkpoint, "limits")


@pytest.mark.parametrize("version", [5, 6])
def test_recursive_child_checkpoint_byte_work_is_cumulative(version):
    runtime, checkpoint = nested_fixture(version, wrappers=2)
    cache_size = len(canonical_json(checkpoint["state"]["requests"]["registry"]))
    total_size, current = 0, checkpoint
    while current["state"]["requests"]["registry"]["datasets"]:
        current = current["state"]["requests"]["registry"]["datasets"][0]["child_state"]["compiled-runtime"]
        total_size += len(canonical_json(current))
    assert cache_size < total_size
    resource = ResourcePolicy(max_request_cache_bytes=(cache_size + total_size) // 2)
    runtime, checkpoint = nested_fixture(version, wrappers=2, resource=resource)
    assert_atomic_rejection(runtime, checkpoint, "limits")


@pytest.mark.parametrize("version", [5, 6])
def test_child_checkpoint_has_individual_state_byte_budget(version):
    runtime, children = fixture(version, policies=RuntimePolicies(resource=ResourcePolicy(max_request_state_bytes=12000)))
    child = next(iter(children.values()))
    tx = begin(child, child.sequence + 1)
    tx.set_slot("padding", "x" * 16000, owner="test")
    tx.commit()
    assert_atomic_rejection(runtime, checkpoint_with(runtime, child.checkpoint().to_dict()), "limits")


@pytest.mark.parametrize("version", [5, 6])
def test_empty_source_has_no_saved_runtime_and_generic_nested_name_is_not_interpreted(version):
    runtime, _ = fixture(version, provider=Provider(values=()))
    saved = runtime.checkpoint().to_dict()
    dataset = saved["state"]["requests"]["registry"]["datasets"][0]
    assert "compiled-runtime" not in dataset["child_state"]
    dataset["child_state"]["ordinary-state"] = {"compiled-runtime": {"any": "ordinary data"}}
    dataset["content_hash"] = sha({key: value for key, value in dataset.items() if key != "content_hash"})
    checkpoint = reseal_state(runtime, saved["state"])
    runtime.restore(checkpoint)
    assert runtime.checkpoint().to_dict() == checkpoint


@pytest.mark.parametrize("version", [5, 6])
def test_live_child_resume_accepts_canonical_na_decoded_by_request_context(version):
    runtime, _ = fixture(version)
    dataset = runtime.requests.registry.committed_datasets[0]
    context = RequestExpressionContext(runtime.requests, dataset.child_context, dataset.child_state, depth=0, stack=())
    context.is_last_bar, context.last_bar_index = True, 3
    decoded = context.state("compiled-runtime", None)
    assert is_na(decoded["state"]["series"]["missing"]["working"])
    tx = begin(runtime, runtime.sequence + 1)
    expression = CompiledRequestExpression(tx, Child, "value", dataset.key.query.expression_id, ResultShape.scalar("float"))
    expression.source = runtime.requests.provider.source("stock:S", "5")
    last = expression.source.bars[-1]
    bar = replace(last, open_time_ms=last.open_time_ms + 300000, close_time_ms=last.close_time_ms + 300000)
    context._bind(bar)
    assert expression(bar, context) == 30
    assert expression._runtime.sequence == 3
    assert all(is_na(value) for value in expression._runtime.series["missing"].committed)
    assert expression._runtime.nominal_registry is runtime.nominal_registry
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("transport", ["decoded-na", "tuple-history", "enum-protocol"])
def test_public_restore_retains_existing_portable_value_owner(version, transport):
    _, children = fixture(version)
    child = next(iter(children.values()))
    expected = child.checkpoint().to_dict()
    saved = deepcopy(expected)
    if transport == "decoded-na":
        saved = from_portable(saved)
    elif transport == "tuple-history":
        saved["state"]["series"]["missing"]["committed"] = tuple(saved["state"]["series"]["missing"]["committed"])
    else:
        saved["state"]["series"]["side"]["working"] = PineEnumValue(E, "buy", 0)
    child.restore(saved)
    assert child.checkpoint().to_dict() == expected


@pytest.mark.parametrize("version", [5, 6])
def test_live_child_resume_rejects_resealed_unknown_member(version):
    runtime, children = fixture(version)
    child = next(iter(children.values()))
    child.series["side"].working = PineEnumValue(E, "forged", 0)
    saved = reseal_state(child, deepcopy(child.checkpoint().state))
    dataset = runtime.requests.registry.committed_datasets[0]
    context = RequestExpressionContext(runtime.requests, dataset.child_context, {"compiled-runtime": saved}, depth=0, stack=())
    tx = begin(runtime, runtime.sequence + 1)
    expression = CompiledRequestExpression(tx, Child, "value", dataset.key.query.expression_id, ResultShape.scalar("float"))
    expression.source = runtime.requests.provider.source("stock:S", "5")
    before = Child.evaluations
    with pytest.raises(PineRuntimeError, match="enum"):
        expression(expression.source.bars[-1], context)
    assert Child.evaluations == before
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("field", ["language_hash", "policy_hash"])
def test_forged_child_context_metadata_cannot_authorize_saved_runtime(version, field):
    runtime, _ = fixture(version)
    state = deepcopy(runtime.checkpoint().state)
    dataset = state["requests"]["registry"]["datasets"][0]
    context = dataset["child_context"]
    context[field] = "sha256:" + "b" * 64
    context["content_hash"] = sha({key: value for key, value in context.items() if key != "content_hash"})
    dataset["content_hash"] = sha({key: value for key, value in dataset.items() if key != "content_hash"})
    assert_atomic_rejection(runtime, reseal_state(runtime, state), "source identity")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "\ud800", 10 ** 5000],
                         ids=["nan", "infinity", "invalid-unicode", "oversized-integer"])
def test_invalid_checkpoint_codec_input_has_a_runtime_error(value):
    runtime, _ = fixture()
    data = runtime.checkpoint().to_dict()
    data["invalid"] = value
    assert_atomic_rejection(runtime, data, "non-finite|not canonical")


@pytest.mark.parametrize("kind", ["cycle", "depth", "bytes"])
def test_hostile_checkpoint_input_is_bounded_before_recursive_codecs(kind):
    runtime, _ = fixture()
    data = runtime.checkpoint().to_dict()
    if kind == "cycle":
        data["cycle"] = data
    elif kind == "depth":
        value = []
        data["deep"] = value
        for _ in range(1500):
            child = []
            value.append(child)
            value = child
    else:
        data["huge"] = "x" * (runtime.policies.resource.max_checkpoint_bytes + 1)
    assert_atomic_rejection(runtime, data, "cycle|limits|byte limit")
