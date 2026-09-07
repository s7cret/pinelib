"""Callable float starts in v4; its versionless numeric kernel is not admission.

Primary authority reviewed 2026-09-08:
https://www.tradingview.com/pine-script-docs/v4/language/type-system/#type-casting
The immutable official surface is retained as provenance, not backported API.
"""

import json
from importlib.resources import files

import pytest

from pinelib import na
from pinelib.abi.builder import build_manifest, check_manifest
from pinelib.abi.primitives import float_v1


@pytest.fixture(scope="module")
def manifest():
    return build_manifest()


def float_row(manifest):
    return next(
        row for row in manifest["rows"] if row["symbol_id"] == "pine:function:float"
    )


@pytest.mark.parametrize("version", range(1, 7))
def test_exact_callable_version_boundary_is_not_inferred_from_kernel_existence(
    manifest, version
):
    row = float_row(manifest)
    admitted = (
        row["disposition"] == "TARGET_DIRECT" and version in row["version_availability"]
    )
    assert admitted is (version >= 4)
    assert row["version_availability"] == [4, 5, 6]
    assert row["symbol_id"] == "pine:function:float"
    assert row["producer_overload_ids"] == ["pine:function:float#canonical"]
    assert row["producer_call_forms"] == ["FUNCTION"]


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize(
    "value,expected", [(0, 0.0), (-2, -2.0), (1.25, 1.25), (na, na)]
)
def test_admitted_float_exact_numeric_and_na_behavior(
    manifest, version, value, expected
):
    assert version in float_row(manifest)["version_availability"]
    actual = float_v1(value)
    if expected is na:
        assert actual is na
    else:
        assert type(actual) is float
        assert actual == expected


def test_catalog_denominator_and_type_identity_survive_function_version_correction(
    manifest,
):
    official = json.loads(
        files("pinelib.abi").joinpath("official_pine_v6_surface.json").read_text()
    )
    assert len(manifest["rows"]) == manifest["classification"]["official_total"] == 1108
    assert {row["symbol_id"] for row in manifest["rows"]} == {
        row["symbol_id"] for row in official["rows"]
    }
    frozen = next(
        row for row in official["rows"] if row["symbol_id"] == "pine:function:float"
    )
    assert frozen["supported_versions"] == [1, 2, 3, 4, 5, 6]
    assert manifest["official_surface"]["content_hash"] == official["content_hash"]
    type_row = next(
        row for row in manifest["rows"] if row["symbol_id"] == "pine:type:float"
    )
    assert type_row["version_availability"] == [1, 2, 3, 4, 5, 6]
    assert type_row["disposition"] == "UNSUPPORTED_FAIL_CLOSED"
    assert type_row["abi_callable"] is None
    assert not any(
        row["symbol_id"] == "pine:function:float"
        for row in manifest["historical_call_bindings"]
    )


def test_closed_registry_contract_survives_manifest_regeneration(manifest):
    assert manifest["compiled_nominal_registry"] == {
        "revision": 1,
        "schema_id": "pinelib.nominal_registry.v1",
        "identity": "source-declaration",
        "admission": "module-literal-before-execution",
        "min_pine_version": 5,
    }
    check_manifest(files("pinelib.abi").joinpath("target_manifest.json"))
