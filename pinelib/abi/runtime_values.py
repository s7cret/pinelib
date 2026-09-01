from __future__ import annotations

from pinelib.runtime.session import RuntimeTransaction


def na_v1(tx: RuntimeTransaction) -> object:
    return tx.value_na


def open_v1(tx: RuntimeTransaction) -> object:
    return tx.value_open


def high_v1(tx: RuntimeTransaction) -> object:
    return tx.value_high


def low_v1(tx: RuntimeTransaction) -> object:
    return tx.value_low


def close_v1(tx: RuntimeTransaction) -> object:
    return tx.value_close


def volume_v1(tx: RuntimeTransaction) -> object:
    return tx.value_volume


def time_v1(tx: RuntimeTransaction) -> object:
    return tx.value_time


def time_close_v1(tx: RuntimeTransaction) -> object:
    return tx.value_time_close


def bar_index_v1(tx: RuntimeTransaction) -> int:
    return tx.value_bar_index


def last_bar_index_v1(tx: RuntimeTransaction) -> int:
    return tx.value_last_bar_index


def syminfo_ticker_v1(tx: RuntimeTransaction) -> str:
    return tx.value_syminfo_ticker


def syminfo_tickerid_v1(tx: RuntimeTransaction) -> str:
    return tx.value_syminfo_tickerid


def syminfo_prefix_v1(tx: RuntimeTransaction) -> str:
    return tx.value_syminfo_prefix


def syminfo_currency_v1(tx: RuntimeTransaction) -> str:
    return tx.value_syminfo_currency


def syminfo_basecurrency_v1(tx: RuntimeTransaction) -> str:
    return tx.value_syminfo_basecurrency


def syminfo_timezone_v1(tx: RuntimeTransaction) -> str:
    return tx.value_syminfo_timezone


def syminfo_type_v1(tx: RuntimeTransaction) -> str:
    return tx.value_syminfo_type


def syminfo_mintick_v1(tx: RuntimeTransaction) -> float:
    return tx.value_syminfo_mintick


def syminfo_pointvalue_v1(tx: RuntimeTransaction) -> float:
    return tx.value_syminfo_pointvalue


def syminfo_mincontract_v1(tx: RuntimeTransaction) -> float:
    return tx.value_syminfo_mincontract


def timeframe_period_v1(tx: RuntimeTransaction) -> str:
    return tx.value_timeframe_period


def timeframe_multiplier_v1(tx: RuntimeTransaction) -> int:
    return tx.value_timeframe_multiplier


def timeframe_in_seconds_v1(tx: RuntimeTransaction) -> object:
    return tx.value_timeframe_in_seconds


def timeframe_isintraday_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_timeframe_isintraday


def timeframe_isdaily_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_timeframe_isdaily


def timeframe_isweekly_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_timeframe_isweekly


def timeframe_ismonthly_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_timeframe_ismonthly


def barstate_isfirst_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_barstate_isfirst


def barstate_islast_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_barstate_islast


def barstate_ishistory_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_barstate_ishistory


def barstate_isrealtime_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_barstate_isrealtime


def barstate_isnew_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_barstate_isnew


def barstate_isconfirmed_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_barstate_isconfirmed


def barstate_islastconfirmedhistory_v1(tx: RuntimeTransaction) -> bool:
    return tx.value_barstate_islastconfirmedhistory
