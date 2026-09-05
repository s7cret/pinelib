from __future__ import annotations

from bisect import bisect_left, bisect_right
from operator import attrgetter

from pinelib.core.values import na
from pinelib.errors import PL_REQUEST_ALIGNMENT, PL_RESOURCE_LIMIT, PineRuntimeError
from pinelib.request.models import (
    DataFinality,
    DatasetStatus,
    GapsMode,
    LookaheadMode,
    RequestDataset,
    RequestKind,
)
from pinelib.request.registry import MergeCursor
from pinelib.runtime.metadata import TimeframeContext

_OPEN = attrgetter("open_time_ms")
_CLOSE = attrgetter("close_time_ms")


def _validate_chart(open_time_ms: int, close_time_ms: int) -> None:
    if (
        type(open_time_ms) is not int
        or type(close_time_ms) is not int
        or close_time_ms <= open_time_ms
    ):
        raise PineRuntimeError(
            "chart bar boundaries are invalid", code=PL_REQUEST_ALIGNMENT
        )


def _last_final_by_close(dataset: RequestDataset, chart_close_ms: int) -> int:
    rows = dataset.evaluated_bars
    index = bisect_right(rows, chart_close_ms, key=_CLOSE) - 1
    while index >= 0 and rows[index].finality != DataFinality.FINAL:
        index -= 1
    return index


def _last_final_before_open(dataset: RequestDataset, exclusive_open_ms: int) -> int:
    rows = dataset.evaluated_bars
    index = bisect_left(rows, exclusive_open_ms, key=_OPEN) - 1
    while index >= 0 and rows[index].finality != DataFinality.FINAL:
        index -= 1
    return index


def align_security(
    dataset: RequestDataset,
    *,
    chart_open_ms: int,
    chart_close_ms: int,
    realtime: bool,
    allow_developing_realtime: bool,
) -> tuple[object, MergeCursor]:
    _validate_chart(chart_open_ms, chart_close_ms)
    query = dataset.key.query
    if query.kind != RequestKind.SECURITY:
        raise PineRuntimeError(
            "request dataset is not a security dataset", code=PL_REQUEST_ALIGNMENT
        )
    if dataset.status == DatasetStatus.INVALID_SYMBOL or not dataset.evaluated_bars:
        return na, MergeCursor(
            "security", dataset.key.key_hash, chart_open_ms, chart_close_ms, -1, -1
        )

    rows = dataset.evaluated_bars
    selected = -1
    updated = False
    if realtime:
        candidate = bisect_left(rows, chart_close_ms, key=_OPEN) - 1
        if candidate >= 0:
            row = rows[candidate]
            overlaps = (
                row.open_time_ms < chart_close_ms and row.close_time_ms > chart_open_ms
            )
            usable = row.finality == DataFinality.FINAL or allow_developing_realtime
            if overlaps and usable:
                selected = candidate
                updated = True
        if selected < 0:
            selected = _last_final_by_close(dataset, chart_close_ms)
            if selected >= 0:
                row = rows[selected]
                updated = chart_open_ms < row.close_time_ms <= chart_close_ms
    elif query.lookahead == LookaheadMode.OFF:
        selected = _last_final_by_close(dataset, chart_close_ms)
        if selected >= 0:
            row = rows[selected]
            updated = chart_open_ms < row.close_time_ms <= chart_close_ms
    else:
        # Pine lookahead observes a higher-timeframe value as soon as that HTF
        # bar opens, including when the opening lies strictly inside a chart bar.
        seconds = TimeframeContext.parse(query.timeframe).seconds
        if seconds is not None and seconds * 1000 < chart_close_ms - chart_open_ms:
            # Historical lower-TF lookahead_on selects the first intrabar.
            start = bisect_left(rows, chart_open_ms, key=_OPEN)
            stop = bisect_right(rows, chart_close_ms, lo=start, key=_CLOSE)
            selected = next((i for i in range(start, stop)
                             if rows[i].finality == DataFinality.FINAL), -1)
            updated = selected >= 0
            if selected < 0:
                selected = _last_final_by_close(dataset, chart_open_ms)
        else:
            selected = _last_final_before_open(dataset, chart_close_ms)
            if selected >= 0:
                row = rows[selected]
                updated = chart_open_ms <= row.open_time_ms < chart_close_ms

    cursor = MergeCursor(
        "security",
        dataset.key.key_hash,
        chart_open_ms,
        chart_close_ms,
        selected,
        selected,
    )
    developing_gap = (
        selected >= 0
        and realtime
        and query.gaps == GapsMode.ON
        and rows[selected].finality != DataFinality.FINAL
    )
    if selected < 0 or developing_gap or (query.gaps == GapsMode.ON and not updated):
        return na, cursor
    return dataset.value(selected), cursor


def align_lower_timeframe(
    dataset: RequestDataset,
    *,
    chart_open_ms: int,
    chart_close_ms: int,
    realtime: bool,
    allow_developing_realtime: bool,
    max_intrabars: int,
) -> tuple[tuple[object, ...], MergeCursor]:
    _validate_chart(chart_open_ms, chart_close_ms)
    query = dataset.key.query
    if query.kind != RequestKind.SECURITY_LOWER_TF:
        raise PineRuntimeError(
            "request dataset is not a lower-timeframe dataset",
            code=PL_REQUEST_ALIGNMENT,
        )
    if dataset.status == DatasetStatus.INVALID_SYMBOL or not dataset.evaluated_bars:
        return (), MergeCursor(
            "security_lower_tf",
            dataset.key.key_hash,
            chart_open_ms,
            chart_close_ms,
            -1,
            -1,
        )

    rows = dataset.evaluated_bars
    start = bisect_left(rows, chart_open_ms, key=_OPEN)
    stop = bisect_right(rows, chart_close_ms, lo=start, key=_CLOSE)
    indexes = [
        index
        for index in range(start, stop)
        if rows[index].open_time_ms >= chart_open_ms
        and rows[index].close_time_ms <= chart_close_ms
        and (
            rows[index].finality == DataFinality.FINAL
            or (realtime and allow_developing_realtime)
        )
    ]
    if len(indexes) > max_intrabars:
        raise PineRuntimeError(
            "lower-timeframe intrabar limit exceeded", code=PL_RESOURCE_LIMIT
        )
    cursor = MergeCursor(
        "security_lower_tf",
        dataset.key.key_hash,
        chart_open_ms,
        chart_close_ms,
        indexes[0] if indexes else -1,
        indexes[-1] if indexes else -1,
    )
    return tuple(dataset.value(index) for index in indexes), cursor
