from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast, get_args

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
        if not isinstance(self.options, (tuple, list)):
            raise PineRuntimeError(
                "input options must be ordered", code=PL_INPUT_INVALID
            )
        object.__setattr__(self, "options", tuple(self.options))
        if self.kind not in get_args(InputKind):
            raise PineRuntimeError("unknown input kind", code=PL_INPUT_INVALID)
        if not isinstance(self.input_id, str) or not self.input_id:
            raise PineRuntimeError("input_id is required", code=PL_INPUT_INVALID)
        self._validate_type(self.default, "default")
        self._validate_type(self.value, "value")
        if self.kind in {"float", "price"}:
            object.__setattr__(self, "default", float(cast(int | float, self.default)))
            object.__setattr__(self, "value", float(cast(int | float, self.value)))
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise PineRuntimeError(
                "input minimum exceeds maximum", code=PL_INPUT_INVALID
            )
        for name, bound in (
            ("minimum", self.minimum),
            ("maximum", self.maximum),
            ("step", self.step),
        ):
            if bound is not None and (
                type(bound) not in (int, float) or not math.isfinite(bound)
            ):
                raise PineRuntimeError(
                    f"input {name} must be a finite number", code=PL_INPUT_INVALID
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
        for option in self.options:
            self._validate_type(option, "option")
        if self.options and any(
            item is not None for item in (self.minimum, self.maximum, self.step)
        ):
            raise PineRuntimeError(
                "options cannot be combined with numeric constraints",
                code=PL_INPUT_INVALID,
            )
        if self.options and (
            self.default not in self.options or self.value not in self.options
        ):
            raise PineRuntimeError(
                "input value is not one of the declared options",
                code=PL_INPUT_INVALID,
            )
        if self.kind in {"int", "float", "price", "time"}:
            if not math.isfinite(cast(int | float, self.default)):
                raise PineRuntimeError(
                    "input default must be finite", code=PL_INPUT_INVALID
                )
            default_number = float(cast(int | float, self.default))
            if (self.minimum is not None and default_number < self.minimum) or (
                self.maximum is not None and default_number > self.maximum
            ):
                raise PineRuntimeError(
                    "input default violates bounds", code=PL_INPUT_INVALID
                )
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

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("input registry is immutable; construct a new run")
        object.__setattr__(self, name, value)

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

    @classmethod
    def from_descriptors(
        cls,
        descriptors: Mapping[str, object],
        overrides: Mapping[str, object] | None = None,
    ) -> InputRegistry:
        from pinelib.input.admission import admit_input_descriptors

        return cls(admit_input_descriptors(descriptors, overrides))

    @property
    def values(self) -> Mapping[str, object]:
        return MappingProxyType({spec.input_id: spec.value for spec in self._specs})

    @property
    def values_hash(self) -> str:
        return sha(
            {
                "schema_id": "pinelib.input-values.v1",
                "values": to_portable(dict(self.values)),
            }
        )

    @property
    def specs(self) -> tuple[InputSpec, ...]:
        return self._specs

    @property
    def identity_hash(self) -> str:
        return self._identity_hash

    def spec(self, input_id: str) -> InputSpec:
        try:
            spec = self._by_id[input_id]
        except KeyError as error:
            raise PineRuntimeError(
                f"unknown input_id: {input_id}", code=PL_INPUT_INVALID
            ) from error
        return spec

    def get(self, input_id: str, kind: InputKind | None = None) -> object:
        spec = self.spec(input_id)
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
