"""Manual reference examples and read-only lifecycle controls for numeric search."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import pytest

from pinelib import CallbackFrame
from pinelib.abi import reference as ref
from pinelib.core.values import na
from pinelib.errors import PineRuntimeError
from tests.stage3_helpers import session

FIXTURE = Path(__file__).parent / "fixtures/array_search_manual_expected.json"
CASES = json.loads(FIXTURE.read_bytes())["cases"]
NAMES = ("leftmost", "rightmost")


def new_array(tx, values, object_id="search", dtype=None):
    dtype = dtype or ("array<float>" if any(type(v) is float for v in values) else "array<int>")
    return tx.references.create(object_id, "array", dtype, list(values))


def search(tx, name, handle, target):
    return getattr(ref, "array_binary_search_" + name + "_v1")(tx, handle, target)


def test_manual_expected_fixture_bytes_are_frozen():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == "1ef56faf74bbd89bb7c7c7011b1ac3c2b9ca4d0a089f7e248572ef7aa532f746"


@pytest.mark.parametrize("case", CASES, ids=lambda c:c["case_id"])
@pytest.mark.parametrize("name", NAMES)
def test_primary_manual_numeric_table(case, name):
    runtime = session(case["version"])
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    handle = new_array(tx, case["array"])
    before = deepcopy(tx.references.to_json())
    assert search(tx, name, handle, case["target"]) == case["expected_" + name]
    assert tx.references.to_json() == before
    tx.commit()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("name,expected", [("leftmost", 0), ("rightmost", 1)])
def test_alias_copy_slice_trial_abort_retry_checkpoint_search_is_read_only(version, compact, name, expected):
    runtime = session(version); runtime.commit_full_identity = not compact
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    handle = new_array(tx, [-9, 1, 5, 20])
    alias = handle
    copy = ref.array_copy_v1(tx, handle, "copy")
    view = ref.array_slice_v1(tx, handle, 1, 3, "slice")
    tx.commit()
    saved = runtime.checkpoint().to_dict()
    for attempt in range(2):
        tx = runtime.begin(CallbackFrame("REALTIME_TICK", 1, bar_index=1, realtime=True, final_tick=False))
        before_heap = tx.references.to_json()
        before_transcript = runtime.transcript.to_dict()
        assert search(tx, name, view, 3) == expected
        assert search(tx, name, alias, 3) == expected + 1
        assert search(tx, name, copy, 3) == expected + 1
        assert tx.references.to_json() == before_heap
        assert runtime.transcript.to_dict() == before_transcript
        tx.abort()
        assert runtime.sequence == 0
        clone = session(version); clone.commit_full_identity = not compact
        clone.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
        assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()
        runtime = clone
    tx = runtime.begin(CallbackFrame("REALTIME_TICK", 1, bar_index=1, realtime=True, final_tick=True))
    ref.array_set_v1(tx, handle, 2, 7)
    assert search(tx, name, view, 6) == expected
    assert search(tx, name, copy, 6) == (2 if name == "leftmost" else 3)
    tx.commit()
    clone = session(version); clone.commit_full_identity = not compact
    clone.restore(runtime.checkpoint().to_dict())
    assert clone.references.read_payload(handle) == [-9, 1, 7, 20]
    assert clone.references.read_payload(copy) == [-9, 1, 5, 20]
    assert saved["state"]["sequence"] == 0


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("name", NAMES)
def test_native_legacy_search_results_remain_unchanged(version, name):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    handle = new_array(tx, [1, 5, 5])
    assert search(tx, name, handle, 3) == -1
    assert search(tx, name, handle, 5) == (1 if name == "leftmost" else 2)
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", NAMES)
def test_empty_and_unverified_descriptor_queries_keep_previous_behavior(version, name):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    empty = new_array(tx, [])
    strings = new_array(tx, ["a", "c"], "strings", "array<string>")
    booleans = new_array(tx, [False, True], "booleans", "array<bool>")
    assert search(tx, name, empty, 3) == -1
    assert search(tx, name, strings, "b") == -1
    assert search(tx, name, strings, "c") == 1
    assert search(tx, name, booleans, True) == 1
    numeric = new_array(tx, [2, 4], "numeric")
    for query in (True, False, float("inf"), float("-inf"), float("nan")):
        assert search(tx, name, numeric, query) == -1
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("bad", [na, None, "x"])
def test_existing_comparison_errors_are_read_only(version, name, bad):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    handle = new_array(tx, [1, 3])
    before = tx.references.to_json()
    with pytest.raises(PineRuntimeError, match="not searchable"):
        search(tx, name, handle, bad)
    assert tx.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
def test_plain_binary_search_absence_and_duplicate_behavior_are_unchanged(version):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    handle = new_array(tx, [1, 5, 5])
    assert ref.array_binary_search_v1(tx, handle, 3) == -1
    assert ref.array_binary_search_v1(tx, handle, 5) == 1
    tx.abort()


@pytest.mark.parametrize("name", NAMES)
def test_large_numeric_search_keeps_logarithmic_element_access(monkeypatch, name):
    runtime = session(6)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    count = 65_536
    handle = new_array(tx, range(0, 2 * count, 2))
    original = tx.references.read_payload
    accesses = []

    class CountedList(list):
        def __getitem__(self, key):
            accesses.append(key)
            return super().__getitem__(key)

        def __iter__(self):
            for i in range(len(self)):
                yield self[i]

    # Instrument the public detached-payload boundary; no private search hook.
    monkeypatch.setattr(tx.references, "read_payload", lambda h:CountedList(original(h)))
    assert search(tx, name, handle, 65535) == (32767 if name == "leftmost" else 32768)
    assert len(accesses) <= math.ceil(math.log2(count)) + 2
    tx.abort()
