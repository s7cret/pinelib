from __future__ import annotations

import math as _py_math
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


# --- v0.6.0 extended TA helpers ---

def _rolling(source: Sequence[Any], length: int, fn: Callable[[list[Any]], Any]) -> list[Any]:
    length = _validate_length(length)
    out: list[Any] = []
    vals = list(source)
    for i in range(len(vals)):
        win = vals[max(0, i - length + 1): i + 1]
        out.append(fn(win) if len(win) == length else na)
    return out


def stdev(source: Any, length: int, biased: bool = True) -> Any:
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


def variance(source: Any, length: int, biased: bool = True) -> Any:
    sd = stdev(source, length, biased)
    if isinstance(sd, list):
        return [na if is_na(v) else float(v) ** 2 for v in sd]
    return na if is_na(sd) else float(sd) ** 2


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


def wma(source: Any, length: int) -> Any:
    length = _validate_length(length)
    weights = list(range(1, length + 1))
    denom = sum(weights)
    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win):
            return na
        return sum(float(v) * w for v, w in zip(win, weights, strict=True)) / denom
    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _rolling(source, length, calc)
    return calc([_history(source, o, "wma") for o in reversed(range(length))])


def vwma(source: Any, length: int, volume: Any | None = None, *, runtime: PineRuntime | None = None) -> Any:
    length = _validate_length(length)
    if runtime is not None and volume is None:
        volume = runtime.volume
    if volume is None:
        raise PineRuntimeError("ta.vwma() requires volume or runtime")
    def calc(src_win: list[Any], vol_win: list[Any]) -> Any:
        if any(is_na(v) for v in src_win + vol_win):
            return na
        den = sum(float(v) for v in vol_win)
        return na if den == 0 else sum(float(s) * float(v) for s, v in zip(src_win, vol_win, strict=True)) / den
    if isinstance(source, Sequence) and isinstance(volume, Sequence) and not isinstance(source, SupportsSeriesLike):
        out: list[Any] = []
        for i in range(len(source)):
            if i + 1 < length:
                out.append(na)
            else:
                out.append(calc(list(source[i-length+1:i+1]), list(volume[i-length+1:i+1])))
        return out
    return calc([_history(source, o, "vwma") for o in reversed(range(length))], [_history(volume, o, "vwma") for o in reversed(range(length))])


def hma(source: Any, length: int) -> Any:
    length = _validate_length(length)
    if not isinstance(source, Sequence) or isinstance(source, SupportsSeriesLike):
        raise PineRuntimeError("ta.hma() scalar/runtime mode is unsupported; use batch series input")
    half = max(1, length // 2)
    sqrt_len = max(1, int(_py_math.sqrt(length)))
    w1 = wma(source, half)
    w2 = wma(source, length)
    diff = [na if is_na(a) or is_na(b) else 2 * float(a) - float(b) for a, b in zip(w1, w2, strict=True)]
    return wma(diff, sqrt_len)


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
        upper = [na if is_na(b) or is_na(s) else float(b) + float(mult) * float(s) for b, s in zip(basis, sd, strict=True)]
        lower = [na if is_na(b) or is_na(s) else float(b) - float(mult) * float(s) for b, s in zip(basis, sd, strict=True)]
        return basis, upper, lower
    if is_na(basis) or is_na(sd):
        return na, na, na
    return basis, float(basis) + float(mult) * float(sd), float(basis) - float(mult) * float(sd)


def bbw(source: Any, length: int, mult: float) -> Any:
    basis, upper, lower = bb(source, length, mult)
    if isinstance(basis, list):
        return [na if is_na(b) or float(b) == 0 or is_na(u) or is_na(l) else (float(u) - float(l)) / float(b) for b, u, l in zip(basis, upper, lower, strict=True)]
    return na if is_na(basis) or float(basis) == 0 else (float(upper) - float(lower)) / float(basis)


def stoch(source: Any, high: Any, low: Any, length: int) -> Any:
    length = _validate_length(length)
    def calc(src: Any, highs: list[Any], lows: list[Any]) -> Any:
        if is_na(src) or any(is_na(v) for v in highs + lows):
            return na
        lo = min(float(v) for v in lows); hi = max(float(v) for v in highs)
        return na if hi == lo else 100.0 * (float(src) - lo) / (hi - lo)
    if isinstance(source, Sequence) and isinstance(high, Sequence) and isinstance(low, Sequence) and not isinstance(source, SupportsSeriesLike):
        out=[]
        for i in range(len(source)):
            out.append(na if i + 1 < length else calc(source[i], list(high[i-length+1:i+1]), list(low[i-length+1:i+1])))
        return out
    return calc(_history(source,0,"stoch"), [_history(high,o,"stoch") for o in range(length)], [_history(low,o,"stoch") for o in range(length)])


def dmi(high: Any, low: Any, close: Any, di_length: int, adx_smoothing: int) -> Any:
    if not (isinstance(high, Sequence) and isinstance(low, Sequence) and isinstance(close, Sequence)) or isinstance(high, SupportsSeriesLike):
        raise PineRuntimeError("ta.dmi() currently supports batch sequences only")
    di_length = _validate_length(di_length); adx_smoothing = _validate_length(adx_smoothing)
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    prev_h: Any = na
    prev_l: Any = na
    prev_c: Any = na
    for h,l,c in zip(high, low, close, strict=True):
        if is_na(prev_h):
            plus_dm.append(0.0); minus_dm.append(0.0); trs.append(float(h)-float(l))
        else:
            up=float(h)-float(prev_h); down=float(prev_l)-float(l)
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
            trs.append(max(float(h)-float(l), abs(float(h)-float(prev_c)), abs(float(l)-float(prev_c))))
        prev_h, prev_l, prev_c = h,l,c
    atrs = rma(trs, di_length); p = rma(plus_dm, di_length); m = rma(minus_dm, di_length)
    plus: list[Any] = []
    minus: list[Any] = []
    dx: list[Any] = []
    for a, pp, mm in zip(atrs, p, m, strict=True):
        if is_na(a) or float(a)==0:
            plus.append(na); minus.append(na); dx.append(na)
        else:
            pv=100*float(pp)/float(a); mv=100*float(mm)/float(a)
            plus.append(pv); minus.append(mv); dx.append(na if pv+mv==0 else 100*abs(pv-mv)/(pv+mv))
    return plus, minus, rma(dx, adx_smoothing)


def adx(high: Any, low: Any, close: Any, di_length: int, adx_smoothing: int) -> Any:
    return dmi(high, low, close, di_length, adx_smoothing)[2]


def supertrend(factor: float, atr_period: int, *, high: Sequence[Any], low: Sequence[Any], close: Sequence[Any]) -> tuple[list[Any], list[Any]]:
    atrs = atr(atr_period, high=high, low=low, close=close)
    line: list[Any] = []
    direction: list[Any] = []
    fub: Any = na
    flb: Any = na
    prev_st: Any = na
    for i,(h,l,c,a) in enumerate(zip(high, low, close, atrs, strict=True)):
        if is_na(a):
            line.append(na); direction.append(na); continue
        hl2=(float(h)+float(l))/2; bub=hl2+factor*float(a); blb=hl2-factor*float(a)
        pc = float(close[i-1]) if i > 0 else float(c)
        fub = bub if is_na(fub) or bub < float(fub) or pc > float(fub) else fub
        flb = blb if is_na(flb) or blb > float(flb) or pc < float(flb) else flb
        if is_na(prev_st):
            st=fub; d=1
        elif prev_st == fub:
            st = flb if float(c) > float(fub) else fub; d = -1 if st == flb else 1
        else:
            st = fub if float(c) < float(flb) else flb; d = 1 if st == fub else -1
        prev_st=st; prev_dir=d
        line.append(st); direction.append(d)
    return line, direction


def sar(high: Sequence[Any], low: Sequence[Any], start: float = 0.02, inc: float = 0.02, max: float = 0.2) -> list[Any]:
    if len(high) != len(low):
        raise PineRuntimeError("ta.sar() high/low length mismatch")
    out: list[Any] = []
    long = True
    af = start
    ep: Any = na
    sarv: Any = na
    for i,(h,l) in enumerate(zip(high, low, strict=True)):
        if i == 0:
            out.append(na); ep=float(h); sarv=float(l); continue
        prev=sarv
        sarv = float(prev) + af * (float(ep) - float(prev))
        if long:
            if float(l) < sarv:
                long=False; sarv=float(ep); ep=float(l); af=start
            elif float(h) > float(ep):
                ep=float(h); af=min(af+inc, max)
        else:
            if float(h) > sarv:
                long=True; sarv=float(ep); ep=float(h); af=start
            elif float(l) < float(ep):
                ep=float(l); af=min(af+inc, max)
        out.append(sarv)
    return out


def pivot_high(source: Any, leftbars: int, rightbars: int) -> Any:
    return pivothigh(source, leftbars, rightbars)


def pivot_low(source: Any, leftbars: int, rightbars: int) -> Any:
    return pivotlow(source, leftbars, rightbars)


def pivothigh(source: Any, leftbars: int, rightbars: int) -> Any:
    leftbars=_validate_length(leftbars); rightbars=_validate_length(rightbars)
    center=_history(source, rightbars, "pivothigh")
    if is_na(center): return na
    vals=[_history(source,o,"pivothigh") for o in range(rightbars+leftbars+1)]
    return center if all(not is_na(v) and float(center) >= float(v) for v in vals) else na


def pivotlow(source: Any, leftbars: int, rightbars: int) -> Any:
    leftbars=_validate_length(leftbars); rightbars=_validate_length(rightbars)
    center=_history(source, rightbars, "pivotlow")
    if is_na(center): return na
    vals=[_history(source,o,"pivotlow") for o in range(rightbars+leftbars+1)]
    return center if all(not is_na(v) and float(center) <= float(v) for v in vals) else na


def valuewhen(condition: Any, source: Any, occurrence: int) -> Any:
    if occurrence < 0: raise PineRuntimeError("ta.valuewhen() occurrence must be >= 0")
    hits: list[Any] = []
    if isinstance(condition, Sequence) and isinstance(source, Sequence) and not isinstance(condition, SupportsSeriesLike):
        out=[]
        for i in range(len(condition)):
            if bool(condition[i]): hits.insert(0, source[i])
            out.append(hits[occurrence] if occurrence < len(hits) else na)
        return out
    for off in range(0, 10000):
        cv=_history(condition, off, "valuewhen")
        if is_na(cv) and off > 0: break
        if bool(cv):
            hits.append(_history(source, off, "valuewhen"))
            if len(hits) > occurrence: return hits[occurrence]
    return na


def barssince(condition: Any) -> Any:
    if isinstance(condition, Sequence) and not isinstance(condition, SupportsSeriesLike):
        last: int | None = None
        out: list[Any] = []
        for i,c in enumerate(condition):
            if bool(c): last=i; out.append(0)
            else: out.append(na if last is None else i-last)
        return out
    for off in range(0, 10000):
        cv=_history(condition, off, "barssince")
        if bool(cv): return off
        if is_na(cv) and off > 0: break
    return na


def linreg(source: Any, length: int, offset: int) -> Any:
    length=_validate_length(length)
    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win): return na
        ys=[float(v) for v in win]; xs=list(range(length)); xm=sum(xs)/length; ym=sum(ys)/length
        den=sum((x-xm)**2 for x in xs)
        slope=0.0 if den==0 else sum((x-xm)*(y-ym) for x,y in zip(xs,ys,strict=True))/den
        intercept=ym-slope*xm
        return intercept + slope * (length - 1 - offset)
    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike): return _rolling(source,length,calc)
    return calc([_history(source,o,"linreg") for o in reversed(range(length))])


def percentile_nearest_rank(source: Any, length: int, percentage: float) -> Any:
    def calc(win: list[Any]) -> Any:
        vals=sorted(float(v) for v in win if not is_na(v))
        if not vals: return na
        rank=max(1, int(_py_math.ceil(float(percentage)/100.0*len(vals))))
        return vals[min(rank-1, len(vals)-1)]
    return _rolling(source, _validate_length(length), calc) if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike) else calc([_history(source,o,"percentile_nearest_rank") for o in range(length)])


def percentile_linear_interpolation(source: Any, length: int, percentage: float) -> Any:
    def calc(win: list[Any]) -> Any:
        vals=sorted(float(v) for v in win if not is_na(v))
        if not vals: return na
        pos=(len(vals)-1)*float(percentage)/100.0; lo=int(_py_math.floor(pos)); hi=int(_py_math.ceil(pos))
        return vals[lo] if lo==hi else vals[lo]+(vals[hi]-vals[lo])*(pos-lo)
    return _rolling(source, _validate_length(length), calc) if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike) else calc([_history(source,o,"percentile_linear_interpolation") for o in range(length)])


def percentrank(source: Any, length: int) -> Any:
    length=_validate_length(length)
    def calc(win: list[Any]) -> Any:
        if any(is_na(v) for v in win): return na
        cur=float(win[-1]); return 100.0 * sum(1 for v in win if float(v) <= cur) / len(win)
    return _rolling(source,length,calc) if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike) else calc([_history(source,o,"percentrank") for o in reversed(range(length))])


def vwap(source: Any, volume: Any | None = None, *, runtime: PineRuntime | None = None) -> Any:
    if runtime is not None:
        source = runtime.close if source is None else source; volume = runtime.volume if volume is None else volume
    if volume is None: raise PineRuntimeError("ta.vwap() requires volume or runtime")
    if isinstance(source, Sequence) and isinstance(volume, Sequence) and not isinstance(source, SupportsSeriesLike):
        out=[]; num=den=0.0
        for s,v in zip(source, volume, strict=True):
            if not is_na(s) and not is_na(v): num += float(s)*float(v); den += float(v)
            out.append(na if den == 0 else num/den)
        return out
    # runtime cumulative via implicit history scan is not possible without state; explicit unsupported
    raise PineRuntimeError("ta.vwap() runtime mode requires anchored state and is unsupported in v0.6.0")


def mom(source: Any, length: int) -> Any: return change(source, length)

def roc(source: Any, length: int) -> Any:
    cur=_history(source,0,"roc"); prev=_history(source,_validate_length(length),"roc")
    return na if is_na(cur) or is_na(prev) or float(prev)==0 else 100.0*(float(cur)-float(prev))/float(prev)


def correlation(source1: Any, source2: Any, length: int) -> Any:
    length=_validate_length(length); a=[_history(source1,o,"correlation") for o in reversed(range(length))]; b=[_history(source2,o,"correlation") for o in reversed(range(length))]
    if any(is_na(v) for v in a+b): return na
    xs=[float(v) for v in a]; ys=[float(v) for v in b]; xm=sum(xs)/length; ym=sum(ys)/length
    denx=sum((x-xm)**2 for x in xs); deny=sum((y-ym)**2 for y in ys)
    return na if denx==0 or deny==0 else sum((x-xm)*(y-ym) for x,y in zip(xs,ys,strict=True)) / _py_math.sqrt(denx*deny)


def rising(source: Any, length: int) -> bool:
    cur=_history(source,0,"rising"); vals=[_history(source,o,"rising") for o in range(1,_validate_length(length)+1)]
    return False if is_na(cur) or any(is_na(v) for v in vals) else all(float(cur)>float(v) for v in vals)


def falling(source: Any, length: int) -> bool:
    cur=_history(source,0,"falling"); vals=[_history(source,o,"falling") for o in range(1,_validate_length(length)+1)]
    return False if is_na(cur) or any(is_na(v) for v in vals) else all(float(cur)<float(v) for v in vals)


def cci(high: Any, low: Any, close: Any, length: int) -> Any:
    tp=[(float(h)+float(l)+float(c))/3 for h,l,c in zip(high,low,close,strict=True)]
    sm=sma(tp,length); dv=dev(tp,length)
    return [na if is_na(s) or is_na(d) or float(d)==0 else (t-float(s))/(0.015*float(d)) for t,s,d in zip(tp,sm,dv,strict=True)]


def mfi(high: Any, low: Any, close: Any, volume: Any, length: int) -> Any:
    tp=[(float(h)+float(l)+float(c))/3 for h,l,c in zip(high,low,close,strict=True)]; pos=[]; neg=[]
    for i,t in enumerate(tp):
        mf=t*float(volume[i])
        pos.append(mf if i>0 and t>tp[i-1] else 0.0); neg.append(mf if i>0 and t<tp[i-1] else 0.0)
    ps=_rolling(pos,_validate_length(length),lambda w: sum(float(x) for x in w)); ns=_rolling(neg,_validate_length(length),lambda w: sum(float(x) for x in w))
    return [na if is_na(p) or is_na(n) else (100.0 if float(n)==0 else 100.0 - 100.0/(1.0+float(p)/float(n))) for p,n in zip(ps,ns,strict=True)]


def obv(close: Any, volume: Any) -> Any:
    out: list[float] = []
    total = 0.0
    prev: Any = na
    for c,v in zip(close,volume,strict=True):
        if not is_na(prev): total += (1 if float(c)>float(prev) else -1 if float(c)<float(prev) else 0)*float(v)
        out.append(total); prev=c
    return out


__all__ += [
    "bb", "bbw", "stoch", "dmi", "adx", "supertrend", "wma", "vwma", "hma", "swma", "alma", "sar",
    "pivot_high", "pivot_low", "pivothigh", "pivotlow", "valuewhen", "barssince", "linreg", "variance",
    "stdev", "dev", "percentile_nearest_rank", "percentile_linear_interpolation", "percentrank", "vwap",
    "mfi", "cci", "obv", "mom", "roc", "correlation", "rising", "falling",
]
