from __future__ import annotations

import math
from typing import TypeGuard

from pinelib.errors import (
    PL_VALUE_BOOL,
    PL_VALUE_DIVISION,
    PL_VALUE_DOMAIN,
    PL_VALUE_TYPE,
    PineRuntimeError,
)
from pinelib.runtime.context import RuntimeLanguageContext


class _NA:
    __slots__ = ()

    def __repr__(self) -> str:
        return "na"

    def __copy__(self) -> _NA:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> _NA:
        del memo
        return self


na = _NA()
PineNumber = int | float


def is_na(value: object) -> TypeGuard[_NA]:
    return value is na


def is_number(value: object) -> TypeGuard[PineNumber]:
    return type(value) in (int, float)


def require_number(value: object, *, name: str = "value") -> PineNumber:
    if not is_number(value):
        raise PineRuntimeError(
            f"{name} must be a Pine int or float",
            code=PL_VALUE_TYPE,
            details={"argument": name, "actual_type": type(value).__name__},
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise PineRuntimeError(
            f"{name} must be finite",
            code=PL_VALUE_TYPE,
            details={"argument": name},
        )
    return value


def pine_bool(value: object, ctx: RuntimeLanguageContext) -> bool | _NA:
    if value is na:
        if ctx.pine_version <= 5:
            return na
        raise PineRuntimeError("bool cannot be na in Pine v6", code=PL_VALUE_BOOL)
    if isinstance(value, bool):
        return value
    if is_number(value):
        if ctx.pine_version <= 5:
            return bool(value)
        raise PineRuntimeError(
            "implicit numeric-to-bool is forbidden in Pine v6",
            code=PL_VALUE_BOOL,
        )
    return bool(value)


def pine_div_const_int(
    left: int, right: int, ctx: RuntimeLanguageContext
) -> int | float:
    if right == 0:
        raise PineRuntimeError("division by zero", code=PL_VALUE_DIVISION)
    if ctx.pine_version <= 5:
        return int(left / right)
    return left / right


def pine_div(left: object, right: object, ctx: RuntimeLanguageContext) -> object:
    del ctx
    if left is na or right is na:
        return na
    left_number = require_number(left, name="left")
    right_number = require_number(right, name="right")
    if right_number == 0:
        raise PineRuntimeError("division by zero", code=PL_VALUE_DIVISION)
    return left_number / right_number


def normalize_na(value: object) -> object:
    """Translate Ast2Python's Python literal sentinel to canonical Pine ``na``."""

    return na if value is None else value


def pine_binary(
    operator: str, left: object, right: object, ctx: RuntimeLanguageContext
) -> object:
    """Evaluate one declared Pine binary operator without name-based dispatch."""

    left = normalize_na(left)
    right = normalize_na(right)
    if operator in {"==", "!="}:
        equal = False if left is na or right is na else left == right
        return equal if operator == "==" else not equal
    if left is na or right is na:
        return False if operator in {"<", "<=", ">", ">="} else na
    if operator == "+" and isinstance(left, str) and isinstance(right, str):
        return left + right
    if operator == "/":
        if type(left) is int and type(right) is int and ctx.pine_version <= 5:
            return pine_div_const_int(left, right, ctx)
        return pine_div(left, right, ctx)
    if operator in {"+", "-", "*", "%", "<", "<=", ">", ">="}:
        left_number = require_number(left, name="left")
        right_number = require_number(right, name="right")
        if operator == "+":
            return left_number + right_number
        if operator == "-":
            return left_number - right_number
        if operator == "*":
            return left_number * right_number
        if operator == "%":
            if right_number == 0:
                raise PineRuntimeError("modulo by zero", code=PL_VALUE_DIVISION)
            if type(left_number) is int and type(right_number) is int:
                remainder = abs(left_number) % abs(right_number)
                return -remainder if left_number < 0 else remainder
            return math.fmod(left_number, right_number)
        if operator == "<":
            return left_number < right_number
        if operator == "<=":
            return left_number <= right_number
        if operator == ">":
            return left_number > right_number
        return left_number >= right_number
    raise PineRuntimeError(
        f"unsupported Pine binary operator: {operator}", code=PL_VALUE_DOMAIN
    )


def pine_unary(operator: str, operand: object, ctx: RuntimeLanguageContext) -> object:
    """Evaluate one declared Pine unary operator without a generic dispatcher."""

    operand = normalize_na(operand)
    if operator == "not":
        value = pine_bool(operand, ctx)
        return na if value is na else not value
    if operator in {"+", "-"}:
        if operand is na:
            return na
        number = require_number(operand, name="operand")
        return number if operator == "+" else -number
    raise PineRuntimeError(
        f"unsupported Pine unary operator: {operator}", code=PL_VALUE_DOMAIN
    )
