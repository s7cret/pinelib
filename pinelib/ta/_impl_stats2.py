from __future__ import annotations

import math as _py_math
from collections.abc import Sequence
from typing import Any

from pinelib.core.na import SupportsSeriesLike, is_na, na
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError
from pinelib.ta._impl_core import (
    _batch_roc,
    _current,
    _state,
    _validate_length,
)
from pinelib.ta._impl_momentum import change
from pinelib.ta._impl_states import (
    _CorrelationState,
    _MeanDevState,
    _RocState,
    _SourceMfiState,
    _VwapState,
)
from pinelib.ta._impl_statistics import _rolling
from pinelib.ta.utils import _condition_history, _history

_valuewhen_cache: dict[tuple[int, int], dict[str, Any]] = {}


def valuewhen(condition: Any, source: Any, occurrence: int) -> Any:
    if occurrence < 0:
        raise PineRuntimeError("ta.valuewhen() occurrence must be >= 0")
    if isinstance(condition, SupportsSeriesLike) and isinstance(source, SupportsSeriesLike):
        state = _valuewhen_cache.setdefault((id(condition), id(source)), {})
        condition_history = getattr(condition, "_history", None)
        source_history = getattr(source, "_history", None)
        if isinstance(condition_history, list) and isinstance(source_history, list):
            hits = state.setdefault("hits", [])
            processed = int(state.get("processed", 0))
            committed = min(len(condition_history), len(source_history), condition.committed_length)
            if processed > committed:
                hits.clear()
                processed = 0
            for idx in range(processed, committed):
                cv = condition_history[idx]
                if (not is_na(cv)) and bool(cv):
                    hits.insert(0, source_history[idx])
            state["processed"] = committed
            cv = condition[0]
            if (not is_na(cv)) and bool(cv):
                return (
                    source[0]
                    if occurrence == 0
                    else (hits[occurrence - 1] if occurrence - 1 < len(hits) else na)
                )
            return hits[occurrence] if occurrence < len(hits) else na

        # Fallback for derived series: pay the history scan once for this bar.
        token = (condition.committed_length, condition[0], source[0])
        if state.get("token") != token:
            hits: list[Any] = []
            for off in range(10000, 0, -1):
                cv = _condition_history(condition, off)
                if (not is_na(cv)) and bool(cv):
                    hits.append(_history(source, off, "valuewhen"))
            cv = condition[0]
            if (not is_na(cv)) and bool(cv):
                hits.append(source[0])
            state["token"] = token
            state["derived_hits"] = list(reversed(hits))
        hits = state.get("derived_hits", [])
        return hits[occurrence] if occurrence < len(hits) else na
    hits: list[Any] = []
    if (
        isinstance(condition, Sequence)
        and isinstance(source, Sequence)
        and not isinstance(condition, SupportsSeriesLike)
    ):
        out = []
        for i in range(len(condition)):
            if bool(condition[i]):
                hits.insert(0, source[i])
            out.append(hits[occurrence] if occurrence < len(hits) else na)
        return out
    for off in range(0, 10000):
        cv = _condition_history(condition, off)
        if is_na(cv) and off > 0:
            break
        if (not is_na(cv)) and bool(cv):
            hits.append(_history(source, off, "valuewhen"))
            if len(hits) > occurrence:
                return hits[occurrence]
    return na


def barssince(condition: Any) -> Any:
    if isinstance(condition, Sequence) and not isinstance(condition, SupportsSeriesLike):
        last: int | None = None
        out: list[Any] = []
        for i, c in enumerate(condition):
            if bool(c):
                last = i
                out.append(0)
            else:
                out.append(na if last is None else i - last)
        return out
    for off in range(0, 10000):
        cv = _condition_history(condition, off)
        if (not is_na(cv)) and bool(cv):
            return off
        if is_na(cv) and off > 0:
            break
    return na


def linreg(source: Any, length: int, offset: int = 0) -> Any:
    length = _validate_length(length)

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        ys = [float(v) for v in win]
        xs = list(range(length))
        xm = sum(xs) / length
        ym = sum(ys) / length
        den = sum((x - xm) ** 2 for x in xs)
        slope = (
            0.0 if den == 0 else sum((x - xm) * (y - ym) for x, y in zip(xs, ys, strict=True)) / den
        )
        intercept = ym - slope * xm
        return intercept + slope * (length - 1 - offset)

    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, length, calc)
    return calc([_history(source, o, "linreg") for o in reversed(range(length))])


def percentile_nearest_rank(source: Any, length: int, percentage: float) -> Any:
    def calc(win: list[Any]) -> Any:
        vals = sorted(float(v) for v in win if not is_na(v))
        if not vals:
            return na
        rank = max(1, int(_py_math.ceil(float(percentage) / 100.0 * len(vals))))
        return vals[min(rank - 1, len(vals) - 1)]

    return (
        _rolling(source, _validate_length(length), calc)
        if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike)
        else calc([_history(source, o, "percentile_nearest_rank") for o in range(length)])
    )


def percentile_linear_interpolation(source: Any, length: int, percentage: float) -> Any:
    def calc(win: list[Any]) -> Any:
        vals = sorted(float(v) for v in win if not is_na(v))
        if not vals:
            return na
        pos = (len(vals) - 1) * float(percentage) / 100.0
        lo = int(_py_math.floor(pos))
        hi = int(_py_math.ceil(pos))
        return vals[lo] if lo == hi else vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)

    return (
        _rolling(source, _validate_length(length), calc)
        if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike)
        else calc([_history(source, o, "percentile_linear_interpolation") for o in range(length)])
    )


def percentrank(source: Any, length: int) -> Any:
    length = _validate_length(length)

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        cur = float(win[-1])
        return 100.0 * sum(1 for v in win if float(v) <= cur) / len(win)

    return (
        _rolling(source, length, calc)
        if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike)
        else calc([_history(source, o, "percentrank") for o in reversed(range(length))])
    )


def vwap(
    source: Any,
    volume: Any | None = None,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.vwap() runtime mode requires state_id")
        source = _current(runtime.close if source is None else source, "vwap")
        volume = _current(runtime.volume if volume is None else volume, "vwap")
        state = _state(runtime, state_id, _VwapState, _VwapState)
        return state.update(source, volume, runtime.time.current)
    if (
        isinstance(source, Sequence)
        and isinstance(volume, Sequence)
        and not isinstance(source, SupportsSeriesLike)
    ):
        out = []
        num = den = 0.0
        for s, v in zip(source, volume, strict=True):
            if not is_na(s) and not is_na(v):
                num += float(s) * float(v)
                den += float(v)
            out.append(na if den == 0 else num / den)
        return out
    if volume is None:
        raise PineRuntimeError("ta.vwap() requires volume or runtime")
    return _VwapState().update(_current(source, "vwap"), _current(volume, "vwap"))


def mom(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    """momentum() with optional runtime state tracking."""
    return change(source, length, runtime=runtime, state_id=state_id)


def roc(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    """ROC (Rate of Change) with optional runtime state tracking."""
    length = _validate_length(length)
    if state_id is not None:
        if runtime is None:
            raise PineRuntimeError("ta.roc() runtime mode requires runtime")
        state = _state(runtime, state_id, lambda: _RocState(length), _RocState)
        return state.update(_current(source, "roc"))
    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _batch_roc(source, length)
    cur = _history(source, 0, "roc")
    prev = _history(source, length, "roc")
    if is_na(cur) or is_na(prev) or float(prev) == 0:
        return na
    return 100.0 * (float(cur) - float(prev)) / float(prev)


def correlation(
    source1: Any,
    source2: Any,
    length: int,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    length = _validate_length(length)
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.correlation() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _CorrelationState(length), _CorrelationState)
        return state.update(_current(source1, "correlation"), _current(source2, "correlation"))
    if (
        isinstance(source1, Sequence)
        and isinstance(source2, Sequence)
        and not isinstance(source1, SupportsSeriesLike)
        and not isinstance(source2, SupportsSeriesLike)
    ):
        state = _CorrelationState(length)
        return [state.update(left, right) for left, right in zip(source1, source2, strict=False)]
    a = [_history(source1, o, "correlation") for o in reversed(range(length))]
    b = [_history(source2, o, "correlation") for o in reversed(range(length))]
    if any(is_na(v) for v in a + b):
        return na
    xs = [float(v) for v in a]
    ys = [float(v) for v in b]
    xm = sum(xs) / length
    ym = sum(ys) / length
    denx = sum((x - xm) ** 2 for x in xs)
    deny = sum((y - ym) ** 2 for y in ys)
    return (
        na
        if denx == 0 or deny == 0
        else sum((x - xm) * (y - ym) for x, y in zip(xs, ys, strict=True))
        / _py_math.sqrt(denx * deny)
    )


def _trend_window(source: Any, length: int, function_name: str) -> list[Any]:
    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        if len(source) < length + 1:
            return [na]
        return list(reversed(source[-(length + 1) :]))
    return [_history(source, offset, function_name) for offset in range(length + 1)]


def rising(source: Any, length: int) -> bool:
    length = _validate_length(length)
    values = _trend_window(source, length, "rising")
    if any(is_na(value) for value in values):
        return False
    return all(float(values[index]) > float(values[index + 1]) for index in range(length))


def falling(source: Any, length: int) -> bool:
    length = _validate_length(length)
    values = _trend_window(source, length, "falling")
    if any(is_na(value) for value in values):
        return False
    return all(float(values[index]) < float(values[index + 1]) for index in range(length))


def cci(
    source: Any,
    length: int,
    *legacy_args: Any,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    if legacy_args:
        low, close, legacy_length = length, legacy_args[0], legacy_args[1]
        source = [
            (float(h) + float(low_value) + float(c)) / 3
            for h, low_value, c in zip(source, low, close, strict=True)
        ]
        length = legacy_length
    length = _validate_length(length)

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        nums = [float(v) for v in win]
        mean = sum(nums) / length
        mean_dev = sum(abs(v - mean) for v in nums) / length
        return na if mean_dev == 0 else (nums[-1] - mean) / (0.015 * mean_dev)

    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, length, calc)
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.cci() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _MeanDevState(length), _MeanDevState)
        result = state.update(_current(source, "cci"))
        if is_na(result):
            return na
        current, _mean, mean_dev = result
        return na if mean_dev == 0 else (float(current) - float(_mean)) / (0.015 * mean_dev)
    return calc([_history(source, o, "cci") for o in reversed(range(length))])


def mfi(
    source: Any,
    length: int,
    *legacy_args: Any,
    volume: Any | None = None,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    if legacy_args:
        low, close, legacy_volume, legacy_length = (
            length,
            legacy_args[0],
            legacy_args[1],
            legacy_args[2],
        )
        source = [
            (float(h) + float(low_value) + float(c)) / 3
            for h, low_value, c in zip(source, low, close, strict=True)
        ]
        volume = legacy_volume
        length = legacy_length
    length = _validate_length(length)
    if runtime is not None and volume is None:
        volume = runtime.volume
    if volume is None:
        raise PineRuntimeError("ta.mfi() requires volume or runtime")

    def calc(src_win: list[Any], vol_win: list[Any]) -> Any:
        if any(is_na(v) for v in src_win + vol_win):
            return na
        pos = neg = 0.0
        for idx in range(length):
            cur = float(src_win[idx])
            prev = float(src_win[idx + 1])
            flow = cur * float(vol_win[idx])
            if cur > prev:
                pos += flow
            elif cur < prev:
                neg += flow
        if neg == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + pos / neg)

    if (
        isinstance(source, Sequence)
        and isinstance(volume, Sequence)
        and not isinstance(source, SupportsSeriesLike)
    ):
        out: list[Any] = []
        for i in range(len(source)):
            if i < length:
                out.append(na)
            else:
                out.append(
                    calc(
                        list(reversed(source[i - length : i + 1])),
                        list(reversed(volume[i - length + 1 : i + 1])),
                    )
                )
        return out
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.mfi() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _SourceMfiState(length), _SourceMfiState)
        return state.update(_current(source, "mfi"), _current(volume, "mfi"))
    return calc(
        [_history(source, o, "mfi") for o in range(length + 1)],
        [_history(volume, o, "mfi") for o in range(length)],
    )


def obv(
    close: Any, volume: Any, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    out: list[float] = []
    total = 0.0
    prev: Any = na
    for c, v in zip(close, volume, strict=True):
        if not is_na(prev):
            total += (1 if float(c) > float(prev) else -1 if float(c) < float(prev) else 0) * float(
                v
            )
        out.append(total)
        prev = c
    return out
