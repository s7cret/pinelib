from __future__ import annotations

import math

import pytest

from pinelib import na
from pinelib.abi import primitives
from pinelib.abi.builder import build_manifest
from pinelib.errors import PL_VALUE_DOMAIN, PL_VALUE_TYPE, PineRuntimeError


def float_target(version):
    row = next(row for row in build_manifest()["rows"] if row["symbol_id"] == "pine:function:float")
    assert row["disposition"] == "TARGET_DIRECT"
    assert version in row["version_availability"]
    assert row["abi_callable"] == "pinelib.abi.primitives.float_v1"
    return primitives.float_v1


@pytest.mark.parametrize("version", range(1, 7))
def test_float_cast_preserves_na_and_converts_only_pine_numbers(version):
    cast = float_target(version)
    assert cast(na) is na
    for value in (0, 1, -2, 1.5, -0.0, 1e308, 5e-324):
        actual = cast(value)
        assert type(actual) is float
        assert actual == value
    assert math.copysign(1.0, cast(-0.0)) == -1.0


@pytest.mark.parametrize("version", range(1, 7))
def test_float_cast_rejects_python_coercions_and_nonfinite_values(version):
    cast = float_target(version)

    class Floatable:
        def __float__(self):
            pytest.fail("Pine float must not call a foreign object's conversion")

    for value in (
        False,
        True,
        None,
        "1.5",
        "NaN",
        [],
        {},
        Floatable(),
        float("nan"),
        float("inf"),
        float("-inf"),
    ):
        with pytest.raises(PineRuntimeError) as error:
            cast(value)
        assert error.value.code == PL_VALUE_TYPE
    with pytest.raises(PineRuntimeError) as error:
        cast(10**400)
    assert error.value.code == PL_VALUE_DOMAIN


def test_float_target_has_exact_source_identity_and_complete_binding():
    row = next(row for row in build_manifest()["rows"] if row["symbol_id"] == "pine:function:float")
    assert row["version_availability"] == [1, 2, 3, 4, 5, 6]
    assert row["call_form"] == "global_function"
    assert row["producer_call_forms"] == ["FUNCTION"]
    assert row["producer_overload_ids"] == ["pine:function:float#canonical"]
    assert row["parameters"] == [
        {"name": "x", "type": "float", "qualifier_max": "series", "required": True}
    ]
    assert row["parameter_bindings"] == [
        {"abi_parameter": "x", "binding": "SOURCE_PARAMETER", "source": "x"}
    ]
    assert row["return"]["runtime_type"] == "float"


def test_float_function_does_not_authorize_the_type_keyword_as_a_call():
    manifest = build_manifest()
    keyword = next(row for row in manifest["rows"] if row["symbol_id"] == "pine:type:float")
    assert keyword["disposition"] == "UNSUPPORTED_FAIL_CLOSED"
    assert keyword["abi_callable"] is None
    assert manifest["classification"]["official_total"] == 1108
