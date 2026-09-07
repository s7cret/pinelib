"""Immutable declaration proof for the generated nominal-type contract.

Sessions and checkpoints use this owner to admit complete v5/v6 declarations,
including forward/cyclic references, before values exist. Structural admission
does not grant recursive varip persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Mapping

from pinelib.errors import PL_REFERENCE_TYPE, PL_RESOURCE_LIMIT, PineRuntimeError
from pinelib.state.checkpoint import canonical_json, is_canonical_sha256, sha

_SCHEMA = "pinelib.nominal_registry.v1"
_FUNDAMENTALS = frozenset({"int", "float", "bool", "color", "string"})
_COLLECTIONS = frozenset({"array", "matrix", "map"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _invalid(message: str) -> None:
    raise PineRuntimeError(message, code=PL_REFERENCE_TYPE)


def _budget(message: str) -> None:
    raise PineRuntimeError(message, code=PL_RESOURCE_LIMIT)


@dataclass(frozen=True, slots=True)
class NominalRegistryLimits:
    max_bytes: int = 1_048_576
    max_types: int = 1_024
    max_fields: int = 10_000
    max_members: int = 10_000
    max_descriptor_chars: int = 4_096
    max_type_depth: int = 32
    max_type_nodes: int = 100_000
    max_json_nodes: int = 100_000
    max_json_depth: int = 16

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                _budget(f"{name} must be a positive int")


@dataclass(frozen=True, slots=True)
class TypeDescriptor:
    """Resolved structure; nominal leaves retain their exact opaque identity."""

    text: str
    kind: str
    arguments: tuple[TypeDescriptor, ...] = ()


@dataclass(frozen=True, slots=True)
class EnumMember:
    name: str
    title: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class EnumDefinition:
    id: str
    members: tuple[EnumMember, ...]
    kind: str = field(default="enum", init=False)


@dataclass(frozen=True, slots=True)
class UDTField:
    name: str
    type: TypeDescriptor
    varip: bool


@dataclass(frozen=True, slots=True)
class UDTDefinition:
    id: str
    fields: tuple[UDTField, ...]
    kind: str = field(default="udt", init=False)


def _json_preflight(payload: object, limits: NominalRegistryLimits) -> None:
    """Bound hostile Python-shaped input before recursive JSON encoding.

    JSON contracts do not contain aliases, but a caller can supply Python
    containers. Shared acyclic containers are fine; actual cycles are rejected.
    """
    pending = [(payload, 0, False)]
    active: list[object] = []
    nodes = chars = 0
    while pending:
        value, depth, leaving = pending.pop()
        if leaving:
            active.pop()
            continue
        nodes += 1
        if nodes > limits.max_json_nodes or depth > limits.max_json_depth:
            _budget("nominal registry JSON structure exceeds limits")
        if type(value) in (dict, list):
            if any(value is ancestor for ancestor in active):
                _invalid("nominal registry JSON contains a container cycle")
            active.append(value)
            pending.append((value, depth, True))
            if len(value) > limits.max_json_nodes - nodes:
                _budget("nominal registry JSON container exceeds limits")
            if type(value) is dict:
                for key in value:
                    if type(key) is not str:
                        _invalid("nominal registry JSON keys must be strings")
                    chars += len(key)
                pending.extend((child, depth + 1, False) for child in value.values())
            else:
                pending.extend((child, depth + 1, False) for child in value)
        elif type(value) is str:
            chars += len(value)
        elif value is not None and type(value) not in (bool, int):
            _invalid("nominal registry JSON contains an unsupported value")
        if chars > limits.max_bytes:
            _budget("nominal registry exceeds byte limit")
    try:
        encoded = canonical_json(payload)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PineRuntimeError("nominal registry JSON is not canonical", code=PL_REFERENCE_TYPE) from error
    if len(encoded) > limits.max_bytes:
        _budget("nominal registry exceeds byte limit")


def _shape(value: object, keys: set[str], message: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        _invalid(message)
    return value


def _name(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _invalid("nominal field/member name must be an identifier")
    return value


def _parse_type(
    text: object, kinds: Mapping[str, str], version: int,
    limits: NominalRegistryLimits, remaining_nodes: list[int],
) -> TypeDescriptor:
    if type(text) is not str or not text:
        _invalid("type descriptor must be a nonempty canonical string")
    if len(text) > limits.max_descriptor_chars:
        _budget("type descriptor exceeds character limit")
    if any(char.isspace() for char in text):
        _invalid("type descriptor must be a nonempty canonical string")
    tokens = re.findall(r"[<>,]|[^<>,]+", text)
    # Explicit stack: custom budgets cannot turn deep descriptors into Python
    # recursion, including malformed inputs with many opening delimiters.
    frames: list[tuple[str, list[TypeDescriptor]]] = []
    result = None
    expect_type, index = True, 0

    def admit(node: TypeDescriptor) -> None:
        nonlocal result
        remaining_nodes[0] -= 1
        if remaining_nodes[0] < 0:
            _budget("nominal registry type nodes exceed limit")
        if frames:
            frames[-1][1].append(node)
        elif result is not None:
            _invalid("type descriptor has multiple roots")
        else:
            result = node

    while index < len(tokens):
        token = tokens[index]
        if expect_type:
            if token in {"<", ">", ","}:
                _invalid("type descriptor has a missing type argument")
            if len(frames) + 1 > limits.max_type_depth:
                _budget("type descriptor exceeds depth limit")
            if index + 1 < len(tokens) and tokens[index + 1] == "<":
                if token not in _COLLECTIONS:
                    _invalid("unknown generic type constructor")
                if version < 5:
                    _invalid("registry collection profile requires Pine v5/v6")
                frames.append((token, []))
                index += 2
                continue
            if token in _FUNDAMENTALS:
                kind = token
            elif token in kinds:
                kind = kinds[token]
            else:
                _invalid("type descriptor references an undeclared type")
            admit(TypeDescriptor(token, kind))
            expect_type = False
        elif token == "," and frames:
            expect_type = True
        elif token == ">" and frames:
            kind, args = frames.pop()
            if len(args) != (2 if kind == "map" else 1):
                _invalid("collection type argument arity mismatch")
            if any(arg.kind in _COLLECTIONS for arg in args):
                _invalid("collections cannot directly contain collections")
            if kind == "map" and args[0].kind not in _FUNDAMENTALS | {"enum"}:
                _invalid("map keys require a fundamental or enum type")
            admit(TypeDescriptor(kind + "<" + ",".join(arg.text for arg in args) + ">", kind, tuple(args)))
        else:
            _invalid("type descriptor delimiters are invalid")
        index += 1
    if expect_type or frames or result is None:
        _invalid("type descriptor is incomplete")
    return result


@dataclass(frozen=True, slots=True, init=False)
class NominalTypeRegistry:
    pine_version: int
    source_hash: str
    content_hash: str
    _definitions: Mapping[str, EnumDefinition | UDTDefinition]
    _kinds: Mapping[str, str]
    _limits: NominalRegistryLimits

    def __init__(self) -> None:
        raise TypeError("use NominalTypeRegistry.from_json for admission")

    @classmethod
    def from_json(
        cls, payload: object, *, pine_version: int, expected_source_hash: str,
        limits: NominalRegistryLimits | None = None,
    ) -> NominalTypeRegistry:
        if type(pine_version) is not int or pine_version not in range(1, 7):
            _invalid("nominal registry requires an exact Pine version from 1 to 6")
        if not is_canonical_sha256(expected_source_hash):
            _invalid("nominal registry expected source hash is invalid")
        if limits is None:
            limits = NominalRegistryLimits()
        if type(limits) is not NominalRegistryLimits:
            _invalid("nominal registry limits must be NominalRegistryLimits")
        _json_preflight(payload, limits)
        data = _shape(payload, {"schema_id", "pine_version", "source_hash", "types"}, "nominal registry schema mismatch")
        if (data["schema_id"] != _SCHEMA or type(data["pine_version"]) is not int
                or data["pine_version"] != pine_version or data["source_hash"] != expected_source_hash):
            _invalid("nominal registry differs from admitted source/version")
        rows = data["types"]
        if type(rows) is not list:
            _invalid("nominal registry types must be a list")
        if len(rows) > limits.max_types:
            _budget("nominal registry type count exceeds limit")
        if rows and pine_version < 5:
            _invalid("nominal declarations require Pine v5/v6")
        kinds: dict[str, str] = {}
        previous = ""
        for row in rows:
            if type(row) is not dict or type(row.get("kind")) is not str or row["kind"] not in {"enum", "udt"}:
                _invalid("nominal registry declaration kind is invalid")
            kind = row["kind"]
            _shape(row, {"id", "kind", "members" if kind == "enum" else "fields"}, "nominal declaration schema mismatch")
            identity = row["id"]
            prefix = kind + ":" + expected_source_hash + ":"
            if (type(identity) is not str or not identity.startswith(prefix)
                    or not identity[len(prefix):] or any(c.isspace() or c in "<>," for c in identity)):
                _invalid("nominal declaration ID differs from source/kind")
            if len(identity) > limits.max_descriptor_chars:
                _budget("nominal declaration ID exceeds character limit")
            if identity <= previous:
                _invalid("nominal declaration IDs must be unique and sorted")
            kinds[identity] = kind
            previous = identity
        definitions: dict[str, EnumDefinition | UDTDefinition] = {}
        fields_count = members_count = 0
        remaining_nodes = [limits.max_type_nodes]
        for row in rows:
            entries = row["members" if row["kind"] == "enum" else "fields"]
            if type(entries) is not list or not entries:
                _invalid("nominal declaration must contain a nonempty list")
            if row["kind"] == "enum":
                members_count += len(entries)
                if members_count > limits.max_members:
                    _budget("nominal enum members exceed limit")
                members = []
                names: set[str] = set()
                for ordinal, raw in enumerate(entries):
                    item = _shape(raw, {"name", "title"}, "enum member schema mismatch")
                    name = _name(item["name"])
                    if name in names or type(item["title"]) is not str:
                        _invalid("enum member names must be unique and titles strings")
                    names.add(name)
                    members.append(EnumMember(name, item["title"], ordinal))
                definitions[row["id"]] = EnumDefinition(row["id"], tuple(members))
            else:
                fields_count += len(entries)
                if fields_count > limits.max_fields:
                    _budget("nominal UDT fields exceed limit")
                fields = []
                names = set()
                for raw in entries:
                    item = _shape(raw, {"name", "type", "varip"}, "UDT field schema mismatch")
                    name = _name(item["name"])
                    if name in names or type(item["varip"]) is not bool:
                        _invalid("UDT field names must be unique and varip boolean")
                    names.add(name)
                    parsed = _parse_type(item["type"], kinds, pine_version, limits, remaining_nodes)
                    fields.append(UDTField(name, parsed, item["varip"]))
                definitions[row["id"]] = UDTDefinition(row["id"], tuple(fields))
        registry = object.__new__(cls)
        for name, value in {
            "pine_version": pine_version, "source_hash": expected_source_hash,
            "content_hash": sha(data), "_definitions": MappingProxyType(definitions),
            "_kinds": MappingProxyType(kinds), "_limits": limits,
        }.items():
            object.__setattr__(registry, name, value)
        return registry

    def lookup(self, dtype: str) -> EnumDefinition | UDTDefinition:
        if type(dtype) is not str or dtype not in self._definitions:
            _invalid("nominal type is not declared in the admitted registry")
        return self._definitions[dtype]

    def udt_schema(self, dtype: str) -> UDTDefinition:
        definition = self.lookup(dtype)
        if not isinstance(definition, UDTDefinition):
            _invalid("nominal type is not a UDT")
        return definition

    def enum_member(self, dtype: str, member: str, ordinal: int) -> EnumMember:
        definition = self.lookup(dtype)
        if not isinstance(definition, EnumDefinition):
            _invalid("nominal type is not an enum")
        if type(member) is not str or type(ordinal) is not int or not 0 <= ordinal < len(definition.members):
            _invalid("enum member/ordinal is invalid")
        value = definition.members[ordinal]
        if value.name != member:
            _invalid("enum member/ordinal differs from its declaration")
        return value

    def parse_type(self, descriptor: str) -> TypeDescriptor:
        return _parse_type(descriptor, self._kinds, self.pine_version, self._limits, [self._limits.max_type_nodes])

    def validate_varip_collection(self, descriptor: str) -> TypeDescriptor:
        """Initial profile: arrays of fundamentals or qualifying UDTs, v5/v6.

        A qualifying UDT has only fundamental fields or array/matrix fields
        containing fundamentals. v5 Arrays documents those field collections;
        its wording does not include maps, unlike the v5 Matrices/Maps pages.
        Keep the same bounded profile in v6 pending distinct execution fixtures
        for wider shapes. Structural map/matrix support does not enable them
        here. Rejection is a profile boundary, not a Pine-language prohibition.

        UDT-to-UDT fields, including cycles, are outside this profile. This query
        neither marks heap objects nor implies deep field persistence.
        https://www.tradingview.com/pine-script-docs/v5/language/arrays/
        https://www.tradingview.com/pine-script-docs/language/arrays/
        """
        parsed = self.parse_type(descriptor)
        if parsed.kind != "array":
            _invalid("initial varip collection profile admits only arrays")
        for argument in parsed.arguments:
            if argument.kind in _FUNDAMENTALS:
                continue
            if argument.kind != "udt":
                _invalid("varip collection element is outside the admitted profile")
            for member in self.udt_schema(argument.text).fields:
                typ = member.type
                if typ.kind in _FUNDAMENTALS:
                    continue
                if typ.kind in {"array", "matrix"} and all(arg.kind in _FUNDAMENTALS for arg in typ.arguments):
                    continue
                _invalid("UDT field type is outside the varip collection profile")
        return parsed

    def to_json(self) -> dict[str, object]:
        rows = []
        for definition in self._definitions.values():
            if isinstance(definition, EnumDefinition):
                rows.append({"id": definition.id, "kind": "enum", "members": [
                    {"name": member.name, "title": member.title} for member in definition.members
                ]})
            else:
                rows.append({"id": definition.id, "kind": "udt", "fields": [
                    {"name": member.name, "type": member.type.text, "varip": member.varip} for member in definition.fields
                ]})
        return {"schema_id": _SCHEMA, "pine_version": self.pine_version,
                "source_hash": self.source_hash, "types": rows}
