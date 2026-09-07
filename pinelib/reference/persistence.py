"""Admitted intrabar collection profile, separate from heap transaction policy.

This profile covers fundamental elements. UDT/chart-point/footprint references
require their own recursively checked binding contracts, not guessed promotion.
"""

from __future__ import annotations

import math

from pinelib.core.values import is_na
from pinelib.errors import PL_REFERENCE_TYPE, PineRuntimeError

FUNDAMENTALS = frozenset({"int", "float", "bool", "color", "string"})


def validate_varip_type(
    kind: str, descriptor: str, pine_version: int
) -> tuple[str, ...]:
    if (
        kind not in {"array", "matrix", "map"}
        or pine_version < 5
        or not isinstance(descriptor, str)
    ):
        raise PineRuntimeError(
            "unsupported varip collection type/version", code=PL_REFERENCE_TYPE
        )
    text = descriptor
    if text.startswith(kind + "<") and text.endswith(">"):
        text = text[len(kind) + 1 : -1]
    parts = tuple(p.strip() for p in text.split(","))
    if len(parts) != (2 if kind == "map" else 1) or any(
        p not in FUNDAMENTALS for p in parts
    ):
        raise PineRuntimeError(
            "varip collection elements must use the admitted fundamental types",
            code=PL_REFERENCE_TYPE,
        )
    return parts


def _validate_value(value: object, expected: str) -> None:
    # Canonical NA is allowed as a missing element. It must not mask an arbitrary
    # Python object or a portable reference descriptor injected into a scalar heap.
    if is_na(value):
        return
    valid = (
        type(value) is int
        if expected == "int"
        else type(value) is bool
        if expected == "bool"
        else type(value) in (int, float)
        and (type(value) is int or math.isfinite(value))
        if expected == "float"
        else type(value) is str
    )
    if not valid:
        raise PineRuntimeError(
            "varip collection payload does not match its element type",
            code=PL_REFERENCE_TYPE,
        )


def validate_collection_payload(
    kind: str, descriptor: str, payload: object, version: int
) -> None:
    parts = validate_varip_type(kind, descriptor, version)
    if kind == "array":
        if not isinstance(payload, list):
            raise PineRuntimeError(
                "invalid varip array payload", code=PL_REFERENCE_TYPE
            )
        for value in payload:
            _validate_value(value, parts[0])
    elif kind == "matrix":
        if (
            not isinstance(payload, dict)
            or set(payload) != {"rows", "columns", "values"}
            or type(payload["rows"]) is not int
            or type(payload["columns"]) is not int
            or payload["rows"] < 0
            or payload["columns"] < 0
            or not isinstance(payload["values"], list)
            or len(payload["values"]) != payload["rows"] * payload["columns"]
        ):
            raise PineRuntimeError(
                "invalid varip matrix payload", code=PL_REFERENCE_TYPE
            )
        for value in payload["values"]:
            _validate_value(value, parts[0])
    else:
        if not isinstance(payload, list):
            raise PineRuntimeError("invalid varip map payload", code=PL_REFERENCE_TYPE)
        for pair in payload:
            if not isinstance(pair, list) or len(pair) != 2:
                raise PineRuntimeError("invalid varip map pair", code=PL_REFERENCE_TYPE)
            _validate_value(pair[0], parts[0])
            _validate_value(pair[1], parts[1])
