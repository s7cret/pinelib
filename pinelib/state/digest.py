"""Incremental identities for append-only, detached runtime history.

History reads return copies. Callers cannot silently mutate a value that has
already contributed to the root. Checkpoint restoration rebuilds the chain
from admitted payloads rather than trusting a cached digest.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar, cast, overload

from pinelib.state.checkpoint import clone_runtime_value, sha

T = TypeVar("T")


@dataclass(slots=True)
class ContentChain:
    domain: str
    count: int = 0
    root: str = ""

    def __post_init__(self) -> None:
        if not self.root:
            self.root = sha(
                {
                    "algorithm": "pinelib.content-chain.v1",
                    "domain": self.domain,
                    "empty": True,
                }
            )

    def append(self, value: object) -> None:
        self.root = sha(
            {
                "algorithm": "pinelib.content-chain.v1",
                "domain": self.domain,
                "previous": self.root,
                "index": self.count,
                "value": value,
            }
        )
        self.count += 1

    def identity(self) -> dict[str, object]:
        return {
            "algorithm": "pinelib.content-chain.v1",
            "domain": self.domain,
            "count": self.count,
            "root": self.root,
        }


class AppendOnlyHistory(Sequence[T], Generic[T]):
    """Committed values with immutable public reads and an incremental root."""

    def __init__(
        self,
        domain: str,
        values: Iterable[T] = (),
        *,
        encoder: Callable[[T], object] | None = None,
        cloner: Callable[[T], T] | None = None,
    ) -> None:
        self._values: list[T] = []
        self._chain = ContentChain(domain)
        self._encoder = encoder
        self._cloner = (
            cloner
            if cloner is not None
            else lambda value: cast(T, clone_runtime_value(value))
        )
        self.extend(values)

    def append(self, value: T) -> None:
        detached = self._cloner(value)
        self._chain.append(
            detached if self._encoder is None else self._encoder(detached)
        )
        self._values.append(detached)

    def extend(self, values: Iterable[T]) -> None:
        for value in values:
            self.append(value)

    @overload
    def __getitem__(self, index: int) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> list[T]: ...
    def __getitem__(self, index: int | slice) -> T | list[T]:
        if isinstance(index, slice):
            return [self._cloner(value) for value in self._values[index]]
        return self._cloner(self._values[index])

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[T]:
        for value in self._values:
            yield self._cloner(value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple, AppendOnlyHistory)):
            return self._values == list(other)
        return NotImplemented

    def identity(self) -> dict[str, object]:
        return self._chain.identity()
