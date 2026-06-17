from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pinelib.core.na import SupportsSeriesLike, is_na, na
from pinelib.core.precision import pine_gt, pine_gte, pine_lt, pine_lte
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError, PineTypeError
from pinelib.ta._impl_core import (
    _bar_token,
    _batch_unary,
    _cached_bar_value,
    _current,
    _EmaState,
    _MacdState,
    _rolling_extreme,
    _RsiState,
    _series_values,
    _state,
    _validate_length,
    rma,
    tr,
    tr_batch,
)
from pinelib.ta._impl_states import _ChangeState, _HighestState, _LowestState
from pinelib.ta.utils import _condition_history, _history


def atr(
    length: int,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
    high: Sequence[Any] | None = None,
    low: Sequence[Any] | None = None,
    close: Sequence[Any] | None = None,
) -> Any:
    length = _validate_length(length)
    if runtime is None:
        if high is None or low is None or close is None:
            raise PineRuntimeError("ta.atr() batch mode requires high, low, and close sequences")
        return rma(tr_batch(high, low, close), length)
    if state_id is None:
        raise PineRuntimeError("ta.atr() runtime mode requires state_id")
    return rma(tr(runtime=runtime), length, runtime=runtime, state_id=f"{state_id}:rma")


def rsi(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    length = _validate_length(length)
    if runtime is None:
        state = _RsiState(length)
        return _batch_unary(source, state.update)
    if state_id is None:
        raise PineRuntimeError("ta.rsi() runtime mode requires state_id")
    state = _state(runtime, state_id, lambda: _RsiState(length), _RsiState)
    if state.length != length:
        raise PineRuntimeError("ta.rsi() length must remain stable for a state_id")
    return state.update(_current(source, "rsi"))


def macd(
    source: Any,
    fast: int,
    slow: int,
    signal: int,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    fast = _validate_length(fast)
    slow = _validate_length(slow)
    signal = _validate_length(signal)
    if fast >= slow:
        raise PineRuntimeError("ta.macd() fast length must be smaller than slow length")
    if runtime is None:
        state = _MacdState(_EmaState(fast), _EmaState(slow), _EmaState(signal))
        rows = [state.update(value) for value in _series_values(source)]
        return tuple([row[index] for row in rows] for index in range(3))
    if state_id is None:
        raise PineRuntimeError("ta.macd() runtime mode requires state_id")
    state = _state(
        runtime,
        state_id,
        lambda: _MacdState(_EmaState(fast), _EmaState(slow), _EmaState(signal)),
        _MacdState,
    )
    if (state.fast_ema.length, state.slow_ema.length, state.signal_ema.length) != (
        fast,
        slow,
        signal,
    ):
        raise PineRuntimeError("ta.macd() lengths must remain stable for a state_id")
    return state.update(_current(source, "macd"))


def highest(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    length = _validate_length(length)
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.highest() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _HighestState(length), _HighestState)
        if state.length != length:
            raise PineRuntimeError("ta.highest() length must remain stable for a state_id")
        # On first call, seed the deque from series history so the rolling
        # window starts with correct context. This matters when highest() is
        # called lazily (e.g. inside a ternary branch): the deque should reflect
        # the last `length` bars of the source series, not just the first call.
        if not state.values and isinstance(source, SupportsSeriesLike):
            for offset in range(min(length, runtime.bar_index + 1) - 1, -1, -1):
                val = _history(source, offset, "highest")
                if not is_na(val):
                    state.values.append(float(val))
        return state.update(_current(source, "highest"))

    def calc() -> Any:
        if isinstance(source, SupportsSeriesLike):
            cached = _rolling_extreme(source, length, "high", bars=False)
            if cached is not None:
                return cached
        values = [_history(source, offset, "highest") for offset in range(length)]
        numbers = [float(value) for value in values if not is_na(value)]
        return max(numbers) if numbers else na

    if isinstance(source, SupportsSeriesLike):
        return _cached_bar_value(("highest", id(source), length), _bar_token(source), calc)
    return calc()


def lowest(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    length = _validate_length(length)
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.lowest() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _LowestState(length), _LowestState)
        if state.length != length:
            raise PineRuntimeError("ta.lowest() length must remain stable for a state_id")
        # On first call, seed the deque from series history. See highest().
        if not state.values and isinstance(source, SupportsSeriesLike):
            for offset in range(min(length, runtime.bar_index + 1) - 1, -1, -1):
                val = _history(source, offset, "lowest")
                if not is_na(val):
                    state.values.append(float(val))
        return state.update(_current(source, "lowest"))

    def calc() -> Any:
        if isinstance(source, SupportsSeriesLike):
            cached = _rolling_extreme(source, length, "low", bars=False)
            if cached is not None:
                return cached
        values = [_history(source, offset, "lowest") for offset in range(length)]
        numbers = [float(value) for value in values if not is_na(value)]
        return min(numbers) if numbers else na

    if isinstance(source, SupportsSeriesLike):
        return _cached_bar_value(("lowest", id(source), length), _bar_token(source), calc)
    return calc()


def highestbars(source: Any, length: int) -> Any:
    length = _validate_length(length)

    def calc() -> Any:
        if isinstance(source, SupportsSeriesLike):
            cached = _rolling_extreme(source, length, "high", bars=True)
            if cached is not None:
                return cached
        best_offset: int | None = None
        best_value: float | None = None
        for offset in range(length):
            value = _history(source, offset, "highestbars")
            if is_na(value):
                continue
            numeric = float(value)
            if best_value is None or numeric > best_value:
                best_value = numeric
                best_offset = offset
        return na if best_offset is None else -best_offset

    if isinstance(source, SupportsSeriesLike):
        return _cached_bar_value(("highestbars", id(source), length), _bar_token(source), calc)
    return calc()


def lowestbars(source: Any, length: int) -> Any:
    length = _validate_length(length)

    def calc() -> Any:
        if isinstance(source, SupportsSeriesLike):
            cached = _rolling_extreme(source, length, "low", bars=True)
            if cached is not None:
                return cached
        best_offset: int | None = None
        best_value: float | None = None
        for offset in range(length):
            value = _history(source, offset, "lowestbars")
            if is_na(value):
                continue
            numeric = float(value)
            if best_value is None or numeric < best_value:
                best_value = numeric
                best_offset = offset
        return na if best_offset is None else -best_offset

    if isinstance(source, SupportsSeriesLike):
        return _cached_bar_value(("lowestbars", id(source), length), _bar_token(source), calc)
    return calc()


@dataclass(slots=True)
class _CrossState:
    previous_left: Any = na
    previous_right: Any = na
    initialized: bool = False

    def crossover(self, current_left: Any, current_right: Any) -> bool:
        result = (
            self.initialized
            and pine_gt(current_left, current_right)
            and pine_lte(self.previous_left, self.previous_right)
        )
        self.previous_left = current_left
        self.previous_right = current_right
        self.initialized = True
        return bool(result)

    def crossunder(self, current_left: Any, current_right: Any) -> bool:
        result = (
            self.initialized
            and pine_lt(current_left, current_right)
            and pine_gte(self.previous_left, self.previous_right)
        )
        self.previous_left = current_left
        self.previous_right = current_right
        self.initialized = True
        return bool(result)


def change(
    source: Any, length: int = 1, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    length = _validate_length(length)
    if state_id is not None:
        if runtime is None:
            raise PineRuntimeError("ta.change() runtime mode requires runtime")
        state = _state(runtime, state_id, lambda: _ChangeState(length), _ChangeState)
        return state.update(_current(source, "change"))
    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        state = _ChangeState(length)
        return _batch_unary(source, state.update)
    current_value = _history(source, 0, "change")
    previous_value = _history(source, length, "change")
    if type(current_value) is bool:
        raise PineTypeError("ta.change() does not accept bool source values")
    if type(previous_value) is bool:
        raise PineTypeError("ta.change() does not accept bool source values")
    if is_na(current_value) or is_na(previous_value):
        return na
    return float(current_value) - float(previous_value)


def crossover(
    source1: Any, source2: Any, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> bool:
    current_left = _history(source1, 0, "crossover")
    current_right = _history(source2, 0, "crossover")
    if runtime is not None and state_id is not None:
        state = _state(runtime, state_id, _CrossState, _CrossState)
        return state.crossover(current_left, current_right)
    previous_left = _history(source1, 1, "crossover")
    # For _ShiftedSeries, source2[1] = original[shift+1] but we need original[shift]
    # (the value of the shifted series at the previous bar = current_right at prev bar)
    # For non-shifted series, source2[1] correctly gives the previous bar's value
    if hasattr(source2, "source"):  # _ShiftedSeries
        previous_right = _history(source2, 0, "crossover")
    else:
        previous_right = _condition_history(source2, 1)
    return pine_gt(current_left, current_right) and pine_lte(previous_left, previous_right)


def crossunder(
    source1: Any, source2: Any, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> bool:
    current_left = _history(source1, 0, "crossunder")
    current_right = _history(source2, 0, "crossunder")
    if runtime is not None and state_id is not None:
        state = _state(runtime, state_id, _CrossState, _CrossState)
        return state.crossunder(current_left, current_right)
    previous_left = _history(source1, 1, "crossunder")
    # Same shifted-series fix as crossover
    if hasattr(source2, "source"):  # _ShiftedSeries
        previous_right = _history(source2, 0, "crossunder")
    else:
        previous_right = _condition_history(source2, 1)
    return pine_lt(current_left, current_right) and pine_gte(previous_left, previous_right)


def cross(source1: Any, source2: Any) -> bool:
    return crossover(source1, source2) or crossunder(source1, source2)


__all__ = [
    "rma",
    "tr",
    "tr_batch",
    "atr",
    "rsi",
    "macd",
    "highest",
    "lowest",
    "highestbars",
    "lowestbars",
    "change",
    "cross",
    "crossover",
    "crossunder",
]


# --- v0.6.0 extended TA helpers ---
