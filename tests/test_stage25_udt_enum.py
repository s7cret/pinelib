"""Stage 2.5 runtime matrix built on the admitted nominal registry owner."""

from __future__ import annotations

import json

import pytest

from pinelib.errors import PineRuntimeError
from pinelib.reference.nominal import enum_coerce
from pinelib.reference.array import array_new
from pinelib.reference.udt import enum_value, udt_copy, udt_get, udt_set
from tests.test_nominal_types import (
    NESTED,
    OTHER_POINT,
    OTHER_SIDE,
    POINT,
    SIDE,
    begin,
    nominal_registry,
    point,
    session,
)


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_same_named_shapes_from_distinct_ids_are_not_mixed(version):
    runtime = session(version)
    tx = begin(runtime, 0)
    left = point(tx)
    right = point(tx, dtype=OTHER_POINT)
    udt_set(tx.references, left, "bars", 3)
    udt_set(tx.references, right, "bars", 30)
    assert udt_get(tx.references, left, "bars") == 3
    assert udt_get(tx.references, right, "bars") == 30
    assert left.object_id != right.object_id
    payload = tx.references.to_json()
    descriptors = {row["type_descriptor"] for row in payload["objects"]}
    assert POINT in descriptors and OTHER_POINT in descriptors
    tx.commit()


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_copy_keeps_field_values_and_new_object_identity(version):
    runtime = session(version)
    tx = begin(runtime, 0)
    original = point(tx, fields={"bars": 4, "ticks": 1})
    copied = udt_copy(tx.references, original, tx.reference_id_v1("copy"))
    udt_set(tx.references, copied, "bars", 9)
    assert udt_get(tx.references, original, "bars") == 4
    assert udt_get(tx.references, copied, "bars") == 9
    assert original.object_id != copied.object_id
    tx.commit()


def test_stage25_unknown_and_foreign_enum_members_fail_closed():
    registry = nominal_registry(6)
    with pytest.raises(PineRuntimeError):
        enum_coerce(enum_value(SIDE, "up", 0), SIDE, 6, registry)
    with pytest.raises(PineRuntimeError):
        enum_coerce(enum_value(OTHER_SIDE, "long", 0), SIDE, 6, registry)


def test_stage25_checkpoint_payload_keeps_distinct_nominal_descriptors():
    runtime = session(6)
    tx = begin(runtime, 0)
    point(tx)
    point(tx, dtype=OTHER_POINT)
    tx.commit()
    portable = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    blob = json.dumps(portable)
    assert POINT in blob and OTHER_POINT in blob
    restored = session(6)
    restored.restore(portable)
    again = json.dumps(restored.checkpoint().to_dict())
    assert POINT in again and OTHER_POINT in again


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_nested_udt_copy_keeps_shared_child_handle(version):
    runtime = session(version)
    tx = begin(runtime, 0)
    child = point(tx, fields={"bars": 2, "ticks": 0})
    parent = point(
        tx,
        dtype=NESTED,
        fields={"child": child, "values": array_new(tx.references, "array", "int", 1, 5), "side": enum_value(SIDE, "long", 0)},
        field_types={"child": POINT, "values": "array<int>", "side": SIDE},
        varip_fields=(),
    )
    copied = udt_copy(tx.references, parent, tx.reference_id_v1("nested-copy"))
    assert udt_get(tx.references, parent, "child").object_id == udt_get(tx.references, copied, "child").object_id
    assert parent.object_id != copied.object_id
    udt_set(tx.references, udt_get(tx.references, copied, "child"), "bars", 8)
    assert udt_get(tx.references, child, "bars") == 8
    tx.commit()


def test_stage25_abort_discards_uncommitted_udt_mutation():
    runtime = session(6)
    tx = begin(runtime, 0)
    handle = point(tx, fields={"bars": 1, "ticks": 0})
    tx.commit()
    tx2 = begin(runtime, 1)
    udt_set(tx2.references, handle, "bars", 99)
    assert udt_get(tx2.references, handle, "bars") == 99
    tx2.abort()
    tx3 = begin(runtime, 2)
    assert udt_get(tx3.references, handle, "bars") == 1
    tx3.commit()


def test_stage25_enum_checkpoint_roundtrip_rejects_foreign_member():
    runtime = session(6)
    tx = begin(runtime, 0)
    point(tx)
    tx.commit()
    portable = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    restored = session(6)
    restored.restore(json.loads(json.dumps(portable)))
    with pytest.raises(PineRuntimeError):
        enum_coerce(enum_value(SIDE, "missing", 3), SIDE, 6, nominal_registry(6))
