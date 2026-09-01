from __future__ import annotations

import math
import random

import pytest

from pinelib.abi import ta as abi
from pinelib.core import is_na
from pinelib.errors import PineRuntimeError
from pinelib.runtime import CallbackFrame
from pinelib.ta.types import BandsResult, DmiResult, MacdResult, SupertrendResult
from tests.stage3_helpers import session


def rollback_sensitive_state(runtime):
    return {
        key: value
        for key, value in runtime.checkpoint().state.items()
        if key not in {"sequence", "transcript"}
    }


def run(values, function, *args, state_id="state"):
    runtime = session()
    output = []
    for index, value in enumerate(values):
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
        output.append(function(tx, state_id, value, *args))
        tx.commit()
    return output, runtime


def test_moving_averages_and_warmup_boundaries():
    values = [1, 2, 3, 4, 5]
    sma, _ = run(values, abi.sma_v1, 3)
    ema, _ = run(values, abi.ema_v1, 3)
    wma, _ = run(values, abi.wma_v1, 3)
    assert list(map(is_na, sma[:2])) == [True, True]
    assert sma[2:] == [2.0, 3.0, 4.0]
    assert ema[2:] == [2.0, 3.0, 4.0]
    assert wma[2] == pytest.approx(14 / 6)
    swma, _ = run(values, abi.swma_v1)
    assert is_na(swma[2]) and swma[3] == pytest.approx(2.5)
    alma, _ = run(values, abi.alma_v1, 3, 0.85, 6.0)
    hma, _ = run(values, abi.hma_v1, 3)
    assert not is_na(alma[-1]) and not is_na(hma[-1])


def test_streaming_sma_wma_stdev_match_slow_references_randomized():
    rng = random.Random(20260830)
    values = [rng.uniform(-10, 10) for _ in range(100)]
    length = 7
    sma_values, _ = run(values, abi.sma_v1, length)
    wma_values, _ = run(values, abi.wma_v1, length)
    stdev_values, _ = run(values, abi.stdev_v1, length, True)
    for index in range(length - 1, len(values)):
        window = values[index - length + 1 : index + 1]
        assert sma_values[index] == pytest.approx(sum(window) / length)
        expected_wma = sum((i + 1) * value for i, value in enumerate(window)) / sum(
            range(1, length + 1)
        )
        assert wma_values[index] == pytest.approx(expected_wma)
        mean = sum(window) / length
        expected_stdev = math.sqrt(
            sum((value - mean) ** 2 for value in window) / length
        )
        assert stdev_values[index] == pytest.approx(expected_stdev)


def test_momentum_tuple_order_and_state_isolation():
    runtime = session()
    macd_values = []
    rsi_values = []
    for index, value in enumerate(range(1, 20)):
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
        macd_values.append(abi.macd_v1(tx, "macd:A", value, 3, 5, 2))
        rsi_values.append(abi.rsi_v1(tx, "rsi:A", value, 3))
        tx.commit()
    assert isinstance(macd_values[-1], MacdResult)
    assert len(macd_values[-1]) == 3
    assert rsi_values[-1] == 100.0
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 20, bar_index=20))
    with pytest.raises(PineRuntimeError):
        abi.ema_v1(tx, "rsi:A", 1, 3)
    tx.abort()


def test_volatility_trend_and_tuple_types():
    runtime = session()
    last = None
    for index in range(20):
        close = 100 + index * 0.5
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
        bands = abi.bb_v1(tx, "bb", close, 5, 2.0)
        keltner = abi.kc_v1(tx, "kc", close, close + 1, close - 1, close, 5, 1.5)
        dmi = abi.dmi_v1(tx, "dmi", close + 1, close - 1, close, 5, 3)
        supertrend = abi.supertrend_v1(tx, "st", close + 1, close - 1, close, 2.0, 5)
        sar = abi.sar_v1(tx, "sar", close + 1, close - 1, 0.02, 0.02, 0.2)
        tx.commit()
        last = (bands, keltner, dmi, supertrend, sar)
    assert isinstance(last[0], BandsResult)
    assert isinstance(last[1], BandsResult)
    assert isinstance(last[2], DmiResult)
    assert isinstance(last[3], SupertrendResult)
    assert not is_na(last[0].basis)
    assert not is_na(last[4])


def test_statistics_volume_and_condition_history():
    runtime = session()
    outputs = []
    for index, value in enumerate([1, 2, 3, 4, 5, 6]):
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
        outputs.append(
            {
                "corr": abi.correlation_v1(tx, "corr", value, value * 2, 3),
                "linreg": abi.linreg_v1(tx, "lin", value, 3, 0),
                "median": abi.median_v1(tx, "med", value, 3),
                "mode": abi.mode_v1(tx, "mode", value % 2, 3),
                "rank": abi.percentrank_v1(tx, "rank", value, 3),
                "valuewhen": abi.valuewhen_v1(tx, "vw", value % 2 == 0, value, 1),
                "barssince": abi.barssince_v1(tx, "bs", value == 3),
                "obv": abi.obv_v1(tx, "obv", value, 10),
                "vwap": abi.vwap_v1(tx, "vwap", value, 10, value == 4),
                "cum": abi.cum_v1(tx, "cum", value),
                "cci": abi.cci_v1(tx, "cci", value + 1, value - 1, value, 3),
                "mfi": abi.mfi_v1(tx, "mfi", value + 1, value - 1, value, 10, 3),
            }
        )
        tx.commit()
    assert outputs[-1]["corr"] == pytest.approx(1.0)
    assert outputs[-1]["linreg"] == pytest.approx(6.0)
    assert outputs[-1]["median"] == 5
    assert outputs[-1]["valuewhen"] == 4
    assert outputs[-1]["barssince"] == 3
    assert outputs[-1]["cum"] == 21
    assert not is_na(outputs[-1]["cci"])
    assert not is_na(outputs[-1]["mfi"])


def test_checkpoint_split_equals_uninterrupted_for_stateful_kernels():
    values = list(range(1, 20))

    def execute(runtime, start, stop):
        out = []
        for index in range(start, stop):
            value = values[index]
            tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
            out.append(
                (abi.ema_v1(tx, "ema", value, 5), abi.rsi_v1(tx, "rsi", value, 5))
            )
            tx.commit()
        return out

    continuous = session()
    continuous_output = execute(continuous, 0, len(values))
    split = session()
    first = execute(split, 0, 9)
    checkpoint = split.checkpoint().to_dict()
    restored = session()
    restored.restore(checkpoint)
    second = execute(restored, 9, len(values))
    assert first + second == continuous_output
    assert restored.state_hash == continuous.state_hash


def test_fault_rollback_discards_ta_mutation():
    runtime = session()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    abi.sma_v1(tx, "sma", 1, 2)
    tx.commit()
    before = rollback_sensitive_state(runtime)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    abi.sma_v1(tx, "sma", 100, 2)
    tx.abort()
    assert rollback_sensitive_state(runtime) == before
    assert runtime.sequence == 1
    assert runtime.transcript.entries[-1]["committed"] is False
