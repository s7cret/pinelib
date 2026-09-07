"""Independent negative checkpoint proof; hashes are intentionally recomputed.

Enum membership is finite and UDT schemas are declared by the source:
https://www.tradingview.com/pine-script-docs/language/enums/
https://www.tradingview.com/pine-script-docs/language/objects/
"""

from copy import deepcopy
import json

import pytest

from pinelib import RuntimeSession, is_na, na
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_new, array_set, array_get, array_slice
from pinelib.reference.heap import PineEnumValue, RuntimeReferenceHeap
from pinelib.reference.map import map_new, map_put
from pinelib.reference.matrix import matrix_new, matrix_set
from pinelib.reference.registry import NominalTypeRegistry
from pinelib.state.checkpoint import RuntimeCheckpoint, sha
from tests.test_language_scopes_once import begin, session as plain_session


SOURCE = "sha256:" + "a" * 64
E = "enum:" + SOURCE + ":Side:enum-node"
F = "enum:" + SOURCE + ":OtherSide:other-enum-node"
BOX = "udt:" + SOURCE + ":Box:box-node"
NODE = "udt:" + SOURCE + ":Node:recursive-node"


def registry(version=6, *, changed_title=False):
    declarations = [
        {"id": identity, "kind": "enum", "members": [
            {"name": "buy", "title": "Changed" if changed_title else "Bullish"},
            {"name": "sell", "title": "Bearish"},
        ]} for identity in (E, F)
    ] + [
        {"id": BOX, "kind": "udt", "fields": [
            {"name": "n", "type": "int", "varip": False},
            {"name": "side", "type": E, "varip": False},
        ]},
        {"id": NODE, "kind": "udt", "fields": [
            {"name": "n", "type": "int", "varip": False},
            {"name": "next", "type": NODE, "varip": False},
        ]},
    ]
    return NominalTypeRegistry.from_json({
        "schema_id": "pinelib.nominal_registry.v1", "pine_version": version,
        "source_hash": SOURCE, "types": sorted(declarations, key=lambda row: row["id"]),
    }, pine_version=version, expected_source_hash=SOURCE)


def session(version=6, *, changed_title=False):
    return RuntimeSession(plain_session(version).language, nominal_registry=registry(version, changed_title=changed_title))


def box(tx, identity="box", n=1):
    return tx.new_udt_v1(identity, BOX, {"n": n, "side": tx.enum_value_v1(E, "buy", 0)},
                         field_types={"n": "int", "side": E})


def checkpoint_fixture(version=6):
    runtime = session(version)
    tx = begin(runtime, 0)
    value = tx.enum_value_v1(E, "buy", 0)
    tx.declare_enum_v1("side", "var", lambda: value, E)
    tx.set_slot("nested", {"values": [value]}, owner="test")
    handle = box(tx)
    tx.declare_reference_v1("box", "var", lambda: handle, BOX)
    array_new(tx.references, "array", E, 1, value)
    matrix_new(tx.references, "matrix", E, 1, 1, value)
    mapping = map_new(tx.references, "map", E + "," + E)
    map_put(tx.references, mapping, value, value)
    tx.commit()
    return runtime


def reseal(saved):
    state = saved["state"]
    state["transcript"]["entries"][-1]["state_hash"] = sha({k: v for k, v in state.items() if k != "transcript"})
    state["transcript"]["content_hash"] = sha({"entries": state["transcript"]["entries"]})
    return RuntimeCheckpoint.seal(saved["identity_hash"], state).to_dict()


def marker_at(state, location):
    if location == "series_history":
        return state["series"]["side"]["committed"][0]["$pinelib_enum"]
    if location == "series_working":
        return state["series"]["side"]["working"]["$pinelib_enum"]
    if location.startswith("slot"):
        row = next(row for row in state["slots"] if row["state_id"] == ("nested" if location == "slot_nested" else "enum-binding:side"))
        value = row["working"]
        return (value["values"][0] if location == "slot_nested" else value)["$pinelib_enum"]
    kind, phase = location.split("_")
    row = next(row for row in state["references"]["objects"] if row["object_id"] == ("map" if kind.startswith("map") else kind))
    value = row[phase]
    if kind == "box":
        return value["side"]["$pinelib_enum"]
    if kind == "array":
        return value[0]["$pinelib_enum"]
    if kind == "matrix":
        return value["values"][0]["$pinelib_enum"]
    return value[0][0 if kind == "mapkey" else 1]["$pinelib_enum"]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("location", [
    "series_history", "series_working", "slot_binding", "slot_nested",
    "box_committed", "box_working", "array_committed", "array_working",
    "matrix_committed", "matrix_working", "mapkey_committed", "mapvalue_working",
])
@pytest.mark.parametrize("change", [
    {"member": "not_declared"}, {"ordinal": 123}, {"member": "sell", "ordinal": 0},
])
def test_fully_rehashed_forged_members_reject_before_session_replacement(version, location, change):
    runtime = checkpoint_fixture(version)
    original = runtime.checkpoint().to_dict()
    bad = deepcopy(original)
    marker_at(bad["state"], location).update(change)
    with pytest.raises(PineRuntimeError):
        runtime.restore(reseal(bad))
    assert runtime.checkpoint().to_dict() == original


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("fault", ["field_type", "varip", "extra_field", "unknown_type"])
def test_rehashed_udt_schema_is_compared_with_admitted_declaration(version, fault):
    runtime = checkpoint_fixture(version)
    original = runtime.checkpoint().to_dict()
    bad = deepcopy(original)
    row = next(row for row in bad["state"]["references"]["objects"] if row["object_id"] == "box")
    if fault == "field_type":
        row["udt_schema"]["fields"]["n"] = "string"
        row["committed"]["n"] = row["working"]["n"] = "forged"
    elif fault == "varip":
        row["udt_schema"]["varip_fields"] = ["n"]
    elif fault == "extra_field":
        row["udt_schema"]["fields"]["extra"] = "int"
        row["committed"]["extra"] = row["working"]["extra"] = 0
    else:
        row["type_descriptor"] += ":unknown"
    with pytest.raises(PineRuntimeError):
        runtime.restore(reseal(bad))
    assert runtime.checkpoint().to_dict() == original


@pytest.mark.parametrize("kind", ["array", "matrix", "map_key", "map_value"])
def test_other_declared_enum_cannot_enter_a_typed_container(kind):
    tx = begin(session(), 0)
    value = tx.enum_value_v1(E, "buy", 0)
    foreign = tx.enum_value_v1(F, "buy", 0)
    if kind == "array":
        handle = array_new(tx.references, "array", E, 1, value)
        mutate = lambda: array_set(tx.references, handle, 0, foreign)
    elif kind == "matrix":
        handle = matrix_new(tx.references, "matrix", E, 1, 1, value)
        mutate = lambda: matrix_set(tx.references, handle, 0, 0, foreign)
    else:
        handle = map_new(tx.references, "map", E + "," + E)
        map_put(tx.references, handle, value, value)
        mutate = lambda: map_put(tx.references, handle, foreign if kind == "map_key" else value, value if kind == "map_key" else foreign)
    before = tx.references.to_json()
    with pytest.raises(PineRuntimeError, match="enum"):
        mutate()
    assert tx.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("dtype", [E, BOX, f"array<{E}>", f"map<string,{BOX}>"])
def test_unknown_nominal_types_are_rejected_even_without_values(dtype):
    tx = begin(plain_session(), 0)
    before = tx.references.to_json()
    with pytest.raises(PineRuntimeError):
        tx.set_series("missing", na, dtype)
    assert "missing" not in tx.session.series
    assert tx.references.to_json() == before
    tx.abort()


def test_registry_required_before_initializer_or_self_reported_schema_can_run():
    tx = begin(plain_session(), 0)
    calls = []
    with pytest.raises(PineRuntimeError):
        tx.declare_enum_v1("side", "var", lambda: calls.append("enum"), E)
    with pytest.raises(PineRuntimeError):
        tx.declare_reference_v1("box", "var", lambda: calls.append("udt"), BOX)
    with pytest.raises(PineRuntimeError):
        box(tx)
    assert calls == []
    assert tx.references.to_json() == {"objects": []}
    tx.abort()


@pytest.mark.parametrize("value", [PineEnumValue(E, "unknown", 0), PineEnumValue(E, "buy", 999),
                                  {"$pinelib_enum": {"enum_id": E, "member": "sell", "ordinal": 0}}])
def test_raw_enum_values_cannot_bypass_slot_or_series_admission(value):
    tx = begin(session(), 0)
    before = tx.session._state_json()
    for action in (
        lambda: tx.set_slot("forged", value),
        lambda: tx.state("forged", owner="test", schema_version="1", initial=value),
        lambda: tx.set_series("forged", value, E),
        lambda: array_new(tx.references, "forged", E, 1, value),
    ):
        with pytest.raises(PineRuntimeError):
            action()
        assert tx.session._state_json() == before
    tx.abort()


def test_registry_hash_binds_identity_and_is_preserved_by_restore():
    runtime = checkpoint_fixture()
    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    clone = session()
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    assert clone.references.nominal_registry is clone.nominal_registry
    with pytest.raises(AttributeError):
        clone.nominal_registry = registry(changed_title=True)
    for incompatible in (plain_session(), session(changed_title=True)):
        before = incompatible.checkpoint().to_dict()
        assert incompatible.identity_hash != runtime.identity_hash
        with pytest.raises(PineRuntimeError, match="identity"):
            incompatible.restore(saved)
        assert incompatible.checkpoint().to_dict() == before
    assert plain_session().identity_hash == plain_session().identity_hash


def test_registry_version_and_mutable_substitutes_are_rejected():
    for candidate in (registry(5), registry().to_json(), object()):
        with pytest.raises(PineRuntimeError):
            RuntimeSession(plain_session(6).language, nominal_registry=candidate)
        with pytest.raises(PineRuntimeError):
            RuntimeReferenceHeap(plain_session(6).language, nominal_registry=candidate)


@pytest.mark.parametrize("version", [5, 6])
def test_cyclic_reference_graph_and_nominal_slice_restore_keep_identity(version):
    runtime = session(version)
    tx = begin(runtime, 0)
    schema = {"n": "int", "next": NODE}
    first = tx.new_udt_v1("first", NODE, {"n": 1, "next": na}, field_types=schema)
    second = tx.new_udt_v1("second", NODE, {"n": 2, "next": first}, field_types=schema)
    tx.set_udt_field_v1(first, "next", second)
    array = array_new(tx.references, "array", NODE, 2, first)
    sliced = array_slice(tx.references, array, 0, 1, "slice")
    tx.commit()
    restored = session(version)
    restored.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    tx = begin(restored, 1)
    assert tx.get_udt_field_v1(tx.get_udt_field_v1(first, "next"), "next") == first
    assert array_get(tx.references, sliced, 0) == first
    assert tx.get_udt_field_v1(first, "n") == 1
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
def test_missing_enum_and_strict_none_bool_zero_paths(version):
    tx = begin(session(version), 0)
    assert is_na(tx.enum_coerce_v1(na, E))
    for value in (None, False, 0, float("nan")):
        with pytest.raises(PineRuntimeError):
            tx.enum_coerce_v1(value, E)
    handle = box(tx)
    before = tx.references.to_json()
    for value in (None, False, float("nan")):
        with pytest.raises(PineRuntimeError):
            tx.set_udt_field_v1(handle, "n", value)
        assert tx.references.to_json() == before
    tx.set_udt_field_v1(handle, "n", 0)
    assert tx.get_udt_field_v1(handle, "n") == 0
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
def test_request_child_receives_registry_before_compact_checkpoint_restore(version):
    from types import SimpleNamespace
    from pinelib.abi.compiled_request import CompiledRequestExpression
    from pinelib.request import CanonicalBar, DataFinality, ResultShape
    from tests.test_compiled_requests import INSTRUMENT

    admitted = registry(version)
    parent = RuntimeSession(plain_session(version).language, nominal_registry=admitted)
    tx = begin(parent, 0)
    saved = {}

    class Child:
        def __init__(self, runtime):
            self.runtime = runtime

        def count(self):
            assert self.runtime.session.nominal_registry is admitted
            handle = self.runtime.declare_reference_v1("box", "var", lambda: box(self.runtime, n=0), BOX)
            current = self.runtime.get_udt_field_v1(handle, "n") + 1
            self.runtime.set_udt_field_v1(handle, "n", current)
            self.runtime.declare_enum_v1("side", "var", lambda: self.runtime.enum_value_v1(E, "buy", 0), E)
            return current

    def context():
        return SimpleNamespace(
            last_bar_index=1, is_last_bar=True,
            state=lambda key, default: saved.get(key, default),
            set_state=lambda key, value: saved.__setitem__(key, json.loads(json.dumps(value))),
        )

    def evaluate(index):
        expression = CompiledRequestExpression(tx, Child, "count", "sha256:" + "c" * 64, ResultShape.scalar("float"))
        expression.source = SimpleNamespace(instrument=INSTRUMENT, timeframe="5")
        bar = CanonicalBar("stock:S", "5", index * 300000, (index + 1) * 300000,
                           "1", "2", "0", "1", "1", DataFinality.FINAL, 0)
        return expression(bar, context())

    assert evaluate(0) == 1
    first = deepcopy(saved["compiled-runtime"])
    assert evaluate(1) == 2
    assert saved["compiled-runtime"]["identity_hash"] == first["identity_hash"]
    assert saved["compiled-runtime"]["state"]["sequence"] == 1
    assert saved["compiled-runtime"]["state"]["references"]["objects"][0]["working"]["n"] == 2
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["array", "matrix", "map"])
def test_erased_collection_type_cannot_hide_a_valid_declared_udt_handle(version, kind):
    runtime = session(version)
    tx = begin(runtime, 0)
    handle = box(tx)
    if kind == "array":
        array_new(tx.references, "container", BOX, 1, handle)
    elif kind == "matrix":
        matrix_new(tx.references, "container", BOX, 1, 1, handle)
    else:
        mapping = map_new(tx.references, "container", "string," + BOX)
        map_put(tx.references, mapping, "box", handle)
    tx.commit()
    original = runtime.checkpoint().to_dict()
    bad = deepcopy(original)
    row = next(row for row in bad["state"]["references"]["objects"] if row["object_id"] == "container")
    row["type_descriptor"] = "string,int" if kind == "map" else "int"
    with pytest.raises(PineRuntimeError, match="declared type"):
        runtime.restore(reseal(bad))
    assert runtime.checkpoint().to_dict() == original


@pytest.mark.parametrize("fault", ["working_list", "wrong_phase_backing", "type_mismatch"])
def test_committed_slice_is_validated_independently_of_working_shape_and_backing(fault):
    runtime = session()
    tx = begin(runtime, 0)
    value = tx.enum_value_v1(E, "buy", 0)
    handle = array_new(tx.references, "parent", E, 2, value)
    array_slice(tx.references, handle, 0, 1, "slice")
    array_new(tx.references, "foreign", F, 2, tx.enum_value_v1(F, "buy", 0))
    tx.commit()
    original = runtime.checkpoint().to_dict()
    bad = deepcopy(original)
    rows = {row["object_id"]: row for row in bad["state"]["references"]["objects"]}
    if fault == "working_list":
        rows["slice"]["working"] = deepcopy(rows["parent"]["working"][:1])
        rows["slice"]["committed"]["$pinelib_array_slice"]["end"] = 3
    elif fault == "wrong_phase_backing":
        rows["parent"]["committed"] = []
        # Working parent still has two values. The committed slice [0:1]
        # cannot be validated against that longer working parent.
    else:
        rows["slice"]["committed"]["$pinelib_array_slice"]["parent"]["$pinelib_ref"]["object_id"] = "foreign"
    with pytest.raises(PineRuntimeError):
        runtime.restore(reseal(bad))
    assert runtime.checkpoint().to_dict() == original


@pytest.mark.parametrize("nominal", ["enum", "udt"])
def test_scalar_series_type_cannot_hide_a_valid_nominal_value(nominal):
    runtime = checkpoint_fixture()
    original = runtime.checkpoint().to_dict()
    bad = deepcopy(original)
    row = bad["state"]["series"]["side" if nominal == "enum" else "box"]
    row["dtype"] = "float"
    with pytest.raises(PineRuntimeError):
        runtime.restore(reseal(bad))
    assert runtime.checkpoint().to_dict() == original
    tx = begin(runtime, 1)
    value = tx.enum_value_v1(E, "buy", 0) if nominal == "enum" else box(tx, identity="second-box")
    with pytest.raises(PineRuntimeError):
        tx.set_series("incorrect", value, "float")
    assert "incorrect" not in runtime.series
    tx.abort()


def test_operator_does_not_admit_a_directly_forged_enum_value():
    tx = begin(session(), 0)
    valid = tx.enum_value_v1(E, "buy", 0)
    for left, right in ((valid, PineEnumValue(E, "unknown", 0)),
                        (PineEnumValue(E, "sell", 0), valid)):
        with pytest.raises(PineRuntimeError):
            tx.op_operator_binary("==", left, right)
    tx.abort()
