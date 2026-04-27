from __future__ import annotations

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

GapsMode = Literal["barmerge.gaps_on", "barmerge.gaps_off"]
LookaheadMode = Literal["barmerge.lookahead_on", "barmerge.lookahead_off"]


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
    for chart_bar in chart_bars:
        value: Any = na
        for requested_bar, requested_value in zip(requested_bars, requested_values, strict=True):
            requested_close = requested_bar.time_close if requested_bar.time_close is not None else requested_bar.time
            chart_close = chart_bar.time_close if chart_bar.time_close is not None else chart_bar.time
            if lookahead == "barmerge.lookahead_on":
                matches = requested_bar.time <= chart_bar.time <= requested_close
            else:
                matches = requested_bar.time <= chart_close and requested_close <= chart_close
            if matches:
                value = requested_value
        if value is na and gaps == "barmerge.gaps_off":
            value = last_value
        elif value is not na:
            last_value = value
        merged.append(value)
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
        if ignore_invalid_symbol:
            return na
        raise PineRequestError("request.security requires runtime.data_provider")

    start = runtime.chart_bars[0].time if runtime.chart_bars else None
    end = runtime.chart_bars[-1].time_close if runtime.chart_bars and runtime.chart_bars[-1].time_close is not None else None
    requested_bars = runtime.data_provider.get_bars(
        symbol,
        timeframe,
        start,
        end,
        max_bars=calc_bars_count,
    )
    if not requested_bars and ignore_invalid_symbol:
        return na

    if isinstance(expression_callable, Sequence) and not callable(expression_callable):
        requested_values = list(expression_callable)
    else:
        child = runtime.spawn_child_context(symbol=symbol, timeframe=timeframe, namespace=state_id)
        child.request_depth = runtime.request_depth + 1
        requested_values = []
        expression = expression_callable
        if not callable(expression):
            raise PineRequestError("request.security expression must be callable or a value sequence")
        for bar in requested_bars:
            child.begin_bar(bar)
            requested_values.append(expression(child))
            child.end_bar()

    merged = merge_requested_series_to_chart_bars(
        requested_values,
        requested_bars=requested_bars,
        chart_bars=runtime.chart_bars,
        gaps=gaps,
        lookahead=lookahead,
    )
    index = runtime.bar_index + 1 if runtime.current_bar is not None else runtime.bar_index
    if index < 0 or index >= len(merged):
        return na
    return merged[index]


def _bar_close_time(bar: Bar) -> int:
    return bar.time_close if bar.time_close is not None else bar.time


def _bars_inside_chart_bar(lower_bars: Sequence[Bar], chart_bar: Bar) -> list[Bar]:
    """Return fully closed intrabars for a chart bar, ordered oldest to newest."""

    chart_close = _bar_close_time(chart_bar)
    return [bar for bar in lower_bars if chart_bar.time <= bar.time and _bar_close_time(bar) <= chart_close]


def security_lower_tf(
    symbol: str,
    timeframe: str,
    expression_callable: Callable[[Any], Any] | Sequence[Any],
    *,
    runtime: Any,
    state_id: str,
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
    - `calc_bars_count` caps the returned intrabar array for the active chart bar;
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

    if runtime.intrabar_provider is not None:
        requested_bars = runtime.intrabar_provider.get_intrabar_bars(
            symbol,
            runtime.current_bar,
            timeframe,
            max_bars=None,
        )
        selected_bars = _bars_inside_chart_bar(requested_bars, runtime.current_bar)
    else:
        if runtime.data_provider is None:
            if ignore_invalid_symbol:
                return PineArray()
            raise PineRequestError("request.security_lower_tf requires runtime.data_provider or runtime.intrabar_provider")
        chart_start = runtime.chart_bars[0].time if runtime.chart_bars else runtime.current_bar.time
        chart_end = _bar_close_time(runtime.current_bar)
        requested_bars = runtime.data_provider.get_bars(symbol, timeframe, chart_start, chart_end)
        selected_bars = _bars_inside_chart_bar(requested_bars, runtime.current_bar)

    if calc_bars_count is not None:
        selected_bars = selected_bars[:calc_bars_count]
    if not selected_bars:
        return PineArray()

    if isinstance(expression_callable, Sequence) and not callable(expression_callable):
        values = list(expression_callable)
        if len(values) != len(selected_bars):
            raise PineRequestError("request.security_lower_tf precomputed values length must match selected intrabars")
        return PineArray(values)

    expression = expression_callable
    if not callable(expression):
        raise PineRequestError("request.security_lower_tf expression must be callable or a value sequence")

    child = runtime.spawn_child_context(symbol=symbol, timeframe=timeframe, namespace=state_id)
    child.request_depth = runtime.request_depth + 1
    values = []
    for bar in selected_bars:
        child.begin_bar(bar)
        values.append(expression(child))
        child.end_bar()
    return PineArray(values)
