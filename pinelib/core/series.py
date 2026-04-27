from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pinelib.core.na import na
from pinelib.core.types import RuntimeConfig, TypeInfo
from pinelib.errors import PL_HISTORY_NOT_ALLOWED, PL_REFERENCE_HISTORY_UNSUPPORTED, PineHistoryError, PineTypeError

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

    def commit_current(self) -> None:
        self._history.append(self._current)

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
            mode = self.runtime_config.reference_history_mode if self.runtime_config else "unsupported"
            if mode == "unsupported":
                raise PineHistoryError(
                    "Reference history is unsupported",
                    code=PL_REFERENCE_HISTORY_UNSUPPORTED,
                )
        index = len(self._history) - offset
        if index < 0:
            return False if self.dtype == "bool" else na
        return self._history[index]

