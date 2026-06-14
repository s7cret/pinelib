from __future__ import annotations

import pytest

from pinelib import (
    Bar,
    PineRuntime,
    PineRuntimeError,
    PineTypeError,
    SymbolInfo,
    TimeframeInfo,
    is_na,
    na,
    ta,
)
from pinelib.ta._impl_states import (
    _CciState,
    _HighestState,
    _LowestState,
    _MfiState,
    _ObvState,
    _SarState,
)


def _runtime() -> PineRuntime:
    return PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
        timeframe=TimeframeInfo.from_string("60"),
    )


def _bar(
    index: int,
    close: float,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1.0,
) -> Bar:
    return Bar(
        time=1_700_000_000_000 + index * 3_600_000,
        open=close - 0.25,
        high=close + 0.25 if high is None else high,
        low=close - 0.25 if low is None else low,
        close=close,
        volume=volume,
    )


def test_runtime_ta_extended_stateful_paths() -> None:
    runtime = _runtime()
    outputs: dict[str, list[object]] = {
        name: []
        for name in [
            "wma",
            "vwma",
            "hma",
            "cmo",
            "tsi",
            "kc",
            "kcw",
            "range",
            "wpr",
            "dmi",
            "supertrend",
            "roc",
            "correlation",
            "cci",
            "mfi",
            "vwap",
        ]
    }
    aux = runtime.series("aux", "float")
    closes = [10.0, 11.0, 13.0, 12.0, 15.0, 14.0, 17.0, 19.0]
    for index, close in enumerate(closes):
        runtime.begin_bar(_bar(index, close, high=close + 1.0, low=close - 1.0, volume=100 + index))
        aux.set_current(close * 1.5)
        outputs["wma"].append(ta.wma(runtime.close, 3, runtime=runtime, state_id="wma"))
        outputs["vwma"].append(ta.vwma(runtime.close, 3, runtime=runtime, state_id="vwma"))
        outputs["hma"].append(ta.hma(runtime.close, 4, runtime=runtime, state_id="hma"))
        outputs["cmo"].append(ta.cmo(runtime.close, 3, runtime=runtime, state_id="cmo"))
        outputs["tsi"].append(ta.tsi(runtime.close, 2, 3, runtime=runtime, state_id="tsi"))
        outputs["kc"].append(ta.kc(runtime.close, 3, 1.5, runtime=runtime, state_id="kc"))
        outputs["kcw"].append(ta.kcw(runtime.close, 3, 1.5, runtime=runtime, state_id="kcw"))
        outputs["range"].append(ta.ta_range(runtime.close, 3, runtime=runtime, state_id="range"))
        outputs["wpr"].append(ta.wpr(3, runtime=runtime, state_id="wpr"))
        outputs["dmi"].append(
            ta.dmi(
                runtime.high.current,
                runtime.low.current,
                runtime.close.current,
                3,
                2,
                runtime=runtime,
                state_id="dmi",
            )
        )
        outputs["supertrend"].append(ta.supertrend(2.0, 3, runtime=runtime, state_id="st"))
        outputs["roc"].append(ta.roc(runtime.close, 2, runtime=runtime, state_id="roc"))
        outputs["correlation"].append(
            ta.correlation(runtime.close, aux, 3, runtime=runtime, state_id="corr")
        )
        outputs["cci"].append(ta.cci(runtime.close, 3, runtime=runtime, state_id="cci"))
        outputs["mfi"].append(ta.mfi(runtime.close, 3, runtime=runtime, state_id="mfi"))
        outputs["vwap"].append(
            ta.vwap(runtime.close, runtime.volume, runtime=runtime, state_id="vwap")
        )
        runtime.end_bar()

    assert not is_na(outputs["wma"][-1])
    assert not is_na(outputs["vwma"][-1])
    assert not is_na(outputs["hma"][-1])
    assert not is_na(outputs["cmo"][-1])
    assert not is_na(outputs["tsi"][-1])
    assert isinstance(outputs["kc"][-1], tuple)
    assert not is_na(outputs["kcw"][-1])
    assert outputs["range"][-1] >= 0
    assert not is_na(outputs["wpr"][-1])
    assert isinstance(outputs["dmi"][-1], tuple)
    assert isinstance(outputs["supertrend"][-1], tuple)
    assert not is_na(outputs["roc"][-1])
    assert not is_na(outputs["correlation"][-1])
    assert not is_na(outputs["vwap"][-1])


def test_runtime_ta_error_paths_for_stateful_helpers() -> None:
    runtime = _runtime()
    runtime.begin_bar(_bar(0, 10.0))
    with pytest.raises(PineRuntimeError):
        ta.wma(runtime.close, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.vwma(runtime.close, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.hma(runtime.close, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.cmo(runtime.close, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.tsi(runtime.close, 2, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.kc(runtime.close, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.wpr(3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.dmi(11, 9, 10, 3, 2, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.supertrend(2, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.roc(runtime.close, 2, state_id="roc")
    with pytest.raises(PineRuntimeError):
        ta.correlation(runtime.close, runtime.close, 2, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.cci(runtime.close, 2, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.mfi(runtime.close, 2)


def test_batch_ta_extended_paths_and_edge_cases() -> None:
    close = [10.0, 11.0, 13.0, 12.0, 15.0, 14.0, 17.0, 19.0]
    high = [x + 1.0 for x in close]
    low = [x - 1.0 for x in close]
    volume = [100.0 + i for i in range(len(close))]

    assert len(ta.wma(close, 3)) == len(close)
    assert len(ta.vwma(close, 3, volume)) == len(close)
    assert len(ta.hma(close, 4)) == len(close)
    assert len(ta.alma(close, 4, 0.85, 6.0, floor=True)) == len(close)
    assert len(ta.bb(close, 3, 2.0)[0]) == len(close)
    assert len(ta.bbw(close, 3, 2.0)) == len(close)
    assert len(ta.stoch(close, high, low, 3)) == len(close)
    plus, minus, adx = ta.dmi(high, low, close, 3, 2)
    assert len(plus) == len(minus) == len(adx) == len(close)
    assert len(ta.supertrend(2.0, 3, high=high, low=low, close=close)[0]) == len(close)
    assert len(ta.sar(high, low, 0.02, 0.02, 0.2)) == len(close)
    assert ta.pivot_high(close, 2, 2) is not None
    assert ta.pivot_low(close, 2, 2) is not None
    assert ta.pivothigh(close, 2, 2) == ta.pivot_high(close, 2, 2)
    assert ta.pivotlow(close, 2, 2) == ta.pivot_low(close, 2, 2)
    assert len(ta.valuewhen([False, True, False, True], [1, 2, 3, 4], 0)) == 4
    assert len(ta.barssince([False, False, True, False])) == 4
    assert not is_na(ta.linreg(close, 4, 1))
    assert not is_na(ta.percentile_nearest_rank(close, 4, 75))
    assert not is_na(ta.percentile_linear_interpolation(close, 4, 75))
    assert not is_na(ta.percentrank(close, 4))
    assert len(ta.vwap(close, volume)) == len(close)
    assert len(ta.mom(close, 2)) == len(close)
    assert len(ta.roc(close, 2)) == len(close)
    assert len(ta.correlation(close, [v * 2 for v in close], 3)) == len(close)
    assert ta.rising([1.0, 2.0, 3.0, 4.0], 2)
    assert ta.falling([4.0, 3.0, 2.0, 1.0], 2)
    assert len(ta.cci(high, low, close, 3)) == len(close)
    assert len(ta.mfi(high, low, close, volume, 3)) == len(close)
    assert len(ta.obv(close, volume)) == len(close)
    assert len(ta.ta_range(close, 3)) == len(close)
    assert len(ta.cmo(close, 3)) == len(close)
    assert len(ta.tsi(close, 2, 3)) == len(close)
    assert len(ta.kc(close, 3, 1.5)[0]) == len(close)
    assert len(ta.kcw(close, 3, 1.5)) == len(close)


def test_private_state_objects_cover_branchy_update_logic() -> None:
    sar = _SarState(0.02, 0.02, 0.2)
    assert is_na(sar.update(10, 9))
    assert not is_na(sar.update(11, 10))
    assert not is_na(sar.update(8, 7))
    assert not is_na(sar.update(12, 11))
    assert is_na(_SarState(0.02, 0.02, 0.2).update(na, 1))

    hi = _HighestState(2)
    lo = _LowestState(2)
    assert is_na(hi.update(na))
    assert is_na(lo.update(na))
    assert is_na(hi.update(1))
    assert hi.update(3) == 3
    assert hi.update(2) == 3
    assert is_na(lo.update(1))
    assert lo.update(3) == 1
    assert lo.update(0) == 0

    cci = _CciState(3)
    assert is_na(cci.update(na, 1, 1))
    assert is_na(cci.update(10, 8, 9))
    assert is_na(cci.update(11, 9, 10))
    assert not is_na(cci.update(13, 9, 12))
    assert is_na(_CciState(2).update(1, 1, 1))

    mfi = _MfiState(3)
    assert is_na(mfi.update(na, 1, 1, 1))
    values = [(10, 8, 9, 100), (11, 9, 10, 110), (12, 10, 11, 120), (10, 8, 9, 130)]
    result = na
    for item in values:
        result = mfi.update(*item)
    assert not is_na(result)

    obv = _ObvState()
    assert is_na(obv.update(na, 1))
    assert obv.update(10, 100) == 100
    assert obv.update(11, 50) == 150
    assert obv.update(9, 20) == 130
    assert obv.update(9, 10) == 130


def test_series_scalar_fallbacks_for_single_bar_ta_contexts() -> None:
    runtime = _runtime()
    for index, close in enumerate([1.0, 2.0, 4.0, 8.0, 16.0]):
        runtime.begin_bar(_bar(index, close, high=close + 1, low=close - 1))
        runtime.end_bar()
    runtime.begin_bar(_bar(5, 32.0, high=33.0, low=31.0))
    assert not is_na(ta.wma(runtime.close, 3))
    assert not is_na(ta.swma(runtime.close))
    assert not is_na(ta.alma(runtime.close, 3, 0.5, 4.0))
    assert not is_na(ta.stoch(runtime.close, runtime.high, runtime.low, 3))
    assert isinstance(ta.valuewhen(runtime.close > 10, runtime.close, 0), float | type(na))
    assert isinstance(ta.barssince(runtime.close > 10), int | type(na))
    assert isinstance(ta.rising(runtime.close, 2), bool)
    assert isinstance(ta.falling(runtime.close, 2), bool)


class _ToySeries:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    @property
    def current(self) -> object:
        return self[0]

    @property
    def committed_length(self) -> int:
        return max(0, len(self._values) - 1)

    def __getitem__(self, offset: int) -> object:
        try:
            return self._values[-1 - offset]
        except IndexError:
            return na


def test_ta_runtime_state_validation_and_scalar_edges() -> None:
    runtime = _runtime()
    runtime.begin_bar(_bar(0, 10.0, high=11.0, low=9.0))
    with pytest.raises(PineRuntimeError):
        ta.atr(3)
    with pytest.raises(PineRuntimeError):
        ta.atr(3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.rsi(runtime.close, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.macd([1, 2, 3], 3, 2, 1)
    with pytest.raises(PineRuntimeError):
        ta.macd(runtime.close, 2, 4, 2, runtime=runtime)

    ta.rsi(runtime.close, 3, runtime=runtime, state_id="rsi-stable")
    with pytest.raises(PineRuntimeError):
        ta.rsi(runtime.close, 4, runtime=runtime, state_id="rsi-stable")
    ta.macd(runtime.close, 2, 4, 2, runtime=runtime, state_id="macd-stable")
    with pytest.raises(PineRuntimeError):
        ta.macd(runtime.close, 2, 5, 2, runtime=runtime, state_id="macd-stable")

    assert ta.highest(7, 3) == 7
    assert ta.lowest(7, 3) == 7
    assert ta.highestbars(7, 3) == 0
    assert ta.lowestbars(7, 3) == 0
    with pytest.raises(PineRuntimeError):
        ta.change([1, 2, 3], 1, state_id="change-no-runtime")
    assert is_na(ta.change(na, 1))
    with pytest.raises(PineTypeError):
        ta.change(True, 1)
    with pytest.raises(PineTypeError):
        ta.change(_ToySeries([True, 2.0]), 1)
    assert ta.roc([1.0, 0.0, 2.0], 1)[-1] is na
    assert is_na(ta.roc(0.0, 1))
    assert ta.rising([1.0], 2) is False
    assert ta.falling([1.0], 2) is False


def test_ta_runtime_length_stability_for_core_and_channel_helpers() -> None:
    runtime = _runtime()
    for index, close in enumerate([10.0, 11.0, 12.0, 13.0, 14.0]):
        runtime.begin_bar(_bar(index, close, high=close + 1, low=close - 1))
        ta.sma(runtime.close, 3, runtime=runtime, state_id="sma")
        ta.ema(runtime.close, 3, runtime=runtime, state_id="ema")
        ta.median(runtime.close, 3, runtime=runtime, state_id="median")
        ta.mode(runtime.close, 3, runtime=runtime, state_id="mode")
        ta.cmo(runtime.close, 3, runtime=runtime, state_id="cmo-stable")
        ta.tsi(runtime.close, 2, 3, runtime=runtime, state_id="tsi-stable")
        runtime.end_bar()

    runtime.begin_bar(_bar(6, 15.0, high=16.0, low=14.0))
    with pytest.raises(PineRuntimeError):
        ta.sma(runtime.close, 4, runtime=runtime, state_id="sma")
    with pytest.raises(PineRuntimeError):
        ta.ema(runtime.close, 4, runtime=runtime, state_id="ema")
    with pytest.raises(PineRuntimeError):
        ta.median(runtime.close, 4, runtime=runtime, state_id="median")
    with pytest.raises(PineRuntimeError):
        ta.mode(runtime.close, 4, runtime=runtime, state_id="mode")
    with pytest.raises(PineRuntimeError):
        ta.cmo(runtime.close, 4, runtime=runtime, state_id="cmo-stable")
    with pytest.raises(PineRuntimeError):
        ta.tsi(runtime.close, 2, 4, runtime=runtime, state_id="tsi-stable")
    assert is_na(ta.kcw([0.0, 0.0, 0.0], 3, 1.5)[-1])
    with pytest.raises(PineRuntimeError):
        ta.wpr(3)


class _HistorySeries(_ToySeries):
    def __init__(self, history: list[object], current: object) -> None:
        super().__init__([*history, current])
        self._history = history
        self._current = current

    @property
    def committed_length(self) -> int:
        return len(self._history)

    def __getitem__(self, offset: int) -> object:
        if offset == 0:
            return self._current
        index = len(self._history) - offset
        return self._history[index] if 0 <= index < len(self._history) else na


class _DerivedSeries(_ToySeries):
    pass


def test_statistics_scalar_runtime_and_na_edges() -> None:
    runtime = _runtime()
    runtime.begin_bar(_bar(0, 10.0))
    with pytest.raises(PineRuntimeError):
        ta.stdev(runtime.close, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.variance(runtime.close, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.dev(runtime.close, 3, runtime=runtime)
    with pytest.raises(PineRuntimeError):
        ta.vwma(runtime.close, 3)
    with pytest.raises(PineRuntimeError):
        ta.hma(10.0, 3)

    assert is_na(ta.stdev([1.0, na], 2)[-1])
    assert is_na(ta.stdev([1.0], 1, biased=False)[-1])
    assert is_na(ta.variance([1.0, na], 2)[-1])
    assert is_na(ta.variance([1.0], 1, biased=False)[-1])
    assert is_na(ta.dev([1.0, na], 2)[-1])
    assert not is_na(ta.stdev(2.0, 2))
    assert not is_na(ta.variance(2.0, 2))
    assert not is_na(ta.dev(2.0, 2))

    values = [10.0, 12.0, 11.0, 15.0]
    volumes = [100.0, 0.0, 110.0, 90.0]
    assert is_na(ta.vwma(values, 2, [0.0, 0.0, 0.0, 0.0])[-1])
    assert not is_na(ta.vwma(10.0, 2, _ToySeries([100.0, 110.0, 120.0])))
    assert len(ta.swma(values)) == len(values)
    assert len(ta.alma(values, 3, 0.5, 4.0)) == len(values)
    runtime.end_bar()

    for index, close in enumerate(values, start=1):
        runtime.begin_bar(_bar(index, close, volume=volumes[index - 1]))
        ta.stdev(runtime.close, 2, runtime=runtime, state_id="stdev")
        ta.variance(runtime.close, 2, runtime=runtime, state_id="variance")
        ta.dev(runtime.close, 2, runtime=runtime, state_id="dev")
        assert not isinstance(ta.vwma(runtime.close, 2, runtime=runtime, state_id="vwma"), list)
        assert not isinstance(ta.hma(runtime.close, 3, runtime=runtime, state_id="hma"), list)
        runtime.end_bar()


def test_stats2_valuewhen_barssince_and_scalar_branches() -> None:
    with pytest.raises(PineRuntimeError):
        ta.valuewhen([True], [1], -1)

    condition = _HistorySeries([False, True, False], True)
    source = _HistorySeries([10.0, 20.0, 30.0], 40.0)
    assert ta.valuewhen(condition, source, 0) == 40.0
    assert ta.valuewhen(condition, source, 1) == 20.0
    condition_false = _HistorySeries([False, True], False)
    source_false = _HistorySeries([1.0, 2.0], 3.0)
    assert ta.valuewhen(condition_false, source_false, 0) == 2.0

    derived_condition = _DerivedSeries([False, True, False, True])
    derived_source = _DerivedSeries([1.0, 2.0, 3.0, 4.0])
    assert ta.valuewhen(derived_condition, derived_source, 0) == 4.0
    assert ta.valuewhen(na, 1.0, 0) is na
    assert ta.barssince(_ToySeries([False, True, False])) == 1
    assert ta.barssince(_ToySeries([False, na])) is na

    assert is_na(ta.linreg([1.0, na], 2)[-1])
    assert is_na(ta.percentile_nearest_rank([na, na], 2, 50)[-1])
    assert is_na(ta.percentile_linear_interpolation([na, na], 2, 50)[-1])
    assert is_na(ta.percentrank([1.0, na], 2)[-1])
    assert is_na(ta.vwap([1.0, 2.0], [0.0, 0.0])[-1])
    with pytest.raises(PineRuntimeError):
        ta.vwap(1.0)
    assert not is_na(ta.vwap(2.0, _ToySeries([10.0])))
    assert not is_na(ta.correlation(_ToySeries([1.0, 2.0]), _ToySeries([2.0, 4.0]), 2))
    assert is_na(ta.correlation(1.0, na, 2))
    assert is_na(ta.correlation([1.0, 1.0, 1.0], [2.0, 2.0, 2.0], 2)[-1])

    highs = [10.0, 12.0, 11.0, 13.0]
    lows = [9.0, 10.0, 9.5, 11.0]
    closes = [9.5, 11.0, 10.0, 12.5]
    volumes = [100.0, 120.0, 110.0, 130.0]
    assert is_na(ta.cci([1.0, 1.0, 1.0], 2)[-1])
    assert len(ta.cci(highs, lows, closes, 2)) == len(highs)
    assert len(ta.mfi(highs, lows, closes, volumes, 2)) == len(highs)
    with pytest.raises(PineRuntimeError):
        ta.mfi([1.0, 2.0], 2)
    assert ta.obv([1.0, 2.0, 1.0, 1.0], [10.0, 5.0, 2.0, 1.0])[-1] == 3.0
