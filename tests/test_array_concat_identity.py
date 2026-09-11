"""Independent first-ID return examples and existing heap lifecycle controls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from pinelib import CallbackFrame
from pinelib.abi import reference as ref
from pinelib.abi.builder import build_manifest, check_manifest
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_concat
from pinelib.reference.heap import ReferenceHandle
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies
from tests.stage3_helpers import session

FIXTURE = Path(__file__).parent / "fixtures/array_concat_manual_expected.json"
CASES = json.loads(FIXTURE.read_bytes())["cases"]


def new_array(tx, values, object_id, dtype="int"):
    return tx.references.create(object_id, "array", f"array<{dtype}>", list(values))


def test_manual_fixture_is_the_original_independent_table():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == "20d833ca9c31265c48c250dbec7edc5a9da3f9b2885e098fd0196e4d4e86ee9e"


@pytest.mark.parametrize("case", CASES, ids=lambda c:c["case_id"])
@pytest.mark.parametrize("entry", ["owner", "abi"])
def test_manual_first_id_alias_and_payloads(case, entry):
    runtime = session(case["version"])
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    first = new_array(tx, case["id1_initial"], "first", case["element_type"])
    second = first if case["same_reference"] else new_array(tx, case["id2_initial"], "second", case["element_type"])
    before_ids = [r["object_id"] for r in tx.references.to_json()["objects"]]
    result = array_concat(tx.references, first, second) if entry == "owner" else ref.array_concat_v1(tx, first, second)
    assert case["expected_return_identity"] == "id1"
    assert result is first
    assert tx.references.read_payload(result) == case["expected_after_concat"]
    ref.array_push_v1(tx, result, case["push_through_return"])
    assert tx.references.read_payload(first) == case["expected_id1_final"]
    assert tx.references.read_payload(second) == case["expected_id2_final"]
    assert [r["object_id"] for r in tx.references.to_json()["objects"]] == before_ids
    tx.commit()


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize("kind,parent_expected,target_expected", [
    ("target", [0, 1, 2, 9, 3], [1, 2, 9]),
    ("source", [0, 1, 2, 3], [9, 1, 2]),
    ("self_view", [0, 1, 2, 1, 2, 3], [1, 2, 1, 2]),
    ("overlapping", [0, 1, 1, 2, 2, 3], [0, 1, 1, 2]),
])
def test_slice_target_identity_parent_insertion_and_snapshot_source(version, kind, parent_expected, target_expected):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    parent = new_array(tx, [0, 1, 2, 3], "parent")
    second = new_array(tx, [9], "second")
    view = ref.array_slice_v1(tx, parent, 1, 3, "view")
    copy = ref.array_copy_v1(tx, parent, "copy")
    if kind == "target": target, source = view, second
    elif kind == "source": target, source = second, view
    elif kind == "self_view": target, source = view, view
    else: target, source = ref.array_slice_v1(tx, parent, 0, 2, "left"), view
    ids = [r["object_id"] for r in tx.references.to_json()["objects"]]
    result = ref.array_concat_v1(tx, target, source)
    assert result is target
    assert runtime.references.read_payload(parent) == parent_expected
    assert runtime.references.read_payload(result) == target_expected
    assert runtime.references.read_payload(copy) == [0, 1, 2, 3]
    assert [r["object_id"] for r in tx.references.to_json()["objects"]] == ids
    tx.commit()
    clone = session(version)
    clone.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    assert clone.references.read_payload(result) == target_expected
    assert clone.references.read_payload(parent) == parent_expected


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("mode,aborted,final", [("var", [1], [1, 2]), ("varip", [1, 2, 3], [1, 2, 3, 2])])
def test_return_alias_ordinary_and_varip_abort_retry_checkpoint(version, compact, mode, aborted, final):
    runtime = session(version); runtime.commit_full_identity = not compact
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    first = tx.declare_reference_v1("first", mode, lambda:new_array(tx, [1], "first"), "array<int>")
    second = new_array(tx, [2], "second")
    copy = ref.array_copy_v1(tx, first, "copy")
    tx.commit()
    transcript = deepcopy(runtime.transcript.to_dict())
    tx = runtime.begin(CallbackFrame("REALTIME_TICK", 1, bar_index=1, realtime=True, final_tick=False))
    result = ref.array_concat_v1(tx, first, second)
    assert result is first
    ref.array_push_v1(tx, result, 3)
    assert tx.references.read_payload(first) == [1, 2, 3]
    tx.abort()
    assert runtime.sequence == 0
    assert runtime.transcript.to_dict() == transcript
    assert runtime.references.read_payload(result) == aborted
    saved = runtime.checkpoint().to_dict()
    clone = session(version); clone.commit_full_identity = not compact
    clone.restore(json.loads(json.dumps(saved)))
    assert clone.checkpoint().to_dict() == saved
    tx = clone.begin(CallbackFrame("REALTIME_TICK", 1, bar_index=1, realtime=True, final_tick=True))
    assert ref.array_concat_v1(tx, result, second) is result
    tx.commit()
    assert clone.sequence == 1
    assert clone.references.read_payload(first) == final
    assert clone.references.read_payload(second) == [2]
    assert clone.references.read_payload(copy) == [1]
    restored = session(version); restored.commit_full_identity = not compact
    restored.restore(json.loads(json.dumps(clone.checkpoint().to_dict())))
    assert restored.references.read_payload(first) == final


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize("bad_target", [False, True])
@pytest.mark.parametrize("bad_kind", ["wrong_kind", "missing"])
def test_existing_invalid_reference_guards_leave_heap_unchanged(version, bad_target, bad_kind):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    first = new_array(tx, [1], "first")
    bad = ReferenceHandle("missing", "array") if bad_kind == "missing" else tx.references.create("map", "map", "map<int,int>", [])
    before = deepcopy(tx.references.to_json())
    with pytest.raises(PineRuntimeError):
        ref.array_concat_v1(tx, bad if bad_target else first, first if bad_target else bad)
    assert tx.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize("slice_target", [False, True])
def test_size_overflow_is_atomic_including_parent_and_slice(version, slice_target):
    # The limit also counts the stored slice descriptor, so admit that setup
    # and exceed the limit only when concat grows the actual parent array.
    runtime = session(version, policies=RuntimePolicies(resource=ResourcePolicy(max_collection_elements=32)))
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    parent = new_array(tx, list(range(31)), "parent")
    second = new_array(tx, [3, 4], "second")
    target = ref.array_slice_v1(tx, parent, 1, 3, "view") if slice_target else parent
    before = deepcopy(tx.references.to_json())
    with pytest.raises(PineRuntimeError, match="collection element limit"):
        ref.array_concat_v1(tx, target, second)
    assert tx.references.to_json() == before
    tx.abort()


@pytest.fixture(scope="module")
def manifest():
    return build_manifest()


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("method", [False, True])
def test_exact_versioned_return_and_receiver_contract(manifest, version, method):
    symbol = "pine:" + ("method" if method else "function") + ":array.concat"
    row = next(r for r in manifest["rows"] if r["symbol_id"] == symbol)
    assert row["version_availability"] == ([5, 6] if method else [4, 5, 6])
    assert (version in row["version_availability"]) is (version >= (5 if method else 4))
    assert row["producer_overload_ids"] == [symbol + "#canonical"]
    assert row["return"] == {"identity":"REFERENCE", "pine_type":"array<any>", "runtime_type":"array<T>", "tuple_arity":0}
    bindings = {p["abi_parameter"]:p for p in row["parameter_bindings"]}
    assert bindings["id1"] == {"abi_parameter":"id1", "binding":"METHOD_RECEIVER" if method else "SOURCE_PARAMETER", "source":"receiver" if method else "id1"}
    assert bindings["id2"] == {"abi_parameter":"id2", "binding":"SOURCE_PARAMETER", "source":"id2"}


def test_every_non_concat_manifest_field_is_unchanged_and_disk_is_exact(manifest):
    remainder = deepcopy(manifest)
    remainder.pop("content_hash")
    remainder["rows"] = [r for r in remainder["rows"] if r["name"] != "array.concat"]
    encoded = json.dumps(remainder, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert hashlib.sha256(encoded).hexdigest() == "46aa154700259398aaee753eb7441bd952b07030ae076480dc6dfb7e0356d854"
    check_manifest(Path(__file__).parents[1] / "pinelib/abi/target_manifest.json")
