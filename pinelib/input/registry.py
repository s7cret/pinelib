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
    "enum",
    "text_area",
]


def _freeze_input_metadata(value: object) -> object:
    """Detach and recursively freeze compiler-emitted input metadata."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_input_metadata(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_input_metadata(item) for item in value)
    return value


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
    tooltip: str | None = None
    display: str | None = None
    active: bool | None = None
    active_input_id: str | None = None
    active_expression: Mapping[str, object] | None = None
    enum_type: str | None = None

    def __post_init__(self) -> None:
        if self.tooltip is not None and not isinstance(self.tooltip, str):
            raise PineRuntimeError("input tooltip must be a string", code=PL_INPUT_INVALID)
        if self.display is not None and self.display not in {
            "display.all", "display.none", "display.status_line", "display.data_window"
        }:
            raise PineRuntimeError("invalid input display", code=PL_INPUT_INVALID)
        if self.active is not None and type(self.active) is not bool:
            raise PineRuntimeError("input active must be boolean", code=PL_INPUT_INVALID)
        if self.active_input_id is not None and (
            not isinstance(self.active_input_id, str) or not self.active_input_id or self.active is None
        ):
            raise PineRuntimeError("invalid input active dependency", code=PL_INPUT_INVALID)
        if self.active_expression is not None and not isinstance(self.active_expression, Mapping):
            raise PineRuntimeError("invalid input active expression", code=PL_INPUT_INVALID)
        if self.active_expression is not None:
            object.__setattr__(
                self, "active_expression", _freeze_input_metadata(self.active_expression)
            )
        if self.kind == "enum":
            if not isinstance(self.enum_type, str) or not self.enum_type:
                raise PineRuntimeError("enum input requires an exact enum type", code=PL_INPUT_INVALID)
        elif self.enum_type is not None:
            raise PineRuntimeError("enum_type is valid only for enum inputs", code=PL_INPUT_INVALID)
        if not isinstance(self.options, (tuple, list)):
            raise PineRuntimeError(
                "input options must be ordered", code=PL_INPUT_INVALID
            )
        object.__setattr__(self, "options", tuple(self.options))
        if self.kind not in get_args(InputKind):
            raise PineRuntimeError("unknown input kind", code=PL_INPUT_INVALID)
        if not isinstance(self.input_id, str) or not self.input_id:
            raise PineRuntimeError("input_id is required", code=PL_INPUT_INVALID)
        if self.kind == "enum":
            object.__setattr__(self, "default", self._enum_value(self.default, "default"))
            object.__setattr__(self, "value", self._enum_value(self.value, "value"))
            object.__setattr__(self, "options", tuple(self._enum_value(item, "option") for item in self.options))
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
                type(bound) not in (int, float)
                or (type(bound) is float and not math.isfinite(bound))
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
            default_number = cast(int | float, self.default)
            number = cast(int | float, self.value)
            # Python ints are arbitrary precision and therefore finite.  Never
            # coerce them through float here: doing so can round an out-of-range
            # integer onto maxval/minval and silently admit it.
            if type(default_number) is float and not math.isfinite(default_number):
                raise PineRuntimeError(
                    "input default must be finite", code=PL_INPUT_INVALID
                )
            if (self.minimum is not None and default_number < self.minimum) or (
                self.maximum is not None and default_number > self.maximum
            ):
                raise PineRuntimeError(
                    "input default violates bounds", code=PL_INPUT_INVALID
                )
            if type(number) is float and not math.isfinite(number):
                raise PineRuntimeError(
                    "input numeric value must be finite", code=PL_INPUT_INVALID
                )
            if self.minimum is not None and number < self.minimum:
                raise PineRuntimeError(
                    "input value is below minimum", code=PL_INPUT_INVALID
                )
            if self.maximum is not None and number > self.maximum:
                raise PineRuntimeError(
                    "input value is above maximum", code=PL_INPUT_INVALID
                )

    def _enum_value(self, value: object, field: str):
        from pinelib.reference.heap import PineEnumValue

        if isinstance(value, PineEnumValue):
            result = value
        elif isinstance(value, Mapping) and set(value) == {"$pinelib_enum"}:
            marker = value["$pinelib_enum"]
            if not isinstance(marker, Mapping) or set(marker) != {"enum_id", "member", "ordinal"}:
                raise PineRuntimeError(f"input {field} has an invalid enum marker", code=PL_INPUT_INVALID)
            result = PineEnumValue(marker["enum_id"], marker["member"], marker["ordinal"])
        else:
            raise PineRuntimeError(f"input {field} does not match kind enum", code=PL_INPUT_INVALID)
        if result.enum_id != self.enum_type:
            raise PineRuntimeError(f"input {field} belongs to another enum", code=PL_INPUT_INVALID)
        return result

    def _validate_type(self, value: object, field: str) -> None:
        valid = False
        if self.kind == "bool":
            valid = type(value) is bool
        elif self.kind in {"int", "time"}:
            valid = type(value) is int
        elif self.kind in {"float", "price"}:
            valid = type(value) in (int, float)
        elif self.kind == "enum":
            from pinelib.reference.heap import PineEnumValue
            valid = isinstance(value, PineEnumValue) and value.enum_id == self.enum_type
        else:
            valid = isinstance(value, str)
        if not valid:
            raise PineRuntimeError(
                f"input {field} does not match kind {self.kind}",
                code=PL_INPUT_INVALID,
            )

    def identity(self) -> dict[str, object]:
        identity = {
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
        # Retain the exact old identity when no new metadata was supplied.
        if any(v is not None for v in (self.tooltip, self.display, self.active, self.active_input_id, self.active_expression)):
            identity["presentation"] = {
                "schema_id": "pinelib.input-presentation.v2" if self.active_expression is not None else "pinelib.input-presentation.v1",
                "tooltip": self.tooltip, "display": self.display,
                "active": self.active, "active_input_id": self.active_input_id,
            }
            if self.active_expression is not None:
                identity["presentation"]["active_expression"] = to_portable(dict(self.active_expression))
        if self.enum_type is not None:
            identity["enum_type"] = self.enum_type
        return identity


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
