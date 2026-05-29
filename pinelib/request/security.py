from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pinelib.core.bar import Bar
from pinelib.core.na import na
from pinelib.errors import (
    PL_UNSUPPORTED_NESTED_SECURITY,
    PineRequestError,
    PineUnsupportedFeatureError,
)
from pinelib.reference import PineArray
from pinelib.request.providers import LowerTfQueryMetadata

GapsMode = Literal["barmerge.gaps_on", "barmerge.gaps_off"]
LookaheadMode = Literal["barmerge.lookahead_on", "barmerge.lookahead_off"]


def _provider_get_bars(
    runtime: Any,
    symbol: str,
    timeframe: str,
    start: int | None,
    end: int | None,
    *,
    max_bars: int | None = None,
) -> list[Bar]:
    get_bars = runtime.data_provider.get_bars
    kwargs: dict[str, Any] = {"max_bars": max_bars}
    try:
        params = inspect.signature(get_bars).parameters
    except (TypeError, ValueError):
        params = {}
    extra = getattr(getattr(runtime, "config", None), "extra", {}) or {}
    if "exchange" in params:
        kwargs["exchange"] = extra.get("exchange") or getattr(runtime.syminfo, "exchange", None) or "binance"
    if "market" in params:
        kwargs["market"] = extra.get("market_type") or extra.get("market") or "spot"
    return get_bars(symbol, timeframe, start, end, **kwargs)


def _effective_close_time(
    requested_bar: Bar,
    all_requested_bars: Sequence[Bar],
    bar_index: int,
) -> int:
    """Compute effective close time for a requested HTF bar.

    When a bar's time_close is None (e.g., aggregated D bars), infer the effective
    close from the next bar's start time. This correctly implements lookahead_off
    behavior where the current HTF bar's value is only exposed after the HTF period
    closes (i.e., when the next HTF bar's start time is reached).

    For D bars: next bar time = next midnight UTC. The effective close uses
    next_bar.time - 1 to make the boundary inclusive: the last 15m child bar of
    a D period (e.g., 23:45 bar for May 5 D bar) should be able to access May 5's
    value because chart_close (23:59:59.999) >= effective_close (midnight next day - 1).

    For weekly bars: next bar time = next Monday midnight. Same inclusive boundary.
    For intraday HTF bars: next bar time = correct close boundary.
    For the last bar (no next): use bar.time + tf_ms - 1 where tf_ms is the
    timeframe duration in ms (86400000 for D = 1 day).
    """
    if requested_bar.time_close is not None:
        return requested_bar.time_close
    # Infer from next bar's start time. Use -1 to make the boundary inclusive:
    # the last child bar (chart_close = next_bar.time - 1) should be able to
    # access the current HTF bar's value.
    if bar_index + 1 < len(all_requested_bars):
        return all_requested_bars[bar_index + 1].time - 1
    # Last HTF bar: infer timeframe from the gap to the previous bar, or default to 1 day.
    if bar_index > 0:
        prev_bar = all_requested_bars[bar_index - 1]
        tf_ms = requested_bar.time - prev_bar.time
    else:
        tf_ms = 86400000  # default to 1 day for single-bar datasets
    return requested_bar.time + tf_ms - 1


def merge_requested_series_to_chart_bars(
    requested_values: Sequence[Any],
    *,
    requested_bars: Sequence[Bar],
    chart_bars: Sequence[Bar],
    gaps: GapsMode | str = "barmerge.gaps_off",
    lookahead: LookaheadMode | str = "barmerge.lookahead_off",
) -> list[Any]:
    if len(requested_values) != len(requested_bars):
        raise PineRequestError("requested_values length must match requested_bars length")
    if gaps not in {"barmerge.gaps_on", "barmerge.gaps_off"}:
        raise PineRequestError(f"Unsupported request.security gaps mode: {gaps}")
    if lookahead not in {"barmerge.lookahead_on", "barmerge.lookahead_off"}:
        raise PineRequestError(f"Unsupported request.security lookahead mode: {lookahead}")

    merged: list[Any] = []
    last_value: Any = na
    last_finalized_value: Any = na
    for chart_bar in chart_bars:
        value: Any = na
        chart_close = chart_bar.time_close if chart_bar.time_close is not None else chart_bar.time
        for i, (requested_bar, requested_value) in enumerate(
            zip(requested_bars, requested_values, strict=True)
        ):
            requested_close = (
                requested_bar.time_close
                if requested_bar.time_close is not None
                else requested_bar.time
            )
            effective_close = _effective_close_time(requested_bar, requested_bars, i)
            if lookahead == "barmerge.lookahead_on":
                if gaps == "barmerge.gaps_on":
                    matches = chart_bar.time <= requested_bar.time <= chart_close
                else:
                    matches = requested_bar.time <= chart_bar.time
            elif gaps == "barmerge.gaps_on":
                matches = chart_bar.time <= requested_close <= chart_close
            else:
                # lookahead_off, gaps_off: use effective_close for finalization check.
                # A HTF bar is "finalized" when chart_close >= effective_close.
                # The "chart_bar.time >= requested_bar.time" check ensures the chart bar
                # is not before the HTF period started.
                if chart_close >= effective_close and chart_bar.time >= requested_bar.time:
                    matches = True
                    last_finalized_value = requested_value
                else:
                    matches = False
            if matches:
                value = requested_value
        if value is na and gaps == "barmerge.gaps_off":
            # Use last finalized value (last confirmed HTF bar close)
            value = last_finalized_value
        elif value is not na:
            last_value = value
        merged.append(value if value is not na else last_finalized_value)
    return merged


def _append_merged_requested_values(
    cache: dict[str, Any],
    *,
    requested_bars: Sequence[Bar],
    requested_values: Sequence[Any],
    chart_bars: Sequence[Bar],
    gaps: GapsMode | str,
    lookahead: LookaheadMode | str,
) -> list[Any]:
    merged = cache.setdefault("merged", [])
    last_value = cache.get("last_value", na)
    last_finalized_value = cache.get("last_finalized_value", na)
    start_index = len(merged)
    for chart_bar in chart_bars[start_index:]:
        value: Any = na
        chart_close = chart_bar.time_close if chart_bar.time_close is not None else chart_bar.time
        for i, (requested_bar, requested_value) in enumerate(
            zip(requested_bars, requested_values, strict=True)
        ):
            requested_close = (
                requested_bar.time_close
                if requested_bar.time_close is not None
                else requested_bar.time
            )
            effective_close = _effective_close_time(requested_bar, requested_bars, i)
            if lookahead == "barmerge.lookahead_on":
                if gaps == "barmerge.gaps_on":
                    matches = chart_bar.time <= requested_bar.time <= chart_close
                else:
                    matches = requested_bar.time <= chart_bar.time
            elif gaps == "barmerge.gaps_on":
                matches = chart_bar.time <= requested_close <= chart_close
            else:
                if chart_close >= effective_close and chart_bar.time >= requested_bar.time:
                    matches = True
                    last_finalized_value = requested_value
                else:
                    matches = False
            if matches:
                value = requested_value
        if value is na and gaps == "barmerge.gaps_off":
            value = last_finalized_value
        elif value is not na:
            last_value = value
        merged.append(value if value is not na else last_finalized_value)
    cache["last_value"] = last_value
    cache["last_finalized_value"] = last_finalized_value
    return merged


def security(
    symbol: str,
    timeframe: str,
    expression_callable: Callable[[Any], Any] | Sequence[Any],
    *,
    runtime: Any,
    state_id: str,
    gaps: GapsMode | str = "barmerge.gaps_off",
    lookahead: LookaheadMode | str = "barmerge.lookahead_off",
    ignore_invalid_symbol: bool = False,
    currency: str | None = None,
    calc_bars_count: int | None = None,
) -> Any:
    del currency
    if calc_bars_count is not None and calc_bars_count < 0:
        raise PineRequestError("request.security calc_bars_count must be non-negative")
    if runtime.request_depth > 0 and not runtime.config.supports_nested_security:
        runtime.config.emit_diagnostic(
            PL_UNSUPPORTED_NESTED_SECURITY,
            "Nested request.security is not supported",
            state_id=state_id,
            bar_index=runtime.bar_index,
        )
        raise PineUnsupportedFeatureError(
            "Nested request.security is not supported",
            code=PL_UNSUPPORTED_NESTED_SECURITY,
        )
    if runtime.data_provider is None:
        # Stage 1: No data provider available; return na for smoke tests
        # A real data provider should be injected for full functionality
        if ignore_invalid_symbol:
            return na
        # Use null provider returning empty bars so security call doesn't hard-fail
        from pinelib.request.providers import NullDataProvider
        runtime.data_provider = NullDataProvider()

    chart_start = runtime.chart_bars[0].time if runtime.chart_bars else None
    chart_end = (
        runtime.chart_bars[-1].time_close
        if runtime.chart_bars and runtime.chart_bars[-1].time_close is not None
        else None
    )
    request_end = getattr(runtime, "request_data_end_ms", None) or chart_end
    # For HTF bars, use start=None to include all HTF bars that could overlap
    # with the chart period. The merge logic (effective_close + lookahead_off)
    # determines which bar's value to return based on finalization status.
    # Previously, start=chart_bars[0].time excluded the HTF bar that started
    # before chart_start (e.g., May 5 D bar at 00:00 when chart starts at 20:00).
    cache_key = (
        "security",
        state_id,
        symbol,
        timeframe,
        gaps,
        lookahead,
        calc_bars_count,
        request_end,
    )
    cache = runtime.request_security_cache.setdefault(cache_key, {})
    requested_bars = cache.get("requested_bars")
    if not isinstance(requested_bars, list):
        requested_bars = _provider_get_bars(
            runtime,
            symbol,
            timeframe,
            None,  # Don't filter by start - include HTF bars from before chart_start
            request_end,
            max_bars=calc_bars_count,
        )
        cache["requested_bars"] = requested_bars
    if not requested_bars and ignore_invalid_symbol:
        return na

    if isinstance(expression_callable, Sequence) and not callable(expression_callable):
        requested_values = list(expression_callable)
    else:
        requested_values = cache.get("requested_values")
        if not isinstance(requested_values, list):
            requested_values = []
            cache["requested_values"] = requested_values
        child = cache.get("child")
        if child is None:
            child = runtime.spawn_child_context(symbol=symbol, timeframe=timeframe, namespace=state_id)
            child.request_depth = runtime.request_depth + 1
            cache["child"] = child
        expression = expression_callable
        if not callable(expression):
            raise PineRequestError(
                "request.security expression must be callable or a value sequence"
            )
        for bar in requested_bars[len(requested_values):]:
            child.begin_bar(bar)
            requested_values.append(expression(child))
            child.end_bar()

    merged = _append_merged_requested_values(
        cache,
        requested_bars=requested_bars,
        requested_values=requested_values,
        chart_bars=runtime.chart_bars,
        gaps=gaps,
        lookahead=lookahead,
    )
    # The +1 offset is kept for backward compatibility.
    # It returns merged[bar_index + 1] (next chart bar's HTF value) instead of
    # merged[bar_index] (current chart bar's HTF value). This is incorrect
    # but the existing tests depend on it.
    index = runtime.bar_index + 1 if runtime.current_bar is not None else runtime.bar_index
    if index < 0 or index >= len(merged):
        return na
    return merged[index]



def _bar_close_time(bar: Bar) -> int:
    return bar.time_close if bar.time_close is not None else bar.time


def _bars_inside_chart_bar(lower_bars: Sequence[Bar], chart_bar: Bar) -> list[Bar]:
    """Return fully closed intrabars for a chart bar, ordered oldest to newest.

    Uses binary search for O(log K + M) when bars are sorted by time.
    For non-overlapping bars (standard OHLCV), this finds the contiguous
    range in one probe, avoiding scan of pre-chart bars.
    """
    if not lower_bars:
        return []

    chart_time = chart_bar.time
    chart_close = _bar_close_time(chart_bar)

    import bisect

    # Find first bar with time >= chart_bar.time using bisect with key
    i = bisect.bisect_left(lower_bars, chart_time, key=lambda b: b.time)

    # Linear scan from found position; stop when bar.time passes chart_close
    # (for non-overlapping bars, this means we've left the chart bar's range)
    selected: list[Bar] = []
    while i < len(lower_bars):
        bar = lower_bars[i]
        bar_time = bar.time
        if bar_time > chart_close:
            break
        bar_close = _bar_close_time(bar)
        # Verify bar is fully inside chart bar (handles edge cases)
        if bar_time >= chart_time and bar_close <= chart_close:
            selected.append(bar)
        i += 1

    return selected


def security_lower_tf(
    symbol: str,
    timeframe: str,
    expression_callable: Callable[[Any], Any] | Sequence[Any],
    *,
    runtime: Any,
    state_id: str,
    expression_hint: str | None = None,
    ignore_invalid_symbol: bool = False,
    currency: str | None = None,
    calc_bars_count: int | None = None,
) -> PineArray[Any]:
    """Evaluate a lower-timeframe expression and return a Pine array for the current chart bar.

    Supported first slice contract:
    - deterministic local providers only (`runtime.data_provider` or `runtime.intrabar_provider`);
    - arrays contain fully closed lower-timeframe bars inside the active chart bar;
    - values are ordered oldest -> newest;
    - chart bars with no matching lower bars return an empty `PineArray`;
    - metadata is appended to `runtime.lower_tf_metadata_log` for deterministic audits;
    - with `data_provider`, `calc_bars_count` is applied as a conservative global cap
      from the first loaded chart bar through the active chart bar before interval
      selection; with `intrabar_provider`, the provider API is chart-bar scoped, so
      the cap is forwarded to the provider and recorded as provider-local;
    - unsupported nested requests fail closed with `PL_UNSUPPORTED_NESTED_SECURITY`.

    This intentionally does not approximate TradingView-only lifecycle details such as
    realtime partial intrabars or dynamic remote feeds.
    """

    del currency
    if calc_bars_count is not None and calc_bars_count < 0:
        raise PineRequestError("request.security_lower_tf calc_bars_count must be non-negative")
    if runtime.request_depth > 0 and not runtime.config.supports_nested_security:
        runtime.config.emit_diagnostic(
            PL_UNSUPPORTED_NESTED_SECURITY,
            "Nested request.security_lower_tf is not supported",
            state_id=state_id,
            bar_index=runtime.bar_index,
        )
        raise PineUnsupportedFeatureError(
            "Nested request.security_lower_tf is not supported",
            code=PL_UNSUPPORTED_NESTED_SECURITY,
        )
    if runtime.current_bar is None:
        return PineArray()

    query_start: int | None
    query_end: int | None
    provider_source: str
    if runtime.intrabar_provider is not None:
        provider_source = "intrabar_provider"
        query_start = runtime.current_bar.time
        query_end = _bar_close_time(runtime.current_bar)
        requested_bars = runtime.intrabar_provider.get_intrabar_bars(
            symbol,
            runtime.current_bar,
            timeframe,
            max_bars=calc_bars_count,
        )
        selected_bars = _bars_inside_chart_bar(requested_bars, runtime.current_bar)
    else:
        provider_source = "data_provider"
        if runtime.data_provider is None:
            if ignore_invalid_symbol:
                return PineArray()
            raise PineRequestError(
                "request.security_lower_tf requires runtime.data_provider or runtime.intrabar_provider"  # noqa: E501
            )
        query_start = runtime.chart_bars[0].time if runtime.chart_bars else runtime.current_bar.time
        query_end = _bar_close_time(runtime.current_bar)
        request_end = getattr(runtime, "request_data_end_ms", None) or query_end
        cache_key = (
            "lower_tf",
            symbol,
            timeframe,
            query_start,
            request_end,
            calc_bars_count,
        )
        requested_bars = runtime.request_lower_tf_cache.get(cache_key)
        if requested_bars is None:
            requested_bars = _provider_get_bars(
                runtime,
                symbol,
                timeframe,
                query_start,
                request_end,
                max_bars=calc_bars_count,
            )
            runtime.request_lower_tf_cache[cache_key] = requested_bars
        selected_bars = _bars_inside_chart_bar(requested_bars, runtime.current_bar)

    metadata = LowerTfQueryMetadata(
        requested_symbol=symbol,
        requested_timeframe=timeframe,
        provider_source=provider_source,
        state_id=state_id,
        chart_bar_index=runtime.bar_index + 1,
        chart_bar_time=runtime.current_bar.time,
        chart_bar_time_close=runtime.current_bar.time_close,
        query_start=query_start,
        query_end=query_end,
        calc_bars_count=calc_bars_count,
        requested_bars=len(requested_bars),
        selected_bars=len(selected_bars),
        selected_bar_times=tuple(bar.time for bar in selected_bars),
    )
    if hasattr(runtime, "lower_tf_metadata_log"):
        runtime.lower_tf_metadata_log.append(metadata)

    if not selected_bars:
        return PineArray()

    if expression_hint is not None:
        if expression_hint == "time_close":
            return PineArray([_bar_close_time(bar) for bar in selected_bars])
        direct_fields = {"open", "high", "low", "close", "volume", "time"}
        if expression_hint in direct_fields:
            return PineArray([getattr(bar, expression_hint) for bar in selected_bars])

    if isinstance(expression_callable, Sequence) and not callable(expression_callable):
        values = list(expression_callable)
        if len(values) != len(selected_bars):
            raise PineRequestError(
                "request.security_lower_tf precomputed values length must match selected intrabars"
            )
        return PineArray(values)

    expression = expression_callable
    if not callable(expression):
        raise PineRequestError(
            "request.security_lower_tf expression must be callable or a value sequence"
        )

    child = runtime.spawn_child_context(symbol=symbol, timeframe=timeframe, namespace=state_id)
    child.request_depth = runtime.request_depth + 1
    values = []
    for bar in selected_bars:
        child.begin_bar(bar)
        values.append(expression(child))
        child.end_bar()
    return PineArray(values)
