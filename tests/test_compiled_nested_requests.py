"""Nested compiled evaluators share the outer engine's atomic cache and budgets."""

import json
from dataclasses import replace

import pytest

from pinelib import is_na
from pinelib.abi.compiled_request import (
    _ACTIVE_CHILD,
    CompiledRequestExpression,
    security_v1,
)
from pinelib.abi.ta import sma_v1
from pinelib.errors import PineRuntimeError
from pinelib.request import ResultShape
from pinelib.runtime.policies import RuntimePolicies
from tests.test_compiled_requests import Provider, begin, runtime


class Script:
    def __init__(self, runtime):
        self.runtime = runtime

    def outer(self):
        expression = CompiledRequestExpression(
            self.runtime,
            Script,
            "inner",
            "sha256:" + "2" * 64,
            ResultShape.scalar("float"),
        )
        # These inherit EX:S/5 from the outer request, not the parent chart EX:S/1.
        return security_v1(self.runtime, "", "", expression, "inner")

    def inner(self):
        return sma_v1(self.runtime, "sma", self.runtime.value_close, 2)


def policies(enabled=True):
    base = RuntimePolicies()
    return replace(
        base,
        request=replace(
            base.request, nested_requests="enabled" if enabled else "disabled"
        ),
    )


def evaluate(session, index):
    tx = begin(session, index)
    try:
        expr = CompiledRequestExpression(
            tx, Script, "outer", "sha256:" + "1" * 64, ResultShape.scalar("float")
        )
        value = security_v1(tx, "EX:S", "5", expr, "outer")
        tx.commit()
        return value
    except Exception:
        if not tx.closed:
            tx.abort()
        raise


def test_nested_cache_is_shared_checkpointable_and_not_recomputed_each_chart_bar():
    provider = Provider()
    whole = runtime(provider, policies=policies())
    output = [evaluate(whole, index) for index in range(15)]
    assert is_na(output[8]) and output[9] == 15 and output[14] == 25
    assert provider.calls == 2  # one fetch per child dataset, not per chart bar
    assert whole.requests.registry.dataset_count == 2
    partial = runtime(Provider(), policies=policies())
    for index in range(7):
        evaluate(partial, index)
    checkpoint = json.loads(json.dumps(partial.checkpoint().to_dict()))
    restored_provider = Provider()
    restored = runtime(restored_provider, policies=policies())
    restored.restore(checkpoint)
    assert [evaluate(restored, index) for index in range(7, 15)] == output[7:]
    assert restored_provider.calls == 0
    assert restored.semantic_state_hash == whole.semantic_state_hash
    assert restored.state_hash == whole.state_hash
    assert _ACTIVE_CHILD.get() is None


def test_disabled_nested_policy_rolls_back_every_staged_dataset_and_context():
    session = runtime(Provider(), policies=policies(False))
    with pytest.raises(PineRuntimeError, match="nested requests are disabled"):
        evaluate(session, 0)
    assert session.requests.registry.dataset_count == 0
    assert _ACTIVE_CHILD.get() is None
    # A later independent session must not inherit the failed evaluation's context.
    clean = runtime(Provider(), policies=policies())
    assert is_na(evaluate(clean, 0))
    assert clean.requests.registry.dataset_count == 2
