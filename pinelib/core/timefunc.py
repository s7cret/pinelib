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


def _bar_time_ms(runtime: PineRuntime) -> int:
    """Return bar.time in milliseconds.

    Bar.time may be stored in microseconds (runner multiplies CSV ms × 1000).
    Detect and convert to milliseconds for consistency with the rest of the code.
    """
    bar_time = runtime.current_bar.time
    # If > 10^15, bar_time is in microseconds — convert to milliseconds
    return bar_time // 1000 if bar_time > 10**15 else bar_time


def _bar_time_close_ms(runtime: PineRuntime) -> int:
    """Return bar.time_close in milliseconds, with same microsecond normalization."""
    tc = runtime.current_bar.time_close
    if tc is None:
        return 0
    return tc // 1000 if tc > 10**15 else tc


def _localize(timestamp_ms: int, timezone_name: str) -> datetime:
    zone = _resolve_timezone(timezone_name)
    # bar.time may be in microseconds; normalize to milliseconds
    if timestamp_ms > 10**15:
        timestamp_ms = timestamp_ms // 1000
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
            return self._daily_bucket_open(_bar_time_ms(runtime))
        if not self._validate_timeframe(timeframe, runtime):
            return na
        resolved_tz = timezone or runtime.syminfo.timezone
        session_value = session or runtime.syminfo.session
        return (
            _bar_time_ms(runtime)
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
            return self._daily_bucket_open(_bar_time_ms(runtime)) + 86_400_000
        if not self._validate_timeframe(timeframe, runtime):
            return na
        resolved_tz = timezone or runtime.syminfo.timezone
        session_value = session or runtime.syminfo.session
        return (
            _bar_time_close_ms(runtime)
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
            return is_timestamp_in_session(_bar_time_ms(runtime), session, timezone_name)
        if runtime.current_bar.time_close is None:
            raise PineSessionError("Current bar is missing time_close")
        return is_timestamp_in_session(
            _bar_time_ms(runtime), session, timezone_name
        ) and is_timestamp_in_session(
            _bar_time_close_ms(runtime),
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

    def _validate_timeframe(self, timeframe: str | None, runtime: PineRuntime) -> bool:
        """Validate timeframe. Returns True if valid, False if unsupported.
        Does NOT raise — caller should return na on False."""
        if timeframe is None:
            return True
        requested = timeframe.strip().upper()
        chart = runtime.timeframe.value.strip().upper()
        requested_ms = parse_timeframe_to_ms(timeframe)
        chart_ms = runtime.timeframe.interval_ms
        if requested == chart or (
            requested_ms is not None and chart_ms is not None and requested_ms == chart_ms
        ):
            return True
        message = (
            f"time()/time_close() requested timeframe {timeframe!r}, but PineLib v1.0.1 only supports "
            "None or the active chart timeframe; non-chart timeframe aggregation is unsupported"
        )
        runtime.config.emit_diagnostic(
            PL_UNSUPPORTED_TIMEFRAME_TIMEFUNC,
            message,
            requested_timeframe=timeframe,
            chart_timeframe=runtime.timeframe.value,
        )
        return False

    def _calendar_value(
        self,
        runtime: PineRuntime,
        timezone_name: str | None,
        field_name: str,
    ) -> int:
        if runtime.current_bar is None:
            raise PineSessionError("No current bar is active")
        localized = _localize(_bar_time_ms(runtime), timezone_name or runtime.syminfo.timezone)
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

    def timestamp_components(
        self,
        timezone_str: str,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int,
        second: int = 0,
    ) -> int:
        """Convert timestamp components (per-bar runtime values) to Unix milliseconds."""
        from datetime import timezone as tz_module
        # Clamp year to valid datetime range; out-of-range year would crash datetime()
        if not (1 <= year <= 9999):
            from pinelib.core.na import na as NA
            return NA
        tz_map = {"UTC": tz_module.utc}
        tz = tz_map.get(timezone_str)
        if tz is None:
            try:
                tz = ZoneInfo(timezone_str)
            except (KeyError, ZoneInfoNotFoundError):
                tz = tz_module.utc
        dt = datetime(year, month, day, hour, minute, second, tzinfo=tz)
        return int(dt.timestamp() * 1000)
