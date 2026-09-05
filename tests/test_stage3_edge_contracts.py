from __future__ import annotations

import copy
import json
import math
import sys
from enum import Enum

import pytest

from pinelib.abi import alert as alert_abi
from pinelib.abi import builder, manifest, metadata
from pinelib.abi.__main__ import main as abi_main
from pinelib.abi.models import CatalogRow, TargetStatus
from pinelib.builtins import math as pine_math
from pinelib.builtins import string as pine_string
from pinelib.core import is_na, na, pine_bool, pine_div
from pinelib.errors import PineRuntimeError
from pinelib.events import AlertTape, SourceSpan, VisualTape
from pinelib.input import InputRegistry, InputSpec
from pinelib.reference import PineEnumValue, ReferenceHandle, RuntimeReferenceHeap
from pinelib.reference import array as arrays
from pinelib.reference import map as maps
from pinelib.reference import matrix as matrices
from pinelib.reference import udt as udts
from pinelib.runtime import (
    CallbackFrame,
    InstrumentContext,
    ResourcePolicy,
    RuntimePolicies,
    RuntimeSession,
    RuntimeTransaction,
    TimeframeContext,
)
from pinelib.state import RuntimeCheckpoint, SeriesStorage, StateSlotRegistry
from pinelib.state.checkpoint import (
    canonical_json,
    clone_runtime_value,
    from_portable,
    sha,
    to_portable,
)
from pinelib.time import from_unix_ms, get_timezone, parse_session, timestamp_ms
from tests.stage3_helpers import language, session, span


class ExampleEnum(Enum):
    A = "a"


class PortableValue:
    def __pinelib_portable__(self):
        return {"ok": [1, na]}


class NonObjectPayload(dict):
    def __pinelib_portable__(self):
        return [1]


class FakeResource:
    def __init__(self, text: str):
        self.text = text

    def joinpath(self, _name: str):
        return self

    def read_text(self, *, encoding: str) -> str:
        assert encoding == "utf-8"
        return self.text


def expect_error(function, *args, **kwargs):
    with pytest.raises(PineRuntimeError):
        function(*args, **kwargs)


def test_value_and_canonical_json_edge_matrix():
    import copy as copy_module

    assert repr(na) == "na"
    assert copy_module.copy(na) is na
    assert copy_module.deepcopy(na) is na
    assert to_portable(na) == {"$pine": "na"}
    assert from_portable({"$pine": "na"}) is na
    assert to_portable(ExampleEnum.A) == "a"
    assert to_portable(PortableValue()) == {"ok": [1, {"$pine": "na"}]}
    assert clone_runtime_value((1, na)) == [1, na]
    expect_error(to_portable, float("inf"))
    expect_error(to_portable, {1: "x"})
    expect_error(to_portable, object())
    assert canonical_json({"β": 1, "a": 2}) == b'{"a":2,"\xce\xb2":1}'
    assert pine_bool("x", language()) is True
    assert pine_bool(False, language()) is False
    expect_error(pine_div, True, 1, language())
    expect_error(pine_div, 1, 0, language())
    assert is_na(pine_div(na, 1, language()))


def test_math_and_string_all_negative_and_formatting_branches(monkeypatch):
    assert is_na(pine_math.abs_value(na))
    assert is_na(pine_math.sign(na))
    assert is_na(pine_math.avg(1, na))
    assert is_na(pine_math.minimum(1, na))
    assert is_na(pine_math.power(na, 2))
    assert is_na(pine_math.round_value(na))
    assert is_na(pine_math.round_to_mintick(na, 0.1))
    assert is_na(pine_math.sum_pair(1, na))
    expect_error(pine_math.maximum)
    expect_error(pine_math.minimum)
    expect_error(pine_math.round_value, 1.0, 1.5)
    expect_error(pine_math.round_to_mintick, 1.0, 0)

    def nonfinite(_value: float) -> float:
        return math.inf

    expect_error(pine_math._unary, 1.0, nonfinite)
    assert pine_math.sign(0) == 0
    assert pine_math.sign(-1) == -1

    expect_error(pine_string.substring, "abc", "0")
    expect_error(pine_string.replace, "abc", "a", "x", -1)
    assert pine_string.replace("abc", "", "x") == "abc"
    assert pine_string.replace("abc", "z", "x") == "abc"
    assert pine_string.replace_all("abc", "", "x") == "abc"
    assert pine_string.split("abc", "") == ("a", "b", "c")
    assert is_na(pine_string.tonumber(""))
    assert is_na(pine_string.tonumber("nan"))
    assert pine_string.tostring(na) == "NaN"
    assert pine_string.tostring(True) == "true"
    assert pine_string.tostring(3) == "3"
    assert pine_string.tostring(3, "0.0") == "3.0"
    assert pine_string.tostring(1.5) == "1.5"
    assert pine_string.tostring("x") == "x"
    expect_error(pine_string.tostring, object())
    assert pine_string.format_template("{0}", 2) == "2"
    assert pine_string.format_template("{0,date,yyyy-MM-dd}", 0) == "1970-01-01"
    expect_error(pine_string.format_template, "{0,date,yyyy}", "bad")
    expect_error(pine_string.format_template, "{")
    expect_error(pine_string.format_time, 1.0, "yyyy", "UTC")
    expect_error(pine_string.tostring, 1.0, "mintick")
    expect_error(pine_string.tostring, 1.0, "mintick", mintick=0)
    assert pine_string.tostring(12.5, "0.00E0") == "1.25E+01"
    assert pine_string.tostring(12.5, "0E0") == "1E+01"
    assert pine_string.tostring(1.2, "0.##") == "1.2"
    assert pine_string.tostring(1.0, "0.00##") == "1.00"
    assert pine_string.tostring(0.12, "0%") == "12%"
    expect_error(pine_string.contains, 1, "x")


def _row(
    path: str | None,
    *,
    status: TargetStatus = TargetStatus.SUPPORTED_PURE,
    diagnostic: str | None = None,
):
    return CatalogRow(
        "pine:function:test",
        "pine:function:test#v1",
        "namespace_function",
        (6,),
        status,
        path,
        "object",
        "EAGER_ARGUMENTS",
        "PURE",
        (),
        diagnostic,
        0,
    )


def test_manifest_builder_cli_and_mutation_fail_closed(monkeypatch, tmp_path):
    output = tmp_path / "manifest.json"
    monkeypatch.setattr(sys, "argv", ["pinelib.abi", "build", "--output", str(output)])
    assert abi_main() == 0
    assert output.is_file()
    monkeypatch.setattr(
        sys, "argv", ["pinelib.abi", "build", "--check", "--output", str(output)]
    )
    assert abi_main() == 0

    missing = tmp_path / "missing.json"
    expect_error(builder.check_manifest, missing)
    output.write_text("{}\n", encoding="utf-8")
    expect_error(builder.check_manifest, output)
    expect_error(builder._resolve, "pinelib.abi.math.does_not_exist")
    expect_error(builder._resolve, "pinelib.abi.math.__doc__")

    monkeypatch.setattr(builder, "CATALOG", (_row("pinelib.abi.math.abs_v1"),) * 2)
    expect_error(builder.build_manifest)
    monkeypatch.setattr(builder, "CATALOG", (_row(None),))
    expect_error(builder.build_manifest)
    monkeypatch.setattr(
        builder,
        "CATALOG",
        (
            _row(
                "pinelib.abi.math.abs_v1",
                status=TargetStatus.UNSUPPORTED_FAIL_CLOSED,
                diagnostic="x",
            ),
        ),
    )
    expect_error(builder.build_manifest)
    monkeypatch.setattr(
        builder,
        "CATALOG",
        (_row(None, status=TargetStatus.UNSUPPORTED_FAIL_CLOSED, diagnostic=None),),
    )
    expect_error(builder.build_manifest)

    def invoke(value):
        return value

    monkeypatch.setattr(builder, "CATALOG", (_row("ignored"),))
    monkeypatch.setattr(builder, "_resolve", lambda _path: invoke)
    expect_error(builder.build_manifest)


def test_manifest_loader_rejects_shape_hash_and_unknown(monkeypatch):
    cache_clear = getattr(manifest.load_target_manifest, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
    monkeypatch.setattr(manifest, "files", lambda _package: FakeResource("[]"))
    expect_error(manifest.load_target_manifest)

    bad_hash = {"classification": {"unknown": 0}, "content_hash": "bad"}
    monkeypatch.setattr(
        manifest, "files", lambda _package: FakeResource(json.dumps(bad_hash))
    )
    expect_error(manifest.load_target_manifest)

    body = {"classification": {"unknown": 1}, "rows": []}
    unknown = {**body, "content_hash": sha(body)}
    monkeypatch.setattr(
        manifest, "files", lambda _package: FakeResource(json.dumps(unknown))
    )
    expect_error(manifest.load_target_manifest)


def test_load_target_manifest_rebuilds_canonical_builder_once(monkeypatch) -> None:
    calls = {"n": 0}
    real = builder.build_manifest

    def counted() -> object:
        calls["n"] += 1
        return real()

    monkeypatch.setattr(builder, "build_manifest", counted)
    cache_clear = getattr(manifest.load_target_manifest, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
    first = manifest.load_target_manifest()
    second = manifest.load_target_manifest()
    assert first == second
    assert first["classification"]["unknown"] == 0
    assert calls["n"] == 1


def test_inputs_metadata_time_and_session_negative_corpus():
    invalid_specs = [
        ("", "int", 1, 1, {}),
        ("x", "int", 1, 1, {"minimum": 2, "maximum": 1}),
        ("x", "int", 1, 1, {"step": 0}),
        ("x", "string", "a", "b", {"options": ("a",)}),
        ("x", "float", 1.0, float("inf"), {}),
        ("x", "int", 1, 0, {"minimum": 1}),
        ("x", "int", 1, 4, {"minimum": 0, "step": 3}),
        ("x", "bool", True, 1, {}),
    ]
    for input_id, kind, default, value, kwargs in invalid_specs:
        expect_error(InputSpec, input_id, kind, default, value, **kwargs)
    registry = InputRegistry([InputSpec("x", "int", 1, 1)])
    expect_error(registry.get, "missing")
    expect_error(registry.get, "x", "float")

    bare = RuntimeSession(language())
    expect_error(metadata.syminfo_ticker_v1, bare)
    expect_error(metadata.timeframe_period_v1, bare)
    expect_error(InstrumentContext, "", "id", "p", "c", "b", "UTC", "x", 1, 1, 1)
    expect_error(InstrumentContext, "t", "id", "p", "c", "b", "UTC", "x", 0, 1, 1)
    expect_error(InstrumentContext, "t", "id", "p", "c", "b", "No/Such", "x", 1, 1, 1)
    assert TimeframeContext.parse("1S").seconds == 1
    assert TimeframeContext.parse("120").seconds == 7200
    assert TimeframeContext.parse("D").seconds == 86_400
    assert TimeframeContext.parse("1T").unit == "tick"
    expect_error(TimeframeContext.parse, "2H")
    assert TimeframeContext.parse("3W").seconds == 1_814_400
    expect_error(TimeframeContext.parse, "bad")

    expect_error(get_timezone, "")
    expect_error(from_unix_ms, 1.2, "UTC")
    expect_error(timestamp_ms, "UTC", 2024, 13, 1)
    assert parse_session("24x7", language()).contains(0, "UTC")
    expect_error(parse_session, "", language())
    expect_error(parse_session, "0900-1700:8", language())
    expect_error(parse_session, "2400-1700", language())
    daytime = parse_session("0900-1700:2", language())
    monday_1200 = timestamp_ms("UTC", 2024, 1, 1, 12)
    monday_1800 = timestamp_ms("UTC", 2024, 1, 1, 18)
    assert daytime.contains(monday_1200, "UTC")
    assert not daytime.contains(monday_1800, "UTC")
    overnight = parse_session("2200-0200:2", language())
    assert overnight.contains(timestamp_ms("UTC", 2024, 1, 1, 23), "UTC")
    assert overnight.contains(timestamp_ms("UTC", 2024, 1, 2, 1), "UTC")
    assert not overnight.contains(timestamp_ms("UTC", 2024, 1, 2, 3), "UTC")


def _limited_session(**limits: int) -> RuntimeSession:
    defaults = ResourcePolicy()
    values = {
        field: getattr(defaults, field) for field in defaults.__dataclass_fields__
    }
    values.update(limits)
    return RuntimeSession(
        language(), RuntimePolicies(resource=ResourcePolicy(**values))
    )


def test_runtime_transaction_limits_sequences_and_atomic_guards():
    for args in (
        ("", 0),
        ("x", -1),
        ("x", 0, False, True, None, -1),
        ("x", 0, False, True, None, 0, -1),
    ):
        expect_error(CallbackFrame, *args)

    runtime = _limited_session(max_series=1, max_state_slots=1)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    expect_error(runtime.begin, CallbackFrame("HISTORICAL_EVAL", 1))
    tx.set_series("x", 1, "int")
    expect_error(tx.set_series, "y", 2, "int")
    expect_error(tx.set_series, "x", 2.0, "float")
    expect_error(tx.read_series, "missing")
    tx.set_slot("slot", 1)
    expect_error(tx.set_slot, "slot2", 2)
    expect_error(runtime.checkpoint)
    expect_error(runtime.restore, {})
    expect_error(runtime.finalize)
    tx.commit()
    expect_error(tx.read_series, "x")
    expect_error(runtime.begin, CallbackFrame("HISTORICAL_EVAL", 0))

    inactive = RuntimeTransaction(runtime, CallbackFrame("HISTORICAL_EVAL", 2))
    expect_error(inactive.read_series, "x")
    expect_error(runtime._finish, inactive, True)

    tiny = _limited_session(max_checkpoint_bytes=1)
    expect_error(tiny.checkpoint)

    storage = SeriesStorage("x", "int")
    expect_error(storage.set, 1)
    storage.begin(1)
    assert storage.read() == 1
    expect_error(storage.read, -1)
    expect_error(
        SeriesStorage.from_json,
        {
            "name": "x",
            "dtype": "int",
            "committed": {},
            "working": 1,
            "initialized": True,
            "revision": 0,
        },
    )

    slots = StateSlotRegistry(1)
    expect_error(slots.register, "", "o", "1")
    slots.register("a", "o", "1")
    expect_error(slots.register, "a", "other", "1")
    expect_error(slots.register, "b", "o", "1")
    transient = StateSlotRegistry()
    transient.register("x", "o", "1")
    transient.begin()
    assert transient.to_json() == []


def _sealed(identity: str, state: dict[str, object]) -> dict[str, object]:
    return RuntimeCheckpoint.seal(identity, state).to_dict()


def test_checkpoint_schema_mutations_and_atomic_restore():
    expect_error(RuntimeCheckpoint.seal, "id", [1])
    identity = sha({"checkpoint": "identity"})
    valid = RuntimeCheckpoint.seal(identity, {"x": 1}).to_dict()
    mutations = []
    missing = dict(valid)
    missing.pop("schema_version")
    mutations.append(missing)
    for key, value in (
        ("schema_id", "wrong"),
        ("schema_version", "2"),
        ("identity_hash", sha({"checkpoint": "other"})),
        ("content_hash", "bad"),
    ):
        row = copy.deepcopy(valid)
        row[key] = value
        mutations.append(row)
    for row in mutations:
        expect_error(RuntimeCheckpoint.parse, row, identity)
    state_not_object = copy.deepcopy(valid)
    state_not_object["state"] = []
    state_not_object["content_hash"] = sha(
        {
            key: state_not_object[key]
            for key in ("schema_id", "schema_version", "identity_hash", "state")
        }
    )
    expect_error(RuntimeCheckpoint.parse, state_not_object, identity)

    runtime = session()
    original = runtime.state_hash
    base = runtime._state_json()
    for mutation in (
        {**base, "series": []},
        {**base, "slots": {}},
        {**base, "references": []},
        {**base, "visuals": []},
        {**base, "series": {"x": []}},
    ):
        expect_error(runtime.restore, _sealed(runtime.identity_hash, mutation))
        assert runtime.state_hash == original


def test_reference_heap_array_map_matrix_udt_mutation_and_limits():
    expect_error(ReferenceHandle, "", "array")
    expect_error(ReferenceHandle, "0:compat", "array")
    expect_error(PineEnumValue, "", "x", 0)
    expect_error(PineEnumValue, "E", "x", -1)

    heap = RuntimeReferenceHeap(language(), max_objects=1, max_elements=2)
    handle = arrays.array_new(heap, "a", "array<int>", 1, 1)
    expect_error(arrays.array_new, heap, "a", "array<int>")
    expect_error(arrays.array_new, heap, "b", "array<int>")
    expect_error(heap.mutate_payload, handle, [1, 2, 3])
    expect_error(heap.normalize_index, "0", 1)
    expect_error(heap.normalize_index, 2, 1)
    expect_error(heap._get, ReferenceHandle("a", "map"))
    expect_error(heap._get, ReferenceHandle("unknown", "array"))
    expect_error(arrays.array_new, RuntimeReferenceHeap(language()), "x", "array", -1)
    empty_heap = RuntimeReferenceHeap(language())
    empty = arrays.array_new(empty_heap, "empty", "array")
    expect_error(arrays.array_pop, empty_heap, empty)
    expect_error(arrays.array_shift, empty_heap, empty)
    expect_error(arrays.array_slice, empty_heap, empty, "0", 1, "slice")
    expect_error(arrays.array_slice, empty_heap, empty, 1, 0, "slice")
    arrays.array_insert(empty_heap, empty, 0, 1)
    assert arrays.array_values(empty_heap, empty) == (1,)
    arrays.array_push(empty_heap, empty, "x")
    expect_error(arrays.array_sort, empty_heap, empty)
    expect_error(arrays.array_binary_search, empty_heap, empty, object())
    assert arrays.array_indexof(empty_heap, empty, 99) == -1
    assert arrays.array_lastindexof(empty_heap, empty, 99) == -1

    wrong = ReferenceHandle("empty", "map")
    expect_error(arrays.array_size, empty_heap, wrong)
    empty_heap._objects["empty"].working = {"bad": True}
    expect_error(arrays.array_size, empty_heap, empty)

    map_heap = RuntimeReferenceHeap(language())
    mapping = maps.map_new(map_heap, "m", "map")
    assert is_na(maps.map_get(map_heap, mapping, "missing"))
    assert is_na(maps.map_remove(map_heap, mapping, "missing"))
    maps.map_clear(map_heap, mapping)
    expect_error(maps.map_get, map_heap, ReferenceHandle("m", "array"), "x")
    map_heap._objects["m"].working = [1]
    expect_error(maps.map_get, map_heap, mapping, "x")

    matrix_heap = RuntimeReferenceHeap(language())
    expect_error(matrices.matrix_new, matrix_heap, "bad", "matrix", -1, 1, 0)
    matrix = matrices.matrix_new(matrix_heap, "mx", "matrix", 1, 1, 0)
    expect_error(matrices.matrix_rows, matrix_heap, ReferenceHandle("mx", "array"))
    matrix_heap._objects["mx"].working = []
    expect_error(matrices.matrix_rows, matrix_heap, matrix)

    udt_heap = RuntimeReferenceHeap(language())
    expect_error(udts.udt_new, udt_heap, "u0", "Point", {"": 1})
    point = udts.udt_new(udt_heap, "u", "Point", {"x": 1})
    expect_error(udts.udt_get, udt_heap, point, "y")
    expect_error(udts.udt_set, udt_heap, point, "y", 2)
    expect_error(udts.udt_get, udt_heap, ReferenceHandle("u", "array"), "x")
    udt_heap._objects["u"].working = []
    expect_error(udts.udt_get, udt_heap, point, "x")

    expect_error(
        RuntimeReferenceHeap.from_json,
        {"objects": {}},
        language(),
        max_objects=2,
        max_elements=2,
    )
    expect_error(
        RuntimeReferenceHeap.from_json,
        {"objects": [1]},
        language(),
        max_objects=2,
        max_elements=2,
    )


def test_event_tapes_source_identity_limits_and_malformed_restore():
    expect_error(SourceSpan, "bad", "f", 1, 0, 1, 1)
    expect_error(SourceSpan, "sha256:" + "1" * 64, "", 1, 0, 1, 1)
    expect_error(SourceSpan, "sha256:" + "1" * 64, "f", 2, 0, 1, 0)
    from pinelib.events.common import delivery_id, event_id

    expect_error(event_id, "", "c", {}, span())
    expect_error(delivery_id, "sha256:x", sequence=-1, phase="x", ordinal=0)

    for tape_cls, label in ((VisualTape, "visual"), (AlertTape, "alert")):
        tape = tape_cls(0)
        expect_error(
            tape.record,
            kind=label,
            call_site_id="c",
            sequence=0,
            phase="HISTORICAL_EVAL",
            payload={},
            source_span=span(),
        )
        tape = tape_cls()
        expect_error(
            tape.record,
            kind=label,
            call_site_id="c",
            sequence=0,
            phase="HISTORICAL_EVAL",
            payload=NonObjectPayload(),
            source_span=span(),
        )
        expect_error(tape_cls.from_json, {"committed": [1]}, 10)
        expect_error(
            tape_cls.from_json,
            {
                "committed": [
                    {
                        "kind": label,
                        "event_id": "e",
                        "delivery_id": "d",
                        "call_site_id": "c",
                        "sequence": 0,
                        "phase": "p",
                        "ordinal": 0,
                        "payload": {},
                        "source_span": [],
                    }
                ]
            },
            10,
        )
        expect_error(
            tape_cls.from_json,
            {
                "committed": [
                    {
                        "kind": label,
                        "event_id": "e",
                        "delivery_id": "d",
                        "call_site_id": "c",
                        "sequence": 0,
                        "phase": "p",
                        "ordinal": 0,
                        "payload": [],
                        "source_span": span().identity(),
                    }
                ]
            },
            10,
        )

    runtime = session()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    assert alert_abi.alertcondition_v1(tx, "c", span(), False, "t", "m") is None
    tx.abort()


def test_pinned_tzdata_policy_is_fail_closed(monkeypatch):
    from importlib.metadata import version

    from pinelib.time import calendar

    assert calendar.PINNED_TZDATA_VERSION == version("tzdata")
    calendar.get_timezone.cache_clear()
    monkeypatch.setattr(calendar, "version", lambda _name: "0.0.invalid")
    expect_error(calendar.get_timezone, "UTC")
    calendar.get_timezone.cache_clear()
    monkeypatch.setattr(calendar, "version", version)
    expect_error(calendar.get_timezone, "../UTC")
    assert calendar.get_timezone("UTC").key == "UTC"
