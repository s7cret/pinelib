"""Independent nominal value and field rollback contracts, Pine v5/v6.

Expected values follow assignment identity, shallow-copy and field-only varip
rules documented at https://www.tradingview.com/pine-script-docs/language/objects/.
They are explicit constants, not generated outputs or TradingView exports.
"""

import json
from copy import deepcopy

import pytest

from pinelib import RuntimeSession, is_na, na
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_get, array_new, array_set
from pinelib.reference.heap import PineEnumValue, RuntimeReferenceHeap
from pinelib.reference.registry import NominalTypeRegistry
from pinelib.state.checkpoint import RuntimeCheckpoint
from tests.test_language_scopes_once import begin, session as language_session


SOURCE_HASH = "sha256:" + "a" * 64
POINT = f"udt:{SOURCE_HASH}:Point:decl-1"
SIDE = f"enum:{SOURCE_HASH}:Side:decl-2"
NESTED = f"udt:{SOURCE_HASH}:Nested:decl-3"
ARRAY_HOLDER = f"udt:{SOURCE_HASH}:ArrayHolder:decl-4"
WRITE_TARGET = f"udt:{SOURCE_HASH}:WriteTarget:decl-5"
FLAG = f"udt:{SOURCE_HASH}:Flag:decl-6"
CHECKPOINT_RECORD = f"udt:{SOURCE_HASH}:CheckpointRecord:decl-7"
OTHER_POINT = f"udt:{SOURCE_HASH}:OtherPoint:decl-8"
OTHER_SIDE = f"enum:{SOURCE_HASH}:OtherSide:decl-9"


def nominal_registry(version):
    """Declare each fixture schema before construction, including foreign types."""
    def udt(dtype, field_types, varip_fields=()):
        return {"id": dtype, "kind": "udt", "fields": [
            {"name": name, "type": field_type, "varip": name in varip_fields}
            for name, field_type in field_types.items()
        ]}

    types = [
        udt(POINT, {"bars": "int", "ticks": "int"}, ("ticks",)),
        udt(NESTED, {"child": POINT, "values": "array<int>", "side": SIDE}),
        udt(ARRAY_HOLDER, {"values": "array<int>"}),
        udt(WRITE_TARGET, {"n": "int", "child": POINT, "side": SIDE}),
        udt(FLAG, {"flag": "bool"}),
        udt(CHECKPOINT_RECORD, {"n": "int", "side": SIDE}, ("n",)),
        udt(OTHER_POINT, {"bars": "int", "ticks": "int"}, ("ticks",)),
        *({"id": dtype, "kind": "enum", "members": [
            {"name": "long", "title": "long"},
            {"name": "short", "title": "short"},
        ]} for dtype in (SIDE, OTHER_SIDE)),
    ]
    return NominalTypeRegistry.from_json(
        {"schema_id": "pinelib.nominal_registry.v1", "pine_version": version,
         "source_hash": SOURCE_HASH, "types": sorted(types, key=lambda row: row["id"])},
        pine_version=version, expected_source_hash=SOURCE_HASH,
    )


def session(version=6):
    return RuntimeSession(
        language_session(version).language,
        nominal_registry=nominal_registry(version) if version >= 5 else None,
    )


def point(tx, *, dtype=POINT, fields=None, field_types=None, varip_fields=("ticks",)):
    return tx.new_udt_v1(
        tx.reference_id_v1("point"), dtype,
        {"bars": 0, "ticks": 0} if fields is None else fields,
        field_types={"bars": "int", "ticks": "int"} if field_types is None else field_types,
        varip_fields=varip_fields,
    )


def declare(tx, mode):
    return tx.declare_reference_v1("counter", mode, lambda: point(tx), POINT)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("mode", ["var", "varip"])
@pytest.mark.parametrize("deferred", [False, True])
def test_only_declared_varip_fields_escape_tick_or_fill_rollback(version, mode, deferred):
    s = session(version)
    tx = begin(s, 0, bar=0, deferred=deferred)
    handle = declare(tx, mode)
    tx.commit()
    if deferred:
        s.finalize_bar(0)
    observed = []
    for tick in range(3):
        tx = begin(s, s.sequence + 1, bar=1, realtime=not deferred, final=tick == 2, deferred=deferred)
        assert declare(tx, mode) == handle
        for field in ("bars", "ticks"):
            tx.set_udt_field_v1(handle, field, tx.get_udt_field_v1(handle, field) + 1)
        observed.append((tx.get_udt_field_v1(handle, "bars"), tx.get_udt_field_v1(handle, "ticks")))
        tx.commit()
    assert observed == [(1, 1), (1, 2), (1, 3)]
    if deferred:
        s.finalize_bar(1)
    saved = json.loads(json.dumps(s.checkpoint().to_dict()))
    restored = session(version)
    restored.restore(saved)
    for runtime in (s, restored):
        tx = begin(runtime, runtime.sequence + 1, bar=2, deferred=deferred)
        assert declare(tx, mode) == handle
        assert tx.get_udt_field_v1(handle, "bars") == 1
        assert tx.get_udt_field_v1(handle, "ticks") == 3
        assert tx.op_series_history("counter", 1) == handle
        tx.commit()
        if deferred:
            runtime.finalize_bar(2)
    assert restored.state_hash == s.state_hash
    assert restored.semantic_state_hash == s.semantic_state_hash


@pytest.mark.parametrize("mode", ["var", "varip"])
def test_first_open_bar_varip_retains_only_identity_and_declared_fields(mode):
    s = session()
    observations = []
    handles = []
    for tick in range(3):
        tx = begin(s, tick, bar=0, realtime=True, final=tick == 2)
        handle = declare(tx, mode)
        handles.append(handle)
        for field in ("bars", "ticks"):
            tx.set_udt_field_v1(handle, field, tx.get_udt_field_v1(handle, field) + 1)
        observations.append((tx.get_udt_field_v1(handle, "bars"), tx.get_udt_field_v1(handle, "ticks")))
        tx.commit()
    assert observations == ([(1, 1), (1, 2), (1, 3)] if mode == "varip" else [(1, 1)] * 3)
    assert len(set(handles)) == (1 if mode == "varip" else 3)


@pytest.mark.parametrize("version", [5, 6])
def test_nested_aliases_and_copy_keep_reference_identity_and_field_policy(version):
    s = session(version)
    tx = begin(s, 0)
    child = point(tx)
    array = array_new(tx.references, "array", "int", 1, 5)
    side = tx.enum_value_v1(SIDE, "long", 0)
    outer = point(tx, dtype=NESTED, fields={"child": child, "values": array, "side": side},
                  field_types={"child": POINT, "values": "array<int>", "side": SIDE}, varip_fields=())
    copied = tx.copy_udt_v1(outer, tx.reference_id_v1("copy"))
    child_copy = tx.copy_udt_v1(child, tx.reference_id_v1("child-copy"))
    assert copied != outer and child_copy != child
    assert tx.get_udt_field_v1(copied, "child") == child
    assert tx.get_udt_field_v1(copied, "values") == array
    assert tx.get_udt_field_v1(copied, "side") == side
    tx.commit()
    tx = begin(s, 1, bar=1, realtime=True, final=False)
    tx.set_udt_field_v1(child, "bars", 7)
    tx.set_udt_field_v1(child, "ticks", 8)
    tx.set_udt_field_v1(child_copy, "ticks", 9)
    array_set(tx.references, array, 0, 10)
    assert tx.get_udt_field_v1(tx.get_udt_field_v1(copied, "child"), "bars") == 7
    tx.commit()
    tx = begin(s, 2, bar=1, realtime=True)
    assert tx.get_udt_field_v1(child, "bars") == 0
    assert tx.get_udt_field_v1(child, "ticks") == 8
    assert tx.get_udt_field_v1(child_copy, "ticks") == 9
    assert array_get(tx.references, tx.get_udt_field_v1(copied, "values"), 0) == 5
    tx.commit()
    r = session(version)
    r.restore(json.loads(json.dumps(s.checkpoint().to_dict())))
    tx = begin(r, 3, bar=2)
    assert tx.get_udt_field_v1(copied, "child") == child
    assert isinstance(tx.get_udt_field_v1(copied, "side"), PineEnumValue)
    tx.abort()


def test_varip_new_udt_keeps_initial_nested_reference_graph_addressable():
    s = session()
    tx = begin(s, 0, bar=0, realtime=True, final=False)
    array = array_new(tx.references, "array", "int", 1, 5)
    outer = point(tx, dtype=ARRAY_HOLDER, fields={"values": array}, field_types={"values": "array<int>"}, varip_fields=())
    tx.declare_reference_v1("outer", "varip", lambda: outer, ARRAY_HOLDER)
    array_set(tx.references, array, 0, 10)
    tx.commit()
    tx = begin(s, 1, bar=0, realtime=True)
    assert tx.declare_reference_v1("outer", "varip", lambda: 1 / 0, ARRAY_HOLDER) == outer
    assert array_get(tx.references, tx.get_udt_field_v1(outer, "values"), 0) == 5
    tx.commit()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("mode", ["default", "var", "varip"])
def test_enum_values_history_rollback_and_checkpoint(version, mode):
    s = session(version)
    tx = begin(s, 0)
    long = tx.enum_value_v1(SIDE, "long", 0)
    short = tx.enum_value_v1(SIDE, "short", 1)
    assert tx.declare_enum_v1("side", mode, lambda: long, SIDE) == long
    assert is_na(tx.op_series_history("side", 1))
    tx.commit()
    tx = begin(s, 1, bar=1, realtime=True, final=False)
    tx.declare_enum_v1("side", mode, lambda: long, SIDE)
    tx.write_enum_v1("side", mode, short, SIDE)
    tx.commit()
    tx = begin(s, 2, bar=1, realtime=True)
    assert tx.declare_enum_v1("side", mode, lambda: long, SIDE) == (short if mode == "varip" else long)
    assert tx.op_series_history("side", 1) == long
    tx.commit()
    r = session(version)
    r.restore(json.loads(json.dumps(s.checkpoint().to_dict())))
    tx = begin(r, 3, bar=2)
    assert tx.op_series_history("side", 1) == (short if mode == "varip" else long)
    tx.abort()


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_nominal_types_reject_old_versions_atomically(version):
    tx = begin(session(version), 0)
    before = tx.references.to_json()
    with pytest.raises(PineRuntimeError):
        point(tx)
    with pytest.raises(PineRuntimeError):
        tx.enum_value_v1(SIDE, "long", 0)
    assert tx.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("fault", ["wrong_scalar", "unknown_field", "foreign_udt", "foreign_enum", "null"])
def test_wrong_udt_field_writes_are_atomic(fault):
    tx = begin(session(), 0)
    child = point(tx)
    side = tx.enum_value_v1(SIDE, "long", 0)
    obj = point(tx, dtype=WRITE_TARGET, fields={"n": 0, "child": child, "side": side},
                field_types={"n": "int", "child": POINT, "side": SIDE}, varip_fields=())
    other = point(tx, dtype=OTHER_POINT)
    foreign = tx.enum_value_v1(OTHER_SIDE, "long", 0)
    field, value = {"wrong_scalar": ("n", True), "unknown_field": ("missing", 0),
                    "foreign_udt": ("child", other), "foreign_enum": ("side", foreign), "null": ("n", None)}[fault]
    before = tx.references.to_json()
    with pytest.raises(PineRuntimeError):
        tx.set_udt_field_v1(obj, field, value)
    assert tx.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
def test_bool_field_missing_default_is_version_exact(version):
    tx = begin(session(version), 0)
    if version == 6:
        with pytest.raises(PineRuntimeError, match="bool"):
            point(tx, dtype=FLAG, fields={"flag": na}, field_types={"flag": "bool"}, varip_fields=())
        obj = point(tx, dtype=FLAG, fields={"flag": False}, field_types={"flag": "bool"}, varip_fields=())
        assert tx.get_udt_field_v1(obj, "flag") is False
    else:
        obj = point(tx, dtype=FLAG, fields={"flag": na}, field_types={"flag": "bool"}, varip_fields=())
        assert is_na(tx.get_udt_field_v1(obj, "flag"))
    tx.abort()


@pytest.mark.parametrize("fault", ["unknown_varip_field", "schema_removed", "wrong_field_type", "foreign_enum", "enum_ordinal_bool", "version"])
def test_rehashed_nominal_heap_corruption_rejected_without_replacing_session(fault):
    s = session()
    tx = begin(s, 0)
    side = tx.enum_value_v1(SIDE, "long", 0)
    point(tx, dtype=CHECKPOINT_RECORD, fields={"n": 0, "side": side}, field_types={"n": "int", "side": SIDE}, varip_fields=("n",))
    tx.commit()
    saved = s.checkpoint().to_dict()
    bad = deepcopy(saved)
    row = bad["state"]["references"]["objects"][0]
    if fault == "unknown_varip_field":
        row["udt_schema"]["varip_fields"] = ["missing"]
    elif fault == "schema_removed":
        row.pop("udt_schema")
    elif fault == "wrong_field_type":
        row["working"]["n"] = False
    elif fault == "foreign_enum":
        row["working"]["side"]["$pinelib_enum"]["enum_id"] = OTHER_SIDE
    elif fault == "enum_ordinal_bool":
        row["working"]["side"]["$pinelib_enum"]["ordinal"] = True
    if fault == "version":
        with pytest.raises(PineRuntimeError):
            RuntimeReferenceHeap.from_json(bad["state"]["references"], session(4).language, max_objects=100, max_elements=100)
    else:
        bad = RuntimeCheckpoint.seal(s.identity_hash, bad["state"]).to_dict()
        with pytest.raises(PineRuntimeError):
            s.restore(bad)
    assert s.checkpoint().to_dict() == saved


@pytest.mark.parametrize("value", [True, -1, 1.5, "0"])
def test_enum_ordinal_is_exact_nonnegative_integer(value):
    tx = begin(session(), 0)
    with pytest.raises(PineRuntimeError):
        tx.enum_value_v1(SIDE, "long", value)
    tx.abort()


def test_nominal_enum_comparisons_reject_foreign_types_and_scalar_truthiness():
    tx = begin(session(), 0)
    long = tx.enum_value_v1(SIDE, "long", 0)
    assert tx.op_operator_binary("==", long, tx.enum_value_v1(SIDE, "long", 0)) is True
    assert tx.op_operator_binary("!=", long, tx.enum_value_v1(SIDE, "short", 1)) is True
    for other in (0, "long", tx.enum_value_v1(OTHER_SIDE, "long", 0)):
        with pytest.raises(PineRuntimeError):
            tx.op_operator_binary("==", long, other)
    with pytest.raises(PineRuntimeError):
        tx.condition_v1(long)
    tx.abort()


def test_historical_abort_discards_nominal_objects_and_state():
    s = session()
    before = s.checkpoint().to_dict()
    tx = begin(s, 0)
    declare(tx, "varip")
    tx.declare_enum_v1("side", "varip", lambda: tx.enum_value_v1(SIDE, "long", 0), SIDE)
    tx.abort()
    assert s.checkpoint().to_dict() == before


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("operator", ["==", "!="])
def test_enum_comparison_with_missing_history_is_version_exact(version, operator):
    tx = begin(session(version), 0)
    side = tx.enum_value_v1(SIDE, "long", 0)
    tx.declare_enum_v1("side", "default", lambda: side, SIDE)
    missing = tx.op_series_history("side", 1)
    result = tx.op_operator_binary(operator, missing, side)
    if version == 5:
        assert is_na(result)
    else:
        assert result is False
    tx.abort()


@pytest.mark.parametrize("segment", ["series", "slots"])
@pytest.mark.parametrize("fault", ["foreign_type", "bad_ordinal", "extra_marker_key"])
def test_standalone_enum_checkpoint_values_are_validated_before_atomic_restore(segment, fault):
    s = session()
    tx = begin(s, 0)
    tx.declare_enum_v1("side", "var", lambda: tx.enum_value_v1(SIDE, "long", 0), SIDE)
    tx.commit()
    before = s.checkpoint().to_dict()
    bad = deepcopy(before)
    value = (bad["state"]["series"]["side"]["working"] if segment == "series"
             else bad["state"]["slots"][0]["working"])
    if fault == "foreign_type":
        value["$pinelib_enum"]["enum_id"] = OTHER_SIDE
    elif fault == "bad_ordinal":
        value["$pinelib_enum"]["ordinal"] = True
    else:
        value["extra"] = 0
    bad = RuntimeCheckpoint.seal(s.identity_hash, bad["state"]).to_dict()
    with pytest.raises(PineRuntimeError, match="enum"):
        s.restore(bad)
    assert s.checkpoint().to_dict() == before


@pytest.mark.parametrize("mode", ["default", "var", "varip"])
def test_na_udt_binding_still_rejects_wrong_version(mode):
    tx = begin(session(4), 0)
    with pytest.raises(PineRuntimeError):
        tx.declare_reference_v1("p", mode, lambda: na, POINT)
    tx.abort()


@pytest.mark.parametrize("value", [na, None, 0, False])
def test_field_access_on_missing_or_invalid_reference_is_controlled(value):
    tx = begin(session(), 0)
    with pytest.raises(PineRuntimeError):
        tx.get_udt_field_v1(value, "n")
    with pytest.raises(PineRuntimeError):
        tx.set_udt_field_v1(value, "n", 1)
    with pytest.raises(PineRuntimeError):
        tx.copy_udt_v1(value, "copy")
    tx.abort()
