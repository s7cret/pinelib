"""Analytical degeneracies and state-admission invariants, not a TV parity oracle."""

import math

import pytest

from pinelib import CallbackFrame
from pinelib.core import is_na, na
from pinelib.errors import PineRuntimeError
from pinelib.ta import kernels as k
from tests.stage3_helpers import session


def run(fn, rows, *args, version=6):
    runtime = session(version)
    out = []
    for i, row in enumerate(rows):
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", i))
        out.append(fn(tx, "s", *(row if isinstance(row, tuple) else (row,)), *args))
        tx.commit()
    return out


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6])
def test_volume_weighted_mean_has_explicit_weights_and_missing_policy(version):
    results = run(k.vwma, [(2, 1), (na, 9), (4, 3), (8, 2)], 2, version=version)
    assert all(is_na(x) for x in results[:2])
    assert results[2:] == [14 / 4, 28 / 5]
    assert is_na(run(k.vwma, [(2, 0), (4, 0)], 2, version=version)[-1])


@pytest.mark.parametrize(
    "name,args",
    [
        ("mom", (2,)),
        ("roc", (2,)),
        ("cmo", (2,)),
        ("stoch", (2,)),
        ("wpr", (2,)),
        ("bbw", (2, 2)),
        ("kcw", (2, 2)),
    ],
)
def test_flat_window_momentum_and_width_degeneracy(name, args):
    fn = getattr(k, name)
    row = (
        (5, 5, 5) if name in {"stoch", "wpr"} else (5, 5, 5, 5) if name == "kcw" else 5
    )
    assert run(fn, [row] * 6, *args)[-1] == 0


def test_zero_denominators_and_missing_values_are_not_infinite():
    assert is_na(run(k.roc, [0, 0, 2], 2)[-1])
    assert is_na(run(k.bbw, [0, 0, 0], 2, 2)[-1])
    assert is_na(run(k.kcw, [(0, 1, -1, 0)] * 4, 2, 2)[-1])
    assert is_na(run(k.cmo, [1, na], 2)[-1])
    for fn in [k.stoch, k.wpr]:
        assert is_na(run(fn, [(2, na, 1)] * 3, 2)[-1])
    assert is_na(run(k.tr, [(na, 1, 2)])[-1])
    assert all(is_na(x) for x in run(k.rma, [na, na], 2))
    assert run(k.rma, [4, 4, na], 2)[-1] == 4


@pytest.mark.parametrize(
    "fn,rows,expected", [(k.pivothigh, [1, 5, 2], 5), (k.pivotlow, [5, 1, 2], 1)]
)
def test_isolated_pivot_is_confirmed_only_after_right_bar(fn, rows, expected):
    values = run(fn, rows, 1, 1)
    assert all(is_na(x) for x in values[:2])
    assert values[-1] == expected
    assert is_na(run(fn, [na, rows[1], rows[2]], 1, 1)[-1])


@pytest.mark.parametrize(
    "fn", [k.percentile_linear_interpolation, k.percentile_nearest_rank]
)
@pytest.mark.parametrize("percentage,expected", [(0, 2), (100, 8)])
def test_percentile_endpoints_are_minimum_and_maximum(fn, percentage, expected):
    assert run(fn, [8, 2, 4], 3, percentage)[-1] == expected
    for bad in [-1, 101]:
        with pytest.raises(PineRuntimeError, match="percentage"):
            run(fn, [1], 3, bad)


def test_percentile_interpolation_and_strict_descending_trend():
    assert run(k.percentile_linear_interpolation, [2, 6], 2, 25)[-1] == 3
    assert run(k.falling, [4, 3, 2, 1], 3)[-1] is True
    assert run(k.rising, [4, 3, 2, 1], 3)[-1] is False
    assert run(k.percentrank, [9], 1)[0] == 100
    assert run(k.linreg, [9], 1)[0] == 9
    with pytest.raises(PineRuntimeError, match="offset"):
        run(k.linreg, [1], 1, True)


@pytest.mark.parametrize(
    "fn,args",
    [
        (k.alma, (1, 2, 0.5, 0)),
        (k.supertrend, (2, 1, 1, 0, 2)),
        (k.sar, (2, 1, 0, 0.02, 0.2)),
        (k.sar, (2, 1, 0.02, 0, 0.2)),
        (k.sar, (2, 1, 0.2, 0.02, 0.1)),
        (k.valuewhen, (1, 2, 0)),
        (k.valuewhen, (True, 2, -1)),
        (k.barssince, (1,)),
        (k.vwap, (2, 3, 1)),
    ],
)
def test_invalid_scalar_configuration_fails_before_a_result(fn, args):
    runtime = session()
    before = runtime.sequence
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError):
        fn(tx, "invalid", *args)
    tx.abort()
    assert runtime.sequence == before


@pytest.mark.parametrize(
    "fn,rows,args",
    [
        (k.dmi, [(na, 1, 1)], (2, 2)),
        (k.supertrend, [(na, 1, 1)], (2, 2)),
        (k.sar, [(na, 1)], (0.02, 0.02, 0.2)),
        (k.cci, [(na, 1, 1)], (2,)),
        (k.mfi, [(na, 1, 1, 1)], (2,)),
        (k.obv, [(na, 1)], ()),
        (k.vwap, [(na, 1)], ()),
    ],
)
def test_missing_market_data_propagates_without_numeric_fabrication(fn, rows, args):
    result = run(fn, rows, *args)[0]
    values = result if isinstance(result, tuple) else (result,)
    assert all(is_na(x) for x in values)


def test_downward_money_flow_and_signed_volume():
    assert run(k.mfi, [(x, x, x, 1) for x in [5, 4, 3, 2]], 2)[-1] == 0
    assert run(k.obv, [(5, 3), (4, 3), (4, 3), (3, 3)]) == [0, -3, -3, -6]
    assert is_na(run(k.cum, [na])[0])
    assert run(k.cum, [2, na, 3])[-1] == 5


@pytest.mark.parametrize(
    "fn,args,nested",
    [
        (k.rsi, (1, 2), "gain"),
        (k.macd, (1, 2, 3, 2), "fast"),
        (k.tsi, (1, 2, 3), "change_long"),
        (k.atr, (2, 0, 1, 2), "tr"),
        (k.kc, (1, 2, 0, 1, 2, 2), "basis"),
        (k.dmi, (2, 0, 1, 2, 2), "plus_rma"),
        (k.supertrend, (2, 0, 1, 2, 2), "atr"),
    ],
)
def test_nested_ta_state_cannot_be_replaced_by_a_scalar(fn, args, nested):
    runtime = session()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    fn(tx, "s", *args)
    symbol = "ta." + fn.__name__
    state = tx.state(
        "s", owner=symbol, schema_version=k.kernel_spec(symbol).state_schema, initial={}
    )
    assert isinstance(state, dict)
    state[nested] = 7
    with pytest.raises(PineRuntimeError, match="state"):
        fn(tx, "s", *args)
    tx.abort()


@pytest.mark.parametrize(
    "key,value",
    [
        ("kernel", "foreign"),
        ("profile", "foreign"),
        ("value", True),
        ("value", math.inf),
    ],
)
def test_ema_rejects_poisoned_identity_profile_or_numeric_storage(key, value):
    runtime = session()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    k.ema(tx, "s", 1, 2)
    state = tx.state("s", owner="ta.ema", schema_version="ta.ema.state.v2", initial={})
    assert isinstance(state, dict)
    original = state[key]
    state[key] = value
    with pytest.raises(PineRuntimeError, match="state"):
        k.ema(tx, "s", 2, 2)
    # Restore the deliberately nonportable internal corruption before serializing abort.
    state[key] = original
    tx.abort()


@pytest.mark.parametrize(
    "helper,payload,key",
    [
        (k._numeric_buffer, {"x": 1}, "x"),
        (k._numeric_buffer, {"x": [True]}, "x"),
        (k._numeric_buffer, {"x": [math.nan]}, "x"),
        (k._object_buffer, {"x": {}}, "x"),
    ],
)
def test_private_state_decoders_reject_nonportable_buffers(helper, payload, key):
    with pytest.raises(PineRuntimeError, match="state"):
        helper(payload, key)


def test_unknown_kernel_and_invalid_integer_storage_are_explicit_errors():
    with pytest.raises(PineRuntimeError, match="unknown TA kernel"):
        k.kernel_spec("ta.unknown")
    with pytest.raises(PineRuntimeError, match="integer state"):
        k._stored_int(True)
