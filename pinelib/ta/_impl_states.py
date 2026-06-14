from __future__ import annotations

import math as _py_math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from pinelib.core.na import is_na, na
from pinelib.errors import PineTypeError


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
        if type(value) is bool:
            raise PineTypeError("ta.change() does not accept bool source values")
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
