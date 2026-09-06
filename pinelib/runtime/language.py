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
