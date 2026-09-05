"""OP-02: immutable input identity must attest the actual normalized values."""

from __future__ import annotations

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.input import InputRegistry, InputSpec


def registry(value=2):
    return InputRegistry.from_descriptors(
        {"input:n1": {"input_id": "input:n1", "kind": "int", "default": 2}},
        {"input:n1": value},
    )


@pytest.mark.parametrize(
    "field,value", [("_sealed", False), ("_identity_hash", "forged"), ("_specs", ())]
)
def test_registry_cannot_be_mutated_after_admission(field, value):
    inputs = registry()
    with pytest.raises(AttributeError):
        setattr(inputs, field, value)
    assert inputs.get("input:n1") == 2


def test_public_values_are_read_only_and_hash_tracks_values():
    a, b = registry(2), registry(7)
    with pytest.raises(TypeError):
        a.values["input:n1"] = 99
    assert a.values_hash != b.values_hash
    assert registry().values_hash == a.values_hash


@pytest.mark.parametrize("kind", ["float", "price"])
def test_numeric_widening_has_one_applied_identity(kind):
    descriptors = {"input:n1": {"input_id": "input:n1", "kind": kind, "default": 2.0}}
    a = InputRegistry.from_descriptors(descriptors, {"input:n1": 2})
    b = InputRegistry.from_descriptors(descriptors, {"input:n1": 2.0})
    assert type(a.get("input:n1")) is float
    assert a.values_hash == b.values_hash and a.identity_hash == b.identity_hash


@pytest.mark.parametrize("bound,value", [("minimum", 3), ("maximum", 1)])
def test_valid_override_does_not_hide_invalid_default(bound, value):
    with pytest.raises(PineRuntimeError, match="default"):
        InputSpec("input:n1", "int", 2, value, **{bound: value})


def test_direct_spec_detaches_mutable_options():
    options = [2, 7]
    spec = InputSpec("input:n1", "int", 2, 2, options=options)
    inputs = InputRegistry([spec])
    before = inputs.identity_hash
    options.append(9)
    assert spec.options == (2, 7) and inputs.identity_hash == before
