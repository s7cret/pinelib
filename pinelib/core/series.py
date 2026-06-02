from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pinelib.core.na import na
from pinelib.core.types import RuntimeConfig, TypeInfo
from pinelib.errors import (
    PL_HISTORY_NOT_ALLOWED,
    PL_REFERENCE_HISTORY_UNSUPPORTED,
    PineHistoryError,
    PineTypeError,
)

T = TypeVar("T")


@dataclass(slots=True)
class Series(Generic[T]):
    name: str
    dtype: str
    initial: T | object = na
    type_info: TypeInfo | None = None
    runtime_config: RuntimeConfig | None = None
    _current: T | object = field(init=False, default=na)
    _history: list[T | object] = field(init=False, default_factory=list)
    # After end_bar(), this is True. After begin_bar() / set_current(), this is False.
    # Distinguishes "between bars" (after end_bar, before next begin_bar) from
    # "during bar execution".
    _between_bars: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._current = self.initial

    @property
    def current(self) -> T | object:
        return self._current

    @property
    def committed_length(self) -> int:
        return len(self._history)

    def set_current(self, value: T | object) -> None:
        if self.dtype == "bool" and value is na:
            raise PineTypeError("Bool series cannot take na values in Pine v6")
        self._current = value
        self._between_bars = False

    def commit_current(self) -> None:
        if self.dtype in {"array", "map", "matrix"} or (
            self.type_info and not self.type_info.is_history_allowed
        ):
            self._history.clear()
            return
        self._history.append(self._current)

    def mark_between_bars(self) -> None:
        """Called by PineRuntime.end_bar() to mark we're between bars."""
        self._between_bars = True

    def __getitem__(self, offset: int) -> T | object:
        if offset < 0:
            raise PineHistoryError("Negative history offsets are not supported")
        if offset == 0:
            return self.current
        if self.type_info and not self.type_info.is_history_allowed:
            raise PineHistoryError(
                f"History access is not allowed for series {self.name!r}",
                code=PL_HISTORY_NOT_ALLOWED,
            )
        if self.type_info and self.type_info.is_reference_type:
            mode = (
                self.runtime_config.reference_history_mode if self.runtime_config else "unsupported"
            )
            if mode == "unsupported":
                raise PineHistoryError(
                    "Reference history is unsupported",
                    code=PL_REFERENCE_HISTORY_UNSUPPORTED,
                )
        history_len = len(self._history)
        if history_len == 0:
            return False if self.dtype == "bool" else na

        # Between bars: _history has the just-committed value as the last element.
        # During bar: _history has previous bars and _current is for the current bar.
        index = history_len - offset - 1 if self._between_bars else history_len - offset

        if index < 0:
            return False if self.dtype == "bool" else na
        return self._history[index]

    # ── Arithmetic operators ─────────────────────────────────────────────────────
    # TradingView Pine semantics: series in arithmetic means the current-value of that
    # series at the current bar.  All operators return a scalar (float / bool).

    def _scalar(self, other: object) -> tuple[object, object]:
        """Convert both operands to scalar values (extract Series.current)."""
        left = self._current
        right = getattr(other, "_current", other)  # other.Series → other.current
        return left, right

    def __add__(self, other: object) -> object:
        left, right = self._scalar(other)
        return left + right

    def __radd__(self, other: object) -> object:
        return self.__add__(other)

    def __sub__(self, other: object) -> object:
        left, right = self._scalar(other)
        return left - right

    def __rsub__(self, other: object) -> object:
        left, right = self._scalar(other)
        return right - left

    def __mul__(self, other: object) -> object:
        left, right = self._scalar(other)
        return left * right

    def __rmul__(self, other: object) -> object:
        return self.__mul__(other)

    def __truediv__(self, other: object) -> object:
        left, right = self._scalar(other)
        return left / right

    def __rtruediv__(self, other: object) -> object:
        left, right = self._scalar(other)
        return right / left

    def __neg__(self) -> object:
        return -self._current

    def __lt__(self, other: object) -> bool:
        left, right = self._scalar(other)
        return left < right

    def __le__(self, other: object) -> bool:
        left, right = self._scalar(other)
        return left <= right

    def __gt__(self, other: object) -> bool:
        left, right = self._scalar(other)
        return left > right

    def __ge__(self, other: object) -> bool:
        left, right = self._scalar(other)
        return left >= right

    def __eq__(self, other: object) -> bool:
        left, right = self._scalar(other)
        return left == right
