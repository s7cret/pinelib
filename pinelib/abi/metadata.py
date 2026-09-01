from __future__ import annotations

from pinelib.errors import PL_METADATA_INVALID, PineRuntimeError
from pinelib.runtime.metadata import InstrumentContext, TimeframeContext
from pinelib.runtime.session import CallbackFrame, RuntimeSession


def _instrument(session: RuntimeSession) -> InstrumentContext:
    if session.instrument is None:
        raise PineRuntimeError(
            "InstrumentContext is required", code=PL_METADATA_INVALID
        )
    return session.instrument


def _timeframe(session: RuntimeSession) -> TimeframeContext:
    if session.timeframe is None:
        raise PineRuntimeError("TimeframeContext is required", code=PL_METADATA_INVALID)
    return session.timeframe


def syminfo_ticker_v1(session: RuntimeSession) -> str:
    return _instrument(session).ticker


def syminfo_tickerid_v1(session: RuntimeSession) -> str:
    return _instrument(session).tickerid


def syminfo_prefix_v1(session: RuntimeSession) -> str:
    return _instrument(session).prefix


def syminfo_currency_v1(session: RuntimeSession) -> str:
    return _instrument(session).currency


def syminfo_basecurrency_v1(session: RuntimeSession) -> str:
    return _instrument(session).basecurrency


def syminfo_timezone_v1(session: RuntimeSession) -> str:
    return _instrument(session).timezone


def syminfo_type_v1(session: RuntimeSession) -> str:
    return _instrument(session).instrument_type


def syminfo_mintick_v1(session: RuntimeSession) -> float:
    return _instrument(session).mintick


def syminfo_pointvalue_v1(session: RuntimeSession) -> float:
    return _instrument(session).pointvalue


def syminfo_mincontract_v1(session: RuntimeSession) -> float:
    return _instrument(session).mincontract


def timeframe_period_v1(session: RuntimeSession) -> str:
    return _timeframe(session).period_for(session.language)


def timeframe_multiplier_v1(session: RuntimeSession) -> int:
    return _timeframe(session).multiplier


def timeframe_in_seconds_v1(session: RuntimeSession) -> object:
    return _timeframe(session).seconds


def timeframe_isintraday_v1(session: RuntimeSession) -> bool:
    timeframe = _timeframe(session)
    return timeframe.unit in {"tick", "second", "minute"}


def timeframe_isdaily_v1(session: RuntimeSession) -> bool:
    return _timeframe(session).unit == "day"


def timeframe_isweekly_v1(session: RuntimeSession) -> bool:
    return _timeframe(session).unit == "week"


def timeframe_ismonthly_v1(session: RuntimeSession) -> bool:
    return _timeframe(session).unit == "month"


def barstate_isfirst_v1(session: RuntimeSession, frame: CallbackFrame) -> bool:
    return session.barstate(frame).isfirst


def barstate_islast_v1(session: RuntimeSession, frame: CallbackFrame) -> bool:
    return session.barstate(frame).islast


def barstate_ishistory_v1(session: RuntimeSession, frame: CallbackFrame) -> bool:
    return session.barstate(frame).ishistory


def barstate_isrealtime_v1(session: RuntimeSession, frame: CallbackFrame) -> bool:
    return session.barstate(frame).isrealtime


def barstate_isnew_v1(session: RuntimeSession, frame: CallbackFrame) -> bool:
    return session.barstate(frame).isnew


def barstate_isconfirmed_v1(session: RuntimeSession, frame: CallbackFrame) -> bool:
    return session.barstate(frame).isconfirmed


def barstate_islastconfirmedhistory_v1(
    session: RuntimeSession, frame: CallbackFrame
) -> bool:
    return session.barstate(frame).islastconfirmedhistory
