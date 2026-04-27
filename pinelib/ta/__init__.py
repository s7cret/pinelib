from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias, cast

from pinelib.core.na import SupportsSeriesLike, is_na, na
from pinelib.core.precision import pine_gt, pine_lte, pine_lt, pine_gte
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError, PineTypeError

Numeric: TypeAlias = int | float
TAValue: TypeAlias = Numeric | object


def _validate_length(length: int) -> int:
    if isinstance(length, bool) or int(length) <= 0:
        raise PineRuntimeError("TA length must be a positive integer")
    return int(length)


def _reject_bool(value: Any, function_name: str) -> None:
    if isinstance(value, bool):
        raise PineTypeError(f"ta.{function_name}() does not accept bool source values")


def _current(source: Any, function_name: str) -> Any:
    value = source[0] if isinstance(source, SupportsSeriesLike) else source
    _reject_bool(value, function_name)
    return value


def _history(source: Any, offset: int, function_name: str) -> Any:
    if isinstance(source, SupportsSeriesLike):
        value = source[offset]
    elif offset == 0:
        value = source
    else:
        value = na
    _reject_bool(value, function_name)
    return value


def _series_values(source: Sequence[Any]) -> list[Any]:
    return list(source)


@dataclass(slots=True)
class _SmaState:
    length: int
    values: deque[float] = field(default_factory=deque)
    total: float = 0.0

    def update(self, value: Any) -> Any:
        _reject_bool(value, "sma")
        if not is_na(value):
            number = float(value)
            self.values.append(number)
            self.total += number
            if len(self.values) > self.length:
                self.total -= self.values.popleft()
        if len(self.values) < self.length:
            return na
        return self.total / self.length


@dataclass(slots=True)
class _EmaState:
    length: int
    value: float | None = None

    def update(self, value: Any) -> Any:
        _reject_bool(value, "ema")
        if is_na(value):
            return na if self.value is None else self.value
        number = float(value)
        alpha = 2.0 / (self.length + 1.0)
        self.value = number if self.value is None else alpha * number + (1.0 - alpha) * self.value
        return self.value


@dataclass(slots=True)
class _RmaState:
    length: int
    value: float | None = None
    warmup: deque[float] = field(default_factory=deque)
    warmup_total: float = 0.0

    def update(self, value: Any) -> Any:
        _reject_bool(value, "rma")
        if is_na(value):
            return na if self.value is None else self.value
        number = float(value)
        if self.value is None:
            self.warmup.append(number)
            self.warmup_total += number
            if len(self.warmup) < self.length:
                return na
            self.value = self.warmup_total / self.length
            return self.value
        self.value = (self.value * (self.length - 1) + number) / self.length
        return self.value


@dataclass(slots=True)
class _RsiState:
    length: int
    previous: float | None = None
    gains: deque[float] = field(default_factory=deque)
    losses: deque[float] = field(default_factory=deque)
    avg_gain: float | None = None
    avg_loss: float | None = None

    def update(self, value: Any) -> Any:
        _reject_bool(value, "rsi")
        if is_na(value):
            return na
        number = float(value)
        if self.previous is None:
            self.previous = number
            return na
        change_value = number - self.previous
        self.previous = number
        gain = max(change_value, 0.0)
        loss = max(-change_value, 0.0)
        if self.avg_gain is None or self.avg_loss is None:
            self.gains.append(gain)
            self.losses.append(loss)
            if len(self.gains) < self.length:
                return na
            self.avg_gain = sum(self.gains) / self.length
            self.avg_loss = sum(self.losses) / self.length
        else:
            self.avg_gain = (self.avg_gain * (self.length - 1) + gain) / self.length
            self.avg_loss = (self.avg_loss * (self.length - 1) + loss) / self.length
        if self.avg_loss == 0.0:
            return 100.0 if self.avg_gain != 0.0 else 50.0
        rs = self.avg_gain / self.avg_loss
        return 100.0 - (100.0 / (1.0 + rs))


@dataclass(slots=True)
class _MacdState:
    fast_ema: _EmaState
    slow_ema: _EmaState
    signal_ema: _EmaState

    def update(self, value: Any) -> tuple[Any, Any, Any]:
        fast_value = self.fast_ema.update(value)
        slow_value = self.slow_ema.update(value)
        if is_na(fast_value) or is_na(slow_value):
            return na, na, na
        macd_value = float(fast_value) - float(slow_value)
        signal_value = self.signal_ema.update(macd_value)
        hist_value = na if is_na(signal_value) else macd_value - float(signal_value)
        return macd_value, signal_value, hist_value


def _state(runtime: PineRuntime, state_id: str, factory: Callable[[], object], expected: type[Any]) -> Any:
    state = runtime.get_indicator_state(state_id, factory)
    if not isinstance(state, expected):
        raise PineRuntimeError(f"State id {state_id!r} is already used by another TA helper")
    return state


def _batch_unary(source: Sequence[Any], updater: Callable[[Any], Any]) -> list[Any]:
    return [updater(value) for value in _series_values(source)]


def sma(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    length = _validate_length(length)
    if runtime is None:
        state = _SmaState(length)
        return _batch_unary(source, state.update)
    if state_id is None:
        raise PineRuntimeError("ta.sma() runtime mode requires state_id")
    state = _state(runtime, state_id, lambda: _SmaState(length), _SmaState)
    if state.length != length:
        raise PineRuntimeError("ta.sma() length must remain stable for a state_id")
    return state.update(_current(source, "sma"))


def ema(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    length = _validate_length(length)
    if runtime is None:
        state = _EmaState(length)
        return _batch_unary(source, state.update)
    if state_id is None:
        raise PineRuntimeError("ta.ema() runtime mode requires state_id")
    state = _state(runtime, state_id, lambda: _EmaState(length), _EmaState)
    if state.length != length:
        raise PineRuntimeError("ta.ema() length must remain stable for a state_id")
    return state.update(_current(source, "ema"))


def rma(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    length = _validate_length(length)
    if runtime is None:
        state = _RmaState(length)
        return _batch_unary(source, state.update)
    if state_id is None:
        raise PineRuntimeError("ta.rma() runtime mode requires state_id")
    state = _state(runtime, state_id, lambda: _RmaState(length), _RmaState)
    if state.length != length:
        raise PineRuntimeError("ta.rma() length must remain stable for a state_id")
    return state.update(_current(source, "rma"))


def tr(*, runtime: PineRuntime | None = None, high: Any = None, low: Any = None, close: Any = None) -> Any:
    if runtime is not None:
        high_value = runtime.high[0]
        low_value = runtime.low[0]
        prev_close = runtime.close[1]
    else:
        high_value = high
        low_value = low
        prev_close = close
    for value in (high_value, low_value):
        _reject_bool(value, "tr")
    if is_na(high_value) or is_na(low_value):
        return na
    high_number = float(cast(Numeric, high_value))
    low_number = float(cast(Numeric, low_value))
    if is_na(prev_close):
        return high_number - low_number
    _reject_bool(prev_close, "tr")
    previous = float(cast(Numeric, prev_close))
    return max(high_number - low_number, abs(high_number - previous), abs(low_number - previous))


def tr_batch(high: Sequence[Any], low: Sequence[Any], close: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    prev_close: Any = na
    for high_value, low_value, close_value in zip(high, low, close, strict=True):
        out.append(tr(high=high_value, low=low_value, close=prev_close))
        prev_close = close_value
    return out


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


def rsi(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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
    if (state.fast_ema.length, state.slow_ema.length, state.signal_ema.length) != (fast, slow, signal):
        raise PineRuntimeError("ta.macd() lengths must remain stable for a state_id")
    return state.update(_current(source, "macd"))


def highest(source: Any, length: int) -> Any:
    length = _validate_length(length)
    values = [_history(source, offset, "highest") for offset in range(length)]
    numbers = [float(value) for value in values if not is_na(value)]
    return max(numbers) if numbers else na


def lowest(source: Any, length: int) -> Any:
    length = _validate_length(length)
    values = [_history(source, offset, "lowest") for offset in range(length)]
    numbers = [float(value) for value in values if not is_na(value)]
    return min(numbers) if numbers else na


def change(source: Any, length: int = 1) -> Any:
    length = _validate_length(length)
    current_value = _history(source, 0, "change")
    previous_value = _history(source, length, "change")
    if is_na(current_value) or is_na(previous_value):
        return na
    return float(current_value) - float(previous_value)


def crossover(source1: Any, source2: Any) -> bool:
    current_left = _history(source1, 0, "crossover")
    current_right = _history(source2, 0, "crossover")
    previous_left = _history(source1, 1, "crossover")
    previous_right = _history(source2, 1, "crossover")
    return pine_gt(current_left, current_right) and pine_lte(previous_left, previous_right)


def crossunder(source1: Any, source2: Any) -> bool:
    current_left = _history(source1, 0, "crossunder")
    current_right = _history(source2, 0, "crossunder")
    previous_left = _history(source1, 1, "crossunder")
    previous_right = _history(source2, 1, "crossunder")
    return pine_lt(current_left, current_right) and pine_gte(previous_left, previous_right)


def cross(source1: Any, source2: Any) -> bool:
    return crossover(source1, source2) or crossunder(source1, source2)


__all__ = [
    "sma", "ema", "rma", "tr", "tr_batch", "atr", "rsi", "macd",
    "highest", "lowest", "change", "cross", "crossover", "crossunder",
]
