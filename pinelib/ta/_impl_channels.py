from __future__ import annotations

from typing import Any

from pinelib.core.na import is_na, na
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError
from pinelib.ta._impl_core import (
    _batch_unary,
    _current,
    _EmaState,
    _state,
    _tr_batch_from_close,
    _validate_length,
    ema,
    tr,
)
from pinelib.ta._impl_momentum import highest, lowest
from pinelib.ta._impl_states import _CmoState, _TsiState


def ta_range(
    source: Any, length: int, *, runtime: PineRuntime | None = None, state_id: str | None = None
) -> Any:
    """Range = highest(source, length) - lowest(source, length)."""
    length = _validate_length(length)
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
                out.append(max(window) - min(window))
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
    if isinstance(kc_basis, list) and isinstance(kc_upper, list) and isinstance(kc_lower, list):
        result: list[Any] = []
        for basis_value, upper_value, lower_value in zip(kc_basis, kc_upper, kc_lower, strict=True):
            if is_na(basis_value) or is_na(upper_value) or is_na(lower_value):
                result.append(na)
                continue
            b = float(basis_value)
            result.append(na if b == 0 else (float(upper_value) - float(lower_value)) / b)
        return result
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
