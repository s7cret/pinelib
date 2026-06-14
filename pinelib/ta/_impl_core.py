from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias, cast

from pinelib.core.na import PineNASentinel, SupportsSeriesLike, is_na, na
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError, PineTypeError

Numeric: TypeAlias = int | float
TAValue: TypeAlias = Numeric | object


def _validate_length(length: Any) -> int:
    # Accept Pine input-backed Series (extract scalar from .current), but reject
    # bool before integer coercion because bool is a subclass of int in Python.
    raw_length = length.current if hasattr(length, "current") else length
    if isinstance(raw_length, bool):
        raise PineRuntimeError("TA length must be a positive integer")
    value = int(raw_length)
    if value <= 0:
        raise PineRuntimeError("TA length must be a positive integer")
    return value


def _current(source: Any, function_name: str) -> Any:
    # Avoid runtime Protocol checks in TA hot loops. request.security evaluates
    # this path for every child bar, and isinstance(..., Protocol) goes through
    # typing/inspect machinery.
    value = source[0] if hasattr(source, "current") and hasattr(source, "__getitem__") else source
    # type() is faster than isinstance for exact type check
    if type(value) is bool:
        raise PineTypeError(f"ta.{function_name}() does not accept bool source values")
    return value


def _series_values(source: Sequence[Any]) -> list[Any]:
    if isinstance(source, (int, float)):
        return [source]
    if isinstance(source, PineNASentinel):
        return [source]
    return list(source)


def _unwrap_singleton(x: Any) -> Any:
    """Unwrap singleton list to scalar for single-bar TA results."""
    if isinstance(x, list) and len(x) == 1:
        return x[0]
    return x


@dataclass(slots=True)
class _SmaState:
    length: int
    values: deque[float] = field(default_factory=deque)
    total: float = 0.0

    def update(self, value: Any) -> Any:
        if not is_na(value):
            if type(value) is bool:
                raise PineTypeError("ta.sma() does not accept bool source values")
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
    warmup: deque[float] = field(default_factory=deque)
    warmup_total: float = 0.0

    def update(self, value: Any) -> Any:
        if is_na(value):
            return na if self.value is None else self.value
        number = float(value)
        alpha = 2.0 / (self.length + 1.0)
        if self.value is None:
            self.warmup.append(number)
            self.warmup_total += number
            if len(self.warmup) < self.length:
                return na
            self.value = self.warmup_total / self.length
            return self.value
        self.value = alpha * number + (1.0 - alpha) * self.value
        return self.value


@dataclass(slots=True)
class _RmaState:
    length: int
    value: float | None = None
    warmup: deque[float] = field(default_factory=deque)
    warmup_total: float = 0.0

    def update(self, value: Any) -> Any:
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


def _state(
    runtime: PineRuntime, state_id: str, factory: Callable[[], object], expected: type[Any]
) -> Any:
    state = runtime.get_indicator_state(state_id, factory)
    if not isinstance(state, expected):
        raise PineRuntimeError(f"State id {state_id!r} is already used by another TA helper")
    return state


_rolling_bar_cache: dict[tuple[object, ...], tuple[tuple[Any, Any], Any]] = {}
_valuewhen_cache: dict[tuple[int, int], dict[str, Any]] = {}
_extreme_cache: dict[tuple[str, int, int], dict[str, Any]] = {}


def _bar_token(source: Any) -> tuple[Any, Any]:
    if isinstance(source, SupportsSeriesLike):
        return source.committed_length, source[0]
    return 0, source


def _cached_bar_value(
    key: tuple[object, ...], token: tuple[Any, Any], factory: Callable[[], Any]
) -> Any:
    cached = _rolling_bar_cache.get(key)
    if cached is not None and cached[0] == token:
        return cached[1]
    value = factory()
    _rolling_bar_cache[key] = (token, value)
    return value


def _rolling_extreme(source: Any, length: int, mode: str, *, bars: bool) -> Any:
    history = getattr(source, "_history", None)
    if not isinstance(history, list):
        return None
    state = _extreme_cache.setdefault(
        (mode, id(source), length),
        {"processed": 0, "deque": deque()},
    )
    queue: deque[tuple[int, float]] = state["deque"]
    committed = min(len(history), source.committed_length)
    if int(state.get("processed", 0)) > committed:
        queue.clear()
        state["processed"] = 0
    for idx in range(int(state.get("processed", 0)), committed):
        value = history[idx]
        if is_na(value):
            continue
        number = float(value)
        if mode == "high":
            while queue and queue[-1][1] <= number:
                queue.pop()
        else:
            while queue and queue[-1][1] >= number:
                queue.pop()
        queue.append((idx, number))
    state["processed"] = committed

    current_idx = committed
    cutoff = current_idx - length + 1
    while queue and queue[0][0] < cutoff:
        queue.popleft()

    best_idx: int | None = None
    best_value: float | None = None
    if queue:
        best_idx, best_value = queue[0]
    current = source[0]
    if not is_na(current):
        current_value = float(current)
        if (
            best_value is None
            or (mode == "high" and current_value >= best_value)
            or (mode == "low" and current_value <= best_value)
        ):
            best_idx, best_value = current_idx, current_value
    if best_value is None or best_idx is None:
        return na
    return -(current_idx - best_idx) if bars else best_value


def _batch_unary(source: Sequence[Any], updater: Callable[[Any], Any]) -> list[Any]:
    return [updater(value) for value in _series_values(source)]


def _batch_roc(source: Sequence[Any], length: int) -> list[Any]:
    values = _series_values(source)
    result: list[Any] = []
    for index, current in enumerate(values):
        if index < length:
            result.append(na)
            continue
        previous = values[index - length]
        if is_na(current) or is_na(previous) or float(previous) == 0:
            result.append(na)
        else:
            result.append(100.0 * (float(current) - float(previous)) / float(previous))
    return result


def sma(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
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


@dataclass(slots=True)
class _MedianState:
    length: int
    values: deque[float] = field(default_factory=deque)

    def update(self, value: Any) -> Any:
        if not is_na(value):
            self.values.append(float(value))
            if len(self.values) > self.length:
                self.values.popleft()
        if len(self.values) < self.length:
            return na
        sorted_vals = sorted(self.values)
        mid = len(sorted_vals) // 2
        if len(sorted_vals) % 2 == 0:
            return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0
        return sorted_vals[mid]


def median(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    length = _validate_length(length)
    if runtime is None:
        state = _MedianState(length)
        return _batch_unary(source, state.update)
    if state_id is None:
        raise PineRuntimeError("ta.median() runtime mode requires state_id")
    state = _state(runtime, state_id, lambda: _MedianState(length), _MedianState)
    if state.length != length:
        raise PineRuntimeError("ta.median() length must remain stable for a state_id")
    return state.update(_current(source, "median"))


@dataclass(slots=True)
class _ModeState:
    length: int
    values: deque[float] = field(default_factory=deque)

    def update(self, value: Any) -> Any:
        if not is_na(value):
            self.values.append(float(value))
            if len(self.values) > self.length:
                self.values.popleft()
        if len(self.values) < self.length:
            return na
        from collections import Counter

        counts = Counter(self.values)
        return counts.most_common(1)[0][0]


def mode(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    length = _validate_length(length)
    if runtime is None:
        state = _ModeState(length)
        return _batch_unary(source, state.update)
    if state_id is None:
        raise PineRuntimeError("ta.mode() runtime mode requires state_id")
    state = _state(runtime, state_id, lambda: _ModeState(length), _ModeState)
    if state.length != length:
        raise PineRuntimeError("ta.mode() length must remain stable for a state_id")
    return state.update(_current(source, "mode"))


def ema(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
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


def rma(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
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


def tr(
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
    high: Any = None,
    low: Any = None,
    close: Any = None,
) -> Any:
    if runtime is not None:
        high_value = runtime.high[0]
        low_value = runtime.low[0]
        prev_close = runtime.close[1]
    else:
        high_value = high
        low_value = low
        prev_close = close
    for value in (high_value, low_value):
        if type(value) is bool:
            raise PineTypeError("ta.tr() does not accept bool source values")
    if is_na(high_value) or is_na(low_value):
        return na
    high_number = float(cast(Numeric, high_value))
    low_number = float(cast(Numeric, low_value))
    if is_na(prev_close):
        return high_number - low_number
    if type(prev_close) is bool:
        raise PineTypeError("ta.tr() does not accept bool source values")
    previous = float(cast(Numeric, prev_close))
    return max(high_number - low_number, abs(high_number - previous), abs(low_number - previous))


def tr_batch(high: Sequence[Any], low: Sequence[Any], close: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    prev_close: Any = na
    for high_value, low_value, close_value in zip(high, low, close, strict=True):
        out.append(tr(high=high_value, low=low_value, close=prev_close))
        prev_close = close_value
    return out


def _tr_batch_from_close(close: Sequence[Any]) -> list[Any]:
    """True Range batch from close-only series (close[0] = current bar close)."""
    out: list[Any] = []
    prev_close: Any = na
    for close_value in close:
        # tr(high=close, low=close, close=prev_close) = abs(close - prev_close)
        tr_val = (
            abs(float(close_value) - float(prev_close))
            if not is_na(prev_close) and not is_na(close_value)
            else 0.0
        )
        out.append(tr_val if tr_val >= 0 else 0.0)
        prev_close = close_value
    return out


# === Additional state classes for batch-only TA functions ===
