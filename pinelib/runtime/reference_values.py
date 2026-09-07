"""Typed collection variables in the existing slots, series and reference heap.

History stores an object ID, not snapshots of its elements. Repeated constructors
allocate fresh IDs, while assignment and parameter passing preserve aliases.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pinelib.core.values import is_na, na
from pinelib.errors import PL_REFERENCE_TYPE, PL_RESOURCE_LIMIT, PineRuntimeError
from pinelib.reference.heap import ReferenceHandle, RuntimeReferenceHeap
from pinelib.state.checkpoint import sha

_FUNDAMENTALS = frozenset({"bool", "color", "float", "int", "string"})
REFERENCE_OWNER = "ast2python.reference.v1"


def collection_type(dtype: str) -> tuple[str, str]:
    """Exact primitive-element descriptors; do not infer UDT object layouts."""
    if type(dtype) is not str:
        raise PineRuntimeError(
            "collection type must be explicit", code=PL_REFERENCE_TYPE
        )
    match = re.fullmatch(r"(array|matrix|map)<([^<>]+)>", dtype)
    if match is None:
        raise PineRuntimeError(
            "unsupported collection storage type", code=PL_REFERENCE_TYPE
        )
    kind, descriptor = match.groups()
    args = descriptor.split(",")
    if len(args) != (2 if kind == "map" else 1) or any(
        t not in _FUNDAMENTALS for t in args
    ):
        raise PineRuntimeError(
            "collection elements require exact fundamental types",
            code=PL_REFERENCE_TYPE,
        )
    return kind, descriptor


def validate_reference(heap: RuntimeReferenceHeap, value: object, dtype: str) -> object:
    kind, expected = collection_type(dtype)
    if is_na(value):
        return na
    if not isinstance(value, ReferenceHandle) or value.kind != kind:
        raise PineRuntimeError(
            "value is not the declared collection reference", code=PL_REFERENCE_TYPE
        )
    actual = heap.type_descriptor(value)  # Also verifies that the ID exists.
    # The existing request ABI uses a full descriptor for lower-TF arrays.
    if actual == dtype:
        actual = collection_type(actual)[1]
    if actual != expected:
        raise PineRuntimeError(
            "collection reference type does not match declaration",
            code=PL_REFERENCE_TYPE,
        )
    return value


def stored_reference(value: object) -> object:
    """Decode exactly one series/slot reference, never general heap payloads."""
    if value is None or is_na(value):
        return na
    if isinstance(value, ReferenceHandle):
        return value
    if isinstance(value, dict) and set(value) == {"$pinelib_ref"}:
        marker = value["$pinelib_ref"]
        if (
            isinstance(marker, dict)
            and set(marker) == {"object_id", "kind"}
            and type(marker["object_id"]) is str
            and type(marker["kind"]) is str
            and marker["kind"] in {"array", "matrix", "map"}
        ):
            return ReferenceHandle(marker["object_id"], marker["kind"])
    raise PineRuntimeError(
        "invalid stored collection reference", code=PL_REFERENCE_TYPE
    )


class ReferenceValuesMixin:
    def new_reference_id_v1(self, source_id: str) -> str:
        self._check()
        site = self.scoped_id_v1(source_id, local=True)
        # A retry at the same sequence can retain a varip allocation from an
        # aborted callback. Skip surviving IDs, never overwrite their contents.
        while True:
            ordinal = self._reference_allocations
            self._reference_allocations += 1
            identity = "ref:" + sha(
                {"site": site, "sequence": self.frame.sequence, "ordinal": ordinal}
            )
            if not self.references.has_id(identity):
                return identity

    def declare_reference_v1(
        self,
        series_id: str,
        mode: str,
        initializer: Callable[[], object],
        dtype: str,
        *,
        history_policy: str = "each_bar",
    ) -> object:
        self._check()
        collection_type(dtype)
        if mode not in {"default", "var", "varip"}:
            raise PineRuntimeError(
                "unsupported collection declaration mode", code=PL_REFERENCE_TYPE
            )
        slot_id = "reference:" + series_id
        if mode == "default":
            value = validate_reference(self.references, initializer(), dtype)
        elif self.session.slots.contains(slot_id):
            value = validate_reference(
                self.references,
                stored_reference(
                    self.state(
                        slot_id,
                        owner=REFERENCE_OWNER,
                        schema_version=dtype,
                        initial=na,
                        varip=mode == "varip",
                    )
                ),
                dtype,
            )
        else:
            value = validate_reference(self.references, initializer(), dtype)
            self.set_slot(
                slot_id,
                value,
                owner=REFERENCE_OWNER,
                schema_version=dtype,
                varip=mode == "varip",
            )
        self.set_series(series_id, value, dtype, history_policy=history_policy)
        return value

    def write_reference_v1(
        self,
        series_id: str,
        mode: str,
        value: object,
        dtype: str,
        *,
        history_policy: str = "each_bar",
    ) -> None:
        self._check()
        value = validate_reference(self.references, value, dtype)
        if mode not in {"default", "var", "varip"}:
            raise PineRuntimeError(
                "unsupported collection assignment mode", code=PL_REFERENCE_TYPE
            )
        if mode != "default":
            self.set_slot(
                "reference:" + series_id,
                value,
                owner=REFERENCE_OWNER,
                schema_version=dtype,
                varip=mode == "varip",
            )
        self.set_series(series_id, value, dtype, history_policy=history_policy)

    def array_iterator_v1(self, value: object, indexed: bool = False):
        """Use the actual array, including size changes, within the loop budget."""
        from pinelib.reference.array import array_get, array_size

        self._check()
        if not isinstance(value, ReferenceHandle) or value.kind != "array":
            raise PineRuntimeError(
                "for-in requires an initialized array", code=PL_REFERENCE_TYPE
            )
        index = 0
        while index < array_size(self.references, value):
            self._check()
            if index >= self.session.policies.resource.max_loop_iterations:
                raise PineRuntimeError(
                    "loop iteration budget exceeded", code=PL_RESOURCE_LIMIT
                )
            item = array_get(self.references, value, index)
            yield (index, item) if indexed else item
            index += 1
