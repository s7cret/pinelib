"""Admit compiler-emitted input descriptors and one immutable set of overrides.

``active`` expressions are a small data AST emitted by Ast2Python. They are
validated and evaluated here; no Python ``eval`` or callback code is admitted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import cast

from pinelib.errors import PL_INPUT_INVALID, PineRuntimeError
from pinelib.core.values import pine_mod
from pinelib.input.registry import InputKind, InputSpec

_ALLOWED = {
    "input_id", "kind", "default", "title", "minimum", "maximum", "step",
    "options", "group", "inline", "confirm", "tooltip", "display", "active",
    "enum_type", "alias", "source_span",
}
_SOURCES = {"open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "hlcc4"}
_NUMERIC = {"int", "float", "time", "price"}


def _active_error(message: str) -> PineRuntimeError:
    return PineRuntimeError(message, code=PL_INPUT_INVALID)


def _enum_identity(value: object) -> tuple[str, str, int] | None:
    """Return a stable nominal enum identity for runtime or portable values."""
    from pinelib.reference.heap import PineEnumValue

    if isinstance(value, PineEnumValue):
        return value.enum_id, value.member, value.ordinal
    if isinstance(value, Mapping) and set(value) == {"$pinelib_enum"}:
        marker = value["$pinelib_enum"]
        if (
            isinstance(marker, Mapping)
            and set(marker) == {"enum_id", "member", "ordinal"}
            and isinstance(marker["enum_id"], str)
            and isinstance(marker["member"], str)
            and type(marker["ordinal"]) is int
        ):
            return marker["enum_id"], marker["member"], marker["ordinal"]
    return None


def _literal_kind(value: object) -> str:
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        if not math.isfinite(value):
            raise _active_error("active expression contains a nonfinite literal")
        return "float"
    if isinstance(value, str):
        return "string"
    enum = _enum_identity(value)
    if enum is not None:
        return "enum:" + enum[0]
    raise _active_error("active expression contains an unsupported literal")


def _numeric_result(left: str, right: str, *, division: bool = False) -> str | None:
    if left not in _NUMERIC or right not in _NUMERIC:
        return None
    return "float" if division or "float" in {left, right} or "price" in {left, right} else "int"


def _validate_active(node: object, rows: Mapping[str, Mapping[str, object]]) -> tuple[str, set[str]]:
    if type(node) is bool:
        return "bool", set()
    if not isinstance(node, Mapping) or not isinstance(node.get("op"), str):
        raise _active_error("invalid input active descriptor")
    op = cast(str, node["op"])
    if op == "literal" and set(node) == {"op", "value"}:
        return _literal_kind(node["value"]), set()
    if op == "input" and set(node) == {"op", "input_id"}:
        input_id = node["input_id"]
        if not isinstance(input_id, str) or input_id not in rows:
            raise _active_error("active expression references an unknown input")
        kind = cast(str, rows[input_id]["kind"])
        if kind == "enum":
            enum_type = rows[input_id].get("enum_type")
            if not isinstance(enum_type, str) or not enum_type:
                raise _active_error("active enum input lacks its nominal type")
            kind = "enum:" + enum_type
        return kind, {input_id}
    if op in {"not", "pos", "neg"} and set(node) == {"op", "arg"}:
        kind, dependencies = _validate_active(node["arg"], rows)
        if op == "not":
            if kind != "bool":
                raise _active_error("active 'not' operand must be bool")
            return "bool", dependencies
        if kind not in _NUMERIC:
            raise _active_error("active unary numeric operand must be numeric")
        return kind, dependencies
    if op in {"and", "or"} and set(node) == {"op", "left", "right"}:
        left_kind, left = _validate_active(node["left"], rows)
        right_kind, right = _validate_active(node["right"], rows)
        if left_kind != "bool" or right_kind != "bool":
            raise _active_error("active logical operands must be bool")
        return "bool", left | right
    if op in {"add", "sub", "mul", "div", "mod"} and set(node) == {"op", "left", "right"}:
        left_kind, left = _validate_active(node["left"], rows)
        right_kind, right = _validate_active(node["right"], rows)
        if op == "add" and left_kind == right_kind == "string":
            return "string", left | right
        result = _numeric_result(left_kind, right_kind, division=op == "div")
        if result is None:
            raise _active_error("active arithmetic operands must be compatible numeric values")
        return result, left | right
    if op in {"eq", "ne", "lt", "le", "gt", "ge"} and set(node) == {"op", "left", "right"}:
        left_kind, left = _validate_active(node["left"], rows)
        right_kind, right = _validate_active(node["right"], rows)
        numeric = left_kind in _NUMERIC and right_kind in _NUMERIC
        same = left_kind == right_kind
        if not (numeric or same):
            raise _active_error("active comparison operands have incompatible types")
        if op not in {"eq", "ne"} and not (numeric or left_kind == "string"):
            raise _active_error("active ordered comparison requires numeric or string operands")
        return "bool", left | right
    if op == "if" and set(node) == {"op", "condition", "then", "else"}:
        condition_kind, condition = _validate_active(node["condition"], rows)
        then_kind, then = _validate_active(node["then"], rows)
        else_kind, otherwise = _validate_active(node["else"], rows)
        if condition_kind != "bool":
            raise _active_error("active conditional condition must be bool")
        branch_kind = then_kind if then_kind == else_kind else _numeric_result(then_kind, else_kind)
        if branch_kind is None:
            raise _active_error("active conditional expression has incompatible branches")
        return branch_kind, condition | then | otherwise
    raise _active_error(f"unsupported input active operation: {op}")


def _enum_comparable(value: object) -> object:
    enum = _enum_identity(value)
    return ("$enum", *enum) if enum is not None else value


def _finite_result(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        raise _active_error("active expression produced a nonfinite value")
    return value


def _evaluate_active(node: object, values: Mapping[str, object]) -> object:
    if type(node) is bool:
        return node
    assert isinstance(node, Mapping)
    op = node["op"]
    if op == "literal":
        return node["value"]
    if op == "input":
        return values[cast(str, node["input_id"])]
    if op == "not":
        return not cast(bool, _evaluate_active(node["arg"], values))
    if op == "pos":
        return +cast(int | float, _evaluate_active(node["arg"], values))
    if op == "neg":
        return -cast(int | float, _evaluate_active(node["arg"], values))
    if op == "and":
        return cast(bool, _evaluate_active(node["left"], values)) and cast(
            bool, _evaluate_active(node["right"], values)
        )
    if op == "or":
        return cast(bool, _evaluate_active(node["left"], values)) or cast(
            bool, _evaluate_active(node["right"], values)
        )
    if op == "if":
        branch = "then" if cast(bool, _evaluate_active(node["condition"], values)) else "else"
        return _evaluate_active(node[branch], values)
    left = _evaluate_active(node["left"], values)
    right = _evaluate_active(node["right"], values)
    if op in {"add", "sub", "mul", "div", "mod"}:
        try:
            result = {
                "add": lambda: left + right,  # type: ignore[operator]
                "sub": lambda: left - right,  # type: ignore[operator]
                "mul": lambda: left * right,  # type: ignore[operator]
                "div": lambda: left / right,  # type: ignore[operator]
                "mod": lambda: pine_mod(left, right),
            }[cast(str, op)]()
        except (TypeError, ZeroDivisionError, OverflowError) as exc:
            raise _active_error("active arithmetic evaluation failed") from exc
        return _finite_result(result)
    left_compare = _enum_comparable(left)
    right_compare = _enum_comparable(right)
    return {
        "eq": lambda: left_compare == right_compare,
        "ne": lambda: left_compare != right_compare,
        "lt": lambda: left_compare < right_compare,
        "le": lambda: left_compare <= right_compare,
        "gt": lambda: left_compare > right_compare,
        "ge": lambda: left_compare >= right_compare,
    }[cast(str, op)]()


def _normalize_active(value: object) -> object:
    """Normalize the compact v1 input leaf anywhere in the expression tree."""
    if isinstance(value, Mapping) and set(value) == {"input_id"}:
        return {"op": "input", "input_id": value["input_id"]}
    if isinstance(value, Mapping):
        if set(value) == {"$pinelib_enum"}:
            return value
        return {key: _normalize_active(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_active(item) for item in value]
    return value

def admit_input_descriptors(
    descriptors: Mapping[str, object], overrides: Mapping[str, object] | None
) -> list[InputSpec]:
    if not isinstance(descriptors, Mapping) or (
        overrides is not None and not isinstance(overrides, Mapping)
    ):
        raise PineRuntimeError(
            "input descriptors and overrides must be mappings", code=PL_INPUT_INVALID
        )
    overrides = {} if overrides is None else dict(overrides)
    aliases: dict[str, list[str]] = {}
    normalized: dict[str, Mapping[str, object]] = {}
    for input_id, row in descriptors.items():
        if (
            not isinstance(input_id, str)
            or not isinstance(row, Mapping)
            or row.get("input_id") != input_id
        ):
            raise PineRuntimeError("malformed input descriptor identity", code=PL_INPUT_INVALID)
        if set(row) - _ALLOWED or not {"input_id", "kind", "default"} <= set(row):
            raise PineRuntimeError("malformed input descriptor fields", code=PL_INPUT_INVALID)
        kind = row.get("kind")
        if kind == "enum" and not isinstance(row.get("enum_type"), str):
            raise PineRuntimeError("enum input requires enum_type", code=PL_INPUT_INVALID)
        alias = row.get("alias")
        if alias is not None:
            if not isinstance(alias, str) or not alias:
                raise PineRuntimeError("invalid input variable alias", code=PL_INPUT_INVALID)
            aliases.setdefault(alias, []).append(input_id)
        for field in ("title", "group", "inline", "tooltip"):
            if field in row and not isinstance(row[field], str):
                raise PineRuntimeError(f"input {field} must be a string", code=PL_INPUT_INVALID)
        if "confirm" in row and type(row["confirm"]) is not bool:
            raise PineRuntimeError("input confirm must be boolean", code=PL_INPUT_INVALID)
        normalized[input_id] = row

    supplied: dict[str, object] = {}
    for key, value in overrides.items():
        if not isinstance(key, str):
            raise PineRuntimeError("input override keys must be strings", code=PL_INPUT_INVALID)
        if key in normalized:
            input_id = key
        elif len(aliases.get(key, [])) == 1:
            input_id = aliases[key][0]
        else:
            raise PineRuntimeError(
                f"unknown or ambiguous input override: {key}", code=PL_INPUT_INVALID
            )
        if input_id in supplied:
            raise PineRuntimeError(f"duplicate override for {input_id}", code=PL_INPUT_INVALID)
        supplied[input_id] = value

    values = {input_id: supplied.get(input_id, row["default"]) for input_id, row in normalized.items()}
    active_nodes: dict[str, object] = {}
    dependency_sets: dict[str, set[str]] = {}
    for input_id, row in normalized.items():
        if "active" not in row:
            continue
        node = _normalize_active(row["active"])
        kind, dependencies = _validate_active(node, normalized)
        if kind != "bool":
            raise _active_error("active expression must return bool")
        active_nodes[input_id] = node
        dependency_sets[input_id] = dependencies

    # Detect dependency cycles over full expression graphs, not only direct references.
    def visit(input_id: str, stack: tuple[str, ...]) -> None:
        if input_id in stack:
            raise _active_error("cyclic active input dependency")
        for dependency in dependency_sets.get(input_id, set()):
            visit(dependency, (*stack, input_id))

    for input_id in dependency_sets:
        visit(input_id, ())

    result: list[InputSpec] = []
    for input_id, row in normalized.items():
        kind = cast(InputKind, row["kind"])
        default = row["default"]
        value = values[input_id]
        if kind == "source" and (default not in _SOURCES or value not in _SOURCES):
            raise PineRuntimeError(
                "source input requires an admitted built-in series; external series are not connected",
                code=PL_INPUT_INVALID,
            )
        options = row.get("options", ())
        if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
            raise PineRuntimeError("input options must be an ordered sequence", code=PL_INPUT_INVALID)
        active_node = active_nodes.get(input_id)
        active_value = (
            cast(bool, _evaluate_active(active_node, values)) if active_node is not None else None
        )
        simple_dependency = None
        if isinstance(active_node, Mapping) and set(active_node) == {"op", "input_id"}:
            simple_dependency = cast(str, active_node["input_id"])
        result.append(
            InputSpec(
                input_id, kind, default, value,
                title=cast(str, row.get("title", row.get("alias", ""))),
                minimum=cast(int | float | None, row.get("minimum")),
                maximum=cast(int | float | None, row.get("maximum")),
                step=cast(int | float | None, row.get("step")),
                options=tuple(options), group=cast(str, row.get("group", "")),
                inline=cast(str, row.get("inline", "")),
                confirm=cast(bool, row.get("confirm", False)),
                tooltip=cast(str | None, row.get("tooltip")),
                display=cast(str | None, row.get("display")),
                active=active_value, active_input_id=simple_dependency,
                active_expression=cast(
                    Mapping[str, object] | None,
                    None if simple_dependency is not None else active_node
                    if isinstance(active_node, Mapping) else None,
                ),
                enum_type=cast(str | None, row.get("enum_type")),
            )
        )
    return result
