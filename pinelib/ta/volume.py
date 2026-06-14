from typing import Any

from pinelib.core.na import is_na
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PineRuntimeError
from pinelib.ta._impl import _current, _state, cci, mfi, obv, stoch, vwap


class _CumState:
    """State for ta.cum (cumulative sum)."""

    total: float = 0.0

    def update(self, value: Any) -> Any:
        if not is_na(value):
            self.total += float(value)
        return self.total


def cum(source: Any, *, runtime: PineRuntime | None = None, state_id: str | None = None) -> Any:
    """Cumulative sum of source."""
    is_iterable = hasattr(source, "__iter__") and not isinstance(source, (str, bytes))
    if runtime is None and is_iterable:
        out: list[float] = []
        total = 0.0
        for v in source:
            if not is_na(v):
                total += float(v)
            out.append(total)
        return out
    if runtime is None:
        raise PineRuntimeError("ta.cum() scalar mode requires runtime")
    if state_id is None:
        state_id = "_cum_default"
    state = _state(runtime, state_id, lambda: _CumState(), _CumState)
    val = _current(source, "cum") if hasattr(source, "current") else source
    return state.update(val)


__all__ = ["cci", "cum", "mfi", "obv", "stoch", "vwap"]
