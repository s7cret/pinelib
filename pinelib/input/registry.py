from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast

from pinelib.errors import PL_INPUT_INVALID, PineRuntimeError
from pinelib.state.checkpoint import sha, to_portable

InputKind = Literal[
    "bool",
    "int",
    "float",
    "string",
    "time",
    "price",
    "symbol",
    "timeframe",
    "session",
    "color",
    "source",
]


@dataclass(frozen=True, slots=True)
class InputSpec:
    input_id: str
    kind: InputKind
    default: object
    value: object
    title: str = ""
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None
    options: tuple[object, ...] = ()
    group: str = ""
    inline: str = ""
    confirm: bool = False

    def __post_init__(self) -> None:
        if not self.input_id:
            raise PineRuntimeError("input_id is required", code=PL_INPUT_INVALID)
        self._validate_type(self.default, "default")
        self._validate_type(self.value, "value")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise PineRuntimeError(
                "input minimum exceeds maximum", code=PL_INPUT_INVALID
            )
        if self.step is not None and self.step <= 0:
            raise PineRuntimeError("input step must be positive", code=PL_INPUT_INVALID)
        if self.kind not in {"int", "float", "price", "time"} and any(
            item is not None for item in (self.minimum, self.maximum, self.step)
        ):
            raise PineRuntimeError(
                "numeric constraints are not valid for this input type",
                code=PL_INPUT_INVALID,
            )
        if self.options and self.value not in self.options:
            raise PineRuntimeError(
                "input value is not one of the declared options",
                code=PL_INPUT_INVALID,
            )
        if self.kind in {"int", "float", "price", "time"}:
            number = float(cast(int | float, self.value))
            if not math.isfinite(number):
                raise PineRuntimeError(
                    "input numeric value must be finite", code=PL_INPUT_INVALID
                )
            if self.minimum is not None and number < float(self.minimum):
                raise PineRuntimeError(
                    "input value is below minimum", code=PL_INPUT_INVALID
                )
            if self.maximum is not None and number > float(self.maximum):
                raise PineRuntimeError(
                    "input value is above maximum", code=PL_INPUT_INVALID
                )
            if self.step is not None and self.minimum is not None:
                quotient = (number - float(self.minimum)) / float(self.step)
                if abs(quotient - round(quotient)) > 1e-9:
                    raise PineRuntimeError(
                        "input value does not align to step", code=PL_INPUT_INVALID
                    )

    def _validate_type(self, value: object, field: str) -> None:
        valid = False
        if self.kind == "bool":
            valid = type(value) is bool
        elif self.kind in {"int", "time"}:
            valid = type(value) is int
        elif self.kind in {"float", "price"}:
            valid = type(value) in (int, float)
        else:
            valid = isinstance(value, str)
        if not valid:
            raise PineRuntimeError(
                f"input {field} does not match kind {self.kind}",
                code=PL_INPUT_INVALID,
            )

    def identity(self) -> dict[str, object]:
        return {
            "input_id": self.input_id,
            "kind": self.kind,
            "default": to_portable(self.default),
            "value": to_portable(self.value),
            "title": self.title,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "options": to_portable(self.options),
            "group": self.group,
            "inline": self.inline,
            "confirm": self.confirm,
        }


class InputRegistry:
    __slots__ = ("_by_id", "_identity_hash", "_sealed", "_specs")

    def __init__(self, specs: tuple[InputSpec, ...] | list[InputSpec] = ()) -> None:
        ordered = tuple(specs)
        by_id: dict[str, InputSpec] = {}
        for spec in ordered:
            if spec.input_id in by_id:
                raise PineRuntimeError("duplicate input_id", code=PL_INPUT_INVALID)
            by_id[spec.input_id] = spec
        self._specs = ordered
        self._by_id: Mapping[str, InputSpec] = MappingProxyType(by_id)
        self._identity_hash = sha({"inputs": [spec.identity() for spec in ordered]})
        self._sealed = True

    @property
    def specs(self) -> tuple[InputSpec, ...]:
        return self._specs

    @property
    def identity_hash(self) -> str:
        return self._identity_hash

    def get(self, input_id: str, kind: InputKind | None = None) -> object:
        try:
            spec = self._by_id[input_id]
        except KeyError as error:
            raise PineRuntimeError(
                f"unknown input_id: {input_id}", code=PL_INPUT_INVALID
            ) from error
        if kind is not None and spec.kind != kind:
            raise PineRuntimeError(
                f"input {input_id} has kind {spec.kind}, expected {kind}",
                code=PL_INPUT_INVALID,
            )
        return spec.value

    def identity(self) -> dict[str, object]:
        return {
            "content_hash": self.identity_hash,
            "specs": [spec.identity() for spec in self._specs],
        }
