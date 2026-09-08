"""Primary string source contracts and narrowly scoped ABI alias."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from pinelib.abi.builder import build_manifest, check_manifest
from pinelib.abi.manifest_v2_builder import _audited_signature, _parameter_bindings

EXPECTED = json.loads(
    (
        Path(__file__).with_name("fixtures") / "string_target_primary_expected.json"
    ).read_bytes()
)


@pytest.fixture(scope="module")
def manifest():
    return build_manifest()


@pytest.mark.parametrize("expected", EXPECTED["rows"], ids=lambda r: r["symbol_id"])
@pytest.mark.parametrize("version", range(1, 7))
def test_primary_string_parameter_type_name_and_version(manifest, expected, version):
    row = next(r for r in manifest["rows"] if r["symbol_id"] == expected["symbol_id"])
    assert row == expected
    assert (version in row["version_availability"]) is (version >= 5)


def test_only_three_rows_and_expected_content_hash(manifest):
    remaining = deepcopy(manifest)
    remaining.pop("content_hash")
    names = {r["name"] for r in EXPECTED["rows"]}
    remaining["rows"] = [r for r in remaining["rows"] if r["name"] not in names]
    raw = json.dumps(
        remaining, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED["remainder_sha256"]
    assert manifest["content_hash"] == EXPECTED["expected_content_hash"]
    check_manifest(Path(__file__).parents[1] / "pinelib/abi/target_manifest.json")


@pytest.mark.parametrize("name", ["str.upper", "str.lower", "str.tonumber"])
@pytest.mark.parametrize("category", ["methods", "variables", "constants"])
def test_source_projection_is_function_only(name, category):
    before = dict(name=name, category=category, parameters=[], returns="unchanged")
    assert _audited_signature(deepcopy(before)) == before


@pytest.mark.parametrize("category", ["functions", "methods", "constants"])
@pytest.mark.parametrize("fault", [None, "name", "source", "abi"])
def test_string_alias_is_scoped_to_exact_callable(category, fault):
    official = dict(
        name="other" if fault == "name" else "str.tonumber",
        category=category,
        parameters=[dict(name="other" if fault == "source" else "string")],
    )
    parameter = dict(
        name="other" if fault == "abi" else "source",
        kind="POSITIONAL_OR_KEYWORD",
        has_default=False,
    )
    admitted = category == "functions" and fault is None
    assert _parameter_bindings(official, [parameter]) == [
        dict(
            abi_parameter=parameter["name"],
            binding="SOURCE_PARAMETER" if admitted else "UNBOUND_FAIL_CLOSED",
            source="string" if admitted else None,
        )
    ]
