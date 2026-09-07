"""Hand-derived bounded RSI/MACD values; no generated expected-output files."""

from __future__ import annotations

import json

import pytest

from pinelib import CallbackFrame, is_na
from pinelib.abi import ta
from pinelib.errors import PineRuntimeError
from tests.stage3_helpers import session


# TradingView's RSI reference uses SMA-seeded RMA(gain)/RMA(loss), alpha=1/length.
# After the changes +2,-1,+3,-1,+3 and length=2, these ratios are 2,8,8/5,32/5.
@pytest.mark.parametrize("version", range(1, 7))
def test_rsi_matches_independent_gain_loss_arithmetic(version):
    runtime = session(version)
    actual = []
    for index, source in enumerate([10, 12, 11, 14, 13, 16]):
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
        actual.append(ta.rsi_v1(tx, "rsi", source, 2))
        tx.commit()
    assert all(is_na(value) for value in actual[:2])
    assert actual[2:] == pytest.approx([200 / 3, 800 / 9, 800 / 13, 3200 / 37])


@pytest.mark.parametrize("version", [4, 5, 6])
def test_rsi_intrabar_recalculation_abort_and_json_restore_use_committed_history(version):
    runtime = session(version)
    for index, source in enumerate([10, 12, 11]):
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
        ta.rsi_v1(tx, "rsi", source, 2)
        tx.commit()
    tx = runtime.begin(
        CallbackFrame("REALTIME_TICK", 3, realtime=True, final_tick=False, bar_index=3)
    )
    assert ta.rsi_v1(tx, "rsi", 14, 2) == pytest.approx(800 / 9)
    tx.commit()
    restored = session(version)
    restored.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    for candidate in [runtime, restored]:
        tx = candidate.begin(
            CallbackFrame(
                "REALTIME_TICK", 4, realtime=True, final_tick=False, bar_index=3, tick_index=1
            )
        )
        assert ta.rsi_v1(tx, "rsi", 13, 2) == pytest.approx(600 / 7)
        tx.abort()
        tx = candidate.begin(
            CallbackFrame(
                "REALTIME_TICK", 5, realtime=True, final_tick=True, bar_index=3, tick_index=2
            )
        )
        assert ta.rsi_v1(tx, "rsi", 9, 2) == pytest.approx(200 / 7)
        tx.commit()
        tx = candidate.begin(
            CallbackFrame("REALTIME_TICK", 6, realtime=True, final_tick=True, bar_index=4)
        )
        assert ta.rsi_v1(tx, "rsi", 10, 2) == pytest.approx(600 / 11)
        tx.commit()
    assert restored.state_hash == runtime.state_hash


@pytest.mark.parametrize("version", [4, 5, 6])
def test_macd_stable_baseline_then_price_change_matches_independent_ema_recurrence(version):
    # Six constant bars make both documented EMA seed conventions equal. This
    # checks MACD arithmetic/lifetime without claiming a warmup oracle result.
    runtime = session(version)
    for index in range(6):
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
        result = ta.macd_v1(tx, "macd", 100, 3, 5, 2)
        tx.commit()
    assert tuple(result) == (0.0, 0.0, 0.0)
    tx = runtime.begin(
        CallbackFrame("REALTIME_TICK", 6, realtime=True, final_tick=False, bar_index=6)
    )
    assert tuple(ta.macd_v1(tx, "macd", 104, 3, 5, 2)) == pytest.approx((2 / 3, 4 / 9, 2 / 9))
    tx.commit()
    restored = session(version)
    restored.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    for candidate in [runtime, restored]:
        tx = candidate.begin(
            CallbackFrame(
                "REALTIME_TICK", 7, realtime=True, final_tick=False, bar_index=6, tick_index=1
            )
        )
        assert tuple(ta.macd_v1(tx, "macd", 94, 3, 5, 2)) == pytest.approx((-1, -2 / 3, -1 / 3))
        tx.abort()
        tx = candidate.begin(
            CallbackFrame(
                "REALTIME_TICK", 8, realtime=True, final_tick=True, bar_index=6, tick_index=2
            )
        )
        assert tuple(ta.macd_v1(tx, "macd", 106, 3, 5, 2)) == pytest.approx((1, 2 / 3, 1 / 3))
        tx.commit()
    assert restored.state_hash == runtime.state_hash


@pytest.mark.parametrize("bad_length", [0, -1, True, 2.5, "2"])
def test_stateful_numeric_lengths_do_not_accept_coercion(bad_length):
    for function, lengths in [(ta.rsi_v1, [bad_length]), (ta.macd_v1, [bad_length, 5, 2])]:
        runtime = session()
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
        with pytest.raises(PineRuntimeError):
            function(tx, "length", 10, *lengths)
        tx.abort()


@pytest.mark.parametrize("name", ["rsi", "macd"])
def test_stateful_lengths_cannot_change_at_an_existing_callsite(name):
    runtime = session()
    function = ta.rsi_v1 if name == "rsi" else ta.macd_v1
    lengths = [2] if name == "rsi" else [3, 5, 2]
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    function(tx, "length", 10, *lengths)
    tx.commit()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 1, bar_index=1))
    with pytest.raises(PineRuntimeError):
        function(tx, "length", 12, lengths[0] + 1, *lengths[1:])
    tx.abort()
