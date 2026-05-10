from __future__ import annotations

import math as _py_math
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias, cast

from pinelib.core.na import SupportsSeriesLike, is_na, na
from pinelib.core.precision import pine_gt, pine_gte, pine_lt, pine_lte
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError, PineTypeError

Numeric: TypeAlias = int | float
TAValue: TypeAlias = Numeric | object


def _validate_length(length: Any) -> int:
    # Accept Pine input-backed Series (extract scalar from .current)
    if hasattr(length, 'current'):
        length = int(length.current)
    else:
        length = int(length)
    if isinstance(length, bool) or length <= 0:
        raise PineRuntimeError("TA length must be a positive integer")
    return length


def _reject_bool(value: Any, function_name: str) -> None:
    if isinstance(value, bool):
        raise PineTypeError(f"ta.{function_name}() does not accept bool source values")


def _current(source: Any, function_name: str) -> Any:
    value = source[0] if isinstance(source, SupportsSeriesLike) else source
    _reject_bool(value, function_name)
    return value


def _history(source: Any, offset: int, function_name: str) -> Any:
    if isinstance(source, SupportsSeriesLike):
        return source[offset]
    return source


def _condition_history(source: Any, offset: int) -> Any:
    if isinstance(source, SupportsSeriesLike):
        return source[offset]
    return source


def _series_values(source: Sequence[Any]) -> list[Any]:
    return list(source)


class _RuntimeDerivedSeries:
    def __init__(self, runtime: PineRuntime, name: str) -> None:
        self.runtime = runtime
        self.name = name

    @property
    def current(self) -> Any:
        return self[0]

    @property
    def committed_length(self) -> int:
        return self.runtime.close.committed_length

    def __getitem__(self, offset: int) -> Any:
        high = self.runtime.high[offset]
        low = self.runtime.low[offset]
        close = self.runtime.close[offset]
        open_ = self.runtime.open[offset]
        if any(is_na(value) for value in (high, low, close)):
            return na
        if self.name == "hl2":
            return (float(high) + float(low)) / 2.0
        if self.name == "hlc3":
            return (float(high) + float(low) + float(close)) / 3.0
        if self.name == "ohlc4":
            if is_na(open_):
                return na
            return (float(open_) + float(high) + float(low) + float(close)) / 4.0
        if self.name == "hlcc4":
            return (float(high) + float(low) + float(close) + float(close)) / 4.0
        return na


def hl2_series(runtime: PineRuntime) -> _RuntimeDerivedSeries:
    return _RuntimeDerivedSeries(runtime, "hl2")


def hlc3_series(runtime: PineRuntime) -> _RuntimeDerivedSeries:
    return _RuntimeDerivedSeries(runtime, "hlc3")


def ohlc4_series(runtime: PineRuntime) -> _RuntimeDerivedSeries:
    return _RuntimeDerivedSeries(runtime, "ohlc4")


def hlcc4_series(runtime: PineRuntime) -> _RuntimeDerivedSeries:
    return _RuntimeDerivedSeries(runtime, "hlcc4")


class _ShiftedSeries:
    def __init__(self, source: SupportsSeriesLike, offset: int) -> None:
        self.source = source
        self.offset = offset

    @property
    def current(self) -> Any:
        return self[0]

    @property
    def committed_length(self) -> int:
        return self.source.committed_length

    def __getitem__(self, offset: int) -> Any:
        return self.source[offset + self.offset]


def shifted_series(source: SupportsSeriesLike, offset: int) -> _ShiftedSeries:
    return _ShiftedSeries(source, offset)


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
                # TradingView returns valid values from bar 0 using SMA until RMA is ready
                return self.warmup_total / len(self.warmup)
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


def _state(
    runtime: PineRuntime, state_id: str, factory: Callable[[], object], expected: type[Any]
) -> Any:
    state = runtime.get_indicator_state(state_id, factory)
    if not isinstance(state, expected):
        raise PineRuntimeError(f"State id {state_id!r} is already used by another TA helper")
    return state


def _batch_unary(source: Sequence[Any], updater: Callable[[Any], Any]) -> list[Any]:
    return [updater(value) for value in _series_values(source)]


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
    *, runtime: PineRuntime | None = None, state_id: str | None = None, high: Any = None, low: Any = None, close: Any = None
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
        l = float(low)
        if self.first_bar:
            self.ep = h
            self.sarv = l
            self.first_bar = False
            self.af = self.start
            return na
        prev = self.sarv
        self.sarv = prev + self.af * (self.ep - prev)
        if self.long:
            if l < self.sarv:
                self.long = False
                self.sarv = self.ep
                self.ep = l
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
            elif l < self.ep:
                self.ep = l
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
        l = float(low)
        c = float(close)
        tp = (h + l + c) / 3.0
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
        _reject_bool(value, "cmo")
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
        _reject_bool(value, "tsi")
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
        ema_abs_val = abs_momentum if self.ema1_abs is None else alpha_s * abs_momentum + (1 - alpha_s) * self.ema1_abs
        self.ema1 = ema_val
        self.ema1_abs = ema_abs_val
        # Second EMA with long_length
        alpha_l = 2.0 / (self.long_length + 1)
        ema2_val = self.ema1 if self.ema2 is None else alpha_l * self.ema1 + (1 - alpha_l) * self.ema2
        ema2_abs_val = self.ema1_abs if self.ema2_abs is None else alpha_l * self.ema1_abs + (1 - alpha_l) * self.ema2_abs
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
        object.__setattr__(self, 'half_length', max(1, self.length // 2))
        object.__setattr__(self, 'sqrt_length', max(1, int(_py_math.sqrt(self.length))))
    
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
        half_wma = sum(w * v for w, v in zip(half_wts, half_list)) / sum(half_wts) if half_wts else 0
        full_wts = list(range(1, len(full_list) + 1))
        full_wma = sum(w * v for w, v in zip(full_wts, full_list)) / sum(full_wts)
        raw = 2 * half_wma - full_wma
        self.results.append(raw)
        if len(self.results) > sqrt_n:
            self.results.popleft()
        if len(self.results) < sqrt_n:
            return na
        results_list = list(self.results)
        res_wts = list(range(1, len(results_list) + 1))
        return sum(w * v for w, v in zip(res_wts, results_list)) / sum(res_wts)


@dataclass(slots=True)
class _WmaState:
    """State for WMA calculation."""
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
        vals_list = list(self.values)
        weights = list(range(1, len(vals_list) + 1))
        return sum(w * v for w, v in zip(weights, vals_list)) / sum(weights)


@dataclass(slots=True)
class _VwmaState:
    """State for VWMA calculation."""
    length: int
    values: deque[float] = field(default_factory=deque)
    volumes: deque[float] = field(default_factory=deque)
    
    def update(self, value: Any, volume: Any) -> Any:
        if is_na(value) or is_na(volume):
            return na
        number = float(value)
        vol = float(volume)
        self.values.append(number)
        self.volumes.append(vol)
        if len(self.values) > self.length:
            self.values.popleft()
            self.volumes.popleft()
        if len(self.values) < self.length:
            return na
        vals = list(self.values)
        vols = list(self.volumes)
        return sum(v * w for v, w in zip(vals, vols)) / sum(vols)


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


def highest(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    length = _validate_length(length)
    values = [_history(source, offset, "highest") for offset in range(length)]
    numbers = [float(value) for value in values if not is_na(value)]
    return max(numbers) if numbers else na


def lowest(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    length = _validate_length(length)
    values = [_history(source, offset, "lowest") for offset in range(length)]
    numbers = [float(value) for value in values if not is_na(value)]
    return min(numbers) if numbers else na


def highestbars(source: Any, length: int) -> Any:
    length = _validate_length(length)
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


def lowestbars(source: Any, length: int) -> Any:
    length = _validate_length(length)
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


def change(source: Any, length: int = 1, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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
    previous_right = _condition_history(source2, 1)
    return pine_gt(current_left, current_right) and pine_lte(previous_left, previous_right)


def crossunder(source1: Any, source2: Any) -> bool:
    current_left = _history(source1, 0, "crossunder")
    current_right = _history(source2, 0, "crossunder")
    previous_left = _history(source1, 1, "crossunder")
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


def stdev(source: Any, length: int, biased: bool = True, *, runtime: Any = None, state_id: str | None = None) -> Any:
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
    win = [_history(source, offset, "stdev") for offset in reversed(range(length))]
    return calc(win)


def variance(source: Any, length: int, biased: bool = True, *, runtime: Any = None, state_id: str | None = None) -> Any:
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
    return calc([_history(source, offset, "variance") for offset in reversed(range(length))])


def dev(source: Any, length: int) -> Any:
    length = _validate_length(length)

    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        nums = [float(v) for v in win]
        mean = sum(nums) / len(nums)
        return sum(abs(x - mean) for x in nums) / len(nums)

    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, length, calc)
    return calc([_history(source, o, "dev") for o in reversed(range(length))])


def wma(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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
    source: Any, length: int, volume: Any | None = None, *, runtime: PineRuntime | None = None, state_id: str | None = None
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
    return calc(
        [_history(source, o, "vwma") for o in reversed(range(length))],
        [_history(volume, o, "vwma") for o in reversed(range(length))],
    )


def hma(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    length = _validate_length(length)
    if runtime is None:
        if not isinstance(source, Sequence) or isinstance(source, SupportsSeriesLike):
            raise PineRuntimeError(
                "ta.hma() scalar mode is unsupported; use batch series input"
            )
        half = max(1, length // 2)
        sqrt_len = max(1, int(_py_math.sqrt(length)))
        w1 = wma(source, half)
        w2 = wma(source, length)
        diff = [
            na if is_na(a) or is_na(b) else 2 * float(a) - float(b) for a, b in zip(w1, w2, strict=True)
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


def bb(source: Any, length: int, mult: float) -> Any:
    basis = sma(source, length)
    sd = stdev(source, length)
    if isinstance(basis, list):
        upper = [
            na if is_na(b) or is_na(s) else float(b) + float(mult) * float(s)
            for b, s in zip(basis, sd, strict=True)
        ]
        lower = [
            na if is_na(b) or is_na(s) else float(b) - float(mult) * float(s)
            for b, s in zip(basis, sd, strict=True)
        ]
        return basis, upper, lower
    if is_na(basis) or is_na(sd):
        return na, na, na
    return basis, float(basis) + float(mult) * float(sd), float(basis) - float(mult) * float(sd)


def bbw(source: Any, length: int, mult: float) -> Any:
    basis, upper, lower = bb(source, length, mult)
    if isinstance(basis, list):
        return [
            na
            if is_na(b) or float(b) == 0 or is_na(u) or is_na(lower_band)
            else (float(u) - float(lower_band)) / float(b)
            for b, u, lower_band in zip(basis, upper, lower, strict=True)
        ]
    return na if is_na(basis) or float(basis) == 0 else (float(upper) - float(lower)) / float(basis)


def stoch(source: Any, high: Any, low: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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
        h, l, c = float(high), float(low), float(close)
        if is_na(self.prev_h):
            plus_dm = 0.0
            minus_dm = 0.0
            tr_val = h - l
        else:
            up = h - float(self.prev_h)
            down = float(self.prev_l) - l
            plus_dm = up if up > down and up > 0 else 0.0
            minus_dm = down if down > up and down > 0 else 0.0
            tr_val = max(h - l, abs(h - float(self.prev_c)), abs(l - float(self.prev_c)))
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


def dmi(high: Any, low: Any, close: Any, di_length: int, adx_smoothing: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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


def adx(high: Any, low: Any, close: Any, di_length: int, adx_smoothing: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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
        l = float(low)
        c = float(close)
        hl2 = (h + l) / 2
        bub = hl2 + self.factor * float(atr_val)
        blb = hl2 - self.factor * float(atr_val)
        prev_upper = self.upper_band
        prev_lower = self.lower_band
        prev_close = self.prev_close
        prev_st = self.prev_st
        pc = float(prev_close) if not is_na(prev_close) else c
        upper = bub if is_na(prev_upper) or bub < float(prev_upper) or pc > float(prev_upper) else prev_upper
        lower = blb if is_na(prev_lower) or blb > float(prev_lower) or pc < float(prev_lower) else prev_lower
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
    factor: float, atr_period: int, *,
    runtime: PineRuntime | None = None, state_id: str | None = None,
    high: Sequence[Any] | None = None, low: Sequence[Any] | None = None, close: Sequence[Any] | None = None
) -> Any:
    if runtime is not None:
        if state_id is None:
            raise PineRuntimeError("ta.supertrend() runtime mode requires state_id")
        state = _state(runtime, state_id, lambda: _SupertrendState(factor, f"{state_id}:atr"), _SupertrendState)
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
    *, runtime: PineRuntime | None = None, state_id: str | None = None,
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


def linreg(source: Any, length: int, offset: int) -> Any:
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


def vwap(source: Any, volume: Any | None = None, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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
    return _VwapState().update(
        _current(source, "vwap"), _current(volume, "vwap")
    )


def mom(
    source: Any, length: int,
    *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    """momentum() with optional runtime state tracking."""
    return change(source, length, runtime=runtime, state_id=state_id)


def roc(
    source: Any, length: int,
    *, runtime: PineRuntime | None = None, state_id: str | None = None
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


def correlation(source1: Any, source2: Any, length: int) -> Any:
    length = _validate_length(length)
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


def cci(source: Any, length: int, *legacy_args: Any, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    if legacy_args:
        low, close, legacy_length = length, legacy_args[0], legacy_args[1]
        source = [(float(h) + float(l) + float(c)) / 3 for h, l, c in zip(source, low, close, strict=True)]
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
        low, close, legacy_volume, legacy_length = length, legacy_args[0], legacy_args[1], legacy_args[2]
        source = [(float(h) + float(l) + float(c)) / 3 for h, l, c in zip(source, low, close, strict=True)]
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
    return calc(
        [_history(source, o, "mfi") for o in range(length + 1)],
        [_history(volume, o, "mfi") for o in range(length)],
    )


def obv(close: Any, volume: Any, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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
    "cum",
    "ta_range",
    "cmo",
    "tsi",
]


class _CumState:
    """State for ta.cum (cumulative sum)."""
    total: float = 0.0

    def update(self, value: Any) -> Any:
        if not is_na(value):
            self.total += float(value)
        return self.total


def cum(source: Any, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    """Cumulative sum of source."""
    is_iterable = hasattr(source, '__iter__') and not isinstance(source, (str, bytes))
    if runtime is None and is_iterable:
        out: list[float] = []
        total = 0.0
        for v in source:
            if not is_na(v):
                total += float(v)
            out.append(total)
        return out
    if state_id is None:
        state_id = "_cum_default"
    state = _state(runtime, state_id, lambda: _CumState(), _CumState)
    val = _current(source, "cum") if hasattr(source, 'current') else source
    return state.update(val)


def ta_range(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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


def cmo(source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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


def tsi(source: Any, short_length: int, long_length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
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

