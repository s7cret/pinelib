"""Only the existing modern canonical occurrence qualifier changes."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from pinelib.abi import ta
from pinelib.abi.builder import build_manifest, check_manifest
from pinelib.abi.manifest_v2_builder import _audited_signature


FIXTURE = Path(__file__).with_name("fixtures") / "valuewhen_occurrence_metadata.json"
EXPECTED = json.loads(FIXTURE.read_bytes())


@pytest.fixture(scope="module")
def manifest():
    return build_manifest()


@pytest.mark.parametrize("version", range(1, 7))
def test_exact_canonical_row_and_unchanged_availability(manifest, version):
    row = next(row for row in manifest["rows"] if row["name"] == "ta.valuewhen")
    assert row == EXPECTED["runtime_row_expected"]
    assert (version in row["version_availability"]) is (version >= 5)


def test_exact_one_row_two_tuples_and_entire_remainder(manifest):
    remaining = deepcopy(manifest)
    remaining.pop("content_hash")
    assert len(remaining["rows"]) == EXPECTED["runtime_rows"] == 1108
    selected = [r for r in remaining["rows"] if r["name"] == "ta.valuewhen"]
    assert len(selected) == 1 and sum(len(r["version_availability"]) for r in selected) == 2
    remaining["rows"] = [r for r in remaining["rows"] if r["name"] != "ta.valuewhen"]
    raw = json.dumps(remaining, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED["runtime_remainder_without_content_hash"]
    check_manifest(Path(__file__).parents[1] / "pinelib/abi/target_manifest.json")


@pytest.mark.parametrize("category", ["methods", "variables", "constants", "types"])
@pytest.mark.parametrize("name", ["ta.valuewhen", "valuewhen"])
def test_modern_occurrence_overlay_is_function_only(name, category):
    original = {"name": name, "category": category, "parameters": [{"name": "occurrence", "qualifier_max": "series"}], "returns": "preserved"}
    assert _audited_signature(deepcopy(original)) == original


@pytest.mark.parametrize("name", ["valuewhen", "ta.other"])
def test_other_function_names_are_not_inferred(name):
    original = {"name": name, "category": "functions", "parameters": [{"name": "occurrence", "qualifier_max": "series"}], "returns": "preserved"}
    assert _audited_signature(deepcopy(original)) == original


def test_existing_abi_signature_is_unchanged():
    signature = inspect.signature(ta.valuewhen_v1)
    assert list(signature.parameters) == ["tx", "state_id", "condition", "source", "occurrence"]
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and p.default is inspect.Parameter.empty for p in signature.parameters.values())


def test_literal_metadata_precedes_builder_change():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == "e85c8740f92e6b856527e7f5baa41ed36f9f8adaa7e58dcb2bd25ce5bdf45a2c"
