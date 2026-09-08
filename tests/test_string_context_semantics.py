"""Source-backed v6 strings and separately identified legacy compatibility."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, na
from pinelib.abi import string as abi
from pinelib.abi.builder import build_manifest, check_manifest
from pinelib.abi.catalog import ROWS
from pinelib.builtins import string as owner
from pinelib.errors import PL_RUNTIME_TRANSACTION_CLOSED, PL_VALUE_TYPE, PineRuntimeError

FIXTURES = Path(__file__).parent / "fixtures"
MANUAL_PATH = FIXTURES / "string_manual_expected.json"
SUPPLEMENT_PATH = FIXTURES / "string_context_supplement.json"
MANUAL = json.loads(MANUAL_PATH.read_text(encoding="utf-8"))
SUPPLEMENT = json.loads(SUPPLEMENT_PATH.read_text(encoding="utf-8"))
FUNCTIONS = ("upper", "lower", "trim", "tonumber")
V5_UNVERIFIED_NUMERIC = {"tonumber-7", "tonumber-8", "tonumber-9"}


def language(version):
    return RuntimeLanguageContext(version, "strings-v1", f"pine-v{version}", "sha256:" + "a" * 64, "compiler_annotation")


def session(version, compact=False):
    runtime = RuntimeSession(language(version))
    runtime.commit_full_identity = not compact
    return runtime


def begin(runtime, sequence=0, *, bar=0, realtime=False, final=True):
    return runtime.begin(CallbackFrame("REALTIME_TICK" if realtime else "HISTORICAL_EVAL", sequence,
                                     bar_index=bar, realtime=realtime, final_tick=final))


def matches(actual, expected):
    if expected["kind"] == "na":
        assert actual is na
    else:
        assert type(actual) is type(expected["value"])
        assert actual == expected["value"]


def call(path, name, source, version):
    if path == "owner":
        function = getattr(owner, name)
        return function(source) if name == "length" else function(source, ctx=language(version))
    runtime = session(version)
    tx = begin(runtime)
    try:
        return abi.length_v1(source) if name == "length" else getattr(abi, name + "_v2")(tx, source)
    finally:
        tx.abort()


def test_literal_fixture_identity_and_unverified_v5_rows_stay_explicit():
    assert hashlib.sha256(MANUAL_PATH.read_bytes()).hexdigest() == "67362aaa9d69bdb9297fbf862a870f4218cfef8493602936f2dca4522df728ac"
    assert hashlib.sha256(SUPPLEMENT_PATH.read_bytes()).hexdigest() == "7163768f5dacd31dc66a99971d7c9a60e535a1cafddd96c2213c8228c5a020f0"
    assert len(MANUAL["rows"]) == 34
    assert sum(len(row["versions"]) for row in MANUAL["rows"]) == 63
    assert SUPPLEMENT["authored_before_new_semantic_sut_execution"] is True
    assert SUPPLEMENT["tradingview_export"] is False
    assert SUPPLEMENT["full_stage2_accepted"] is False
    assert {row["id"] for row in MANUAL["rows"] if row["id"] in V5_UNVERIFIED_NUMERIC} == V5_UNVERIFIED_NUMERIC
    assert len([row for row in MANUAL["rows"] if 5 in row["versions"] and row["id"] not in V5_UNVERIFIED_NUMERIC]) == 26


@pytest.mark.parametrize("path", ["owner", "abi"])
@pytest.mark.parametrize("row", MANUAL["rows"], ids=lambda row: row["id"])
def test_v6_original_manual_values(path, row):
    source = row["argument"]
    matches(call(path, row["function"].split(".")[1], source, 6), row["expected"])
    assert source == row["argument"]


@pytest.mark.parametrize("path", ["owner", "abi"])
@pytest.mark.parametrize("row", [row for row in MANUAL["rows"] if 5 in row["versions"] and row["id"] not in V5_UNVERIFIED_NUMERIC], ids=lambda row: row["id"])
def test_v5_common_ascii_compatibility_values(path, row):
    matches(call(path, row["function"].split(".")[1], row["argument"], 5), row["expected"])


@pytest.mark.parametrize("path", ["owner", "abi"])
@pytest.mark.parametrize("row", SUPPLEMENT["v6_extra"])
def test_v6_full_input_decimal_and_ascii_boundaries(path, row):
    matches(call(path, row["function"], row["argument"], 6), row["expected"])


@pytest.mark.parametrize("path", ["owner", "abi"])
@pytest.mark.parametrize("row", SUPPLEMENT["na_trim"])
def test_trim_na_has_documented_empty_string_result(path, row):
    matches(call(path, "trim", na, row["version"]), row["expected"])


@pytest.mark.parametrize("version", [None, 1, 2, 3, 4, 5])
@pytest.mark.parametrize("row", SUPPLEMENT["legacy_controls"])
def test_legacy_policies_are_controls_not_v5_ascii_parity(version, row):
    function = getattr(owner, row["function"])
    actual = function(row["argument"]) if version is None else function(row["argument"], ctx=language(version))
    matches(actual, row["expected"])
    matches(getattr(abi, row["function"] + "_v1")(row["argument"]), row["expected"])
    if version is not None:
        matches(call("abi", row["function"], row["argument"], version), row["expected"])


@pytest.mark.parametrize("name", FUNCTIONS)
@pytest.mark.parametrize("version", [None, 5, 6])
def test_invalid_native_types_remain_strict_and_do_not_convert(name, version):
    class Foreign:
        def __str__(self):
            pytest.fail("foreign object must not be coerced to Pine string")

    for bad in (False, True, 0, 1.5, None, [], {}, b"1", Foreign()):
        with pytest.raises(PineRuntimeError) as error:
            if version is None:
                getattr(owner, name)(bad)
            else:
                call("owner", name, bad, version)
        assert error.value.code == PL_VALUE_TYPE
        with pytest.raises(PineRuntimeError) as error:
            if version is None:
                getattr(abi, name + "_v1")(bad)
            else:
                call("abi", name, bad, version)
        assert error.value.code == PL_VALUE_TYPE


@pytest.mark.parametrize("name", FUNCTIONS)
def test_na_exceptions_are_scoped_to_contextual_trim_only(name):
    for function in (getattr(owner, name), getattr(abi, name + "_v1")):
        with pytest.raises(PineRuntimeError) as error:
            function(na)
        assert error.value.code == PL_VALUE_TYPE
    for version in range(1, 7):
        if name == "trim" and version >= 5:
            assert call("owner", name, na, version) == ""
            continue
        for path in ("owner", "abi"):
            with pytest.raises(PineRuntimeError) as error:
                call(path, name, na, version)
            assert error.value.code == PL_VALUE_TYPE


@pytest.mark.parametrize("name", FUNCTIONS)
@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("inactive", [False, True])
def test_v2_adapter_requires_its_live_transaction(name, version, inactive):
    runtime = session(version)
    tx = begin(runtime)
    tx.commit()
    saved = runtime.checkpoint().to_dict()
    if inactive:
        # A stale transaction whose closed flag was forged still fails ownership.
        tx.closed = False
    with pytest.raises(PineRuntimeError) as error:
        getattr(abi, name + "_v2")(tx, "Ab")
    assert error.value.code == PL_RUNTIME_TRANSACTION_CLOSED
    assert runtime.checkpoint().to_dict() == saved


@pytest.mark.parametrize("name", FUNCTIONS)
@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True], ids=["full", "compact"])
def test_context_policy_survives_real_rollback_and_checkpoint(name, version, compact):
    controls = {row["function"]: row for row in SUPPLEMENT["legacy_controls"][:3]}
    controls["tonumber"] = SUPPLEMENT["legacy_controls"][-1]
    row = controls[name]
    original = next(value for value in MANUAL["rows"] if value["function"] == "str." + name and value["argument"] == row["argument"])
    expected = row["expected"] if version == 5 else original["expected"]
    interim = {"upper": ("Ab", "AB"), "lower": ("Ab", "ab"), "trim": (" \tx\n", "x"), "tonumber": ("12.5", 12.5)}[name]
    runtime = session(version, compact)

    def evaluate(tx, source, wanted):
        tx.set_series("source", source, dtype="string")
        actual = getattr(abi, name + "_v2")(tx, tx.read_series("source"))
        matches(actual, wanted)
        tx.set_series("result", actual, dtype="float" if name == "tonumber" else "string")

    tx = begin(runtime)
    evaluate(tx, row["argument"], expected)
    tx.commit()
    baseline_series = deepcopy(runtime.checkpoint().to_dict()["state"]["series"])
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    evaluate(tx, interim[0], {"kind": "value", "value": interim[1]})
    tx.commit()
    tx = begin(runtime, 2, bar=1, realtime=True, final=False)
    with pytest.raises(PineRuntimeError):
        getattr(abi, name + "_v2")(tx, False)
    tx.abort()
    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    assert saved["state"]["series"] == baseline_series
    clone = session(version, compact)
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    for current in (runtime, clone):
        tx = begin(current, 2, bar=1, realtime=True)
        evaluate(tx, row["argument"], expected)
        tx.commit()
        tx = begin(current, 3, bar=2)
        matches(tx.read_series("result", 1), expected)
        evaluate(tx, row["argument"], expected)
        tx.commit()
    assert runtime.checkpoint().to_dict() == clone.checkpoint().to_dict()


@pytest.fixture(scope="module")
def manifest():
    return build_manifest()


@pytest.mark.parametrize("name", FUNCTIONS)
@pytest.mark.parametrize("version", range(1, 7))
def test_only_existing_modern_target_admits_the_exact_context_adapter(manifest, name, version):
    row = next(row for row in manifest["rows"] if row["name"] == "str." + name)
    assert row["version_availability"] == [5, 6]
    assert (version in row["version_availability"]) is (version >= 5)
    assert row["abi_callable"] == "pinelib.abi.string." + name + "_v2"
    assert row["producer_overload_ids"] == ["pine:function:str." + name + "#canonical"]
    assert row["overload_id"] == "pine:function:str." + name + "#v1"
    assert row["state_model"] == "PURE"
    assert row["capabilities"] == ["string"]
    assert row["parameter_bindings"] == [
        {"abi_parameter": "tx", "binding": "INJECTED", "source": "RUNTIME_TRANSACTION"},
        {"abi_parameter": "source", "binding": "SOURCE_PARAMETER", "source": "string" if name == "tonumber" else "source"},
    ]
    assert row["abi_parameters"] == [
        {"annotation": "RuntimeTransaction", "has_default": False, "kind": "POSITIONAL_OR_KEYWORD", "name": "tx", "position": 0},
        {"annotation": "str", "has_default": False, "kind": "POSITIONAL_OR_KEYWORD", "name": "source", "position": 1},
    ]


def test_historical_numeric_adapter_is_still_the_original_callable():
    row = next(row for row in ROWS if row.symbol_id == "pine:function:tonumber")
    assert row.pine_versions == (1, 2, 3, 4)
    assert row.abi_callable == "pinelib.abi.string.tonumber_v1"
    module, name = row.abi_callable.rsplit(".", 1)
    assert getattr(importlib.import_module(module), name)("1e2") == 100.0


def test_manifest_outside_four_rows_and_exact_disk_remain_unchanged(manifest):
    remainder = deepcopy(manifest)
    remainder.pop("content_hash")
    remainder["rows"] = [row for row in remainder["rows"] if row["name"] not in {"str." + name for name in FUNCTIONS}]
    raw = json.dumps(remainder, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert hashlib.sha256(raw).hexdigest() == "d0eb8f035ba7f6b4a766ce321474df08397481fbf4ec1e6ff117d9884bbd256b"
    assert manifest["classification"]["official_total"] == 1108
    check_manifest(Path(__file__).parents[1] / "pinelib/abi/target_manifest.json")
