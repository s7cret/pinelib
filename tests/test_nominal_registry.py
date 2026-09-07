"""Declaration admission independent of observed objects or checkpoint values.

Initial varip profile: arrays of fundamentals or UDTs with fundamental and
fundamental array/matrix fields, explicitly documented by v5 Arrays. v5
Matrices/Maps list map fields too, and v6 Arrays uses broader collection wording;
those wider shapes need a separate execution profile and are rejected here.
Structural map parsing does not grant varip admission. Rejection of such a
shape is a runtime profile boundary, not a claim that Pine forbids it.
https://www.tradingview.com/pine-script-docs/v5/language/arrays/
https://www.tradingview.com/pine-script-docs/language/arrays/
https://www.tradingview.com/pine-script-docs/v5/language/matrices/
https://www.tradingview.com/pine-script-docs/v5/language/maps/
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json

import pytest

from pinelib.errors import PL_REFERENCE_TYPE, PL_RESOURCE_LIMIT, PineRuntimeError
from pinelib.reference.registry import (
    EnumDefinition, NominalRegistryLimits, NominalTypeRegistry, UDTDefinition,
)


SOURCE = "sha256:" + "a" * 64
SIDE = "enum:" + SOURCE + ":Side:decl-1"
BOX = "udt:" + SOURCE + ":Box:decl-2"
COUNTER = "udt:" + SOURCE + ":Counter:decl-3"
ENVELOPE = "udt:" + SOURCE + ":Envelope:decl-4"


def payload(version=6):
    return {
        "schema_id": "pinelib.nominal_registry.v1", "pine_version": version,
        "source_hash": SOURCE,
        "types": [
            {"id": SIDE, "kind": "enum", "members": [
                {"name": "buy", "title": "Bullish"},
                {"name": "sell", "title": "Bearish"},
                {"name": "neutral", "title": "neutral"},
            ]},
            {"id": BOX, "kind": "udt", "fields": [
                {"name": "side", "type": SIDE, "varip": True},
                {"name": "counter", "type": COUNTER, "varip": False},
            ]},
            {"id": COUNTER, "kind": "udt", "fields": [
                {"name": "n", "type": "int", "varip": False},
                {"name": "ticks", "type": "int", "varip": True},
                {"name": "values", "type": "array<float>", "varip": False},
                {"name": "grid", "type": "matrix<bool>", "varip": False},
                {"name": "table", "type": "map<string,int>", "varip": False},
            ]},
        ],
    }


def admit(data=None, *, version=6, limits=None):
    return NominalTypeRegistry.from_json(
        payload(version) if data is None else data, pine_version=version,
        expected_source_hash=SOURCE, limits=limits,
    )


@pytest.mark.parametrize("version", [5, 6])
def test_complete_declarations_round_trip_before_any_values_exist(version):
    data = payload(version)
    registry = admit(data, version=version)
    assert registry.to_json() == data
    expected_hash = "sha256:" + hashlib.sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    assert registry.content_hash == expected_hash
    assert registry.enum_member(SIDE, "neutral", 2).title == "neutral"
    assert registry.enum_member(SIDE, "buy", 0).title == "Bullish"
    box = registry.udt_schema(BOX)
    assert box.fields[1].type.text == COUNTER  # Forward declaration.
    assert box.fields[0].varip is True
    assert isinstance(registry.lookup(SIDE), EnumDefinition)
    assert isinstance(registry.lookup(COUNTER), UDTDefinition)
    restored = admit(json.loads(json.dumps(registry.to_json())), version=version)
    assert restored.content_hash == registry.content_hash
    assert restored.udt_schema(BOX) == box


def test_input_output_and_lookup_records_cannot_mutate_admitted_proof():
    data = payload()
    original = deepcopy(data)
    registry = admit(data)
    digest = registry.content_hash
    data["types"][0]["members"][0]["name"] = "forged"
    data["types"][2]["fields"][0]["type"] = "string"
    exported = registry.to_json()
    exported["types"][0]["members"].clear()
    exported["types"][1]["fields"][0]["varip"] = False
    with pytest.raises(FrozenInstanceError):
        registry.enum_member(SIDE, "buy", 0).ordinal = 123
    with pytest.raises(FrozenInstanceError):
        registry.udt_schema(COUNTER).fields[0].type.text = "string"
    with pytest.raises(FrozenInstanceError):
        registry.source_hash = "sha256:" + "b" * 64
    with pytest.raises(TypeError):
        registry._definitions[SIDE] = registry.udt_schema(BOX)
    assert registry.to_json() == original
    assert registry.content_hash == digest
    other = admit(original)
    assert other.to_json() == original


@pytest.mark.parametrize("member,ordinal", [
    ("not_declared", 0), ("buy", 123), ("sell", 0), ("buy", -1),
    ("buy", True), ("buy", False), ("buy", 0.0), ("buy", "0"),
    ("buy", None), ("Buy", 0), (None, 0), (0, 0),
])
@pytest.mark.parametrize("version", [5, 6])
def test_rehashed_checkpoint_member_claims_cannot_create_members(member, ordinal, version):
    registry = admit(version=version)
    with pytest.raises(PineRuntimeError) as error:
        registry.enum_member(SIDE, member, ordinal)
    assert error.value.code == PL_REFERENCE_TYPE


@pytest.mark.parametrize("dtype", ["enum:foreign:Side", SIDE + ":extra", "Side", None, [], False])
def test_lookup_requires_exact_admitted_identity(dtype):
    with pytest.raises(PineRuntimeError, match="not declared"):
        admit().lookup(dtype)


def test_enum_and_udt_lookup_do_not_cross_kinds_or_alias_same_names():
    data = payload()
    second = SIDE.replace("Side:decl-1", "OtherSide:decl-9")
    data["types"].append({"id": second, "kind": "enum", "members": [{"name": "buy", "title": "Other"}]})
    data["types"].sort(key=lambda row: row["id"])
    registry = admit(data)
    assert registry.enum_member(second, "buy", 0).title == "Other"
    assert registry.enum_member(SIDE, "buy", 0).title == "Bullish"
    with pytest.raises(PineRuntimeError, match="not a UDT"):
        registry.udt_schema(SIDE)
    with pytest.raises(PineRuntimeError, match="not an enum"):
        registry.enum_member(BOX, "buy", 0)


@pytest.mark.parametrize("key", ["schema_id", "pine_version", "source_hash", "types"])
def test_missing_registry_keys_rejected(key):
    data = payload()
    del data[key]
    with pytest.raises(PineRuntimeError, match="schema mismatch"):
        admit(data)


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(extra=True),
    lambda d: d.update(schema_id="pinelib.nominal_registry.v2"),
    lambda d: d.update(pine_version=True),
    lambda d: d.update(pine_version=5),
    lambda d: d.update(source_hash="sha256:" + "b" * 64),
    lambda d: d.update(types=tuple(d["types"])),
    lambda d: d["types"].reverse(),
    lambda d: d["types"].append(deepcopy(d["types"][-1])),
    lambda d: d["types"][0].update(kind="other"),
    lambda d: d["types"][0].update(id=BOX),
    lambda d: d["types"][0].update(id="enum:sha256:" + "b" * 64 + ":Side:decl-1"),
    lambda d: d["types"][0].update(id="enum:" + SOURCE + ":"),
    lambda d: d["types"][0].update(id=SIDE + "<int>"),
    lambda d: d["types"][0].update(extra=True),
    lambda d: d["types"][0].update(members=[]),
    lambda d: d["types"][1].update(fields=[]),
    lambda d: d["types"][0]["members"].append(deepcopy(d["types"][0]["members"][0])),
    lambda d: d["types"][1]["fields"].append(deepcopy(d["types"][1]["fields"][0])),
    lambda d: d["types"][0]["members"][0].update(ordinal=0),
    lambda d: d["types"][0]["members"][0].update(title=None),
    lambda d: d["types"][0]["members"][0].pop("title"),
    lambda d: d["types"][0]["members"][0].update(name=""),
    lambda d: d["types"][0]["members"][0].update(name="a.b"),
    lambda d: d["types"][1]["fields"][0].update(varip=1),
    lambda d: d["types"][1]["fields"][0].pop("type"),
    lambda d: d["types"][1]["fields"][0].update(default=0),
    lambda d: d["types"][1]["fields"][0].update(type="udt:" + SOURCE + ":Missing:decl-9"),
])
def test_closed_declaration_schema_rejects_forged_or_incomplete_proof(mutation):
    data = payload()
    mutation(data)
    with pytest.raises(PineRuntimeError) as error:
        admit(data)
    assert error.value.code == PL_REFERENCE_TYPE


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_old_versions_accept_empty_registry_but_not_nominal_or_collection_profile(version):
    data = payload(version)
    with pytest.raises(PineRuntimeError, match="v5/v6"):
        admit(data, version=version)
    data["types"] = []
    registry = admit(data, version=version)
    assert registry.to_json() == data
    assert registry.parse_type("int").kind == "int"
    for dtype in ("array<int>", "matrix<float>", "map<string,int>"):
        with pytest.raises(PineRuntimeError, match="profile requires Pine v5/v6"):
            registry.parse_type(dtype)
        with pytest.raises(PineRuntimeError, match="profile requires Pine v5/v6"):
            registry.validate_varip_collection(dtype)


@pytest.mark.parametrize("version", [0, 7, True, False, 5.0, "6", None])
def test_version_is_exact_supported_integer(version):
    with pytest.raises(PineRuntimeError, match="exact Pine version"):
        admit(version=version)


@pytest.mark.parametrize("source", [None, "a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 63])
def test_expected_source_hash_must_be_canonical(source):
    with pytest.raises(PineRuntimeError, match="source hash is invalid"):
        NominalTypeRegistry.from_json(payload(), pine_version=6, expected_source_hash=source)


@pytest.mark.parametrize("version", [5, 6])
def test_resolved_generic_arguments_preserve_nominal_identity(version):
    registry = admit(version=version)
    enum_map = registry.parse_type(f"map<{SIDE},{BOX}>")
    assert enum_map.kind == "map"
    assert [(arg.kind, arg.text) for arg in enum_map.arguments] == [("enum", SIDE), ("udt", BOX)]
    assert registry.parse_type(f"array<{COUNTER}>").arguments[0].text == COUNTER
    assert registry.parse_type("matrix<float>").arguments[0].kind == "float"
    assert registry.parse_type("bool").arguments == ()


@pytest.mark.parametrize("descriptor", [
    "", None, False, "array", "array<>", "array<int,float>", "map<int>",
    "matrix<int,int>", "map<int,float,bool>", "array<int", "array<int>>",
    "array<int>,float", "array<int>int", "array<,int>", "map<int,>",
    "map<<int>,float>", "array<int float>", "array< int>", "int[]",
    "unknown<int>", "int<float>", "na", "series<float>",
    "array<array<int>>", "map<string,array<int>>", "matrix<map<int,float>>",
    "array<enum:" + SOURCE + ":Missing:decl-9>", f"map<{BOX},int>",
])
@pytest.mark.parametrize("version", [5, 6])
def test_generic_arity_shape_and_nominal_closure_fail_closed(descriptor, version):
    with pytest.raises(PineRuntimeError) as error:
        admit(version=version).parse_type(descriptor)
    assert error.value.code == PL_REFERENCE_TYPE


@pytest.mark.parametrize("version", [5, 6])
def test_varip_profile_accepts_proved_udt_fundamental_collection_fields(version):
    data = payload(version)
    assert data["types"][2]["fields"].pop()["name"] == "table"
    registry = admit(data, version=version)
    for descriptor in (f"array<{COUNTER}>", "array<bool>", "array<int>",
                       "array<float>", "array<string>", "array<color>"):
        assert registry.validate_varip_collection(descriptor).text == descriptor
    for descriptor in (f"array<{BOX}>", f"array<{SIDE}>", f"map<{SIDE},int>", COUNTER):
        with pytest.raises(PineRuntimeError):
            registry.validate_varip_collection(descriptor)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("descriptor", [
    "matrix<float>", "map<string,int>", f"matrix<{COUNTER}>",
    f"map<string,{COUNTER}>",
])
def test_structural_matrix_map_support_does_not_grant_varip_profile(descriptor, version):
    data = payload(version)
    assert data["types"][2]["fields"].pop()["name"] == "table"
    registry = admit(data, version=version)
    assert registry.parse_type(descriptor).text == descriptor
    with pytest.raises(PineRuntimeError, match="admits only arrays"):
        registry.validate_varip_collection(descriptor)


@pytest.mark.parametrize("version", [5, 6])
def test_udt_map_field_remains_structural_without_implied_varip_parity(version):
    registry = admit(version=version)
    assert registry.udt_schema(COUNTER).fields[-1].type.text == "map<string,int>"
    assert registry.parse_type(f"array<{COUNTER}>").arguments[0].text == COUNTER
    with pytest.raises(PineRuntimeError, match="outside the varip collection profile"):
        registry.validate_varip_collection(f"array<{COUNTER}>")


@pytest.mark.parametrize("mutual", [False, True])
def test_cyclic_declarations_are_represented_but_not_granted_recursive_varip(mutual):
    data = payload()
    data["types"][2]["fields"] = [{"name": "next", "type": ENVELOPE if mutual else COUNTER, "varip": True}]
    if mutual:
        data["types"].append({"id": ENVELOPE, "kind": "udt", "fields": [
            {"name": "back", "type": COUNTER, "varip": False},
        ]})
    registry = admit(data)
    assert registry.to_json() == data
    assert registry.udt_schema(COUNTER).fields[0].type.text == (ENVELOPE if mutual else COUNTER)
    with pytest.raises(PineRuntimeError, match="UDT field type is outside the varip collection profile"):
        registry.validate_varip_collection(f"array<{COUNTER}>")


@pytest.mark.parametrize("limit,value", [
    ("max_types", 2), ("max_fields", 6), ("max_members", 2),
    ("max_bytes", 100), ("max_json_nodes", 10), ("max_json_depth", 3),
    ("max_type_nodes", 10), ("max_descriptor_chars", 20), ("max_type_depth", 1),
])
def test_admission_budgets_are_enforced_before_a_registry_escapes(limit, value):
    with pytest.raises(PineRuntimeError) as error:
        admit(limits=replace(NominalRegistryLimits(), **{limit: value}))
    assert error.value.code == PL_RESOURCE_LIMIT


def test_budget_boundaries_and_total_counts_are_exact():
    data = payload()
    size = len(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    # Seven UDT fields; scalar/nominal leaves + three collection roots = 11 nodes.
    limits = NominalRegistryLimits(max_types=3, max_fields=7, max_members=3, max_type_nodes=11, max_bytes=size)
    assert admit(data, limits=limits).to_json() == data
    with pytest.raises(PineRuntimeError) as error:
        admit(data, limits=replace(limits, max_bytes=size - 1))
    assert error.value.code == PL_RESOURCE_LIMIT


def test_utf8_byte_budget_is_not_a_character_budget():
    data = payload()
    data["types"][0]["members"][0]["title"] = "\u0416" * 100
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with pytest.raises(PineRuntimeError) as error:
        admit(data, limits=NominalRegistryLimits(max_bytes=len(encoded)))
    assert error.value.code == PL_RESOURCE_LIMIT


def test_deep_malformed_generic_stops_at_depth_budget_without_python_recursion():
    registry = admit(limits=NominalRegistryLimits(max_type_depth=8))
    with pytest.raises(PineRuntimeError) as error:
        registry.parse_type("array<" * 300 + "int" + ">" * 300)
    assert error.value.code == PL_RESOURCE_LIMIT


def test_python_container_cycles_and_non_json_values_are_not_registry_proof():
    data = payload()
    data["types"][0]["members"].append(data)
    with pytest.raises(PineRuntimeError, match="container cycle"):
        admit(data)
    for value in (float("nan"), float("inf"), object(), {"not", "json"}):
        data = payload()
        data["types"][0]["members"][0]["title"] = value
        with pytest.raises(PineRuntimeError):
            admit(data)


def test_identical_shared_python_lists_are_copied_and_validated_as_json():
    data = payload()
    data["types"].append({"id": ENVELOPE, "kind": "udt", "fields": data["types"][2]["fields"]})
    registry = admit(data)
    data["types"][2]["fields"].clear()
    assert len(registry.udt_schema(COUNTER).fields) == 5
    assert len(registry.udt_schema(ENVELOPE).fields) == 5


@pytest.mark.parametrize("value", [0, -1, True, 1.0, None])
def test_limit_values_are_positive_exact_ints(value):
    with pytest.raises(PineRuntimeError) as error:
        NominalRegistryLimits(max_types=value)
    assert error.value.code == PL_RESOURCE_LIMIT


def test_unvalidated_constructor_and_external_limit_objects_rejected():
    with pytest.raises(TypeError, match="from_json"):
        NominalTypeRegistry()
    with pytest.raises(PineRuntimeError, match="limits must be"):
        admit(limits={"max_types": 1})
