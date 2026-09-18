"""Stage 2.7 runtime matrix: shared loop budget and once fill/rollback."""

from __future__ import annotations

import json

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from tests.test_language_scopes_once import begin, session
from tests.test_once_fill_recalculation import callback


def test_stage27_nested_loops_share_iteration_budget():
    runtime = session(policies=RuntimePolicies(resource=ResourcePolicy(max_loop_iterations=5)))
    tx = begin(runtime, 0)
    with pytest.raises(PineRuntimeError, match="budget"):
        for _ in tx.range_v1(0, lambda: 3):
            tx.consume_loop_iteration_v1()
            for _ in tx.range_v1(0, lambda: 3):
                tx.consume_loop_iteration_v1()
    tx.abort()


def test_stage27_aborted_fill_does_not_complete_once():
    runtime = session()
    tx = callback(runtime, 0, phase="HISTORICAL_EVAL")
    assert tx.once_v1("gate", lambda: False) is False
    tx.commit()
    runtime.finalize_bar(0)
    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    tx = callback(runtime, 1)
    assert tx.once_v1("gate", lambda: True) is True
    tx.abort()
    assert runtime.checkpoint().to_dict() == saved
    tx = callback(runtime, 1)
    assert tx.once_v1("gate", lambda: True) is True
    tx.commit()
    runtime.finalize_bar(1)
    restored = session()
    restored.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    tx = callback(restored, 2)
    assert tx.once_v1("gate", lambda: True) is False
    tx.commit()
    restored.finalize_bar(2)


def test_stage27_once_slot_is_not_silently_varip():
    runtime = session()
    tx = begin(runtime, 0)
    assert tx.once_v1("gate", lambda: True) is True
    tx.commit()
    rows = [row for row in runtime.slots.to_json() if row.get("owner") == "ast2python.once.v1"]
    assert rows
    assert all(row["varip"] is False for row in rows)
