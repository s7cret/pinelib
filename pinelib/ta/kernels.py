from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Callable
from itertools import pairwise
from typing import TypeVar, cast

from pinelib.core.values import is_na, na, require_number
from pinelib.errors import PL_TA_KERNEL, PL_TA_STATE, PineRuntimeError
from pinelib.runtime.session import RuntimeTransaction
from pinelib.ta.types import (
    BandsResult,
    DmiResult,
    KernelSpec,
    MacdResult,
    SupertrendResult,
)

KERNEL_SPECS: tuple[KernelSpec, ...] = (
    KernelSpec("ta.sma", "moving_average", "ta.sma.state.v1", 1, "ignore_na"),
    KernelSpec("ta.ema", "moving_average", "ta.ema.state.v1", 1, "ignore_na"),
    KernelSpec("ta.rma", "moving_average", "ta.rma.state.v1", 1, "ignore_na"),
    KernelSpec("ta.wma", "moving_average", "ta.wma.state.v1", 1, "ignore_na"),
    KernelSpec("ta.vwma", "moving_average", "ta.vwma.state.v1", 1, "ignore_na"),
    KernelSpec("ta.swma", "moving_average", "ta.swma.state.v1", 4, "propagate_na"),
    KernelSpec("ta.alma", "moving_average", "ta.alma.state.v1", 1, "ignore_na"),
    KernelSpec("ta.hma", "moving_average", "ta.hma.state.v1", 1, "ignore_na"),
    KernelSpec("ta.rsi", "momentum", "ta.rsi.state.v1", 2, "ignore_na"),
    KernelSpec("ta.macd", "momentum", "ta.macd.state.v1", 2, "ignore_na", 3),
    KernelSpec("ta.mom", "momentum", "ta.mom.state.v1", 2, "propagate_na"),
    KernelSpec("ta.roc", "momentum", "ta.roc.state.v1", 2, "propagate_na"),
    KernelSpec("ta.cmo", "momentum", "ta.cmo.state.v1", 2, "ignore_na"),
    KernelSpec("ta.tsi", "momentum", "ta.tsi.state.v1", 2, "ignore_na"),
    KernelSpec("ta.stoch", "momentum", "ta.stoch.state.v1", 1, "propagate_na"),
    KernelSpec("ta.tr", "volatility", "ta.tr.state.v1", 1, "propagate_na"),
    KernelSpec("ta.atr", "volatility", "ta.atr.state.v1", 1, "ignore_na"),
    KernelSpec("ta.bb", "volatility", "ta.bb.state.v1", 1, "ignore_na", 3),
    KernelSpec("ta.bbw", "volatility", "ta.bbw.state.v1", 1, "ignore_na"),
    KernelSpec("ta.kc", "volatility", "ta.kc.state.v1", 1, "ignore_na", 3),
    KernelSpec("ta.kcw", "volatility", "ta.kcw.state.v1", 1, "ignore_na"),
    KernelSpec("ta.range", "volatility", "ta.range.state.v1", 1, "ignore_na"),
    KernelSpec("ta.wpr", "volatility", "ta.wpr.state.v1", 1, "propagate_na"),
    KernelSpec("ta.dmi", "trend", "ta.dmi.state.v1", 2, "propagate_na", 3),
    KernelSpec(
        "ta.supertrend", "trend", "ta.supertrend.state.v1", 2, "propagate_na", 2
    ),
    KernelSpec("ta.sar", "trend", "ta.sar.state.v1", 2, "propagate_na"),
    KernelSpec("ta.pivothigh", "trend", "ta.pivothigh.state.v1", 1, "propagate_na"),
    KernelSpec("ta.pivotlow", "trend", "ta.pivotlow.state.v1", 1, "propagate_na"),
    KernelSpec("ta.rising", "trend", "ta.rising.state.v1", 1, "ignore_na"),
    KernelSpec("ta.falling", "trend", "ta.falling.state.v1", 1, "ignore_na"),
    KernelSpec("ta.highest", "trend", "ta.highest.state.v1", 1, "ignore_na"),
    KernelSpec("ta.lowest", "trend", "ta.lowest.state.v1", 1, "ignore_na"),
    KernelSpec("ta.highestbars", "trend", "ta.highestbars.state.v1", 1, "ignore_na"),
    KernelSpec("ta.lowestbars", "trend", "ta.lowestbars.state.v1", 1, "ignore_na"),
    KernelSpec("ta.variance", "statistics", "ta.variance.state.v1", 1, "ignore_na"),
    KernelSpec("ta.stdev", "statistics", "ta.stdev.state.v1", 1, "ignore_na"),
    KernelSpec("ta.dev", "statistics", "ta.dev.state.v1", 1, "ignore_na"),
    KernelSpec(
        "ta.correlation", "statistics", "ta.correlation.state.v1", 2, "ignore_na"
    ),
    KernelSpec(
        "ta.percentile_linear_interpolation",
        "statistics",
        "ta.percentile_linear.state.v1",
        1,
        "ignore_na",
    ),
    KernelSpec(
        "ta.percentile_nearest_rank",
        "statistics",
        "ta.percentile_nearest.state.v1",
        1,
        "ignore_na",
    ),
    KernelSpec(
        "ta.percentrank", "statistics", "ta.percentrank.state.v1", 1, "ignore_na"
    ),
    KernelSpec("ta.linreg", "statistics", "ta.linreg.state.v1", 2, "ignore_na"),
    KernelSpec("ta.median", "statistics", "ta.median.state.v1", 1, "ignore_na"),
    KernelSpec("ta.mode", "statistics", "ta.mode.state.v1", 1, "ignore_na"),
    KernelSpec(
        "ta.valuewhen", "statistics", "ta.valuewhen.state.v1", 1, "event_history"
    ),
    KernelSpec(
        "ta.barssince", "statistics", "ta.barssince.state.v1", 1, "condition_history"
    ),
    KernelSpec("ta.cci", "volume", "ta.cci.state.v1", 1, "ignore_na"),
    KernelSpec("ta.mfi", "volume", "ta.mfi.state.v1", 2, "ignore_na"),
    KernelSpec("ta.obv", "volume", "ta.obv.state.v1", 2, "propagate_na"),
    KernelSpec("ta.vwap", "volume", "ta.vwap.state.v1", 1, "ignore_na"),
    KernelSpec("ta.cum", "volume", "ta.cum.state.v1", 1, "ignore_na"),
)

_KERNEL_BY_SYMBOL = {spec.symbol: spec for spec in KERNEL_SPECS}
_BufferValue = TypeVar("_BufferValue")


def kernel_spec(symbol: str) -> KernelSpec:
    try:
        return _KERNEL_BY_SYMBOL[symbol]
    except KeyError as error:
        raise PineRuntimeError(
            f"unknown TA kernel: {symbol}", code=PL_TA_KERNEL
        ) from error


def _state(
    tx: RuntimeTransaction,
    state_id: str,
    symbol: str,
    initial: dict[str, object],
) -> dict[str, object]:
    spec = kernel_spec(symbol)
    state = tx.state(
        state_id,
        owner=symbol,
        schema_version=spec.state_schema,
        initial={"kernel": symbol, **initial},
    )
    if not isinstance(state, dict) or state.get("kernel") != symbol:
        raise PineRuntimeError("invalid TA state payload", code=PL_TA_STATE)
    return state


def _length(value: int, name: str = "length") -> int:
    if type(value) is not int or value <= 0:
        raise PineRuntimeError(f"{name} must be a positive int", code=PL_TA_KERNEL)
    return value


def _stable(state: dict[str, object], **parameters: object) -> None:
    stored = state.setdefault("parameters", dict(parameters))
    if stored != parameters:
        raise PineRuntimeError(
            "TA parameters must remain stable for a state_id",
            code=PL_TA_STATE,
            details={"expected": stored, "actual": parameters},
        )


def _number(value: object, name: str = "source") -> float | None:
    if is_na(value):
        return None
    return float(require_number(value, name=name))


def _stored_number(value: object, name: str = "TA numeric state") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PineRuntimeError(f"invalid {name}", code=PL_TA_STATE)
    number = float(value)
    if not math.isfinite(number):
        raise PineRuntimeError(f"invalid {name}", code=PL_TA_STATE)
    return number


def _stored_int(value: object, name: str = "TA integer state") -> int:
    if type(value) is not int:
        raise PineRuntimeError(f"invalid {name}", code=PL_TA_STATE)
    return value


def _append(buffer: list[_BufferValue], value: _BufferValue, limit: int) -> None:
    buffer.append(value)
    if len(buffer) > limit:
        del buffer[0 : len(buffer) - limit]


def _numeric_buffer(state: dict[str, object], key: str) -> list[float]:
    value = state.setdefault(key, [])
    if not isinstance(value, list) or any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(float(item))
        for item in value
    ):
        raise PineRuntimeError("invalid TA buffer state", code=PL_TA_STATE)
    return cast(list[float], value)


def _object_buffer(state: dict[str, object], key: str) -> list[object]:
    value = state.setdefault(key, [])
    if not isinstance(value, list):
        raise PineRuntimeError("invalid TA buffer state", code=PL_TA_STATE)
    return value


def _rolling_non_na(
    state: dict[str, object],
    key: str,
    value: object,
    length: int,
    *,
    dynamic_length: bool = False,
) -> list[float]:
    buffer = _numeric_buffer(state, key)
    number = _number(value)
    if number is not None:
        if dynamic_length:
            buffer.append(number)
        else:
            _append(buffer, number, length)
    return buffer[-length:] if dynamic_length else buffer


def _rolling_exact(
    state: dict[str, object], key: str, value: object, length: int
) -> list[object]:
    buffer = _object_buffer(state, key)
    _append(buffer, value, length)
    return buffer


def _sma_values(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def _weighted(values: list[float]) -> float:
    denominator = len(values) * (len(values) + 1) / 2
    return (
        math.fsum((index + 1) * value for index, value in enumerate(values))
        / denominator
    )


def _ema_step(state: dict[str, object], value: object, length: int) -> object:
    number = _number(value)
    if number is None:
        current = state.get("value")
        return na if current is None else current
    current = state.get("value")
    if current is None:
        warmup = _numeric_buffer(state, "warmup")
        _append(warmup, number, length)
        if len(warmup) < length:
            return na
        current = _sma_values(warmup)
    else:
        alpha = 2.0 / (length + 1.0)
        current = alpha * number + (1.0 - alpha) * _stored_number(current)
    state["value"] = current
    return current


def _rma_step(state: dict[str, object], value: object, length: int) -> object:
    number = _number(value)
    if number is None:
        current = state.get("value")
        return na if current is None else current
    current = state.get("value")
    if current is None:
        warmup = _numeric_buffer(state, "warmup")
        _append(warmup, number, length)
        if len(warmup) < length:
            return na
        current = _sma_values(warmup)
    else:
        current = (_stored_number(current) * (length - 1) + number) / length
    state["value"] = current
    return current


def sma(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.sma", {})
    values = _rolling_non_na(state, "values", source, length, dynamic_length=True)
    return na if len(values) < length else _sma_values(values)


def ema(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.ema", {})
    _stable(state, length=length)
    return _ema_step(state, source, length)


def rma(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.rma", {})
    _stable(state, length=length)
    return _rma_step(state, source, length)


def wma(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.wma", {})
    values = _rolling_non_na(state, "values", source, length, dynamic_length=True)
    return na if len(values) < length else _weighted(values)


def vwma(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    volume: object,
    length: int,
) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.vwma", {})
    _stable(state, length=length)
    source_number = _number(source)
    volume_number = _number(volume, "volume")
    pairs = _object_buffer(state, "pairs")
    if source_number is not None and volume_number is not None:
        _append(pairs, [source_number, volume_number], length)
    if len(pairs) < length:
        return na
    denominator = math.fsum(float(pair[1]) for pair in pairs)  # type: ignore[index]
    if denominator == 0:
        return na
    return math.fsum(float(pair[0]) * float(pair[1]) for pair in pairs) / denominator  # type: ignore[index]


def swma(tx: RuntimeTransaction, state_id: str, source: object) -> object:
    state = _state(tx, state_id, "ta.swma", {})
    values = _rolling_exact(state, "values", source, 4)
    if len(values) < 4 or any(is_na(value) for value in values):
        return na
    numbers = [float(require_number(value)) for value in values]
    return (numbers[0] + 2 * numbers[1] + 2 * numbers[2] + numbers[3]) / 6.0


def alma(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    offset: float,
    sigma: float,
) -> object:
    length = _length(length)
    offset_number = float(require_number(offset, name="offset"))
    sigma_number = float(require_number(sigma, name="sigma"))
    if sigma_number <= 0:
        raise PineRuntimeError("ALMA sigma must be positive", code=PL_TA_KERNEL)
    state = _state(tx, state_id, "ta.alma", {})
    _stable(state, length=length, offset=offset_number, sigma=sigma_number)
    values = _rolling_non_na(state, "values", source, length)
    if len(values) < length:
        return na
    center = offset_number * (length - 1)
    width = length / sigma_number
    weights = [
        math.exp(-((index - center) ** 2) / (2 * width * width))
        for index in range(length)
    ]
    denominator = math.fsum(weights)
    return (
        math.fsum(value * weight for value, weight in zip(values, weights, strict=True))
        / denominator
    )


def hma(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.hma", {})
    _stable(state, length=length)
    values = _rolling_non_na(state, "values", source, length)
    if len(values) < length:
        return na
    half = max(1, length // 2)
    full_wma = _weighted(values[-length:])
    half_wma = _weighted(values[-half:])
    differences = _numeric_buffer(state, "differences")
    _append(differences, 2.0 * half_wma - full_wma, max(1, int(math.sqrt(length))))
    root = max(1, int(math.sqrt(length)))
    return na if len(differences) < root else _weighted(differences)


def rsi(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.rsi", {})
    _stable(state, length=length)
    number = _number(source)
    if number is None:
        return na
    previous = state.get("previous")
    state["previous"] = number
    if previous is None:
        return na
    change = number - _stored_number(previous)
    gain_state = state.setdefault("gain", {})
    loss_state = state.setdefault("loss", {})
    if not isinstance(gain_state, dict) or not isinstance(loss_state, dict):
        raise PineRuntimeError("invalid RSI state", code=PL_TA_STATE)
    average_gain = _rma_step(gain_state, max(change, 0.0), length)
    average_loss = _rma_step(loss_state, max(-change, 0.0), length)
    if is_na(average_gain) or is_na(average_loss):
        return na
    gain = _stored_number(average_gain)
    loss = _stored_number(average_loss)
    if loss == 0:
        return 100.0 if gain != 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def macd(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    fast_length: int,
    slow_length: int,
    signal_length: int,
) -> MacdResult:
    fast_length = _length(fast_length, "fast_length")
    slow_length = _length(slow_length, "slow_length")
    signal_length = _length(signal_length, "signal_length")
    state = _state(tx, state_id, "ta.macd", {})
    _stable(
        state,
        fast_length=fast_length,
        slow_length=slow_length,
        signal_length=signal_length,
    )
    fast_state = state.setdefault("fast", {})
    slow_state = state.setdefault("slow", {})
    signal_state = state.setdefault("signal", {})
    if not all(
        isinstance(item, dict) for item in (fast_state, slow_state, signal_state)
    ):
        raise PineRuntimeError("invalid MACD state", code=PL_TA_STATE)
    fast = _ema_step(fast_state, source, fast_length)  # type: ignore[arg-type]
    slow = _ema_step(slow_state, source, slow_length)  # type: ignore[arg-type]
    if is_na(fast) or is_na(slow):
        return MacdResult(na, na, na)
    value = _stored_number(fast) - _stored_number(slow)
    signal = _ema_step(signal_state, value, signal_length)  # type: ignore[arg-type]
    histogram = na if is_na(signal) else value - _stored_number(signal)
    return MacdResult(value, signal, histogram)


def _lagged(
    tx: RuntimeTransaction,
    state_id: str,
    symbol: str,
    source: object,
    length: int,
    transform: Callable[[float, float], object],
) -> object:
    length = _length(length)
    state = _state(tx, state_id, symbol, {})
    _stable(state, length=length)
    values = _rolling_exact(state, "values", source, length + 1)
    if len(values) <= length or is_na(values[-1]) or is_na(values[-length - 1]):
        return na
    current = float(require_number(values[-1]))
    previous = float(require_number(values[-length - 1]))
    return transform(current, previous)


def mom(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    return _lagged(
        tx,
        state_id,
        "ta.mom",
        source,
        length,
        lambda current, previous: current - previous,
    )


def roc(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    def calculate(current: float, previous: float) -> object:
        return na if previous == 0 else 100.0 * (current - previous) / previous

    return _lagged(tx, state_id, "ta.roc", source, length, calculate)


def cmo(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.cmo", {})
    _stable(state, length=length)
    number = _number(source)
    if number is None:
        return na
    previous = state.get("previous")
    state["previous"] = number
    if previous is None:
        return na
    change = number - _stored_number(previous)
    gains = _numeric_buffer(state, "gains")
    losses = _numeric_buffer(state, "losses")
    _append(gains, max(change, 0.0), length)
    _append(losses, max(-change, 0.0), length)
    if len(gains) < length:
        return na
    gain = math.fsum(gains)
    loss = math.fsum(losses)
    total = gain + loss
    return 0.0 if total == 0 else 100.0 * (gain - loss) / total


def tsi(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    short_length: int,
    long_length: int,
) -> object:
    short_length = _length(short_length, "short_length")
    long_length = _length(long_length, "long_length")
    state = _state(tx, state_id, "ta.tsi", {})
    _stable(state, short_length=short_length, long_length=long_length)
    number = _number(source)
    if number is None:
        return na
    previous = state.get("previous")
    state["previous"] = number
    if previous is None:
        return na
    change = number - _stored_number(previous)
    change_long = state.setdefault("change_long", {})
    change_short = state.setdefault("change_short", {})
    absolute_long = state.setdefault("absolute_long", {})
    absolute_short = state.setdefault("absolute_short", {})
    if not all(
        isinstance(item, dict)
        for item in (change_long, change_short, absolute_long, absolute_short)
    ):
        raise PineRuntimeError("invalid TSI state", code=PL_TA_STATE)
    first_change = _ema_step(change_long, change, long_length)  # type: ignore[arg-type]
    first_absolute = _ema_step(absolute_long, abs(change), long_length)  # type: ignore[arg-type]
    second_change = _ema_step(change_short, first_change, short_length)  # type: ignore[arg-type]
    second_absolute = _ema_step(absolute_short, first_absolute, short_length)  # type: ignore[arg-type]
    if (
        is_na(second_change)
        or is_na(second_absolute)
        or _stored_number(second_absolute) == 0
    ):
        return na
    return 100.0 * _stored_number(second_change) / _stored_number(second_absolute)


def stoch(
    tx: RuntimeTransaction,
    state_id: str,
    close: object,
    high: object,
    low: object,
    length: int,
) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.stoch", {})
    _stable(state, length=length)
    highs = _rolling_exact(state, "highs", high, length)
    lows = _rolling_exact(state, "lows", low, length)
    close_number = _number(close, "close")
    if (
        len(highs) < length
        or len(lows) < length
        or close_number is None
        or any(is_na(item) for item in highs + lows)
    ):
        return na
    highest_value = max(float(require_number(item)) for item in highs)
    lowest_value = min(float(require_number(item)) for item in lows)
    denominator = highest_value - lowest_value
    return (
        0.0 if denominator == 0 else 100.0 * (close_number - lowest_value) / denominator
    )


def _true_range(
    state: dict[str, object], high: object, low: object, close: object
) -> object:
    high_number = _number(high, "high")
    low_number = _number(low, "low")
    close_number = _number(close, "close")
    if high_number is None or low_number is None:
        return na
    previous_close = state.get("previous_close")
    if close_number is not None:
        state["previous_close"] = close_number
    if previous_close is None:
        return high_number - low_number
    return max(
        high_number - low_number,
        abs(high_number - _stored_number(previous_close)),
        abs(low_number - _stored_number(previous_close)),
    )


def tr(
    tx: RuntimeTransaction, state_id: str, high: object, low: object, close: object
) -> object:
    state = _state(tx, state_id, "ta.tr", {})
    return _true_range(state, high, low, close)


def atr(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    length: int,
) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.atr", {})
    _stable(state, length=length)
    true_range_state = state.setdefault("tr", {})
    average_state = state.setdefault("rma", {})
    if not isinstance(true_range_state, dict) or not isinstance(average_state, dict):
        raise PineRuntimeError("invalid ATR state", code=PL_TA_STATE)
    value = _true_range(true_range_state, high, low, close)
    return _rma_step(average_state, value, length)


def _rolling_stats(
    state: dict[str, object], source: object, length: int
) -> tuple[list[float], float, float] | None:
    values = _rolling_non_na(state, "values", source, length)
    if len(values) < length:
        return None
    mean = _sma_values(values)
    variance_value = math.fsum((value - mean) ** 2 for value in values) / length
    return values, mean, math.sqrt(variance_value)


def bb(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    multiplier: float,
) -> BandsResult:
    length = _length(length)
    multiplier_number = float(require_number(multiplier, name="multiplier"))
    state = _state(tx, state_id, "ta.bb", {})
    _stable(state, length=length, multiplier=multiplier_number)
    stats = _rolling_stats(state, source, length)
    if stats is None:
        return BandsResult(na, na, na)
    _, basis, deviation = stats
    return BandsResult(
        basis,
        basis + multiplier_number * deviation,
        basis - multiplier_number * deviation,
    )


def bbw(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    multiplier: float,
) -> object:
    length = _length(length)
    multiplier_number = float(require_number(multiplier, name="multiplier"))
    state = _state(tx, state_id, "ta.bbw", {})
    _stable(state, length=length, multiplier=multiplier_number)
    stats = _rolling_stats(state, source, length)
    if stats is None:
        return na
    _, basis, deviation = stats
    return na if basis == 0 else 2.0 * multiplier_number * deviation / basis


def _kc_values(
    state: dict[str, object],
    source: object,
    high: object,
    low: object,
    close: object,
    length: int,
    multiplier: float,
    use_true_range: bool,
) -> BandsResult:
    basis_state = state.setdefault("basis", {})
    range_state = state.setdefault("range", {})
    tr_state = state.setdefault("tr", {})
    if not all(isinstance(item, dict) for item in (basis_state, range_state, tr_state)):
        raise PineRuntimeError("invalid Keltner state", code=PL_TA_STATE)
    basis = _ema_step(basis_state, source, length)  # type: ignore[arg-type]
    if use_true_range:
        range_value = _true_range(tr_state, high, low, close)  # type: ignore[arg-type]
    else:
        high_number = _number(high, "high")
        low_number = _number(low, "low")
        range_value = (
            na
            if high_number is None or low_number is None
            else high_number - low_number
        )
    average_range = _ema_step(range_state, range_value, length)  # type: ignore[arg-type]
    if is_na(basis) or is_na(average_range):
        return BandsResult(na, na, na)
    span = multiplier * _stored_number(average_range)
    return BandsResult(
        _stored_number(basis),
        _stored_number(basis) + span,
        _stored_number(basis) - span,
    )


def kc(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    high: object,
    low: object,
    close: object,
    length: int,
    multiplier: float,
    use_true_range: bool = True,
) -> BandsResult:
    length = _length(length)
    multiplier_number = float(require_number(multiplier, name="multiplier"))
    state = _state(tx, state_id, "ta.kc", {})
    _stable(
        state,
        length=length,
        multiplier=multiplier_number,
        use_true_range=bool(use_true_range),
    )
    return _kc_values(
        state, source, high, low, close, length, multiplier_number, bool(use_true_range)
    )


def kcw(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    high: object,
    low: object,
    close: object,
    length: int,
    multiplier: float,
    use_true_range: bool = True,
) -> object:
    length = _length(length)
    multiplier_number = float(require_number(multiplier, name="multiplier"))
    state = _state(tx, state_id, "ta.kcw", {})
    _stable(
        state,
        length=length,
        multiplier=multiplier_number,
        use_true_range=bool(use_true_range),
    )
    bands = _kc_values(
        state, source, high, low, close, length, multiplier_number, bool(use_true_range)
    )
    if is_na(bands.basis) or _stored_number(bands.basis) == 0:
        return na
    return (_stored_number(bands.upper) - _stored_number(bands.lower)) / _stored_number(
        bands.basis
    )


def range_value(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.range", {})
    values = _rolling_non_na(state, "values", source, length, dynamic_length=True)
    return na if len(values) < length else max(values) - min(values)


def wpr(
    tx: RuntimeTransaction,
    state_id: str,
    close: object,
    high: object,
    low: object,
    length: int,
) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.wpr", {})
    _stable(state, length=length)
    highs = _rolling_exact(state, "highs", high, length)
    lows = _rolling_exact(state, "lows", low, length)
    close_number = _number(close, "close")
    if (
        len(highs) < length
        or len(lows) < length
        or close_number is None
        or any(is_na(item) for item in highs + lows)
    ):
        return na
    highest_value = max(float(require_number(item)) for item in highs)
    lowest_value = min(float(require_number(item)) for item in lows)
    denominator = highest_value - lowest_value
    return (
        0.0
        if denominator == 0
        else -100.0 * (highest_value - close_number) / denominator
    )


def dmi(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    di_length: int,
    adx_smoothing: int,
) -> DmiResult:
    di_length = _length(di_length, "di_length")
    adx_smoothing = _length(adx_smoothing, "adx_smoothing")
    state = _state(tx, state_id, "ta.dmi", {})
    _stable(state, di_length=di_length, adx_smoothing=adx_smoothing)
    high_number = _number(high, "high")
    low_number = _number(low, "low")
    close_number = _number(close, "close")
    if high_number is None or low_number is None or close_number is None:
        return DmiResult(na, na, na)
    previous_high = state.get("previous_high")
    previous_low = state.get("previous_low")
    previous_close = state.get("previous_close")
    state.update(
        previous_high=high_number, previous_low=low_number, previous_close=close_number
    )
    if previous_high is None or previous_low is None or previous_close is None:
        return DmiResult(na, na, na)
    up_move = high_number - _stored_number(previous_high)
    down_move = _stored_number(previous_low) - low_number
    plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
    minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0
    tr_value = max(
        high_number - low_number,
        abs(high_number - _stored_number(previous_close)),
        abs(low_number - _stored_number(previous_close)),
    )
    tr_state = state.setdefault("tr_rma", {})
    plus_state = state.setdefault("plus_rma", {})
    minus_state = state.setdefault("minus_rma", {})
    adx_state = state.setdefault("adx_rma", {})
    if not all(
        isinstance(item, dict)
        for item in (tr_state, plus_state, minus_state, adx_state)
    ):
        raise PineRuntimeError("invalid DMI state", code=PL_TA_STATE)
    tr_average = _rma_step(tr_state, tr_value, di_length)  # type: ignore[arg-type]
    plus_average = _rma_step(plus_state, plus_dm, di_length)  # type: ignore[arg-type]
    minus_average = _rma_step(minus_state, minus_dm, di_length)  # type: ignore[arg-type]
    if (
        is_na(tr_average)
        or _stored_number(tr_average) == 0
        or is_na(plus_average)
        or is_na(minus_average)
    ):
        return DmiResult(na, na, na)
    plus_di = 100.0 * _stored_number(plus_average) / _stored_number(tr_average)
    minus_di = 100.0 * _stored_number(minus_average) / _stored_number(tr_average)
    denominator = plus_di + minus_di
    dx = 0.0 if denominator == 0 else 100.0 * abs(plus_di - minus_di) / denominator
    adx_value = _rma_step(adx_state, dx, adx_smoothing)  # type: ignore[arg-type]
    return DmiResult(plus_di, minus_di, adx_value)


def supertrend(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    factor: float,
    atr_length: int,
) -> SupertrendResult:
    atr_length = _length(atr_length, "atr_length")
    factor_number = float(require_number(factor, name="factor"))
    if factor_number <= 0:
        raise PineRuntimeError("supertrend factor must be positive", code=PL_TA_KERNEL)
    state = _state(tx, state_id, "ta.supertrend", {})
    _stable(state, factor=factor_number, atr_length=atr_length)
    high_number = _number(high, "high")
    low_number = _number(low, "low")
    close_number = _number(close, "close")
    if high_number is None or low_number is None or close_number is None:
        return SupertrendResult(na, na)
    tr_state = state.setdefault("tr", {})
    atr_state = state.setdefault("atr", {})
    if not isinstance(tr_state, dict) or not isinstance(atr_state, dict):
        raise PineRuntimeError("invalid supertrend state", code=PL_TA_STATE)
    tr_value = _true_range(tr_state, high, low, close)
    atr_value = _rma_step(atr_state, tr_value, atr_length)
    if is_na(atr_value):
        state["previous_close"] = close_number
        return SupertrendResult(na, na)
    midpoint = (high_number + low_number) / 2.0
    basic_upper = midpoint + factor_number * _stored_number(atr_value)
    basic_lower = midpoint - factor_number * _stored_number(atr_value)
    previous_upper = state.get("final_upper")
    previous_lower = state.get("final_lower")
    previous_close = state.get("previous_close")
    if (
        previous_upper is None
        or previous_close is None
        or basic_upper < _stored_number(previous_upper)
        or _stored_number(previous_close) > _stored_number(previous_upper)
    ):
        final_upper = basic_upper
    else:
        final_upper = _stored_number(previous_upper)
    if (
        previous_lower is None
        or previous_close is None
        or basic_lower > _stored_number(previous_lower)
        or _stored_number(previous_close) < _stored_number(previous_lower)
    ):
        final_lower = basic_lower
    else:
        final_lower = _stored_number(previous_lower)
    previous_value = state.get("value")
    if previous_value is None:
        value = final_upper
        direction = 1
    elif _stored_number(previous_value) == _stored_number(previous_upper):
        if close_number > final_upper:
            value = final_lower
            direction = -1
        else:
            value = final_upper
            direction = 1
    elif close_number < final_lower:
        value = final_upper
        direction = 1
    else:
        value = final_lower
        direction = -1
    state.update(
        final_upper=final_upper,
        final_lower=final_lower,
        previous_close=close_number,
        value=value,
        direction=direction,
    )
    return SupertrendResult(value, direction)


def sar(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    start: float,
    increment: float,
    maximum: float,
) -> object:
    start_number = float(require_number(start, name="start"))
    increment_number = float(require_number(increment, name="increment"))
    maximum_number = float(require_number(maximum, name="maximum"))
    if start_number <= 0 or increment_number <= 0 or maximum_number < start_number:
        raise PineRuntimeError("invalid SAR parameters", code=PL_TA_KERNEL)
    state = _state(tx, state_id, "ta.sar", {})
    _stable(
        state, start=start_number, increment=increment_number, maximum=maximum_number
    )
    high_number = _number(high, "high")
    low_number = _number(low, "low")
    if high_number is None or low_number is None:
        return na
    previous_high = state.get("previous_high")
    previous_low = state.get("previous_low")
    if previous_high is None or previous_low is None:
        state.update(previous_high=high_number, previous_low=low_number)
        return na
    if "sar" not in state:
        uptrend = high_number >= _stored_number(previous_high)
        state.update(
            uptrend=uptrend,
            sar=(
                _stored_number(previous_low)
                if uptrend
                else _stored_number(previous_high)
            ),
            extreme=(
                max(high_number, _stored_number(previous_high))
                if uptrend
                else min(low_number, _stored_number(previous_low))
            ),
            acceleration=start_number,
            previous2_high=_stored_number(previous_high),
            previous2_low=_stored_number(previous_low),
            previous_high=high_number,
            previous_low=low_number,
        )
        return state["sar"]
    previous2_high = state.get("previous2_high")
    previous2_low = state.get("previous2_low")
    uptrend = bool(state["uptrend"])
    sar_value = _stored_number(state["sar"])
    extreme = _stored_number(state["extreme"])
    acceleration = _stored_number(state["acceleration"])
    projected = sar_value + acceleration * (extreme - sar_value)
    if uptrend:
        if low_number < projected:
            uptrend = False
            next_sar = extreme
            extreme = low_number
            acceleration = start_number
        else:
            lows = [_stored_number(previous_low)]
            if previous2_low is not None:
                lows.append(_stored_number(previous2_low))
            next_sar = min(projected, *lows)
            if high_number > extreme:
                extreme = high_number
                acceleration = min(maximum_number, acceleration + increment_number)
    else:
        if high_number > projected:
            uptrend = True
            next_sar = extreme
            extreme = high_number
            acceleration = start_number
        else:
            highs = [_stored_number(previous_high)]
            if previous2_high is not None:
                highs.append(_stored_number(previous2_high))
            next_sar = max(projected, *highs)
            if low_number < extreme:
                extreme = low_number
                acceleration = min(maximum_number, acceleration + increment_number)
    state.update(
        uptrend=uptrend,
        sar=next_sar,
        extreme=extreme,
        acceleration=acceleration,
        previous2_high=_stored_number(previous_high),
        previous2_low=_stored_number(previous_low),
        previous_high=high_number,
        previous_low=low_number,
    )
    return next_sar


def _pivot(
    tx: RuntimeTransaction,
    state_id: str,
    symbol: str,
    source: object,
    left: int,
    right: int,
    highest_mode: bool,
) -> object:
    left = _length(left, "left")
    right = _length(right, "right")
    state = _state(tx, state_id, symbol, {})
    _stable(state, left=left, right=right)
    window = _rolling_exact(state, "values", source, left + right + 1)
    if len(window) < left + right + 1 or any(is_na(value) for value in window):
        return na
    numbers = [float(require_number(value)) for value in window]
    center = numbers[left]
    left_values = numbers[:left]
    right_values = numbers[left + 1 :]
    if highest_mode:
        return (
            center
            if all(center > value for value in left_values)
            and all(center >= value for value in right_values)
            else na
        )
    return (
        center
        if all(center < value for value in left_values)
        and all(center <= value for value in right_values)
        else na
    )


def pivothigh(
    tx: RuntimeTransaction, state_id: str, source: object, left: int, right: int
) -> object:
    return _pivot(tx, state_id, "ta.pivothigh", source, left, right, True)


def pivotlow(
    tx: RuntimeTransaction, state_id: str, source: object, left: int, right: int
) -> object:
    return _pivot(tx, state_id, "ta.pivotlow", source, left, right, False)


def _monotonic(
    tx: RuntimeTransaction,
    state_id: str,
    symbol: str,
    source: object,
    length: int,
    rising_mode: bool,
) -> bool:
    length = _length(length)
    state = _state(tx, state_id, symbol, {})
    _stable(state, length=length)
    values = _rolling_non_na(state, "values", source, length + 1)
    if len(values) < length + 1:
        return False
    pairs = pairwise(values)
    return (
        all(right > left for left, right in pairs)
        if rising_mode
        else all(right < left for left, right in pairs)
    )


def rising(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> bool:
    return _monotonic(tx, state_id, "ta.rising", source, length, True)


def falling(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> bool:
    return _monotonic(tx, state_id, "ta.falling", source, length, False)


def _extreme(
    tx: RuntimeTransaction,
    state_id: str,
    symbol: str,
    source: object,
    length: int,
    highest_mode: bool,
    bars: bool,
) -> object:
    length = _length(length)
    state = _state(tx, state_id, symbol, {})
    values = _rolling_non_na(state, "values", source, length, dynamic_length=True)
    if len(values) < length:
        return na
    extreme_value = max(values) if highest_mode else min(values)
    if not bars:
        return extreme_value
    for reverse_index, value in enumerate(reversed(values)):
        if value == extreme_value:
            return -reverse_index
    return na


def highest(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _extreme(tx, state_id, "ta.highest", source, length, True, False)


def lowest(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _extreme(tx, state_id, "ta.lowest", source, length, False, False)


def highestbars(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _extreme(tx, state_id, "ta.highestbars", source, length, True, True)


def lowestbars(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    return _extreme(tx, state_id, "ta.lowestbars", source, length, False, True)


def _stat_values(
    tx: RuntimeTransaction,
    state_id: str,
    symbol: str,
    source: object,
    length: int,
    **parameters: object,
) -> tuple[dict[str, object], list[float]]:
    length = _length(length)
    state = _state(tx, state_id, symbol, {})
    _stable(state, **parameters)
    return state, _rolling_non_na(state, "values", source, length, dynamic_length=True)


def variance(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    biased: bool = True,
) -> object:
    _, values = _stat_values(
        tx, state_id, "ta.variance", source, length, biased=bool(biased)
    )
    if len(values) < length or (not biased and length < 2):
        return na
    mean = _sma_values(values)
    denominator = length if biased else length - 1
    return math.fsum((value - mean) ** 2 for value in values) / denominator


def stdev(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    biased: bool = True,
) -> object:
    _, values = _stat_values(
        tx, state_id, "ta.stdev", source, length, biased=bool(biased)
    )
    if len(values) < length or (not biased and length < 2):
        return na
    mean = _sma_values(values)
    denominator = length if biased else length - 1
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / denominator)


def dev(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    _, values = _stat_values(tx, state_id, "ta.dev", source, length)
    if len(values) < length:
        return na
    mean = _sma_values(values)
    return math.fsum(abs(value - mean) for value in values) / length


def correlation(
    tx: RuntimeTransaction,
    state_id: str,
    source1: object,
    source2: object,
    length: int,
) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.correlation", {})
    _stable(state, length=length)
    first = _number(source1, "source1")
    second = _number(source2, "source2")
    pairs = _object_buffer(state, "pairs")
    if first is not None and second is not None:
        _append(pairs, [first, second], length)
    if len(pairs) < length:
        return na
    xs = [float(pair[0]) for pair in pairs]  # type: ignore[index]
    ys = [float(pair[1]) for pair in pairs]  # type: ignore[index]
    mean_x = _sma_values(xs)
    mean_y = _sma_values(ys)
    covariance = math.fsum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)
    )
    variance_x = math.fsum((x - mean_x) ** 2 for x in xs)
    variance_y = math.fsum((y - mean_y) ** 2 for y in ys)
    denominator = math.sqrt(variance_x * variance_y)
    return na if denominator == 0 else covariance / denominator


def _percentile_values(
    tx: RuntimeTransaction,
    state_id: str,
    symbol: str,
    source: object,
    length: int,
    percentage: float,
) -> list[float] | None:
    length = _length(length)
    percentage_number = float(require_number(percentage, name="percentage"))
    if percentage_number < 0 or percentage_number > 100:
        raise PineRuntimeError("percentage must be in [0, 100]", code=PL_TA_KERNEL)
    state = _state(tx, state_id, symbol, {})
    _stable(state, length=length, percentage=percentage_number)
    values = _rolling_non_na(state, "values", source, length)
    return None if len(values) < length else sorted(values)


def percentile_linear_interpolation(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    percentage: float,
) -> object:
    values = _percentile_values(
        tx, state_id, "ta.percentile_linear_interpolation", source, length, percentage
    )
    if values is None:
        return na
    position = (len(values) - 1) * float(percentage) / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] + fraction * (values[upper] - values[lower])


def percentile_nearest_rank(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    percentage: float,
) -> object:
    values = _percentile_values(
        tx, state_id, "ta.percentile_nearest_rank", source, length, percentage
    )
    if values is None:
        return na
    rank = max(1, math.ceil(float(percentage) / 100.0 * len(values)))
    return values[rank - 1]


def percentrank(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.percentrank", {})
    _stable(state, length=length)
    number = _number(source)
    values = _rolling_non_na(state, "values", source, length)
    if number is None or len(values) < length:
        return na
    if length == 1:
        return 100.0
    below = sum(1 for value in values if value < number)
    equal = sum(1 for value in values if value == number)
    return 100.0 * (below + max(0, equal - 1) / 2.0) / (length - 1)


def linreg(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    length: int,
    offset: int = 0,
) -> object:
    length = _length(length)
    if type(offset) is not int:
        raise PineRuntimeError("linreg offset must be int", code=PL_TA_KERNEL)
    state = _state(tx, state_id, "ta.linreg", {})
    _stable(state, length=length, offset=offset)
    values = _rolling_non_na(state, "values", source, length)
    if len(values) < length:
        return na
    xs = list(range(length))
    mean_x = (length - 1) / 2.0
    mean_y = _sma_values(values)
    denominator = math.fsum((x - mean_x) ** 2 for x in xs)
    slope = (
        0.0
        if denominator == 0
        else math.fsum(
            (x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=True)
        )
        / denominator
    )
    intercept = mean_y - slope * mean_x
    return intercept + slope * (length - 1 - offset)


def median(
    tx: RuntimeTransaction, state_id: str, source: object, length: int
) -> object:
    _, values = _stat_values(tx, state_id, "ta.median", source, length)
    return na if len(values) < length else statistics.median(values)


def mode(tx: RuntimeTransaction, state_id: str, source: object, length: int) -> object:
    _, values = _stat_values(tx, state_id, "ta.mode", source, length)
    if len(values) < length:
        return na
    counts = Counter(values)
    highest_count = max(counts.values())
    return min(value for value, count in counts.items() if count == highest_count)


def valuewhen(
    tx: RuntimeTransaction,
    state_id: str,
    condition: bool,
    source: object,
    occurrence: int,
) -> object:
    if type(condition) is not bool or type(occurrence) is not int or occurrence < 0:
        raise PineRuntimeError("invalid valuewhen arguments", code=PL_TA_KERNEL)
    state = _state(tx, state_id, "ta.valuewhen", {})
    _stable(state, occurrence=occurrence)
    values = _object_buffer(state, "matches")
    if condition:
        values.append(source)
    return values[-occurrence - 1] if len(values) > occurrence else na


def barssince(tx: RuntimeTransaction, state_id: str, condition: bool) -> object:
    if type(condition) is not bool:
        raise PineRuntimeError("barssince condition must be bool", code=PL_TA_KERNEL)
    state = _state(tx, state_id, "ta.barssince", {})
    if condition:
        state["count"] = 0
        return 0
    count = state.get("count")
    if count is None:
        return na
    state["count"] = _stored_int(count) + 1
    return state["count"]


def cci(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    length: int,
) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.cci", {})
    _stable(state, length=length)
    high_number = _number(high, "high")
    low_number = _number(low, "low")
    close_number = _number(close, "close")
    if high_number is None or low_number is None or close_number is None:
        return na
    typical = (high_number + low_number + close_number) / 3.0
    values = _rolling_non_na(state, "values", typical, length)
    if len(values) < length:
        return na
    mean = _sma_values(values)
    mean_deviation = math.fsum(abs(value - mean) for value in values) / length
    return 0.0 if mean_deviation == 0 else (typical - mean) / (0.015 * mean_deviation)


def mfi(
    tx: RuntimeTransaction,
    state_id: str,
    high: object,
    low: object,
    close: object,
    volume: object,
    length: int,
) -> object:
    length = _length(length)
    state = _state(tx, state_id, "ta.mfi", {})
    _stable(state, length=length)
    high_number = _number(high, "high")
    low_number = _number(low, "low")
    close_number = _number(close, "close")
    volume_number = _number(volume, "volume")
    if (
        high_number is None
        or low_number is None
        or close_number is None
        or volume_number is None
    ):
        return na
    typical = (high_number + low_number + close_number) / 3.0
    previous = state.get("previous_typical")
    state["previous_typical"] = typical
    if previous is None:
        return na
    raw_flow = typical * volume_number
    positives = _numeric_buffer(state, "positive")
    negatives = _numeric_buffer(state, "negative")
    _append(positives, raw_flow if typical > _stored_number(previous) else 0.0, length)
    _append(negatives, raw_flow if typical < _stored_number(previous) else 0.0, length)
    if len(positives) < length:
        return na
    positive = math.fsum(positives)
    negative = math.fsum(negatives)
    if negative == 0:
        return 100.0 if positive > 0 else 50.0
    ratio = positive / negative
    return 100.0 - 100.0 / (1.0 + ratio)


def obv(
    tx: RuntimeTransaction,
    state_id: str,
    close: object,
    volume: object,
) -> object:
    state = _state(tx, state_id, "ta.obv", {})
    close_number = _number(close, "close")
    volume_number = _number(volume, "volume")
    if close_number is None or volume_number is None:
        return na
    previous = state.get("previous_close")
    total = _stored_number(state.get("total", 0.0))
    if previous is not None:
        if close_number > _stored_number(previous):
            total += volume_number
        elif close_number < _stored_number(previous):
            total -= volume_number
    state.update(previous_close=close_number, total=total)
    return total


def vwap(
    tx: RuntimeTransaction,
    state_id: str,
    source: object,
    volume: object,
    reset: bool = False,
) -> object:
    if type(reset) is not bool:
        raise PineRuntimeError("VWAP reset must be bool", code=PL_TA_KERNEL)
    state = _state(tx, state_id, "ta.vwap", {})
    if reset:
        state["price_volume"] = 0.0
        state["volume"] = 0.0
    source_number = _number(source)
    volume_number = _number(volume, "volume")
    if source_number is None or volume_number is None:
        return na
    price_volume = (
        _stored_number(state.get("price_volume", 0.0)) + source_number * volume_number
    )
    volume_total = _stored_number(state.get("volume", 0.0)) + volume_number
    state.update(price_volume=price_volume, volume=volume_total)
    return na if volume_total == 0 else price_volume / volume_total


def cum(tx: RuntimeTransaction, state_id: str, source: object) -> object:
    state = _state(tx, state_id, "ta.cum", {})
    number = _number(source)
    if number is None:
        return state.get("total", na)
    total = _stored_number(state.get("total", 0.0)) + number
    state["total"] = total
    return total
