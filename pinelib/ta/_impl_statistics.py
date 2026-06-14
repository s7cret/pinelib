from __future__ import annotations

import math as _py_math
from collections.abc import Callable, Sequence
from typing import Any

from pinelib.core.na import SupportsSeriesLike, is_na, na
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError
from pinelib.ta._impl_core import (
    _current,
    _state,
    _unwrap_singleton,
    _validate_length,
    sma,
)
from pinelib.ta._impl_states import (
    _HmaState,
    _MeanDevState,
    _VarianceState,
    _VwmaState,
    _WmaState,
)
from pinelib.ta.utils import _history


def _rolling(source: Sequence[Any], length: int, fn: Callable[[list[Any]], Any]) -> list[Any]:
    length = _validate_length(length)
    out: list[Any] = []
    vals = list(source)
    for i in range(len(vals)):
        win = vals[max(0, i - length + 1) : i + 1]
        out.append(fn(win) if len(win) == length else na)
    return out


def stdev(
    source: Any,
    length: int,
    biased: bool = True,
    *,
    runtime: Any = None,
    state_id: str | None = None,
) -> Any:
    length = _validate_length(length)

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        nums = [float(v) for v in win]
        if not biased and len(nums) <= 1:
            return na
        mean = sum(nums) / len(nums)
        denom = len(nums) if biased else len(nums) - 1
        return _py_math.sqrt(sum((x - mean) ** 2 for x in nums) / denom)

    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, length, calc)
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.stdev() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _VarianceState(length, biased), _VarianceState)
        variance_value = state.update(_current(source, "stdev"))
        return na if is_na(variance_value) else _py_math.sqrt(float(variance_value))
    win = [_history(source, offset, "stdev") for offset in reversed(range(length))]
    result = calc(win)
    # Always return scalar for single-bar context (runtime/generated execution).
    # _rolling batch path already returns list for batch callers.
    return result


def variance(
    source: Any,
    length: int,
    biased: bool = True,
    *,
    runtime: Any = None,
    state_id: str | None = None,
) -> Any:
    length = _validate_length(length)

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        nums = [float(v) for v in win]
        if not biased and len(nums) <= 1:
            return na
        mean = sum(nums) / len(nums)
        denom = len(nums) if biased else len(nums) - 1
        return sum((x - mean) ** 2 for x in nums) / denom

    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, length, calc)
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.variance() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _VarianceState(length, biased), _VarianceState)
        return state.update(_current(source, "variance"))
    win = [_history(source, offset, "variance") for offset in reversed(range(length))]
    result = calc(win)
    # Always return scalar for single-bar context (runtime/generated execution).
    # _rolling batch path already returns list for batch callers.
    return result


def dev(source: Any, length: int, *, runtime: Any = None, state_id: str | None = None) -> Any:
    length = _validate_length(length)

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        nums = [float(v) for v in win]
        mean = sum(nums) / len(nums)
        return sum(abs(x - mean) for x in nums) / len(nums)

    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, length, calc)
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.dev() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _MeanDevState(length), _MeanDevState)
        result = state.update(_current(source, "dev"))
        return na if is_na(result) else result[2]
    win = [_history(source, o, "dev") for o in reversed(range(length))]
    result = calc(win)
    # Always return scalar for single-bar context (runtime/generated execution).
    # _rolling batch path already returns list for batch callers.
    return result


def wma(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    length = _validate_length(length)
    weights = list(range(1, length + 1))
    denom = sum(weights)

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        return sum(float(v) * w for v, w in zip(win, weights, strict=True)) / denom

    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.wma() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _WmaState(length), _WmaState)
        return state.update(_current(source, "wma"))
    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, length, calc)
    return calc([_history(source, o, "wma") for o in reversed(range(length))])


def vwma(
    source: Any,
    length: int,
    volume: Any | None = None,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    length = _validate_length(length)
    if runtime is not None and volume is None:
        volume = runtime.volume
    if volume is None:
        raise PineRuntimeError("ta.vwma() requires volume or runtime")

    def calc(src_win: list[Any], vol_win: list[Any]) -> Any:
        if any(is_na(v) for v in src_win + vol_win):
            return na
        den = sum(float(v) for v in vol_win)
        return (
            na
            if den == 0
            else sum(float(s) * float(v) for s, v in zip(src_win, vol_win, strict=True)) / den
        )

    if (
        isinstance(source, Sequence)
        and isinstance(volume, Sequence)
        and not isinstance(source, SupportsSeriesLike)
    ):
        out: list[Any] = []
        for i in range(len(source)):
            if i + 1 < length:
                out.append(na)
            else:
                out.append(
                    calc(list(source[i - length + 1 : i + 1]), list(volume[i - length + 1 : i + 1]))
                )
        return out
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.vwma() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _VwmaState(length), _VwmaState)
        return state.update(_current(source, "vwma"), _current(volume, "vwma"))
    return calc(
        [_history(source, o, "vwma") for o in reversed(range(length))],
        [_history(volume, o, "vwma") for o in reversed(range(length))],
    )


def hma(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    length = _validate_length(length)
    if runtime is None:
        if not isinstance(source, Sequence) or isinstance(source, SupportsSeriesLike):
            raise PineRuntimeError("ta.hma() scalar mode is unsupported; use batch series input")
        half = max(1, length // 2)
        sqrt_len = max(1, int(_py_math.sqrt(length)))
        w1 = wma(source, half)
        w2 = wma(source, length)
        diff = [
            na if is_na(a) or is_na(b) else 2 * float(a) - float(b)
            for a, b in zip(w1, w2, strict=True)
        ]
        return wma(diff, sqrt_len)
    if state_id is None:
        raise PineRuntimeError("ta.hma() runtime mode requires state_id")
    state = _state(runtime, state_id, lambda: _HmaState(length), _HmaState)
    return state.update(_current(source, "hma"))


def swma(source: Any) -> Any:
    weights = [1.0, 2.0, 2.0, 1.0]

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        return sum(float(v) * w for v, w in zip(win, weights, strict=True)) / 6.0

    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, 4, calc)
    return calc([_history(source, o, "swma") for o in reversed(range(4))])


def alma(source: Any, length: int, offset: float, sigma: float, floor: bool = False) -> Any:
    length = _validate_length(length)
    m = offset * (length - 1)
    if floor:
        m = _py_math.floor(m)
    s = length / sigma
    weights = [_py_math.exp(-((i - m) ** 2) / (2 * s * s)) for i in range(length)]
    den = sum(weights)

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        return sum(float(v) * w for v, w in zip(win, weights, strict=True)) / den

    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, length, calc)
    return calc([_history(source, o, "alma") for o in reversed(range(length))])


def bb(
    source: Any, length: int, mult: float, *, runtime: Any = None, state_id: str | None = None
) -> Any:
    # Use runtime path for both sma and stdev so they return scalars consistently.
    # Without runtime: sma/stdev return lists, which breaks generated execution.
    basis = sma(
        source, length, runtime=runtime, state_id=f"{state_id}_bb_sma" if state_id else None
    )
    sd = stdev(source, length, runtime=runtime, state_id=f"{state_id}_bb_sd" if state_id else None)
    # Unwrap singleton lists that may come from batch paths when runtime is None.
    basis = _unwrap_singleton(basis)
    sd = _unwrap_singleton(sd)
    # Scalar path: both basis and sd are scalars (or na)
    if not isinstance(basis, list) and not isinstance(sd, list):
        if is_na(basis) or is_na(sd):
            return na, na, na
        return (
            float(basis),
            float(basis) + float(mult) * float(sd),
            float(basis) - float(mult) * float(sd),
        )
    # Series/list path
    if isinstance(basis, list) and isinstance(sd, list):
        upper = [
            na if is_na(b) or is_na(s) else float(b) + float(mult) * float(s)
            for b, s in zip(basis, sd, strict=True)
        ]
        lower = [
            na if is_na(b) or is_na(s) else float(b) - float(mult) * float(s)
            for b, s in zip(basis, sd, strict=True)
        ]
        return basis, upper, lower
    # Mixed: one is list, one is scalar (shouldn't happen, but handle gracefully)
    return na, na, na


def bbw(
    source: Any, length: int, mult: float, *, runtime: Any = None, state_id: str | None = None
) -> Any:
    basis, upper, lower = bb(source, length, mult, runtime=runtime, state_id=state_id)
    if isinstance(basis, list):
        return [
            (
                na
                if is_na(b) or float(b) == 0 or is_na(u) or is_na(lower_value)
                else 100.0 * (float(u) - float(lower_value)) / float(b)
            )
            for b, u, lower_value in zip(basis, upper, lower, strict=True)
        ]
    if is_na(basis) or float(basis) == 0 or is_na(upper) or is_na(lower):
        return na
    return 100.0 * (float(upper) - float(lower)) / float(basis)
