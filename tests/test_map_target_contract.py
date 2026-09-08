"""Audited map metadata and unchanged literal ABI behavior, Pine v5/v6."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from pinelib import na
from pinelib.abi import reference as abi
from pinelib.abi.builder import build_manifest, check_manifest
from pinelib.abi.manifest_v2_builder import _audited_signature, _parameter_bindings
from tests.test_language_scopes_once import begin, session


FIXTURES = Path(__file__).with_name("fixtures")
EXPECTED = json.loads((FIXTURES / "map_target_metadata_expected.json").read_text(encoding="utf-8"))
MANUAL = json.loads((FIXTURES / "map_operations_manual_expected.json").read_text(encoding="utf-8"))
MANUAL_ROWS = [row for row in MANUAL["rows"] if row["operation"] in {"put", "put_all"}]


@pytest.fixture(scope="module")
def manifest():
    return build_manifest()


@pytest.mark.parametrize("expected", EXPECTED["rows"], ids=lambda row: row["symbol_id"])
@pytest.mark.parametrize("version", range(1, 7))
def test_exact_generic_return_parameters_and_versioned_binding(manifest, expected, version):
    row = next(row for row in manifest["rows"] if row["symbol_id"] == expected["symbol_id"])
    assert row == expected
    assert row["version_availability"] == [5, 6]
    assert (version in row["version_availability"]) is (version >= 5)
    assert row["producer_overload_ids"] == [row["symbol_id"] + "#canonical"]
    assert row["state_model"] == "REFERENCE_HEAP"


def test_only_four_rows_change_and_frozen_manifest_is_exact(manifest):
    remaining = deepcopy(manifest)
    remaining.pop("content_hash")
    symbols = {row["symbol_id"] for row in EXPECTED["rows"]}
    selected = [row for row in remaining["rows"] if row["symbol_id"] in symbols]
    assert len(selected) == 4 and sum(len(row["version_availability"]) for row in selected) == 8
    remaining["rows"] = [row for row in remaining["rows"] if row["symbol_id"] not in symbols]
    encoded = json.dumps(remaining, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == EXPECTED["remainder_sha256"]
    assert manifest["content_hash"] == EXPECTED["expected_content_hash"]
    check_manifest(Path(__file__).parents[1] / "pinelib/abi/target_manifest.json")


@pytest.mark.parametrize("name", ["map.put", "map.put_all"])
@pytest.mark.parametrize("category", ["variables", "types", "constants"])
def test_audited_map_overlay_never_rewrites_noncallable_rows(name, category):
    original = {"name": name, "category": category, "parameters": [{"name": "unrelated"}], "returns": "unrelated"}
    assert _audited_signature(deepcopy(original)) == original


@pytest.mark.parametrize("category", ["functions", "methods"])
@pytest.mark.parametrize("fault", [None, "other_name", "other_category", "other_source", "other_abi"])
def test_second_map_alias_is_scoped_to_exact_callable_and_names(category, fault):
    official = {"name": "map.put_all", "category": category, "parameters": [{"name": "id2"}]}
    parameters = [{"name": "from_handle", "kind": "POSITIONAL_OR_KEYWORD", "has_default": False}]
    if fault == "other_name":
        official["name"] = "map.other"
    elif fault == "other_category":
        official["category"] = "variables"
    elif fault == "other_source":
        official["parameters"][0]["name"] = "id3"
    elif fault == "other_abi":
        parameters[0]["name"] = "other_handle"
    expected = {"abi_parameter": parameters[0]["name"],
                "binding": "SOURCE_PARAMETER" if fault is None else "UNBOUND_FAIL_CLOSED",
                "source": "id2" if fault is None else None}
    assert _parameter_bindings(official, parameters) == [expected]


@pytest.mark.parametrize("name,parameters", [("map_put_v1", ["tx", "handle", "key", "value"]),
                                            ("map_put_all_v1", ["tx", "handle", "from_handle"])])
def test_existing_public_abi_parameter_identity_is_unchanged(name, parameters):
    signature = inspect.signature(getattr(abi, name))
    assert list(signature.parameters) == parameters
    assert all(parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and parameter.default is inspect.Parameter.empty
               for parameter in signature.parameters.values())


def typed_equal(actual, expected):
    return type(actual) is type(expected) and (len(actual) == len(expected) and all(typed_equal(a, b) for a, b in zip(actual, expected))
                                              if isinstance(actual, list) else actual == expected)


@pytest.mark.parametrize("row", MANUAL_ROWS, ids=lambda row: row["id"])
@pytest.mark.parametrize("version", [5, 6])
def test_existing_abi_retains_literal_previous_value_and_order(row, version):
    runtime = session(version)
    tx = begin(runtime, 0)
    descriptor = "map<" + row["key_type"] + "," + row["value_type"] + ">"
    first = abi.map_new_v1(tx, "first", descriptor)
    for key, value in row["before"]:
        abi.map_put_v1(tx, first, key, value)
    if row["operation"] == "put":
        result = abi.map_put_v1(tx, first, *row["arguments"])
    else:
        second = first if row["same_id"] else abi.map_new_v1(tx, "second", descriptor)
        if second != first:
            for key, value in row["second"]:
                abi.map_put_v1(tx, second, key, value)
        result = abi.map_put_all_v1(tx, first, second)
        assert (first == second) is row["same_id"]
        assert typed_equal(runtime.references.read_payload(second), row["second_after"])
    if row["result"]["kind"] == "na":
        assert result is na
    elif row["result"]["kind"] == "void":
        assert result is None
    else:
        assert typed_equal(result, row["result"]["value"])
    assert typed_equal(runtime.references.read_payload(first), row["after"])
    tx.commit()


def test_manual_and_metadata_authority_bytes_are_frozen():
    assert len(MANUAL_ROWS) == 10
    assert hashlib.sha256((FIXTURES / "map_operations_manual_expected.json").read_bytes()).hexdigest() == "3afd6e3a0a1a0abe972c40190bff3dd2caf566aa5e7a7a355aa9d2acd5bb9ffe"
    assert hashlib.sha256((FIXTURES / "map_target_metadata_expected.json").read_bytes()).hexdigest() == "ab299c90c4166b64bbb3cbc599a84cfbb8f0dd30867dc28ede7096cb35235040"


@pytest.mark.parametrize("actual,expected", [(False, 0), (0, False), ([1], [1.0]), ([["a", 1]], [["a", 2]])])
def test_literal_comparison_preserves_key_and_value_types(actual, expected):
    assert not typed_equal(actual, expected)
