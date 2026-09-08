"""Pine 5/6 array element persistence is distinct from UDT field rollback.

Primary: https://www.tradingview.com/pine-script-docs/v5/language/arrays/
https://www.tradingview.com/pine-script-docs/language/objects/
Hand-authored traces; no source-to-storage authenticity claim.
"""
from copy import deepcopy
import json

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, na
from pinelib.errors import PineRuntimeError
from pinelib.reference.array import array_new, array_get, array_push, array_pop, array_set, array_size, array_copy, array_slice
from pinelib.reference.matrix import matrix_new, matrix_get, matrix_set
from pinelib.reference.registry import NominalTypeRegistry
from pinelib.reference.heap import ReferenceHandle, RuntimeReferenceHeap
from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies

SOURCE = "sha256:" + "d" * 64
COUNTER = "udt:" + SOURCE + ":Counter:varip-array-1"
OTHER = "udt:" + SOURCE + ":Other:varip-array-2"
SIDE = "enum:" + SOURCE + ":Side:varip-array-3"
DTYPE = "array<" + COUNTER + ">"
FIELDS = [("n", "int", False), ("ticks", "int", True),
          ("values", "array<int>", False), ("grid", "matrix<float>", False)]


def factory(version, compact=False, fields=FIELDS, policies=None):
    definitions = [
        {"id": SIDE, "kind": "enum", "members": [{"name": "one", "title": "one"}]},
        {"id": COUNTER, "kind": "udt", "fields": [{"name": n, "type": t, "varip": ip} for n, t, ip in fields]},
        {"id": OTHER, "kind": "udt", "fields": [{"name": "n", "type": "int", "varip": False}]},
    ]
    registry = NominalTypeRegistry.from_json({"schema_id": "pinelib.nominal_registry.v1", "pine_version": version,
        "source_hash": SOURCE, "types": sorted(definitions, key=lambda row: row["id"])},
        pine_version=version, expected_source_hash=SOURCE)
    def make():
        runtime = RuntimeSession(RuntimeLanguageContext(version, "stage2", f"pine-v{version}", SOURCE, "compiler_annotation"),
            policies, nominal_registry=registry)
        runtime.commit_full_identity = not compact
        return runtime
    return make


def begin(runtime, seq, *, bar=0, realtime=False, final=True, deferred=False):
    return runtime.begin(CallbackFrame("REALTIME_TICK" if realtime else "HISTORICAL_EVAL", seq,
        bar_index=bar, realtime=realtime, final_tick=final, defer_bar_commit=deferred))


def counter(tx, prefix="counter", fields=FIELDS):
    values = {}
    for name, typ, ip in fields:
        if typ == "array<int>": values[name] = array_new(tx.references, prefix + "-" + name, "int", 1, 0)
        elif typ == "matrix<float>": values[name] = matrix_new(tx.references, prefix + "-" + name, "float", 1, 1, 0.0)
        else: values[name] = 0
    return tx.new_udt_v1(prefix, COUNTER, values, field_types={n: t for n, t, ip in fields},
        varip_fields=tuple(n for n, t, ip in fields if ip))


def state(runtime, handle):
    heap = runtime.references
    from pinelib.reference.udt import udt_get
    return [udt_get(heap, handle, "n"), udt_get(heap, handle, "ticks"),
            array_get(heap, udt_get(heap, handle, "values"), 0), matrix_get(heap, udt_get(heap, handle, "grid"), 0, 0)]


def increment(tx, handle):
    n, ticks, values, grid = state(tx.session, handle)
    tx.set_udt_field_v1(handle, "n", n + 1)
    tx.set_udt_field_v1(handle, "ticks", ticks + 1)
    array_set(tx.references, tx.get_udt_field_v1(handle, "values"), 0, values + 1)
    matrix_set(tx.references, tx.get_udt_field_v1(handle, "grid"), 0, 0, grid + 1)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("fields", [FIELDS[:1], FIELDS[:2], FIELDS[2:3], FIELDS[3:], FIELDS])
def test_documented_empty_and_populated_admission(version, populated, fields):
    runtime = factory(version, fields=fields)()
    tx = begin(runtime, 0)
    value = counter(tx, fields=fields) if populated else na
    bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER, int(populated), value), DTYPE)
    assert array_size(tx.references, bag) == int(populated)
    if populated: assert array_get(tx.references, bag, 0) == value
    tx.commit()
    clone = factory(version, fields=fields)()
    clone.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    assert clone.references.to_json() == runtime.references.to_json()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("abort_middle", [False, True])
def test_alias_trial_abort_restore_and_same_sequence_final_retry(version, compact, abort_middle):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0)
    handle = counter(tx)
    bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER, 0), DTYPE)
    tx.commit()
    for seq, before in [(1, [0, 0, 0, 0.0]), (2, [0, 1, 0, 0.0])]:
        tx = begin(runtime, seq, bar=1, realtime=True, final=False)
        assert state(runtime, handle) == before
        array_push(tx.references, bag, handle)
        increment(tx, array_get(tx.references, bag, 0))
        assert state(runtime, handle) == [1, seq, 1, 1.0]
        if seq == 2 and abort_middle:
            success = deepcopy(runtime.transcript.to_dict())
            tx.abort()
            assert runtime.sequence == 1 and runtime.transcript.to_dict() == success
            assert state(runtime, handle) == [0, 2, 0, 0.0]
        else: tx.commit()
    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    clone = make()
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    for current in (runtime, clone):
        tx = begin(current, current.sequence + 1, bar=1, realtime=True)
        assert state(current, handle) == [0, 2, 0, 0.0]
        array_push(tx.references, bag, handle)
        increment(tx, handle)
        tx.commit()
        assert state(current, handle) == [1, 3, 1, 1.0]
        assert [array_get(current.references, bag, i) for i in range(3)] == [handle] * 3
        rows = {r["object_id"]: r for r in current.references.to_json()["objects"]}
        assert "intrabar_persistence" in rows["bag"]
        assert all("intrabar_persistence" not in rows[key] for key in ("counter", "counter-values", "counter-grid"))
    assert runtime.checkpoint().to_dict() == clone.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_fresh_udt_keeps_constructor_and_working_edges_without_promoting_children(version, compact):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0)
    bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER), DTYPE)
    tx.commit()
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    handle = counter(tx, "fresh")
    original = tx.get_udt_field_v1(handle, "values")
    replacement = array_new(tx.references, "replacement", "int", 1, 10)
    tx.set_udt_field_v1(handle, "values", replacement)
    increment(tx, handle)
    array_push(tx.references, bag, handle)
    tx.abort()
    assert state(runtime, handle) == [0, 1, 0, 0.0]
    assert runtime.references.contains("replacement")
    clone = make()
    clone.restore(runtime.checkpoint().to_dict())
    for current in (runtime, clone):
        tx = begin(current, 1, bar=1, realtime=True)
        assert not current.references.contains("replacement")
        assert tx.get_udt_field_v1(handle, "values") == original
        assert array_get(current.references, bag, 0) == handle
        tx.commit()
    assert runtime.checkpoint().to_dict() == clone.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("field_type,varip", [(SIDE, False), (OTHER, False), (COUNTER, False),
    ("array<" + OTHER + ">", False), ("map<string,int>", False), ("array<int>", True), ("matrix<float>", True)])
def test_deferred_profiles_reject_before_initializer_without_heap_change(version, field_type, varip):
    runtime = factory(version, fields=[("field", field_type, varip)])()
    tx = begin(runtime, 0)
    before = runtime.references.to_json()
    calls = []
    with pytest.raises(PineRuntimeError):
        tx.declare_reference_v1("bag", "varip", lambda: calls.append(True), DTYPE)
    assert not calls and before == runtime.references.to_json()
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("bad", [False, 0, "wrong", None, ReferenceHandle("foreign", "udt")])
def test_nominal_insert_rejection_is_atomic(version, bad):
    runtime = factory(version)()
    tx = begin(runtime, 0)
    bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER), DTYPE)
    before = runtime.references.to_json()
    with pytest.raises(PineRuntimeError): array_push(tx.references, bag, bad)
    assert runtime.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
def test_ordinary_child_alias_payload_rejection_remains_atomic(version):
    runtime = factory(version)()
    tx = begin(runtime, 0)
    handle = counter(tx)
    tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER, 1, handle), DTYPE)
    a, m = (tx.get_udt_field_v1(handle, name) for name in ("values", "grid"))
    before = runtime.references.to_json()
    with pytest.raises(PineRuntimeError): array_set(tx.references, a, 0, "wrong")
    assert runtime.references.to_json() == before
    with pytest.raises(PineRuntimeError): matrix_set(tx.references, m, 0, 0, False)
    assert runtime.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_shallow_copies_slice_backing_and_explicit_child_promotion(version, compact):
    make = factory(version, compact)
    runtime = make()
    tx = begin(runtime, 0)
    handle = counter(tx)
    bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER, 1, handle), DTYPE)
    copied = array_copy(tx.references, bag, "copied")
    view = tx.declare_reference_v1("view", "varip", lambda: array_slice(tx.references, bag, 0, 1, "view"), DTYPE)
    duplicate = tx.copy_udt_v1(handle, "duplicate")
    assert tx.get_udt_field_v1(duplicate, "values") == tx.get_udt_field_v1(handle, "values")
    tx.declare_reference_v1("values", "varip", lambda: tx.get_udt_field_v1(handle, "values"), "array<int>")
    tx.commit()
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    array_push(tx.references, view, duplicate)
    array_push(tx.references, copied, duplicate)
    increment(tx, handle)
    assert state(runtime, duplicate) == [0, 0, 1, 1.0]
    tx.commit()
    tx = begin(runtime, 2, bar=1, realtime=True)
    assert array_size(tx.references, bag) == array_size(tx.references, view) == 2
    assert array_size(tx.references, copied) == 1
    assert state(runtime, handle) == [0, 1, 1, 0.0]
    assert state(runtime, duplicate) == [0, 0, 1, 0.0]
    tx.commit()
    clone = make()
    clone.restore(runtime.checkpoint().to_dict())
    assert clone.references.to_json() == runtime.references.to_json()
    policies = {row["object_id"] for row in clone.references.to_json()["objects"] if row.get("intrabar_persistence")}
    assert policies == {"bag", "view", "counter-values"}


@pytest.mark.parametrize("version", [5, 6])
def test_removing_new_element_does_not_leave_permanent_referent_promotion(version):
    runtime = factory(version)()
    tx = begin(runtime, 0)
    bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER), DTYPE)
    tx.commit()
    tx = begin(runtime, 1, bar=1, realtime=True, final=False)
    handle = counter(tx, "temporary")
    array_push(tx.references, bag, handle)
    assert array_pop(tx.references, bag) == handle
    tx.abort()
    assert not any(runtime.references.contains(key) for key in ("temporary", "temporary-values", "temporary-grid"))
    assert array_size(runtime.references, bag) == 0
    # The two successful array mutations retain their revision despite equal
    # payloads, so the abort still requires its ordinary transition witness.
    assert runtime.references.revision(bag) == 2
    clone = factory(version)()
    clone.restore(runtime.checkpoint().to_dict())
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
def test_promotion_valid_prefix_then_invalid_child_is_atomic(version):
    runtime = factory(version)()
    tx = begin(runtime, 0)
    good, bad = counter(tx, "good"), counter(tx, "bad")
    # This ordinary, unretained child is outside the new graph's policy so far.
    array_set(tx.references, tx.get_udt_field_v1(bad, "values"), 0, "wrong")
    bag = array_new(tx.references, "bag", COUNTER, 1, good)
    array_push(tx.references, bag, bad)
    before = runtime.references.to_json()
    with pytest.raises(PineRuntimeError, match="element type"):
        tx.references.retain_intrabar(bag)
    assert runtime.references.to_json() == before
    assert not runtime.references._nominal_intrabar_roots
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("portable", [False, True])
def test_inserting_new_bad_child_graph_rejects_before_publication(version, portable):
    runtime = factory(version)()
    tx = begin(runtime, 0)
    bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER), DTYPE)
    bad = counter(tx, "bad")
    array_set(tx.references, tx.get_udt_field_v1(bad, "values"), 0, "wrong")
    before = runtime.references.to_json()
    with pytest.raises(PineRuntimeError, match="element type"):
        array_push(tx.references, bag, bad.__pinelib_portable__() if portable else bad)
    assert runtime.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("corruption", ["wrong_member", "child_payload", "schema", "missing_child", "root_flags"])
def test_checkpoint_nominal_graph_and_binding_policy_rejection_is_atomic(version, corruption):
    make = factory(version)
    runtime = make()
    tx = begin(runtime, 0)
    handle = counter(tx)
    tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER, 1, handle), DTYPE)
    tx.commit()
    before = runtime.checkpoint().to_dict()
    state_json = deepcopy(before["state"])
    rows = {row["object_id"]: row for row in state_json["references"]["objects"]}
    if corruption == "wrong_member": rows["bag"]["working"] = [False]
    elif corruption == "child_payload": rows["counter-values"]["working"] = ["wrong"]
    elif corruption == "schema": rows["counter"]["udt_schema"]["varip_fields"] = ["n", "ticks"]
    elif corruption == "missing_child": state_json["references"]["objects"].remove(rows["counter-grid"])
    else: del rows["bag"]["intrabar_persistence"]
    from pinelib.state.checkpoint import RuntimeCheckpoint
    forged = RuntimeCheckpoint.seal(runtime.identity_hash, state_json)
    with pytest.raises(PineRuntimeError): runtime.restore(forged.to_dict())
    assert runtime.checkpoint().to_dict() == before


@pytest.mark.parametrize("version", [5, 6])
def test_rejected_resource_limited_insert_keeps_all_flags_and_revisions(version):
    policies = RuntimePolicies(resource=ResourcePolicy(max_collection_elements=64))
    runtime = factory(version, policies=policies)()
    tx = begin(runtime, 0)
    handle = counter(tx)
    bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER), DTYPE)
    before = runtime.references.to_json()
    with pytest.raises(PineRuntimeError, match="limit"):
        tx.references.mutate_payload(bag, [handle] * 65)
    assert runtime.references.to_json() == before
    tx.abort()


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_nominal_varip_array_profile_is_unavailable_before_v5(version):
    from pinelib.reference.persistence import validate_varip_type
    with pytest.raises(PineRuntimeError, match="type/version"):
        validate_varip_type("array", DTYPE, version)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_parent_request_restore_admits_nominal_array_and_rejects_forged_child_payload(version, compact):
    from pinelib.abi.compiled_request import CompiledRequestExpression, security_v1
    from pinelib.request import ResultShape
    from pinelib.runtime.metadata import TimeframeContext
    from tests.test_compiled_requests import Provider, INSTRUMENT, begin as request_begin
    from tests.test_nominal_registry_request_restore import reseal_state, checkpoint_with

    prototype = factory(version)()
    def make():
        parent = RuntimeSession(prototype.language, instrument=INSTRUMENT, timeframe=TimeframeContext.parse("1"),
            request_provider=Provider(), nominal_registry=prototype.nominal_registry)
        parent.commit_full_identity = not compact
        return parent
    class Child:
        evaluations = 0
        def __init__(self, runtime): self.runtime = runtime
        def value(self):
            Child.evaluations += 1
            tx = self.runtime
            handle = tx.declare_reference_v1("c", "var", lambda: counter(tx), COUNTER)
            bag = tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER), DTYPE)
            array_push(tx.references, bag, handle)
            return float(array_size(tx.references, bag))
    parent = make()
    tx = request_begin(parent, 0)
    expression = CompiledRequestExpression(tx, Child, "value", "sha256:" + "e" * 64, ResultShape.scalar("float"))
    security_v1(tx, "EX:S", "5", expression, "nominal-array-child")
    tx.commit()
    saved = json.loads(json.dumps(parent.checkpoint().to_dict()))
    clone = make()
    evaluations, fetches = Child.evaluations, clone.requests.provider.calls
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    assert Child.evaluations == evaluations and clone.requests.provider.calls == fetches
    child = expression._runtime
    child.references._objects["counter-values"].working = ["forged"]
    child_saved = reseal_state(child, deepcopy(child.checkpoint().state))
    forged = checkpoint_with(parent, child_saved)
    with pytest.raises(PineRuntimeError, match="element type"):
        clone.restore(forged)
    assert clone.checkpoint().to_dict() == saved
    assert Child.evaluations == evaluations and clone.requests.provider.calls == fetches


@pytest.mark.parametrize("version", [5, 6])
def test_all_fundamental_field_and_collection_types_use_existing_value_owner(version):
    primitive = {"int": 0, "float": 1.5, "bool": False, "color": "#ff0000", "string": ""}
    fields = [(typ, typ, True) for typ in primitive]
    fields += [(kind + "_" + typ, kind + "<" + typ + ">", False)
               for kind in ("array", "matrix") for typ in primitive]
    make = factory(version, fields=fields)
    runtime = make()
    tx = begin(runtime, 0)
    values = dict(primitive)
    for typ, value in primitive.items():
        values["array_" + typ] = array_new(tx.references, "array-" + typ, typ, 1, value)
        values["matrix_" + typ] = matrix_new(tx.references, "matrix-" + typ, typ, 1, 1, value)
    handle = tx.new_udt_v1("all", COUNTER, values, field_types={n: t for n, t, ip in fields}, varip_fields=tuple(primitive))
    tx.declare_reference_v1("bag", "varip", lambda: array_new(tx.references, "bag", COUNTER, 1, handle), DTYPE)
    tx.commit()
    clone = make()
    clone.restore(runtime.checkpoint().to_dict())
    assert clone.references.to_json() == runtime.references.to_json()


def test_target_addition_keeps_existing_fundamental_contract_and_rows_unchanged():
    from pinelib.abi.builder import build_manifest, check_manifest
    from importlib.resources import files
    manifest = build_manifest()
    assert manifest["compiled_varip_reference_storage"] == {
        "revision": 1, "policy": "per-object-transactional-persistence",
        "kinds": ["array", "matrix", "map"], "element_types": ["int", "float", "bool", "color", "string"], "min_pine_version": 5}
    assert manifest["compiled_varip_nominal_arrays"] == {
        "revision": 1, "registry_schema_id": "pinelib.nominal_registry.v1", "element_type": "udt",
        "field_profile": "fundamentals-and-ordinary-fundamental-array-matrix",
        "persistence": "array-elements-and-declared-varip-fields", "min_pine_version": 5}
    assert next(row for row in manifest["rows"] if row["symbol_id"] == "pine:function:float")["version_availability"] == [4, 5, 6]
    check_manifest(files("pinelib.abi").joinpath("target_manifest.json"))
