from __future__ import annotations

from collections.abc import Iterable, Iterator
from copy import copy as shallow_copy
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pinelib.core.types import RuntimeConfig
from pinelib.errors import PL_REFERENCE_HISTORY_UNSUPPORTED, PineUnsupportedFeatureError

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


class PineArray(Generic[T]):
    def __init__(self, values: Iterable[T] | None = None) -> None:
        self._values = list(values or [])

    # Factory methods for array.new_float, array.new_int, etc.
    @classmethod
    def new_float(cls, initial: float | None = None, max_size: int | None = None) -> PineArray[float]:
        arr = cls()
        if initial is not None:
            arr._values = [initial]
        if max_size is not None:
            arr._max_size = max_size
        return arr

    @classmethod
    def new_int(cls, initial: int | None = None, max_size: int | None = None) -> PineArray[int]:
        arr = cls()
        if initial is not None:
            arr._values = [initial]
        if max_size is not None:
            arr._max_size = max_size
        return arr

    @classmethod
    def new_bool(cls, initial: bool | None = None, max_size: int | None = None) -> PineArray[bool]:
        arr = cls()
        if initial is not None:
            arr._values = [initial]
        if max_size is not None:
            arr._max_size = max_size
        return arr

    @classmethod
    def new_string(cls, initial: str | None = None, max_size: int | None = None) -> PineArray[str]:
        arr = cls()
        if initial is not None:
            arr._values = [initial]
        if max_size is not None:
            arr._max_size = max_size
        return arr

    @classmethod
    def new_color(cls, initial: int | None = None, max_size: int | None = None) -> PineArray[int]:
        arr = cls()
        if initial is not None:
            arr._values = [initial]
        if max_size is not None:
            arr._max_size = max_size
        return arr

    @property
    def size(self) -> int:
        return len(self._values)

    def shift(self, index: int = 0) -> T:
        if index >= len(self._values):
            from pinelib.core.na import NA
            return NA  # type: ignore[return-value]
        return self._values[index]

    def avg(self) -> float:
        if not self._values:
            return float("nan")
        return sum(self._values) / len(self._values)

    def sum(self) -> float:
        return sum(self._values)

    def min(self) -> float:
        if not self._values:
            return float("nan")
        return min(self._values)

    def max(self) -> float:
        if not self._values:
            return float("nan")
        return max(self._values)

    def sort(self, order: str = "asc") -> None:
        self._values.sort(reverse=(order == "desc"))

    def push(self, value: T) -> None:
        self._values.append(value)

    def get(self, index: int) -> T:
        return self._values[index]

    def set(self, index: int, value: T) -> None:
        self._values[index] = value

    def copy(self) -> PineArray[T]:
        return PineArray(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[T]:
        return iter(self._values)


class PineMap(Generic[K, V]):
    def __init__(self, values: dict[K, V] | None = None) -> None:
        self._values = dict(values or {})

    def put(self, key: K, value: V) -> None:
        self._values[key] = value

    def get(self, key: K, default: V | None = None) -> V | None:
        return self._values.get(key, default)

    def remove(self, key: K) -> V:
        return self._values.pop(key)

    def copy(self) -> PineMap[K, V]:
        return PineMap(self._values)

    def __len__(self) -> int:
        return len(self._values)


@dataclass(slots=True)
class PineMatrix(Generic[T]):
    rows: int
    columns: int
    initial: T | None = None
    _values: list[list[T | None]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._values = [
            [shallow_copy(self.initial) for _ in range(self.columns)] for _ in range(self.rows)
        ]

    def get(self, row: int, column: int) -> T | None:
        return self._values[row][column]

    def set(self, row: int, column: int, value: T) -> None:
        self._values[row][column] = value

    def copy(self) -> PineMatrix[T]:
        clone: PineMatrix[T] = PineMatrix(self.rows, self.columns)
        clone._values = [list(row) for row in self._values]
        return clone


def reference_history(ref: object, index: int, config: RuntimeConfig | None = None) -> object:
    del ref, index
    message = "History access for reference types is not supported in v0.5.0"
    if config is not None:
        config.emit_diagnostic(PL_REFERENCE_HISTORY_UNSUPPORTED, message)
    raise PineUnsupportedFeatureError(message, code=PL_REFERENCE_HISTORY_UNSUPPORTED)
