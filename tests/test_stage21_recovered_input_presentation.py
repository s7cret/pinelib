"""Presentation metadata survives admission without changing legacy identities."""

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.input import InputRegistry, InputSpec


def descriptors():
    return {
        "n": {
            "input_id": "n",
            "kind": "int",
            "default": 2,
            "alias": "n",
            "active": {"input_id": "on"},
        },
        "on": {"input_id": "on", "kind": "bool", "default": True, "alias": "enabled"},
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_dependency_uses_applied_override_independent_of_row_order(enabled):
    reg = InputRegistry.from_descriptors(descriptors(), {"enabled": enabled, "n": 0})
    assert reg.spec("n").active is enabled and reg.get("n") == 0
    assert reg.spec("n").active_input_id == "on"


@pytest.mark.parametrize(
    "fault", ["missing", "self", "wrong_type", "shape", "nonbool", "cycle"]
)
def test_bad_dependencies_fail_closed(fault):
    rows = descriptors()
    overrides = {}
    if fault == "missing":
        rows["n"]["active"] = {"input_id": "absent"}
    elif fault == "self":
        rows["on"]["active"] = {"input_id": "on"}
    elif fault == "wrong_type":
        rows["on"]["active"] = {"input_id": "n"}
    elif fault == "shape":
        rows["n"]["active"] = {"name": "enabled"}
    elif fault == "nonbool":
        overrides = {"enabled": 0}
    else:
        rows["a"] = {
            "input_id": "a",
            "kind": "bool",
            "default": True,
            "active": {"input_id": "on"},
        }
        rows["on"]["active"] = {"input_id": "a"}
    with pytest.raises(PineRuntimeError):
        InputRegistry.from_descriptors(rows, overrides)


def test_legacy_identity_shape_is_exactly_unchanged():
    spec = InputSpec("x", "int", 2, 0)
    assert set(spec.identity()) == {
        "input_id",
        "kind",
        "default",
        "value",
        "title",
        "minimum",
        "maximum",
        "step",
        "options",
        "group",
        "inline",
        "confirm",
    }
    assert "presentation" not in spec.identity()
    other = InputSpec(
        "x", "int", 2, 0, tooltip="", display="display.none", active=False
    )
    assert other.identity()["presentation"] == {
        "schema_id": "pinelib.input-presentation.v1",
        "tooltip": "",
        "display": "display.none",
        "active": False,
        "active_input_id": None,
    }
    assert InputRegistry([spec]).identity_hash != InputRegistry([other]).identity_hash
    assert InputRegistry([spec]).values_hash == InputRegistry([other]).values_hash


@pytest.mark.parametrize(
    "field,value",
    [("tooltip", 1), ("display", "unknown"), ("active", 0), ("active", None)],
)
def test_invalid_metadata_is_not_silently_ignored(field, value):
    row = {"input_id": "x", "kind": "int", "default": 2, field: value}
    with pytest.raises(PineRuntimeError):
        InputRegistry.from_descriptors({"x": row})


def test_registry_and_specs_remain_immutable():
    reg = InputRegistry.from_descriptors(descriptors(), {"enabled": False})
    with pytest.raises(AttributeError):
        reg.spec("n").active = True
    with pytest.raises(TypeError):
        reg.values["n"] = 10
