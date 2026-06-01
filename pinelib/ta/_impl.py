from __future__ import annotations

import math as _py_math
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias, cast

from pinelib.core.na import PineNASentinel, SupportsSeriesLike, is_na, na
from pinelib.core.precision import pine_gt, pine_gte, pine_lt, pine_lte
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError, PineTypeError
from pinelib.ta.utils import _condition_history, _history

Numeric: TypeAlias = int | float
TAValue: TypeAlias = Numeric | object


def _validate_length(length: Any) -> int:
    # Accept Pine input-backed Series (extract scalar from .current)
    length = int(length.current) if hasattr(length, "current") else int(length)
    if isinstance(length, bool) or length <= 0:
        raise PineRuntimeError("TA length must be a positive integer")
    return length


def _current(source: Any, function_name: str) -> Any:
    # Inlined bool rejection: faster than isinstance + function call
    value = source[0] if isinstance(source, SupportsSeriesLike) else source
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


@dataclass(slots=True)
class _SarState:
    """State for SAR calculation."""

    start: float
    inc: float
    max_val: float
    long: bool = True
    af: float = 0.02
    ep: float = 0.0
    sarv: float = 0.0
    first_bar: bool = True

    def update(self, high: Any, low: Any) -> Any:
        if is_na(high) or is_na(low):
            return na
        h = float(high)
        low_value = float(low)
        if self.first_bar:
            self.ep = h
            self.sarv = low_value
            self.first_bar = False
            self.af = self.start
            return na
        prev = self.sarv
        self.sarv = prev + self.af * (self.ep - prev)
        if self.long:
            if low_value < self.sarv:
                self.long = False
                self.sarv = self.ep
                self.ep = low_value
                self.af = self.start
            elif h > self.ep:
                self.ep = h
                self.af = min(self.af + self.inc, self.max_val)
        else:
            if h > self.sarv:
                self.long = True
                self.sarv = self.ep
                self.ep = h
                self.af = self.start
            elif low_value < self.ep:
                self.ep = low_value
                self.af = min(self.af + self.inc, self.max_val)
        return self.sarv


@dataclass(slots=True)
class _HighestState:
    """State for highest() calculation."""

    length: int
    values: deque[float] = field(default_factory=deque)

    def update(self, value: Any) -> Any:
        if is_na(value):
            return na
        number = float(value)
        self.values.append(number)
        if len(self.values) > self.length:
            self.values.popleft()
        if len(self.values) < self.length:
            return na
        return max(self.values)


@dataclass(slots=True)
class _LowestState:
    """State for lowest() calculation."""

    length: int
    values: deque[float] = field(default_factory=deque)

    def update(self, value: Any) -> Any:
        if is_na(value):
            return na
        number = float(value)
        self.values.append(number)
        if len(self.values) > self.length:
            self.values.popleft()
        if len(self.values) < self.length:
            return na
        return min(self.values)


@dataclass(slots=True)
class _CciState:
    """State for CCI calculation."""

    length: int
    typical_prices: deque[float] = field(default_factory=deque)

    def update(self, high: Any, low: Any, close: Any) -> Any:
        if is_na(high) or is_na(low) or is_na(close):
            return na
        h = float(high)
        low_value = float(low)
        c = float(close)
        tp = (h + low_value + c) / 3.0
        self.typical_prices.append(tp)
        if len(self.typical_prices) > self.length:
            self.typical_prices.popleft()
        if len(self.typical_prices) < self.length:
            return na
        sma_tp = sum(self.typical_prices) / self.length
        mean_dev = sum(abs(tp - v) for v in self.typical_prices) / self.length
        if mean_dev == 0:
            return na
        return (tp - sma_tp) / (0.015 * mean_dev)


class _MfiState:
    """State for MFI (Money Flow Index) calculation."""

    __slots__ = ("length", "typical_prices", "raw_mfs", "pos_sum", "neg_sum")

    def __init__(self, length: int) -> None:
        self.length: int = length
        self.typical_prices: deque[float] = deque()
        self.raw_mfs: deque[float] = deque()
        self.pos_sum: float = 0.0
        self.neg_sum: float = 0.0

    def update(self, high: Any, low: Any, close: Any, volume: Any) -> Any:
        if is_na(high) or is_na(low) or is_na(close) or is_na(volume):
            return na
        tp = (float(high) + float(low) + float(close)) / 3.0
        mf = tp * float(volume)
        prev_tp = self.typical_prices[-1] if self.typical_prices else None
        self.typical_prices.append(tp)
        self.raw_mfs.append(mf)
        if len(self.typical_prices) > self.length:
            oldest_tp = self.typical_prices[0]
            oldest_mf = self.raw_mfs[0]
            self.typical_prices.popleft()
            self.raw_mfs.popleft()
            # Subtract oldest from cumulative sums
            if oldest_tp is not None:
                if len(self.typical_prices) >= 2 and oldest_tp < self.typical_prices[1]:
                    self.pos_sum -= oldest_mf
                elif len(self.typical_prices) >= 2 and oldest_tp > self.typical_prices[1]:
                    self.neg_sum -= oldest_mf
        # Add current to cumulative sums
        if prev_tp is not None:
            if tp > prev_tp:
                self.pos_sum += mf
            elif tp < prev_tp:
                self.neg_sum += mf
        if len(self.typical_prices) < self.length:
            return na
        if self.neg_sum == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + self.pos_sum / self.neg_sum)


@dataclass(slots=True)
class _CmoState:
    """State for Chande Momentum Oscillator (CMO) calculation."""

    length: int
    prev_value: float | None = None
    changes: deque[float] = field(default_factory=deque)
    pos_sum: float = 0.0
    neg_sum: float = 0.0

    def update(self, value: Any) -> Any:
        if is_na(value):
            return na
        number = float(value)
        if self.prev_value is None:
            self.prev_value = number
            return na
        change = number - self.prev_value
        self.prev_value = number
        # Add current change to rolling sums
        if change > 0:
            self.pos_sum += change
        elif change < 0:
            self.neg_sum += abs(change)
        # Remove oldest change if window exceeded
        if len(self.changes) >= self.length:
            oldest = self.changes.popleft()
            if oldest > 0:
                self.pos_sum = max(0.0, self.pos_sum - oldest)
            elif oldest < 0:
                self.neg_sum = max(0.0, self.neg_sum - abs(oldest))
        self.changes.append(change)
        if len(self.changes) < self.length:
            return na
        denom = self.pos_sum + self.neg_sum
        if denom == 0:
            return na
        return 100.0 * (self.pos_sum - self.neg_sum) / denom


@dataclass(slots=True)
class _TsiState:
    """State for True Strength Index (TSI) calculation."""

    short_length: int
    long_length: int
    prev_value: float | None = None
    momentum: deque[float] = field(default_factory=deque)
    abs_momentum: deque[float] = field(default_factory=deque)
    ema1: float | None = None
    ema1_abs: float | None = None
    ema2: float | None = None
    ema2_abs: float | None = None
    warmup_count: int = 0

    def update(self, value: Any) -> Any:
        if is_na(value):
            return na
        number = float(value)
        if self.prev_value is None:
            self.prev_value = number
            self.warmup_count = 0
            return na
        momentum = number - self.prev_value
        abs_momentum = abs(momentum)
        self.prev_value = number
        self.warmup_count += 1
        # Remove oldest if window exceeded
        if len(self.momentum) >= self.long_length:
            self.momentum.popleft()
            self.abs_momentum.popleft()
        self.momentum.append(momentum)
        self.abs_momentum.append(abs_momentum)
        if self.warmup_count < self.long_length:
            return na
        # Double EMA smoothing: first EMA with short_length
        alpha_s = 2.0 / (self.short_length + 1)
        ema_val = momentum if self.ema1 is None else alpha_s * momentum + (1 - alpha_s) * self.ema1
        ema_abs_val = (
            abs_momentum
            if self.ema1_abs is None
            else alpha_s * abs_momentum + (1 - alpha_s) * self.ema1_abs
        )
        self.ema1 = ema_val
        self.ema1_abs = ema_abs_val
        # Second EMA with long_length
        alpha_l = 2.0 / (self.long_length + 1)
        ema2_val = (
            self.ema1 if self.ema2 is None else alpha_l * self.ema1 + (1 - alpha_l) * self.ema2
        )
        ema2_abs_val = (
            self.ema1_abs
            if self.ema2_abs is None
            else alpha_l * self.ema1_abs + (1 - alpha_l) * self.ema2_abs
        )
        self.ema2 = ema2_val
        self.ema2_abs = ema2_abs_val
        if self.ema2_abs == 0:
            return na
        return self.ema2 / self.ema2_abs


@dataclass(slots=True)
class _ObvState:
    """State for OBV calculation."""

    prev_close: float | None = None
    obv: float = 0.0

    def update(self, close: Any, volume: Any) -> Any:
        if is_na(close) or is_na(volume):
            return na
        c = float(close)
        v = float(volume)
        if self.prev_close is None:
            self.prev_close = c
            self.obv = v
        else:
            if c > self.prev_close:
                self.obv += v
            elif c < self.prev_close:
                self.obv -= v
            self.prev_close = c
        return self.obv


@dataclass(slots=True)
class _HmaState:
    """State for Hull MA calculation."""

    length: int
    half_length: int = field(init=False)
    sqrt_length: int = field(init=False)
    wma_half_vals: deque[float] = field(default_factory=deque)
    wma_full_vals: deque[float] = field(default_factory=deque)
    results: deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        object.__setattr__(self, "half_length", max(1, self.length // 2))
        object.__setattr__(self, "sqrt_length", max(1, int(_py_math.sqrt(self.length))))

    def update(self, value: Any) -> Any:
        if is_na(value):
            return na
        number = float(value)
        n = self.length
        half_n = self.half_length
        sqrt_n = self.sqrt_length
        self.wma_half_vals.append(number)
        if len(self.wma_half_vals) > half_n:
            self.wma_half_vals.popleft()
        self.wma_full_vals.append(number)
        if len(self.wma_full_vals) > n:
            self.wma_full_vals.popleft()
        if len(self.wma_full_vals) < n:
            return na
        half_list = list(self.wma_half_vals)
        full_list = list(self.wma_full_vals)
        half_wts = list(range(1, len(half_list) + 1))
        half_wma = (
            sum(w * v for w, v in zip(half_wts, half_list, strict=True)) / sum(half_wts)
            if half_wts
            else 0
        )
        full_wts = list(range(1, len(full_list) + 1))
        full_wma = sum(w * v for w, v in zip(full_wts, full_list, strict=True)) / sum(full_wts)
        raw = 2 * half_wma - full_wma
        self.results.append(raw)
        if len(self.results) > sqrt_n:
            self.results.popleft()
        if len(self.results) < sqrt_n:
            return na
        results_list = list(self.results)
        res_wts = list(range(1, len(results_list) + 1))
        return sum(w * v for w, v in zip(res_wts, results_list, strict=True)) / sum(res_wts)


@dataclass(slots=True)
class _WmaState:
    """State for WMA calculation."""

    length: int
    values: deque[float] = field(default_factory=deque)
    total: float = 0.0
    weighted_total: float = 0.0

    def update(self, value: Any) -> Any:
        if is_na(value):
            return na
        number = float(value)
        if len(self.values) >= self.length:
            oldest = self.values.popleft()
            self.weighted_total = self.weighted_total - self.total + self.length * number
            self.total = self.total - oldest + number
        else:
            self.weighted_total += (len(self.values) + 1) * number
            self.total += number
        self.values.append(number)
        if len(self.values) < self.length:
            return na
        return self.weighted_total / (self.length * (self.length + 1) / 2.0)


@dataclass(slots=True)
class _VwmaState:
    """State for VWMA calculation."""

    length: int
    values: deque[float] = field(default_factory=deque)
    volumes: deque[float] = field(default_factory=deque)
    weighted_total: float = 0.0
    volume_total: float = 0.0

    def update(self, value: Any, volume: Any) -> Any:
        if is_na(value) or is_na(volume):
            return na
        number = float(value)
        vol = float(volume)
        self.values.append(number)
        self.volumes.append(vol)
        self.weighted_total += number * vol
        self.volume_total += vol
        if len(self.values) > self.length:
            old_value = self.values.popleft()
            old_volume = self.volumes.popleft()
            self.weighted_total -= old_value * old_volume
            self.volume_total -= old_volume
        if len(self.values) < self.length:
            return na
        return na if self.volume_total == 0 else self.weighted_total / self.volume_total


@dataclass(slots=True)
class _VarianceState:
    length: int
    biased: bool = True
    values: deque[Any] = field(default_factory=deque)
    total: float = 0.0
    total_sq: float = 0.0
    na_count: int = 0

    def update(self, value: Any) -> Any:
        self.values.append(value)
        if is_na(value):
            self.na_count += 1
        else:
            number = float(value)
            self.total += number
            self.total_sq += number * number
        if len(self.values) > self.length:
            old = self.values.popleft()
            if is_na(old):
                self.na_count -= 1
            else:
                old_number = float(old)
                self.total -= old_number
                self.total_sq -= old_number * old_number
        if len(self.values) < self.length or self.na_count:
            return na
        if not self.biased and self.length <= 1:
            return na
        denom = self.length if self.biased else self.length - 1
        mean = self.total / self.length
        value = (self.total_sq - self.length * mean * mean) / denom
        return max(0.0, value)


@dataclass(slots=True)
class _MeanDevState:
    length: int
    values: deque[Any] = field(default_factory=deque)

    def update(self, value: Any) -> Any:
        self.values.append(value)
        if len(self.values) > self.length:
            self.values.popleft()
        if len(self.values) < self.length or any(is_na(v) for v in self.values):
            return na
        nums = [float(v) for v in self.values]
        mean = sum(nums) / self.length
        return nums[-1], mean, sum(abs(v - mean) for v in nums) / self.length


@dataclass(slots=True)
class _CorrelationState:
    length: int
    values1: deque[Any] = field(default_factory=deque)
    values2: deque[Any] = field(default_factory=deque)

    def update(self, value1: Any, value2: Any) -> Any:
        self.values1.append(value1)
        self.values2.append(value2)
        if len(self.values1) > self.length:
            self.values1.popleft()
            self.values2.popleft()
        if (
            len(self.values1) < self.length
            or any(is_na(v) for v in self.values1)
            or any(is_na(v) for v in self.values2)
        ):
            return na
        xs = [float(v) for v in self.values1]
        ys = [float(v) for v in self.values2]
        xm = sum(xs) / self.length
        ym = sum(ys) / self.length
        denx = sum((x - xm) ** 2 for x in xs)
        deny = sum((y - ym) ** 2 for y in ys)
        if denx == 0 or deny == 0:
            return na
        return sum((x - xm) * (y - ym) for x, y in zip(xs, ys, strict=True)) / _py_math.sqrt(
            denx * deny
        )


@dataclass(slots=True)
class _SourceMfiState:
    length: int
    sources: deque[float] = field(default_factory=deque)
    flows: deque[float] = field(default_factory=deque)
    pos_sum: float = 0.0
    neg_sum: float = 0.0

    def update(self, source: Any, volume: Any) -> Any:
        if is_na(source) or is_na(volume):
            return na
        current = float(source)
        flow = current * float(volume)
        previous = self.sources[-1] if self.sources else None
        if previous is not None:
            self.flows.append(flow)
            if current > previous:
                self.pos_sum += flow
            elif current < previous:
                self.neg_sum += flow
        self.sources.append(current)
        if len(self.sources) > self.length + 1:
            old = self.sources.popleft()
            next_old = self.sources[0]
            old_flow = self.flows.popleft()
            if next_old > old:
                self.pos_sum -= old_flow
            elif next_old < old:
                self.neg_sum -= old_flow
        if len(self.sources) <= self.length:
            return na
        if self.neg_sum == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + self.pos_sum / self.neg_sum)


@dataclass(slots=True)
class _ChangeState:
    """State for change() calculation."""

    length: int
    prev_values: deque[float] = field(default_factory=deque)

    def update(self, value: Any) -> Any:
        if is_na(value):
            return na
        number = float(value)
        self.prev_values.append(number)
        if len(self.prev_values) > self.length + 1:
            self.prev_values.popleft()
        if len(self.prev_values) < self.length + 1:
            return na
        return number - self.prev_values[0]


@dataclass(slots=True)
class _RocState:
    """State for ROC calculation."""

    length: int
    prev_values: deque[float] = field(default_factory=deque)

    def update(self, value: Any) -> Any:
        if is_na(value):
            return na
        number = float(value)
        self.prev_values.append(number)
        if len(self.prev_values) > self.length + 1:
            self.prev_values.popleft()
        if len(self.prev_values) < self.length + 1:
            return na
        prev = self.prev_values[0]
        if prev == 0:
            return na
        return 100.0 * (number - prev) / prev


class _VwapState:
    """State for VWAP calculation."""

    __slots__ = ("cumulative_volume", "cumulative_price_volume", "session_key")

    def __init__(self) -> None:
        self.cumulative_volume: float = 0.0
        self.cumulative_price_volume: float = 0.0
        self.session_key: int | None = None

    def update(self, source: Any, volume: Any, time_value: Any = None) -> Any:
        if is_na(source) or is_na(volume):
            return na
        if time_value is not None and not is_na(time_value):
            key = int(time_value) // 86_400_000
            if self.session_key is None:
                self.session_key = key
            elif key != self.session_key:
                self.session_key = key
                self.cumulative_volume = 0.0
                self.cumulative_price_volume = 0.0
        s = float(source)
        v = float(volume)
        self.cumulative_volume += v
        self.cumulative_price_volume += s * v
        if self.cumulative_volume == 0:
            return na
        return self.cumulative_price_volume / self.cumulative_volume


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
    "sma",
    "ema",
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
            na
            if is_na(b) or float(b) == 0 or is_na(u) or is_na(lower_value)
            else 100.0 * (float(u) - float(lower_value)) / float(b)
            for b, u, lower_value in zip(basis, upper, lower, strict=True)
        ]
    if is_na(basis) or float(basis) == 0 or is_na(upper) or is_na(lower):
        return na
    return 100.0 * (float(upper) - float(lower)) / float(basis)


def stoch(
    source: Any,
    high: Any,
    low: Any,
    length: int,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    length = _validate_length(length)

    def calc(src: Any, highs: list[Any], lows: list[Any]) -> Any:
        if is_na(src) or any(is_na(v) for v in highs + lows):
            return na
        lo = min(float(v) for v in lows)
        hi = max(float(v) for v in highs)
        return na if hi == lo else 100.0 * (float(src) - lo) / (hi - lo)

    if (
        isinstance(source, Sequence)
        and isinstance(high, Sequence)
        and isinstance(low, Sequence)
        and not isinstance(source, SupportsSeriesLike)
    ):
        out = []
        for i in range(len(source)):
            out.append(
                na
                if i + 1 < length
                else calc(
                    source[i], list(high[i - length + 1 : i + 1]), list(low[i - length + 1 : i + 1])
                )
            )
        return out
    return calc(
        _history(source, 0, "stoch"),
        [_history(high, o, "stoch") for o in range(length)],
        [_history(low, o, "stoch") for o in range(length)],
    )


@dataclass(slots=True)
class _DmiState:
    di_length: int
    adx_smoothing: int
    rma_tr: Any = field(default_factory=lambda: _RmaState(0))
    rma_plus_dm: Any = field(default_factory=lambda: _RmaState(0))
    rma_minus_dm: Any = field(default_factory=lambda: _RmaState(0))
    rma_dx: Any = field(default_factory=lambda: _RmaState(0))
    prev_h: Any = na
    prev_l: Any = na
    prev_c: Any = na
    _initialized: bool = False

    def __post_init__(self) -> None:
        self.rma_tr = _RmaState(self.di_length)
        self.rma_plus_dm = _RmaState(self.di_length)
        self.rma_minus_dm = _RmaState(self.di_length)
        self.rma_dx = _RmaState(self.adx_smoothing)

    def update(self, high: Any, low: Any, close: Any) -> tuple[Any, Any, Any]:
        h = float(high)
        low_value = float(low)
        if is_na(self.prev_h):
            plus_dm = 0.0
            minus_dm = 0.0
            tr_val = h - low_value
        else:
            up = h - float(self.prev_h)
            down = float(self.prev_l) - low_value
            plus_dm = up if up > down and up > 0 else 0.0
            minus_dm = down if down > up and down > 0 else 0.0
            tr_val = max(
                h - low_value,
                abs(h - float(self.prev_c)),
                abs(low_value - float(self.prev_c)),
            )
        self.prev_h, self.prev_l, self.prev_c = high, low, close
        atr_val = self.rma_tr.update(tr_val)
        plus_rma = self.rma_plus_dm.update(plus_dm)
        minus_rma = self.rma_minus_dm.update(minus_dm)
        if is_na(atr_val) or float(atr_val) == 0:
            return na, na, na
        di_plus = 100 * float(plus_rma) / float(atr_val)
        di_minus = 100 * float(minus_rma) / float(atr_val)
        dx = na if di_plus + di_minus == 0 else 100 * abs(di_plus - di_minus) / (di_plus + di_minus)
        adx_val = self.rma_dx.update(dx)
        return di_plus, di_minus, adx_val


def dmi(
    high: Any,
    low: Any,
    close: Any,
    di_length: int,
    adx_smoothing: int,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.dmi() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _DmiState(di_length, adx_smoothing), _DmiState)
        return state.update(high, low, close)
    if not (
        isinstance(high, Sequence) and isinstance(low, Sequence) and isinstance(close, Sequence)
    ) or isinstance(high, SupportsSeriesLike):
        raise PineRuntimeError("ta.dmi() currently supports batch sequences only")
    di_length = _validate_length(di_length)
    adx_smoothing = _validate_length(adx_smoothing)
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    prev_h: Any = na
    prev_l: Any = na
    prev_c: Any = na
    for h, low_value, c in zip(high, low, close, strict=True):
        if is_na(prev_h):
            plus_dm.append(0.0)
            minus_dm.append(0.0)
            trs.append(float(h) - float(low_value))
        else:
            up = float(h) - float(prev_h)
            down = float(prev_l) - float(low_value)
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
            trs.append(
                max(
                    float(h) - float(low_value),
                    abs(float(h) - float(prev_c)),
                    abs(float(low_value) - float(prev_c)),
                )
            )
        prev_h, prev_l, prev_c = h, low_value, c
    atrs = rma(trs, di_length)
    p = rma(plus_dm, di_length)
    m = rma(minus_dm, di_length)
    plus: list[Any] = []
    minus: list[Any] = []
    dx: list[Any] = []
    for a, pp, mm in zip(atrs, p, m, strict=True):
        if is_na(a) or float(a) == 0:
            plus.append(na)
            minus.append(na)
            dx.append(na)
        else:
            pv = 100 * float(pp) / float(a)
            mv = 100 * float(mm) / float(a)
            plus.append(pv)
            minus.append(mv)
            dx.append(na if pv + mv == 0 else 100 * abs(pv - mv) / (pv + mv))
    return plus, minus, rma(dx, adx_smoothing)


def adx(
    high: Any,
    low: Any,
    close: Any,
    di_length: int,
    adx_smoothing: int,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    return dmi(high, low, close, di_length, adx_smoothing)[2]


@dataclass
class _SupertrendState:
    factor: float
    atr_state_id: str
    upper_band: Any = na
    lower_band: Any = na
    prev_st: Any = na
    direction: int = 0
    prev_close: Any = na

    def update(self, high: Any, low: Any, close: Any, atr_val: Any) -> tuple[Any, int]:
        if is_na(atr_val):
            return na, 0
        h = float(high)
        low_value = float(low)
        c = float(close)
        hl2 = (h + low_value) / 2
        bub = hl2 + self.factor * float(atr_val)
        blb = hl2 - self.factor * float(atr_val)
        prev_upper = self.upper_band
        prev_lower = self.lower_band
        prev_close = self.prev_close
        prev_st = self.prev_st
        pc = float(prev_close) if not is_na(prev_close) else c
        upper = (
            bub
            if is_na(prev_upper) or bub < float(prev_upper) or pc > float(prev_upper)
            else prev_upper
        )
        lower = (
            blb
            if is_na(prev_lower) or blb > float(prev_lower) or pc < float(prev_lower)
            else prev_lower
        )
        if is_na(self.prev_st):
            st = upper
            d = 1
        elif prev_st == prev_upper:
            d = -1 if c > float(upper) else 1
            st = lower if d == -1 else upper
        else:
            d = 1 if c < float(lower) else -1
            st = upper if d == 1 else lower
        self.upper_band = upper
        self.lower_band = lower
        self.prev_st = st
        self.prev_close = close
        return st, d


def supertrend(
    factor: float,
    atr_period: int,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
    high: Sequence[Any] | None = None,
    low: Sequence[Any] | None = None,
    close: Sequence[Any] | None = None,
) -> Any:
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.supertrend() runtime mode requires state_id")
        state = _state(
            runtime, state_id, lambda: _SupertrendState(factor, f"{state_id}:atr"), _SupertrendState
        )
        atr_val = atr(atr_period, runtime=runtime, state_id=state.atr_state_id)
        st, d = state.update(
            runtime.high.current, runtime.low.current, runtime.close.current, atr_val
        )
        return st, d
    atrs = atr(atr_period, high=high, low=low, close=close)
    line: list[Any] = []
    direction: list[Any] = []
    fub: Any = na
    flb: Any = na
    prev_st: Any = na
    for i, (h, low_value, c, a) in enumerate(zip(high, low, close, atrs, strict=True)):
        if is_na(a):
            line.append(na)
            direction.append(na)
            continue
        hl2 = (float(h) + float(low_value)) / 2
        bub = hl2 + factor * float(a)
        blb = hl2 - factor * float(a)
        pc = float(close[i - 1]) if i > 0 else float(c)
        fub = bub if is_na(fub) or bub < float(fub) or pc > float(fub) else fub
        flb = blb if is_na(flb) or blb > float(flb) or pc < float(flb) else flb
        if is_na(prev_st):
            st = fub
            d = 1
        elif prev_st == fub:
            st = flb if float(c) > float(fub) else fub
            d = -1 if st == flb else 1
        else:
            st = fub if float(c) < float(flb) else flb
            d = 1 if st == fub else -1
        prev_st = st
        line.append(st)
        direction.append(d)
    return line, direction


def sar(
    high: Sequence[Any],
    low: Sequence[Any],
    start: float = 0.02,
    inc: float = 0.02,
    max_val: float = 0.2,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.sar() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _SarState(start, inc, max_val), _SarState)
        return state.update(_current(high, "sar"), _current(low, "sar"))
    if len(high) != len(low):
        raise PineRuntimeError("ta.sar() high/low length mismatch")
    out: list[Any] = []
    long = True
    af = start
    ep: Any = na
    sarv: Any = na
    for i, (h, low_value) in enumerate(zip(high, low, strict=True)):
        if i == 0:
            out.append(na)
            ep = float(h)
            sarv = float(low_value)
            continue
        prev = sarv
        sarv = float(prev) + af * (float(ep) - float(prev))
        if long:
            if float(low_value) < sarv:
                long = False
                sarv = float(ep)
                ep = float(low_value)
                af = start
            elif float(h) > float(ep):
                ep = float(h)
                af = min(af + inc, max)
        else:
            if float(h) > sarv:
                long = True
                sarv = float(ep)
                ep = float(h)
                af = start
            elif float(low_value) < float(ep):
                ep = float(low_value)
                af = min(af + inc, max)
        out.append(sarv)
    return out


def pivot_high(source: Any, leftbars: int, rightbars: int) -> Any:
    return pivothigh(source, leftbars, rightbars)


def pivot_low(source: Any, leftbars: int, rightbars: int) -> Any:
    return pivotlow(source, leftbars, rightbars)


def pivothigh(source: Any, leftbars: int, rightbars: int) -> Any:
    leftbars = _validate_length(leftbars)
    rightbars = _validate_length(rightbars)
    center = _history(source, rightbars, "pivothigh")
    if is_na(center):
        return na
    vals = [_history(source, o, "pivothigh") for o in range(rightbars + leftbars + 1)]
    return center if all(not is_na(v) and float(center) >= float(v) for v in vals) else na


def pivotlow(source: Any, leftbars: int, rightbars: int) -> Any:
    leftbars = _validate_length(leftbars)
    rightbars = _validate_length(rightbars)
    center = _history(source, rightbars, "pivotlow")
    if is_na(center):
        return na
    vals = [_history(source, o, "pivotlow") for o in range(rightbars + leftbars + 1)]
    return center if all(not is_na(v) and float(center) <= float(v) for v in vals) else na


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


def rising(source: Any, length: int) -> bool:
    length = _validate_length(length)
    values = [_history(source, offset, "rising") for offset in range(length + 1)]
    if any(is_na(value) for value in values):
        return False
    return all(float(values[index]) > float(values[index + 1]) for index in range(length))


def falling(source: Any, length: int) -> bool:
    length = _validate_length(length)
    values = [_history(source, offset, "falling") for offset in range(length + 1)]
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


__all__ += [
    "bb",
    "bbw",
    "stoch",
    "dmi",
    "adx",
    "supertrend",
    "wma",
    "vwma",
    "hma",
    "swma",
    "alma",
    "sar",
    "pivot_high",
    "pivot_low",
    "pivothigh",
    "pivotlow",
    "valuewhen",
    "barssince",
    "linreg",
    "variance",
    "stdev",
    "dev",
    "percentile_nearest_rank",
    "percentile_linear_interpolation",
    "percentrank",
    "vwap",
    "mfi",
    "cci",
    "obv",
    "mom",
    "roc",
    "correlation",
    "rising",
    "falling",
    "ta_range",
    "cmo",
    "tsi",
]


def ta_range(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    """Range = highest(source, length) - lowest(source, length)."""
    if runtime is None:
        vals: list[float] = []
        out: list[float] = []
        for v in source:
            if is_na(v):
                vals.append(0.0)
            else:
                vals.append(float(v))
            if len(vals) >= length:
                window = vals[-length:]
                numeric = [x for x in window if x != 0.0 or len(window) == length]
                if numeric:
                    out.append(max(numeric) - min(numeric))
                else:
                    out.append(na)
            else:
                out.append(na)
        return out
    hi = highest(source, length, runtime=runtime, state_id=f"{state_id}_h")
    lo = lowest(source, length, runtime=runtime, state_id=f"{state_id}_l")
    from pinelib.core.operators import pine_sub

    return pine_sub(hi, lo)


def cmo(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    """Chande Momentum Oscillator — rolling mode with runtime support."""
    length = _validate_length(length)
    if runtime is None:
        state = _CmoState(length)
        return _batch_unary(source, state.update)
    if state_id is None:
        raise PineRuntimeError("ta.cmo() runtime mode requires state_id")
    state = _state(runtime, state_id, lambda: _CmoState(length), _CmoState)
    if state.length != length:
        raise PineRuntimeError("ta.cmo() length must remain stable for a state_id")
    return state.update(_current(source, "cmo"))


def tsi(
    source: Any,
    short_length: int,
    long_length: int,
    *,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    """True Strength Index — rolling mode with runtime support."""
    short_length = _validate_length(short_length)
    long_length = _validate_length(long_length)
    if runtime is None:
        state = _TsiState(short_length, long_length)
        return _batch_unary(source, state.update)
    if state_id is None:
        raise PineRuntimeError("ta.tsi() runtime mode requires state_id")
    state = _state(runtime, state_id, lambda: _TsiState(short_length, long_length), _TsiState)
    if state.short_length != short_length or state.long_length != long_length:
        raise PineRuntimeError("ta.tsi() lengths must remain stable for a state_id")
    return state.update(_current(source, "tsi"))


def kc(
    source: Any,
    length: int,
    mult: float = 1.0,
    *,
    usesource: int | None = None,
    scaletype: int | None = None,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> tuple[Any, Any, Any]:
    """
    Keltner Channels: (basis, upper, lower)

    basis  = ema(source, length)
    range  = ema(tr, length)  — True Range EMA
    upper  = basis + range * mult
    lower  = basis - range * mult

    scaletype and usesource are accepted for compatibility but not used
    (Pine Keltner uses high/low ATR variant; our implementation uses close-based TR).
    """
    length = _validate_length(length)
    mult = float(mult)

    if runtime is None:
        # Batch mode: process full series
        close_vals = list(source)
        tr_vals = _tr_batch_from_close(close_vals)
        basis_vals = ema(source, length)
        range_vals = ema(tr_vals, length)
        out_basis, out_upper, out_lower = [], [], []
        for b, r in zip(basis_vals, range_vals, strict=True):
            if is_na(b) or is_na(r):
                out_basis.append(na)
                out_upper.append(na)
                out_lower.append(na)
            else:
                u = float(b) + float(r) * mult
                lower_value = float(b) - float(r) * mult
                out_basis.append(b)
                out_upper.append(u)
                out_lower.append(lower_value)
        return (out_basis, out_upper, out_lower)

    if state_id is None:
        raise PineRuntimeError("ta.kc() runtime mode requires state_id")

    # Runtime mode: stateful EMA chains
    basis_state = _state(runtime, f"{state_id}_basis", lambda: _EmaState(length), _EmaState)
    range_state = _state(runtime, f"{state_id}_range", lambda: _EmaState(length), _EmaState)

    current_tr = tr(runtime=runtime)
    b = basis_state.update(_current(source, "kc:source"))
    r = range_state.update(current_tr)
    if is_na(b) or is_na(r):
        return (na, na, na)
    u = float(b) + float(r) * mult
    lower_value = float(b) - float(r) * mult
    return (b, u, lower_value)


def kcw(
    source: Any,
    length: int,
    mult: float = 1.0,
    *,
    usesource: int | None = None,
    scaletype: int | None = None,
    runtime: PineRuntime | None = None,
    state_id: str | None = None,
) -> Any:
    """
    Keltner Channel Width: (upper - lower) / basis

    Returns the normalised width of Keltner Channels as a percentage.
    """
    kc_basis, kc_upper, kc_lower = kc(
        source,
        length,
        mult,
        usesource=usesource,
        scaletype=scaletype,
        runtime=runtime,
        state_id=state_id,
    )
    if is_na(kc_basis) or is_na(kc_upper) or is_na(kc_lower):
        return na
    b = float(kc_basis)
    if b == 0:
        return na
    return (float(kc_upper) - float(kc_lower)) / b


def wpr(length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    """
    Williams %%R:
    100 * (close - highest(high, length)) / (highest(high, length) - lowest(low, length))

    Simplified form (used in corpus files with just length arg):
    100 * (close - highest(high, length)) / (highest(high, length) - lowest(low, length))
    """
    length = _validate_length(length)

    if runtime is None:
        raise PineRuntimeError("ta.wpr() requires runtime (used as stateful builtin)")

    if state_id is None:
        raise PineRuntimeError("ta.wpr() runtime mode requires state_id")

    hi = highest(runtime.high, length, runtime=runtime, state_id=f"{state_id}_hi")
    lo = lowest(runtime.low, length, runtime=runtime, state_id=f"{state_id}_lo")
    close = runtime.close.current

    if is_na(hi) or is_na(lo) or is_na(close):
        return na
    if hi == lo:
        return na
    return 100.0 * (float(close) - float(hi)) / (float(hi) - float(lo))
