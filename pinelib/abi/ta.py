from __future__ import annotations

from pinelib import ta as _ta
from pinelib.runtime.session import RuntimeTransaction
from pinelib.ta.types import BandsResult, DmiResult, MacdResult, SupertrendResult


def sma_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.sma(tx, state_id, source, length)


def ema_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.ema(tx, state_id, source, length)


def rma_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.rma(tx, state_id, source, length)


def wma_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.wma(tx, state_id, source, length)


def vwma_v1(
    tx: RuntimeTransaction, state_id: str, source: object, volume: object, length: int
) -> object:
    return _ta.vwma(tx, state_id, source, volume, length)


def swma_v1(tx: RuntimeTransaction, state_id: str, source: object) -> object:
    return _ta.swma(tx, state_id, source)


def alma_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    offset: float,
    sigma: float,
) -> object:
    return _ta.alma(tx, state_id, source, length, offset, sigma)


def hma_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.hma(tx, state_id, source, length)


def rsi_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.rsi(tx, state_id, source, length)


def macd_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    fast_length: int,
    slow_length: int,
    signal_length: int,
) -> MacdResult:
    return _ta.macd(tx, state_id, source, fast_length, slow_length, signal_length)


def mom_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.mom(tx, state_id, source, length)


def roc_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.roc(tx, state_id, source, length)


def cmo_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.cmo(tx, state_id, source, length)


def tsi_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    short_length: int,
    long_length: int,
) -> object:
    return _ta.tsi(tx, state_id, source, short_length, long_length)


def stoch_v1(
    tx: RuntimeTransaction,
    state_id: str,
    close: object,
    high: object,
    low: object,
    length: int,
) -> object:
    return _ta.stoch(tx, state_id, close, high, low, length)


def tr_v1(
    tx: RuntimeTransaction, state_id: str, high: object, low: object, close: object
) -> object:
    return _ta.tr(tx, state_id, high, low, close)


def atr_v1(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    length: int,
) -> object:
    return _ta.atr(tx, state_id, high, low, close, length)


def bb_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    multiplier: float,
) -> BandsResult:
    return _ta.bb(tx, state_id, source, length, multiplier)


def bbw_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    multiplier: float,
) -> object:
    return _ta.bbw(tx, state_id, source, length, multiplier)


def kc_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    high: object,
    low: object,
    close: object,
    length: int,
    multiplier: float,
    use_true_range: bool = True,
) -> BandsResult:
    return _ta.kc(
        tx, state_id, source, high, low, close, length, multiplier, use_true_range
    )


def kcw_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    high: object,
    low: object,
    close: object,
    length: int,
    multiplier: float,
    use_true_range: bool = True,
) -> object:
    return _ta.kcw(
        tx, state_id, source, high, low, close, length, multiplier, use_true_range
    )


def range_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.range_value(tx, state_id, source, length)


def wpr_v1(
    tx: RuntimeTransaction,
    state_id: str,
    close: object,
    high: object,
    low: object,
    length: int,
) -> object:
    return _ta.wpr(tx, state_id, close, high, low, length)


def dmi_v1(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    di_length: int,
    adx_smoothing: int,
) -> DmiResult:
    return _ta.dmi(tx, state_id, high, low, close, di_length, adx_smoothing)


def supertrend_v1(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    factor: float,
    atr_length: int,
) -> SupertrendResult:
    return _ta.supertrend(tx, state_id, high, low, close, factor, atr_length)


def sar_v1(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    start: float,
    increment: float,
    maximum: float,
) -> object:
    return _ta.sar(tx, state_id, high, low, start, increment, maximum)


def pivothigh_v1(
    tx: RuntimeTransaction, state_id: str, source: object, left: int, right: int
) -> object:
    return _ta.pivothigh(tx, state_id, source, left, right)


def pivotlow_v1(
    tx: RuntimeTransaction, state_id: str, source: object, left: int, right: int
) -> object:
    return _ta.pivotlow(tx, state_id, source, left, right)


def rising_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> bool:
    return _ta.rising(tx, state_id, source, length)


def falling_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> bool:
    return _ta.falling(tx, state_id, source, length)


def highest_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.highest(tx, state_id, source, length)


def lowest_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.lowest(tx, state_id, source, length)


def highestbars_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.highestbars(tx, state_id, source, length)


def lowestbars_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.lowestbars(tx, state_id, source, length)


def variance_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    biased: bool = True,
) -> object:
    return _ta.variance(tx, state_id, source, length, biased)


def stdev_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    biased: bool = True,
) -> object:
    return _ta.stdev(tx, state_id, source, length, biased)


def dev_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.dev(tx, state_id, source, length)


def correlation_v1(
    tx: RuntimeTransaction, state_id: str, source1: object, source2: object, length: int
) -> object:
    return _ta.correlation(tx, state_id, source1, source2, length)


def percentile_linear_interpolation_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    percentage: float,
) -> object:
    return _ta.percentile_linear_interpolation(tx, state_id, source, length, percentage)


def percentile_nearest_rank_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    percentage: float,
) -> object:
    return _ta.percentile_nearest_rank(tx, state_id, source, length, percentage)


def percentrank_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.percentrank(tx, state_id, source, length)


def linreg_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int, offset: int = 0
) -> object:
    return _ta.linreg(tx, state_id, source, length, offset)


def median_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.median(tx, state_id, source, length)


def mode_v1(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _ta.mode(tx, state_id, source, length)


def valuewhen_v1(
    tx: RuntimeTransaction,
    state_id: str,
    condition: bool,
    source: object,
    occurrence: int,
) -> object:
    return _ta.valuewhen(tx, state_id, condition, source, occurrence)


def barssince_v1(tx: RuntimeTransaction, state_id: str, condition: bool) -> object:
    return _ta.barssince(tx, state_id, condition)


def cci_v1(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    length: int,
) -> object:
    return _ta.cci(tx, state_id, high, low, close, length)


def mfi_v1(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    volume: object,
    length: int,
) -> object:
    return _ta.mfi(tx, state_id, high, low, close, volume, length)


def obv_v1(
    tx: RuntimeTransaction, state_id: str, close: object, volume: object
) -> object:
    return _ta.obv(tx, state_id, close, volume)


def vwap_v1(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    volume: object,
    reset: bool = False,
) -> object:
    return _ta.vwap(tx, state_id, source, volume, reset)


def cum_v1(tx: RuntimeTransaction, state_id: str, source: object) -> object:
    return _ta.cum(tx, state_id, source)
