"""Admit compiler-emitted input descriptors and one immutable set of overrides."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pinelib.errors import PL_INPUT_INVALID, PineRuntimeError
from pinelib.input.registry import InputKind, InputSpec

_ALLOWED = {
    "input_id",
    "kind",
    "default",
    "title",
    "minimum",
    "maximum",
    "step",
    "options",
    "group",
    "inline",
    "confirm",
    "tooltip",
    "display",
    "active",
    "alias",
    "source_span",
}
_SOURCES = {"open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "hlcc4"}


def admit_input_descriptors(
    descriptors: Mapping[str, object], overrides: Mapping[str, object] | None
) -> list[InputSpec]:
    if not isinstance(descriptors, Mapping) or (
        overrides is not None and not isinstance(overrides, Mapping)
    ):
        raise PineRuntimeError(
            "input descriptors and overrides must be mappings", code=PL_INPUT_INVALID
        )
    overrides = {} if overrides is None else dict(overrides)
    aliases: dict[str, list[str]] = {}
    normalized: dict[str, Mapping[str, object]] = {}
    for input_id, row in descriptors.items():
        if (
            not isinstance(input_id, str)
            or not isinstance(row, Mapping)
            or row.get("input_id") != input_id
        ):
            raise PineRuntimeError(
                "malformed input descriptor identity", code=PL_INPUT_INVALID
            )
        if set(row) - _ALLOWED or not {"input_id", "kind", "default"} <= set(row):
            raise PineRuntimeError(
                "malformed input descriptor fields", code=PL_INPUT_INVALID
            )
        alias = row.get("alias")
        if alias is not None:
            if not isinstance(alias, str) or not alias:
                raise PineRuntimeError(
                    "invalid input variable alias", code=PL_INPUT_INVALID
                )
            aliases.setdefault(alias, []).append(input_id)
        for field in ("title", "group", "inline", "tooltip"):
            if field in row and not isinstance(row[field], str):
                raise PineRuntimeError(
                    f"input {field} must be a string", code=PL_INPUT_INVALID
                )
        if "confirm" in row and type(row["confirm"]) is not bool:
            raise PineRuntimeError(
                "input confirm must be boolean", code=PL_INPUT_INVALID
            )
        normalized[input_id] = row
    values: dict[str, object] = {}
    for key, value in overrides.items():
        if not isinstance(key, str):
            raise PineRuntimeError(
                "input override keys must be strings", code=PL_INPUT_INVALID
            )
        if key in normalized:
            input_id = key
        elif len(aliases.get(key, [])) == 1:
            input_id = aliases[key][0]
        else:
            raise PineRuntimeError(
                f"unknown or ambiguous input override: {key}", code=PL_INPUT_INVALID
            )
        if input_id in values:
            raise PineRuntimeError(
                f"duplicate override for {input_id}", code=PL_INPUT_INVALID
            )
        values[input_id] = value
    result = []
    for input_id, row in normalized.items():
        kind = cast(InputKind, row["kind"])
        default = row["default"]
        value = values.get(input_id, default)
        if kind == "source" and (default not in _SOURCES or value not in _SOURCES):
            raise PineRuntimeError(
                "source input requires an admitted built-in series; external series are not connected",
                code=PL_INPUT_INVALID,
            )
        options = row.get("options", ())
        if not isinstance(options, (list, tuple)):
            raise PineRuntimeError(
                "input options must be an ordered sequence", code=PL_INPUT_INVALID
            )
        result.append(
            InputSpec(
                input_id,
                kind,
                default,
                value,
                title=cast(str, row.get("title", row.get("alias", ""))),
                minimum=cast(int | float | None, row.get("minimum")),
                maximum=cast(int | float | None, row.get("maximum")),
                step=cast(int | float | None, row.get("step")),
                options=tuple(options),
                group=cast(str, row.get("group", "")),
                inline=cast(str, row.get("inline", "")),
                confirm=cast(bool, row.get("confirm", False)),
            )
        )
    return result
