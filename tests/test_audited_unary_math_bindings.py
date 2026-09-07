from __future__ import annotations

import pytest

from pinelib import na
from pinelib.abi import math as math_abi
from pinelib.abi.builder import build_manifest
from pinelib.errors import PineRuntimeError


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("name,expected", [("abs", 1.25), ("ceil", -1), ("floor", -2)])
def test_audited_unary_source_bindings_and_typed_results(version, name, expected):
    manifest = build_manifest()
    historical = version < 5
    rows = manifest["historical_call_bindings"] if historical else manifest["rows"]
    row = next(item for item in rows if item["name"] == (name if historical else "math." + name))
    parameter = "x" if historical else "number"
    assert row["disposition"] == "TARGET_DIRECT"
    assert row["version_availability"] == ([1, 2, 3, 4] if historical else [5, 6])
    assert row["producer_call_forms"] == (["FUNCTION"] if historical else ["NAMESPACE_FUNCTION"])
    assert row["state_model"] == "PURE"
    assert row["parameters"] == [
        {"name": parameter, "type": "float", "qualifier_max": "series", "required": True}
    ]
    assert row["parameter_bindings"] == [
        {"abi_parameter": "value", "binding": "SOURCE_PARAMETER", "source": parameter}
    ]
    assert row["return"]["pine_type"] == ("int|float" if name == "abs" else "int")
    assert row["return"]["runtime_type"] == ("int|float" if name == "abs" else "int")
    suffixes = ["#canonical", "#overload:0"] if name == "abs" else ["#canonical"]
    assert row["producer_overload_ids"] == [
        "pine:function:math." + name + suffix for suffix in suffixes
    ]
    assert row["abi_callable"] == "pinelib.abi.math." + name + "_v1"

    function = getattr(math_abi, name + "_v1")
    actual = function(-1.25)
    assert actual == expected
    assert type(actual) is type(expected)
    assert function(na) is na
    if name == "abs":
        assert type(function(-2)) is int
        assert type(function(-2.0)) is float
        assert function(-2) == function(-2.0) == 2
    for invalid in (True, None, "-1.25"):
        with pytest.raises(PineRuntimeError):
            function(invalid)
