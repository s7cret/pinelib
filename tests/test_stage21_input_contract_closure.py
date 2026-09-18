"""Stage 2.1 runtime input contracts: nominal enum, text area and active expressions."""

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.input import InputRegistry
from pinelib.reference.heap import PineEnumValue


def marker(enum_id: str, member: str, ordinal: int):
    return {"$pinelib_enum": {"enum_id": enum_id, "member": member, "ordinal": ordinal}}


def test_enum_input_keeps_nominal_identity_and_ordered_options():
    enum_id = "enum:source:Mode:decl"
    fast = marker(enum_id, "fast", 0)
    slow = marker(enum_id, "slow", 1)
    registry = InputRegistry.from_descriptors(
        {
            "input:mode": {
                "input_id": "input:mode", "kind": "enum", "enum_type": enum_id,
                "default": fast, "options": [fast, slow], "title": "Mode",
            }
        },
        {"input:mode": slow},
    )
    spec = registry.spec("input:mode")
    assert spec.default == PineEnumValue(enum_id, "fast", 0)
    assert spec.value == PineEnumValue(enum_id, "slow", 1)
    assert spec.options == (
        PineEnumValue(enum_id, "fast", 0), PineEnumValue(enum_id, "slow", 1)
    )
    assert spec.identity()["enum_type"] == enum_id


@pytest.mark.parametrize("fault", ["foreign_default", "foreign_option", "foreign_override", "not_enum"])
def test_enum_input_rejects_cross_type_or_untyped_values(fault):
    enum_id, other = "enum:source:A:decl", "enum:source:B:decl"
    a = marker(enum_id, "x", 0)
    b = marker(other, "x", 0)
    descriptor = {
        "input_id": "input:e", "kind": "enum", "enum_type": enum_id,
        "default": b if fault == "foreign_default" else a,
        "options": [a, b] if fault == "foreign_option" else [a],
    }
    override = b if fault == "foreign_override" else 1 if fault == "not_enum" else a
    with pytest.raises(PineRuntimeError, match="enum|kind"):
        InputRegistry.from_descriptors({"input:e": descriptor}, {"input:e": override})


def test_text_area_preserves_multiline_and_literal_backslashes():
    text = "line one\nline two\\nnot-an-escape\tend"
    registry = InputRegistry.from_descriptors(
        {"input:text": {"input_id": "input:text", "kind": "text_area", "default": text}},
        {"input:text": "a\nb\\tc"},
    )
    assert registry.get("input:text", "text_area") == "a\nb\\tc"
    assert registry.spec("input:text").default == text


def test_compound_active_expression_uses_applied_overrides_and_enum_identity():
    enum_id = "enum:source:Mode:decl"
    fast, slow = marker(enum_id, "fast", 0), marker(enum_id, "slow", 1)
    descriptors = {
        "input:on": {"input_id": "input:on", "kind": "bool", "default": True},
        "input:n": {"input_id": "input:n", "kind": "int", "default": 2},
        "input:mode": {
            "input_id": "input:mode", "kind": "enum", "enum_type": enum_id,
            "default": fast, "options": [fast, slow],
        },
        "input:value": {
            "input_id": "input:value", "kind": "float", "default": 1.5,
            "active": {
                "op": "or",
                "left": {
                    "op": "and",
                    "left": {"input_id": "input:on"},
                    "right": {
                        "op": "ge",
                        "left": {"op": "add", "left": {"input_id": "input:n"}, "right": {"op": "literal", "value": 1}},
                        "right": {"op": "literal", "value": 5},
                    },
                },
                "right": {
                    "op": "eq",
                    "left": {"input_id": "input:mode"},
                    "right": {"op": "literal", "value": slow},
                },
            },
        },
    }
    disabled = InputRegistry.from_descriptors(
        descriptors, {"input:on": False, "input:n": 10, "input:mode": fast}
    )
    enabled_by_number = InputRegistry.from_descriptors(
        descriptors, {"input:on": True, "input:n": 4, "input:mode": fast}
    )
    enabled_by_enum = InputRegistry.from_descriptors(
        descriptors, {"input:on": False, "input:n": 0, "input:mode": slow}
    )
    assert disabled.spec("input:value").active is False
    assert enabled_by_number.spec("input:value").active is True
    assert enabled_by_enum.spec("input:value").active is True
    assert enabled_by_enum.spec("input:value").value == 1.5
    assert enabled_by_enum.spec("input:value").identity()["presentation"]["schema_id"] == "pinelib.input-presentation.v2"


def test_direct_active_dependency_retains_v1_identity_shape():
    registry = InputRegistry.from_descriptors(
        {
            "input:on": {"input_id": "input:on", "kind": "bool", "default": True},
            "input:x": {"input_id": "input:x", "kind": "int", "default": 2, "active": {"input_id": "input:on"}},
        },
        {"input:on": False},
    )
    spec = registry.spec("input:x")
    assert spec.active is False and spec.active_input_id == "input:on"
    assert spec.active_expression is None
    assert spec.identity()["presentation"]["schema_id"] == "pinelib.input-presentation.v1"


@pytest.mark.parametrize("fault", ["cycle", "nonbool", "bad_arithmetic", "division_by_zero", "unknown"])
def test_active_expression_failures_are_deterministic(fault):
    descriptors = {
        "input:a": {"input_id": "input:a", "kind": "bool", "default": True},
        "input:b": {"input_id": "input:b", "kind": "int", "default": 1},
    }
    if fault == "cycle":
        descriptors["input:a"]["active"] = {"input_id": "input:b"}
        descriptors["input:b"]["active"] = {"input_id": "input:a"}
    elif fault == "nonbool":
        descriptors["input:b"]["active"] = {"input_id": "input:b"}
    elif fault == "bad_arithmetic":
        descriptors["input:b"]["active"] = {
            "op": "eq", "left": {"op": "add", "left": {"input_id": "input:a"}, "right": {"op": "literal", "value": 1}},
            "right": {"op": "literal", "value": 2},
        }
    elif fault == "division_by_zero":
        descriptors["input:a"]["active"] = {
            "op": "eq", "left": {"op": "div", "left": {"op": "literal", "value": 1}, "right": {"op": "literal", "value": 0}},
            "right": {"op": "literal", "value": 0},
        }
    else:
        descriptors["input:a"]["active"] = {"input_id": "input:missing"}
    with pytest.raises(PineRuntimeError):
        InputRegistry.from_descriptors(descriptors)
