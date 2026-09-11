"""Versioned compiler services over the existing transaction/slot/series model.

Written function calls own scopes; loop iterations do not create new callsites.
No separate interpreter, global mutable cache, or parallel checkpoint format.
"""

from __future__ import annotations

from pinelib.core.values import is_na, na, pine_bool
from pinelib.errors import PL_RESOURCE_LIMIT, PL_VALUE_TYPE, PineRuntimeError
from pinelib.state.checkpoint import sha


class LanguageExecutionMixin:
    def scoped_id_v1(self, source_id: str, *, local: bool = False) -> str:
        self._check()
        if type(source_id) is not str or not source_id:
            raise PineRuntimeError(
                "source state identity must be nonempty text", code=PL_VALUE_TYPE
            )
        path = self._function_path
        if not path and not local:
            return source_id
        return "lexical:" + sha({"path": list(path), "source": source_id})

    def invoke_function_v1(self, callsite: str, function, arguments: dict):
        self._check()
        if not callable(function) or not isinstance(arguments, dict):
            raise PineRuntimeError(
                "invalid compiled function invocation", code=PL_VALUE_TYPE
            )
        if type(callsite) is not str or not callsite:
            raise PineRuntimeError("function callsite is missing", code=PL_VALUE_TYPE)
        # Recursive Pine calls are rejected by the frontend; bound native misuse
        # as well, without relying on the Python recursion limit.
        if len(self._function_path) >= 64:
            raise PineRuntimeError(
                "compiled function call depth exceeded", code=PL_RESOURCE_LIMIT
            )
        prior = self._function_path
        self._function_path = (*prior, callsite)
        try:
            return function(**arguments)
        finally:
            self._function_path = prior

    def condition_v1(self, value: object) -> bool:
        self._check()
        if value is None or is_na(value):
            if self.session.language.pine_version >= 6:
                raise PineRuntimeError(
                    "bool cannot be na in Pine v6", code=PL_VALUE_TYPE
                )
            return False
        if type(value) not in (bool, int, float):
            raise PineRuntimeError(
                "condition requires bool or legacy numeric value", code=PL_VALUE_TYPE
            )
        result = pine_bool(value, self.session.language)
        return False if result is na else result

    def once_v1(self, state_id: str, condition) -> bool:
        self._check()
        if self.session.language.pine_version != 6:
            raise PineRuntimeError("once requires Pine v6", code=PL_VALUE_TYPE)
        key = self.scoped_id_v1("once:" + state_id, local=True)
        done = self.state(
            key, owner="ast2python.once.v1", schema_version="1", initial=False
        )
        if done:
            return False
        # Do not even evaluate the predicate after committed completion.
        if not self.condition_v1(condition()):
            return False
        self.set_slot(key, True, owner="ast2python.once.v1")
        return True

    def range_v1(self, start: int, end, step: int = 1):
        self._check()
        stop = end()
        if is_na(start) or is_na(stop) or is_na(step):
            return
        if (
            type(start) is not int
            or type(stop) is not int
            or type(step) is not int
            or step <= 0
        ):
            raise PineRuntimeError(
                "Pine range requires int boundaries and positive step",
                code=PL_VALUE_TYPE,
            )
        direction = 1 if start <= stop else -1
        current = start
        iterations = 0
        while current <= stop if direction == 1 else current >= stop:
            self._check()
            iterations += 1
            if iterations > self.session.policies.resource.max_loop_iterations:
                raise PineRuntimeError(
                    "loop iteration budget exceeded", code=PL_RESOURCE_LIMIT
                )
            yield current
            current += direction * step
            if self.session.language.pine_version >= 6:
                stop = end()
                if is_na(stop):
                    return
                if type(stop) is not int:
                    raise PineRuntimeError(
                        "dynamic range boundary must remain int", code=PL_VALUE_TYPE
                    )

    def history_value_v1(self, source_id: str, value: object, offset: int, dtype: str):
        key = self.scoped_id_v1("expression-history:" + source_id, local=True)
        self.set_series(key, value, dtype, history_policy="on_evaluation")
        return self.op_series_history(key, offset)

    def reference_id_v1(self, source_id: str) -> str:
        """A constructor occurrence is distinct from its persistent written callsite."""
        self._check()
        key = self.scoped_id_v1(source_id)
        while True:
            count = getattr(self, "_reference_occurrences", 0)
            self._reference_occurrences = count + 1
            identity = "allocation:" + sha(
                {"source": key, "callback": self.frame.sequence, "occurrence": count}
            )
            # An aborted intrabar callback may retain varip objects. Retrying
            # that callback must not reuse their identities, while rolled-back
            # ordinary allocations keep their deterministic replay identities.
            if not self.references.contains(identity):
                return identity

    def _check_reference_binding(self, value: object, dtype: str) -> object:
        from pinelib.errors import PL_REFERENCE_TYPE
        from pinelib.reference.heap import ReferenceHandle

        if not isinstance(dtype, str) or not dtype.startswith(
            ("array<", "matrix<", "map<", "udt:")
        ):
            raise PineRuntimeError(
                "unsupported reference binding type", code=PL_REFERENCE_TYPE
            )
        from pinelib.reference.nominal import validate_field_type
        validate_field_type(dtype, self.session.language.pine_version, self.session.nominal_registry)
        if is_na(value):
            return na
        if isinstance(value, dict) and set(value) == {"$pinelib_ref"}:
            marker = value["$pinelib_ref"]
            if (
                not isinstance(marker, dict)
                or set(marker) != {"object_id", "kind"}
                or any(type(v) is not str for v in marker.values())
            ):
                raise PineRuntimeError(
                    "malformed typed reference marker", code=PL_REFERENCE_TYPE
                )
            value = ReferenceHandle(marker["object_id"], marker["kind"])
        kind = "udt" if dtype.startswith("udt:") else dtype.split("<", 1)[0]
        if not isinstance(value, ReferenceHandle) or value.kind != kind:
            raise PineRuntimeError(
                "reference binding kind differs from declared type",
                code=PL_REFERENCE_TYPE,
            )
        actual = self.references.normalized_type_descriptor(value)
        if actual != dtype:
            raise PineRuntimeError(
                "reference binding type differs from heap object",
                code=PL_REFERENCE_TYPE,
            )
        return value

    def declare_reference_v1(
        self,
        series_id: str,
        mode: str,
        initializer,
        dtype: str,
        *,
        history_policy: str = "each_bar",
    ) -> object:
        """Store typed handles in the established slots/series and transactional heap."""
        self._check()
        if mode not in {"default", "var", "varip"}:
            raise PineRuntimeError("unsupported reference declaration mode", code=PL_VALUE_TYPE)
        from pinelib.reference.nominal import validate_field_type
        validate_field_type(dtype, self.session.language.pine_version, self.session.nominal_registry)
        if mode == "varip":
            self._validate_varip_binding_type(dtype)
        if mode == "default":
            value = self._check_reference_binding(initializer(), dtype)
        else:
            key = "reference-binding:" + series_id
            if not self.session.slots.contains(key):
                value = self._check_reference_binding(initializer(), dtype)
                if mode == "varip" and not is_na(value):
                    self.references.retain_intrabar(value)
                self.set_slot(key, value, owner="ast2python.reference.v1", varip=mode == "varip")
            value = self.state(
                key, owner="ast2python.reference.v1", schema_version="1", initial=na,
                varip=mode == "varip",
            )
            value = self._check_reference_binding(value, dtype)
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
        if mode not in {"default", "var", "varip"}:
            raise PineRuntimeError("unsupported reference declaration mode", code=PL_VALUE_TYPE)
        if mode == "varip":
            self._validate_varip_binding_type(dtype)
        value = self._check_reference_binding(value, dtype)
        if mode == "varip" and not is_na(value):
            self.references.retain_intrabar(value)
        if mode != "default":
            self.set_slot(
                "reference-binding:" + series_id, value, owner="ast2python.reference.v1", varip=mode == "varip"
            )
        self.set_series(series_id, value, dtype, history_policy=history_policy)

    def _validate_varip_binding_type(self, dtype):
        if type(dtype) is str and dtype.startswith("udt:"):
            from pinelib.reference.nominal import nominal_type
            nominal_type(dtype, "udt", self.session.language.pine_version)
        else:
            from pinelib.reference.persistence import validate_varip_type
            validate_varip_type(dtype.split("<", 1)[0], dtype, self.session.language.pine_version,
                                nominal_registry=self.session.nominal_registry)

    def new_udt_v1(self, object_id, dtype, fields, *, varip_fields=(), field_types=None):
        self._check()
        from pinelib.reference.udt import udt_new_typed
        return udt_new_typed(self.references, object_id, dtype, fields, field_types, varip_fields)

    def get_udt_field_v1(self, handle, field):
        self._check()
        from pinelib.reference.udt import udt_get
        return udt_get(self.references, handle, field)

    def set_udt_field_v1(self, handle, field, value):
        self._check()
        from pinelib.reference.udt import udt_set
        return udt_set(self.references, handle, field, value)

    def copy_udt_v1(self, handle, new_object_id):
        self._check()
        from pinelib.reference.udt import udt_copy
        return udt_copy(self.references, handle, new_object_id)

    def enum_value_v1(self, dtype, member, ordinal):
        self._check()
        from pinelib.reference.heap import PineEnumValue
        return self.enum_coerce_v1(PineEnumValue(dtype, member, ordinal), dtype)

    def enum_coerce_v1(self, value, dtype):
        self._check()
        from pinelib.reference.nominal import enum_coerce
        return enum_coerce(value, dtype, self.session.language.pine_version, self.session.nominal_registry)

    def declare_enum_v1(self, series_id, mode, initializer, dtype, *, history_policy="each_bar"):
        self._check()
        if mode not in {"default", "var", "varip"}:
            raise PineRuntimeError("unsupported enum declaration mode", code=PL_VALUE_TYPE)
        from pinelib.reference.nominal import nominal_type, require_registry
        nominal_type(dtype, "enum", self.session.language.pine_version)
        require_registry(self.session.nominal_registry, dtype, "enum")
        key = "enum-binding:" + series_id
        if mode == "default":
            value = self.enum_coerce_v1(initializer(), dtype)
        else:
            if not self.session.slots.contains(key):
                self.set_slot(key, self.enum_coerce_v1(initializer(), dtype), owner="ast2python.enum.v1", varip=mode == "varip")
            value = self.enum_coerce_v1(self.state(key, owner="ast2python.enum.v1", schema_version="1", initial=na, varip=mode == "varip"), dtype)
        self.set_series(series_id, value, dtype, history_policy=history_policy)
        return value

    def write_enum_v1(self, series_id, mode, value, dtype, *, history_policy="each_bar"):
        self._check()
        if mode not in {"default", "var", "varip"}:
            raise PineRuntimeError("unsupported enum declaration mode", code=PL_VALUE_TYPE)
        value = self.enum_coerce_v1(value, dtype)
        if mode != "default":
            self.set_slot("enum-binding:" + series_id, value, owner="ast2python.enum.v1", varip=mode == "varip")
        self.set_series(series_id, value, dtype, history_policy=history_policy)

    def consume_loop_iteration_v1(self):
        """One shared callback budget also bounds nested while/for-in loops."""
        self._check()
        from pinelib.errors import PL_RESOURCE_LIMIT, PineRuntimeError

        count = getattr(self, "_loop_iterations", 0) + 1
        if count > self.session.policies.resource.max_loop_iterations:
            raise PineRuntimeError(
                "callback loop iteration budget exceeded", code=PL_RESOURCE_LIMIT
            )
        self._loop_iterations = count

    def iter_array_v1(self, handle, *, indexed=False):
        """Read the live array in index order without aliasing its Python payload."""
        from pinelib.reference.array import array_get, array_size

        self._check()
        index = 0
        while index < array_size(self.references, handle):
            value = array_get(self.references, handle, index)
            yield (index, value) if indexed else value
            index += 1


    def iter_map_v1(self, handle):
        self._check()
        if self.session.language.pine_version < 5:
            raise PineRuntimeError("map iteration requires Pine v5/v6", code=PL_VALUE_TYPE)
        return self.references.map_iteration(handle)

    def iter_matrix_v1(self, handle, source_id, *, indexed=False):
        """Retrieve current rows as independent arrays; retain element references."""
        self._check()
        if self.session.language.pine_version < 5:
            raise PineRuntimeError("matrix iteration requires Pine v5/v6", code=PL_VALUE_TYPE)
        index = 0
        dtype = self.references.type_descriptor(handle)
        if dtype.startswith("matrix<") and dtype.endswith(">"):
            dtype = dtype[len("matrix<"):-1]
        while index < self.references.matrix_dimensions(handle)[0]:
            self._check()
            values = self.references.read_matrix_row(handle, index)
            row = self.references.create(self.reference_id_v1(source_id), "array", dtype, values)
            yield (index, row) if indexed else row
            index += 1
