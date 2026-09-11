"""Exact nominal value admission shared by generated code and heap restoration."""

from __future__ import annotations

import math

from pinelib.core.values import is_na, na
from pinelib.errors import PL_REFERENCE_TYPE, PineRuntimeError


def nominal_type(dtype: object, kind: str, version: int) -> str:
    if version < 5 or type(dtype) is not str or not dtype.startswith(kind + ":") or not dtype[len(kind) + 1:]:
        raise PineRuntimeError(f"{kind} requires an exact nominal type and Pine v5/v6", code=PL_REFERENCE_TYPE)
    return dtype


def enum_coerce(value: object, dtype: str, version: int, registry=None):
    from pinelib.reference.heap import PineEnumValue

    nominal_type(dtype, "enum", version)
    require_registry(registry, dtype, "enum")
    if is_na(value):
        return na
    if isinstance(value, dict) and set(value) == {"$pinelib_enum"}:
        marker = value["$pinelib_enum"]
        if not isinstance(marker, dict) or set(marker) != {"enum_id", "member", "ordinal"}:
            raise PineRuntimeError("invalid enum marker", code=PL_REFERENCE_TYPE)
        value = PineEnumValue(marker["enum_id"], marker["member"], marker["ordinal"])
    if not isinstance(value, PineEnumValue) or value.enum_id != dtype:
        raise PineRuntimeError("enum value differs from declared nominal type", code=PL_REFERENCE_TYPE)
    registry.enum_member(dtype, value.member, value.ordinal)
    return value


def require_registry(registry, dtype, kind):
    from pinelib.reference.registry import NominalTypeRegistry
    if type(registry) is not NominalTypeRegistry:
        raise PineRuntimeError("nominal values require an admitted immutable registry", code=PL_REFERENCE_TYPE)
    definition = registry.lookup(dtype)
    if definition.kind != kind:
        raise PineRuntimeError("nominal declaration kind mismatch", code=PL_REFERENCE_TYPE)
    return definition


def validate_field_type(dtype: object, version: int, registry=None) -> None:
    if type(dtype) is str and dtype in {"int", "float", "bool", "color", "string"}:
        return
    if type(dtype) is str and dtype.startswith(("udt:", "enum:")):
        nominal_type(dtype, dtype.split(":", 1)[0], version)
        require_registry(registry, dtype, dtype.split(":", 1)[0])
        return
    if type(dtype) is str and dtype.startswith(("array<", "matrix<", "map<")) and dtype.endswith(">"):
        if "udt:" in dtype or "enum:" in dtype:
            if registry is None:
                raise PineRuntimeError("nominal collection requires an admitted registry", code=PL_REFERENCE_TYPE)
            registry.parse_type(dtype)
        return
    raise PineRuntimeError("unsupported UDT field type", code=PL_REFERENCE_TYPE)


def validate_field_value(heap, value: object, dtype: str) -> None:
    from pinelib.reference.heap import ReferenceHandle

    validate_field_type(dtype, heap.language.pine_version, heap.nominal_registry)
    if is_na(value):
        if dtype == "bool" and heap.language.pine_version >= 6:
            raise PineRuntimeError("bool UDT field cannot be na in Pine v6", code=PL_REFERENCE_TYPE)
        return
    if dtype.startswith("enum:"):
        enum_coerce(value, dtype, heap.language.pine_version, heap.nominal_registry)
        return
    if dtype.startswith(("array<", "matrix<", "map<", "udt:")):
        value = heap._decode_value(value)
        kind = "udt" if dtype.startswith("udt:") else dtype.split("<", 1)[0]
        if not isinstance(value, ReferenceHandle) or value.kind != kind:
            raise PineRuntimeError("UDT reference field kind mismatch", code=PL_REFERENCE_TYPE)
        actual = heap.normalized_type_descriptor(value)
        if actual != dtype:
            raise PineRuntimeError("UDT reference field nominal type mismatch", code=PL_REFERENCE_TYPE)
        return
    valid = (type(value) is int if dtype == "int" else type(value) is bool if dtype == "bool"
             else type(value) in (int, float) and math.isfinite(value) if dtype == "float"
             else type(value) is str)
    if not valid:
        raise PineRuntimeError("UDT field value does not match its declared type", code=PL_REFERENCE_TYPE)


def validate_udt_schema(heap, dtype, fields, field_types, varip_fields):
    nominal_type(dtype, "udt", heap.language.pine_version)
    definition = require_registry(heap.nominal_registry, dtype, "udt")
    if (not isinstance(fields, dict) or not isinstance(field_types, dict)
        or set(fields) != set(field_types)
        or any(type(key) is not str or not key for key in field_types)
        or not isinstance(varip_fields, (list, tuple))
        or any(type(name) is not str for name in varip_fields)
        or len(set(varip_fields)) != len(varip_fields)
        or not set(varip_fields).issubset(field_types)):
        raise PineRuntimeError("invalid typed UDT field schema", code=PL_REFERENCE_TYPE)
    expected_types = {field.name: field.type.text for field in definition.fields}
    expected_varip = sorted(field.name for field in definition.fields if field.varip)
    if field_types != expected_types or sorted(varip_fields) != expected_varip:
        raise PineRuntimeError("UDT schema differs from admitted declaration", code=PL_REFERENCE_TYPE)
    for name, field_type in field_types.items():
        validate_field_type(field_type, heap.language.pine_version, heap.nominal_registry)
        if name in varip_fields and field_type not in {"int", "float", "bool", "color", "string"} and not field_type.startswith("enum:"):
            raise PineRuntimeError("varip UDT fields currently require fundamental or enum values", code=PL_REFERENCE_TYPE)
        validate_field_value(heap, fields[name], field_type)
    return {"fields": dict(field_types), "varip_fields": sorted(varip_fields)}
