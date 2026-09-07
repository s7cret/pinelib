"""Once uses the bar transaction boundary for historical fills and live ticks.

The control state has the same rollback lifetime as the documented var-bool
equivalent. Historical fill executions can also undergo rollback:
https://www.tradingview.com/pine-script-docs/language/execution-model/
https://www.tradingview.com/pine-script-docs/language/conditional-structures/
"""

import json

import pytest

from pinelib import CallbackFrame
from pinelib.errors import PineRuntimeError
from tests.test_language_scopes_once import session


def callback(s, bar, *, phase="ORDER_FILL_RECALC", realtime=False, final=True):
    return s.begin(CallbackFrame(phase, s.sequence + 1, bar_index=bar,
                                 realtime=realtime, final_tick=final, defer_bar_commit=True))


@pytest.mark.parametrize("realtime", [False, True])
@pytest.mark.parametrize("last_condition", [False, True])
@pytest.mark.parametrize("scoped", [False, True])
def test_once_completion_tracks_final_successful_callback_not_first_order_fill(realtime, last_condition, scoped):
    s = session()
    calls = []
    executions = []
    for tick, condition in enumerate((True, False, last_condition)):
        tx = callback(s, 0, phase="HISTORICAL_EVAL" if tick == 0 and not realtime else "ORDER_FILL_RECALC",
                      realtime=realtime, final=tick == 2)
        def body():
            for _ in range(3):
                if tx.once_v1("gate", lambda: calls.append(tick) or condition):
                    executions.append(tick)
                    n = tx.state("count", owner="test", schema_version="1", varip=True, initial=0)
                    tx.set_slot("count", n + 1, owner="test", varip=True)
        if scoped:
            tx.invoke_function_v1("written-callsite", body, {})
        else:
            body()
        tx.commit()
        with pytest.raises(PineRuntimeError, match="provisional"):
            s.checkpoint()
    assert executions == ([0, 2] if last_condition else [0])
    assert calls == ([0, 1, 1, 1, 2] if last_condition else [0, 1, 1, 1, 2, 2, 2])
    s.finalize_bar(0)
    saved = json.loads(json.dumps(s.checkpoint().to_dict()))
    restored = session()
    restored.restore(saved)
    for runtime in (s, restored):
        tx = callback(runtime, 1)
        def check():
            return tx.once_v1("gate", lambda: True)
        result = tx.invoke_function_v1("written-callsite", check, {}) if scoped else check()
        assert result is (not last_condition)
        assert tx.state("count", owner="test", schema_version="1", varip=True, initial=0) == (2 if last_condition else 1)
        tx.commit()
        runtime.finalize_bar(1)
    assert restored.state_hash == s.state_hash
    assert restored.semantic_state_hash == s.semantic_state_hash
    assert all(row["varip"] is False for row in s.slots.to_json() if row["owner"] == "ast2python.once.v1")


def test_aborted_historical_fill_does_not_complete_once_or_publish_bar():
    s = session()
    tx = callback(s, 0, phase="HISTORICAL_EVAL")
    assert not tx.once_v1("gate", lambda: False)
    tx.commit()
    s.finalize_bar(0)
    saved = s.checkpoint().to_dict()
    tx = callback(s, 1)
    assert tx.once_v1("gate", lambda: True)
    tx.abort()
    assert s.checkpoint().to_dict() == saved
    with pytest.raises(PineRuntimeError, match="provisional"):
        s.finalize_bar(1)
    tx = callback(s, 1)
    assert tx.once_v1("gate", lambda: True)
    tx.commit()
    s.finalize_bar(1)
    tx = callback(s, 2)
    assert not tx.once_v1("gate", lambda: 1 / 0)
    tx.abort()


def test_once_written_callsites_remain_independent_during_historical_fills():
    s = session()
    for tick in range(2):
        tx = callback(s, 0)
        def gate():
            return tx.once_v1("same-definition", lambda: True)
        assert tx.invoke_function_v1("A", gate, {}) is True
        assert tx.invoke_function_v1("A", gate, {}) is False
        assert tx.invoke_function_v1("B", gate, {}) is True
        tx.commit()
    s.finalize_bar(0)
    tx = callback(s, 1)
    def unreachable():
        return tx.once_v1("same-definition", lambda: 1 / 0)
    assert tx.invoke_function_v1("A", unreachable, {}) is False
    assert tx.invoke_function_v1("B", unreachable, {}) is False
    tx.abort()
