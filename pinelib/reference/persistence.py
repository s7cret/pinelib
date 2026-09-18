"""Admitted intrabar collection profile, separate from heap transaction policy.

Fundamental collections retain their established profile. Nominal arrays use
the admitted declaration owner; reference-valued varip fields remain separate.
"""

from __future__ import annotations

import math

from pinelib.core.values import is_na
from pinelib.errors import PL_REFERENCE_TYPE, PineRuntimeError

FUNDAMENTALS = frozenset({"int", "float", "bool", "color", "string"})


_SPECIAL_REFERENCES = frozenset({
    "line", "linefill", "box", "polyline", "label", "table",
    "chart.point", "footprint", "volume_row",
})
_COLLECTION_KINDS = frozenset({"array", "matrix", "map"})


def _split_type_arguments(text: str) -> tuple[str, ...]:
    """Split a canonical collection template without accepting nested collections.

    Pine collections cannot directly contain collection IDs.  We still parse with
    nesting awareness so malformed/host-provided descriptors fail closed instead
    of being accidentally interpreted as comma-separated scalar names.
    """
    parts: list[str] = []
    start = depth = 0
    for index, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
            if depth < 0:
                raise PineRuntimeError("collection type descriptor is malformed", code=PL_REFERENCE_TYPE)
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    if depth != 0:
        raise PineRuntimeError("collection type descriptor is malformed", code=PL_REFERENCE_TYPE)
    parts.append(text[start:].strip())
    if any(not part for part in parts):
        raise PineRuntimeError("collection type descriptor has an empty argument", code=PL_REFERENCE_TYPE)
    return tuple(parts)


def collection_type_arguments(kind: str, descriptor: str) -> tuple[str, ...] | None:
    """Return exact element/key/value types for a runtime collection descriptor.

    Older internal tests use the bare descriptors ``array``/``map``/``matrix`` as
    deliberately untyped heap fixtures.  They remain structural-only fixtures and
    are never treated as admitted Pine collection types.  All real typed forms
    are validated here for both native (``int`` / ``string,int``) and full wire
    (``array<int>`` / ``map<string,int>``) descriptors.
    """
    if kind not in _COLLECTION_KINDS or type(descriptor) is not str or not descriptor:
        raise PineRuntimeError("invalid collection type descriptor", code=PL_REFERENCE_TYPE)
    if descriptor in {kind, "any"}:
        return None
    prefix = kind + "<"
    if descriptor.startswith(prefix):
        if not descriptor.endswith(">"):
            raise PineRuntimeError("collection type descriptor is malformed", code=PL_REFERENCE_TYPE)
        body = descriptor[len(prefix):-1]
    else:
        body = descriptor
    parts = _split_type_arguments(body)
    expected = 2 if kind == "map" else 1
    if len(parts) != expected:
        raise PineRuntimeError("collection type argument arity mismatch", code=PL_REFERENCE_TYPE)
    if any(part.startswith(("array<", "matrix<", "map<")) for part in parts):
        raise PineRuntimeError("collections cannot directly contain collections", code=PL_REFERENCE_TYPE)
    if kind == "map" and parts[0] not in FUNDAMENTALS and not parts[0].startswith("enum:"):
        raise PineRuntimeError("map keys require a value or enum type", code=PL_REFERENCE_TYPE)
    return parts


def _validate_typed_value(heap, value: object, expected: str) -> None:
    from pinelib.reference.heap import PineEnumValue, ReferenceHandle

    if is_na(value):
        if expected == "bool" and heap.language.pine_version >= 6:
            raise PineRuntimeError("bool collection element cannot be na in Pine v6", code=PL_REFERENCE_TYPE)
        return
    if expected == "int":
        valid = type(value) is int
    elif expected == "bool":
        valid = type(value) is bool
    elif expected == "float":
        valid = type(value) in (int, float) and (type(value) is int or math.isfinite(value))
    elif expected in {"string", "color"}:
        valid = type(value) is str
    elif expected.startswith("enum:"):
        from pinelib.reference.nominal import enum_coerce
        enum_coerce(value, expected, heap.language.pine_version, heap.nominal_registry)
        return
    else:
        decoded = heap._decode_value(value)
        if not isinstance(decoded, ReferenceHandle):
            valid = False
        elif decoded.kind in _COLLECTION_KINDS:
            # Pine explicitly forbids collection IDs as direct collection elements.
            valid = False
        else:
            valid = heap.normalized_type_descriptor(decoded) == expected
            # Nominal UDT identities must also be admitted by the immutable registry.
            if valid and expected.startswith("udt:"):
                from pinelib.reference.nominal import require_registry
                require_registry(heap.nominal_registry, expected, "udt")
    if not valid:
        raise PineRuntimeError("collection payload does not match its declared type", code=PL_REFERENCE_TYPE)


def validate_typed_collection_argument(
    kind: str, descriptor: str, value: object, *, heap, role: str = "element"
) -> None:
    parts = collection_type_arguments(kind, descriptor)
    if parts is None:
        return
    if kind == "map":
        index = 0 if role == "key" else 1
    else:
        index = 0
    _validate_typed_value(heap, value, parts[index])


def validate_typed_collection_payload(
    kind: str, descriptor: str, payload: object, *, heap
) -> None:
    """Validate every admitted ordinary collection payload, not only ``varip``.

    This is the single runtime owner for direct ABI, compiler-created, host-created
    and restored collection objects.  The stricter intrabar/``varip`` profile is
    layered on top by :func:`validate_collection_payload`.
    """
    parts = collection_type_arguments(kind, descriptor)
    if kind == "array":
        if not isinstance(payload, list):
            raise PineRuntimeError("invalid array payload", code=PL_REFERENCE_TYPE)
        if parts is not None:
            for value in payload:
                _validate_typed_value(heap, value, parts[0])
        return
    if kind == "matrix":
        if (not isinstance(payload, dict) or set(payload) != {"rows", "columns", "values"}
                or type(payload["rows"]) is not int or type(payload["columns"]) is not int
                or payload["rows"] < 0 or payload["columns"] < 0
                or not isinstance(payload["values"], list)
                or len(payload["values"]) != payload["rows"] * payload["columns"]):
            raise PineRuntimeError("invalid matrix payload", code=PL_REFERENCE_TYPE)
        if parts is not None:
            for value in payload["values"]:
                _validate_typed_value(heap, value, parts[0])
        return
    if kind != "map" or not isinstance(payload, list):
        raise PineRuntimeError("invalid map payload", code=PL_REFERENCE_TYPE)
    seen: list[object] = []
    for pair in payload:
        if not isinstance(pair, list) or len(pair) != 2:
            raise PineRuntimeError("invalid map pair", code=PL_REFERENCE_TYPE)
        if parts is not None:
            _validate_typed_value(heap, pair[0], parts[0])
            _validate_typed_value(heap, pair[1], parts[1])
        if any(pair[0] == key for key in seen):
            raise PineRuntimeError("map payload contains duplicate keys", code=PL_REFERENCE_TYPE)
        seen.append(pair[0])


def validate_varip_type(
    kind: str, descriptor: str, pine_version: int, *, nominal_registry=None
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
    if kind == "array" and text.startswith("udt:"):
        from pinelib.reference.nominal import require_registry
        definition = require_registry(nominal_registry, text, "udt")
        if type(pine_version) is not int or nominal_registry.pine_version != pine_version:
            raise PineRuntimeError("varip nominal array registry version mismatch", code=PL_REFERENCE_TYPE)
        nominal_registry.validate_varip_collection("array<" + text + ">")
        if any(field.varip and field.type.kind not in FUNDAMENTALS for field in definition.fields):
            raise PineRuntimeError("varip nominal arrays require ordinary collection fields", code=PL_REFERENCE_TYPE)
        return (text,)
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
    kind: str, descriptor: str, payload: object, version: int, *, heap=None
) -> None:
    parts = validate_varip_type(kind, descriptor, version,
                                nominal_registry=heap.nominal_registry if heap is not None else None)
    if kind == "array":
        if not isinstance(payload, list):
            raise PineRuntimeError(
                "invalid varip array payload", code=PL_REFERENCE_TYPE
            )
        for value in payload:
            if parts[0].startswith("udt:"):
                from pinelib.reference.nominal import validate_field_value
                validate_field_value(heap, value, parts[0])
            else:
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
