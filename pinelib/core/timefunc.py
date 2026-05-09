from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pinelib.core.na import na
from pinelib.core.types import parse_timeframe_to_ms
from pinelib.errors import (
    PL_UNSUPPORTED_TIMEFRAME_TIMEFUNC,
    PineSessionError,
    PineUnsupportedFeatureError,
)

if TYPE_CHECKING:
    from pinelib.core.runtime import PineRuntime


_PYTHON_WEEKDAY_TO_PINE = {0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 1}


@dataclass(frozen=True, slots=True)
class SessionSpec:
    raw: str
    timezone: str
    start: time
    end: time
    day_mask: frozenset[int]

    @property
    def is_overnight(self) -> bool:
        return self.start >= self.end


def _parse_clock(value: str) -> time:
    if len(value) != 4 or not value.isdigit():
        raise PineSessionError(f"Invalid session clock component: {value}")
    hour = int(value[:2])
    minute = int(value[2:])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise PineSessionError(f"Invalid session clock component: {value}")
    return time(hour=hour, minute=minute)


def parse_session(session: str, timezone: str) -> SessionSpec:
    try:
        span, _, days = session.partition(":")
        start_raw, sep, end_raw = span.partition("-")
        if sep != "-":
            raise PineSessionError(f"Invalid session string: {session}")
        mask = frozenset(int(day) for day in (days or "1234567"))
        if not mask.issubset({1, 2, 3, 4, 5, 6, 7}):
            raise PineSessionError(f"Invalid session day mask: {session}")
        return SessionSpec(
            raw=session,
            timezone=timezone,
            start=_parse_clock(start_raw),
            end=_parse_clock(end_raw),
            day_mask=mask,
        )
    except ValueError as exc:
        raise PineSessionError(f"Invalid session string: {session}") from exc


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise PineSessionError(f"Unknown timezone: {timezone_name}") from exc


def _localize(timestamp_ms: int, timezone_name: str) -> datetime:
    zone = _resolve_timezone(timezone_name)
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=zone)


def _interval_bounds(local_dt: datetime, spec: SessionSpec) -> tuple[datetime, datetime]:
    day_start = local_dt.replace(
        hour=spec.start.hour, minute=spec.start.minute, second=0, microsecond=0
    )
    day_end = local_dt.replace(hour=spec.end.hour, minute=spec.end.minute, second=0, microsecond=0)
    if not spec.is_overnight:
        return day_start, day_end
    if local_dt.time() >= spec.start:
        return day_start, day_end + timedelta(days=1)
    return day_start - timedelta(days=1), day_end


def _trading_day_code(local_dt: datetime, spec: SessionSpec) -> int:
    if spec.is_overnight and local_dt.time() >= spec.start:
        local_dt = local_dt + timedelta(days=1)
    return _PYTHON_WEEKDAY_TO_PINE[local_dt.weekday()]


def is_timestamp_in_session(timestamp_ms: int, session: str, timezone_name: str) -> bool:
    spec = parse_session(session, timezone_name)
    local_dt = _localize(timestamp_ms, timezone_name)
    trading_day = _trading_day_code(local_dt, spec)
    if trading_day not in spec.day_mask:
        return False
    start_dt, end_dt = _interval_bounds(local_dt, spec)
    return start_dt <= local_dt <= end_dt


class TimeFunctions:
    def time(
        self,
        timeframe: str | None = None,
        session: str | None = None,
        timezone: str | None = None,
        *,
        runtime: PineRuntime,
    ) -> int | object:
        if runtime.current_bar is None:
            return na
        if self._is_intraday_daily_request(timeframe, runtime):
            return self._daily_bucket_open(runtime.current_bar.time)
        self._validate_timeframe(timeframe, runtime)
        resolved_tz = timezone or runtime.syminfo.timezone
        session_value = session or runtime.syminfo.session
        return (
            runtime.current_bar.time
            if self._bar_in_session(runtime, session_value, resolved_tz)
            else na
        )

    def time_close(
        self,
        timeframe: str | None = None,
        session: str | None = None,
        timezone: str | None = None,
        *,
        runtime: PineRuntime,
    ) -> int | object:
        if runtime.current_bar is None:
            return na
        if self._is_intraday_daily_request(timeframe, runtime):
            return self._daily_bucket_open(runtime.current_bar.time) + 86_400_000
        self._validate_timeframe(timeframe, runtime)
        resolved_tz = timezone or runtime.syminfo.timezone
        session_value = session or runtime.syminfo.session
        return (
            runtime.current_bar.time_close
            if self._bar_in_session(runtime, session_value, resolved_tz)
            else na
        )

    def year(self, *, runtime: PineRuntime, timezone: str | None = None) -> int:
        return self._calendar_value(runtime, timezone, "year")

    def month(self, *, runtime: PineRuntime, timezone: str | None = None) -> int:
        return self._calendar_value(runtime, timezone, "month")

    def weekofyear(self, *, runtime: PineRuntime, timezone: str | None = None) -> int:
        return self._calendar_value(runtime, timezone, "weekofyear")

    def dayofmonth(self, *, runtime: PineRuntime, timezone: str | None = None) -> int:
        return self._calendar_value(runtime, timezone, "dayofmonth")

    def dayofweek(self, *, runtime: PineRuntime, timezone: str | None = None) -> int:
        return self._calendar_value(runtime, timezone, "dayofweek")

    def hour(self, *, runtime: PineRuntime, timezone: str | None = None) -> int:
        return self._calendar_value(runtime, timezone, "hour")

    def minute(self, *, runtime: PineRuntime, timezone: str | None = None) -> int:
        return self._calendar_value(runtime, timezone, "minute")

    def second(self, *, runtime: PineRuntime, timezone: str | None = None) -> int:
        return self._calendar_value(runtime, timezone, "second")

    def _bar_in_session(self, runtime: PineRuntime, session: str, timezone_name: str) -> bool:
        assert runtime.current_bar is not None
        if getattr(runtime.timeframe, "isdaily", False):
            # For daily TradingView stock bars, `time(tf, session, tz)` is keyed
            # by the bar/session open. Requiring both daily bar open and inferred
            # daily close to be inside an intraday session incorrectly filters
            # every regular daily bar out.
            return is_timestamp_in_session(runtime.current_bar.time, session, timezone_name)
        if runtime.current_bar.time_close is None:
            raise PineSessionError("Current bar is missing time_close")
        return is_timestamp_in_session(
            runtime.current_bar.time, session, timezone_name
        ) and is_timestamp_in_session(
            runtime.current_bar.time_close,
            session,
            timezone_name,
        )

    @staticmethod
    def _daily_bucket_open(timestamp_ms: int) -> int:
        return (timestamp_ms // 86_400_000) * 86_400_000

    @staticmethod
    def _is_intraday_daily_request(timeframe: str | None, runtime: PineRuntime) -> bool:
        if timeframe is None:
            return False
        requested = timeframe.strip().upper()
        if requested not in {"D", "1D"}:
            return False
        chart_ms = runtime.timeframe.interval_ms
        return chart_ms is not None and chart_ms < 86_400_000

    def _validate_timeframe(self, timeframe: str | None, runtime: PineRuntime) -> None:
        if timeframe is None:
            return
        requested = timeframe.strip().upper()
        chart = runtime.timeframe.value.strip().upper()
        requested_ms = parse_timeframe_to_ms(timeframe)
        chart_ms = runtime.timeframe.interval_ms
        if requested == chart or (
            requested_ms is not None and chart_ms is not None and requested_ms == chart_ms
        ):
            return
        message = (
            f"time()/time_close() requested timeframe {timeframe!r}, but PineLib v1.0.1 only supports "  # noqa: E501
            "None or the active chart timeframe; non-chart timeframe aggregation is unsupported"
        )
        runtime.config.emit_diagnostic(
            PL_UNSUPPORTED_TIMEFRAME_TIMEFUNC,
            message,
            requested_timeframe=timeframe,
            chart_timeframe=runtime.timeframe.value,
        )
        raise PineUnsupportedFeatureError(message, code=PL_UNSUPPORTED_TIMEFRAME_TIMEFUNC)

    def _calendar_value(
        self,
        runtime: PineRuntime,
        timezone_name: str | None,
        field_name: str,
    ) -> int:
        if runtime.current_bar is None:
            raise PineSessionError("No current bar is active")
        localized = _localize(runtime.current_bar.time, timezone_name or runtime.syminfo.timezone)
        if field_name == "year":
            return localized.year
        if field_name == "month":
            return localized.month
        if field_name == "weekofyear":
            return localized.isocalendar().week
        if field_name == "dayofmonth":
            return localized.day
        if field_name == "dayofweek":
            return _PYTHON_WEEKDAY_TO_PINE[localized.weekday()]
        if field_name == "hour":
            return localized.hour
        if field_name == "minute":
            return localized.minute
        if field_name == "second":
            return localized.second
        raise PineSessionError(f"Unsupported calendar field: {field_name}")
