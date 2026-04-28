import pytest

from pinelib import (
    PL_INPUT_VALIDATION_ERROR,
    Bar,
    PineRuntime,
    PineRuntimeError,
    RuntimeConfig,
    SymbolInfo,
    TimeframeInfo,
)


def _runtime() -> PineRuntime:
    return PineRuntime(
        SymbolInfo("TEST:AAA", timezone="UTC"),
        TimeframeInfo.from_string("60"),
        config=RuntimeConfig(),
    )


def test_input_metadata_and_basic_validation() -> None:
    rt = _runtime()
    assert rt.inputs.int("len", 14, minval=1, maxval=100, options=[7, 14]) == 14
    assert rt.inputs.float("mult", 2.5, minval=0.5, maxval=5.0) == 2.5
    assert rt.inputs.bool("enabled", True) is True
    assert rt.inputs.string("mode", "fast", options=["fast", "slow"]) == "fast"
    assert rt.inputs.timeframe("tf", "15", options=["5", "15", "1H"]) == "15"
    assert rt.inputs.symbol("sym", "BINANCE:BTCUSDT") == "BINANCE:BTCUSDT"
    assert (
        rt.inputs.session("sess", "0930-1600:23456", timezone="America/New_York")
        == "0930-1600:23456"
    )
    assert rt.inputs.source("src", rt.close) is rt.close
    assert rt.inputs.metadata["len"].kind == "int"
    assert rt.inputs.metadata["len"].options == (7, 14)


def test_input_validation_failure_collects_diagnostic() -> None:
    rt = _runtime()
    with pytest.raises(PineRuntimeError) as excinfo:
        rt.inputs.int("bad", 0, minval=1)
    assert excinfo.value.code == PL_INPUT_VALIDATION_ERROR
    assert rt.config.diagnostics[-1]["code"] == PL_INPUT_VALIDATION_ERROR


def test_source_rejects_missing_default() -> None:
    rt = _runtime()
    with pytest.raises(PineRuntimeError):
        rt.inputs.source("src", None)


def test_barstate_syminfo_timeframe_models() -> None:
    rt = _runtime()
    bar = Bar(time=1_700_000_000_000, open=1, high=2, low=0.5, close=1.5)
    rt.begin_bar(bar)
    assert rt.syminfo.tickerid == "TEST:AAA"
    assert rt.timeframe.isminutes is True
    assert rt.timeframe.multiplier == 60
    assert rt.barstate.isfirst is True
    assert rt.barstate.isnew is True
    assert rt.barstate.isconfirmed is False
    rt.end_bar()
    assert rt.barstate.isconfirmed is True
