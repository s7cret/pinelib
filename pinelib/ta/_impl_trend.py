from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pinelib.core.na import SupportsSeriesLike, is_na, na
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError
from pinelib.ta._impl_core import _current, _RmaState, _state, _validate_length, rma
from pinelib.ta._impl_momentum import atr
from pinelib.ta._impl_states import _SarState
from pinelib.ta.utils import _history


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
                af = min(af + inc, max_val)
        else:
            if float(h) > sarv:
                long = True
                sarv = float(ep)
                ep = float(h)
                af = start
            elif float(low_value) < float(ep):
                ep = float(low_value)
                af = min(af + inc, max_val)
        out.append(sarv)
    return out


def pivot_high(source: Any, leftbars: int, rightbars: int) -> Any:
    return pivothigh(source, leftbars, rightbars)


def pivot_low(source: Any, leftbars: int, rightbars: int) -> Any:
    return pivotlow(source, leftbars, rightbars)


def _pivot_batch(source: Sequence[Any], leftbars: int, rightbars: int, *, mode: str) -> list[Any]:
    out: list[Any] = []
    total = leftbars + rightbars + 1
    for index in range(len(source)):
        if index < leftbars or index + rightbars >= len(source):
            out.append(na)
            continue
        center = source[index]
        window = source[index - leftbars : index + rightbars + 1]
        if is_na(center) or len(window) < total or any(is_na(value) for value in window):
            out.append(na)
        elif mode == "high":
            out.append(center if all(float(center) >= float(value) for value in window) else na)
        else:
            out.append(center if all(float(center) <= float(value) for value in window) else na)
    return out


def pivothigh(source: Any, leftbars: int, rightbars: int) -> Any:
    leftbars = _validate_length(leftbars)
    rightbars = _validate_length(rightbars)
    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _pivot_batch(source, leftbars, rightbars, mode="high")
    center = _history(source, rightbars, "pivothigh")
    if is_na(center):
        return na
    vals = [_history(source, o, "pivothigh") for o in range(rightbars + leftbars + 1)]
    return center if all(not is_na(v) and float(center) >= float(v) for v in vals) else na


def pivotlow(source: Any, leftbars: int, rightbars: int) -> Any:
    leftbars = _validate_length(leftbars)
    rightbars = _validate_length(rightbars)
    if isinstance(source, Sequence) and not isinstance(source, SupportsSeriesLike):
        return _pivot_batch(source, leftbars, rightbars, mode="low")
    center = _history(source, rightbars, "pivotlow")
    if is_na(center):
        return na
    vals = [_history(source, o, "pivotlow") for o in range(rightbars + leftbars + 1)]
    return center if all(not is_na(v) and float(center) <= float(v) for v in vals) else na
