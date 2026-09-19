from __future__ import annotations

import math
import re
from enum import Enum as _Enum
from typing import TypeGuard, cast

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


def pine_float(value: object) -> float | _NA:
    """Explicit Pine numeric cast, sharing the canonical numeric/NA boundary."""
    if is_na(value):
        return na
    number = require_number(value, name="x")
    try:
        return float(number)
    except OverflowError as error:
        raise PineRuntimeError(
            "float conversion exceeds the finite numeric domain", code=PL_VALUE_DOMAIN
        ) from error


def pine_bool(value: object, ctx: RuntimeLanguageContext) -> bool | _NA:
    """Implicit Pine condition coercion. Never falls back to Python truthiness."""
    if value is None:
        raise PineRuntimeError("transport null is not Pine na", code=PL_VALUE_TYPE)
    if value is na:
        if ctx.pine_version <= 5:
            return na
        raise PineRuntimeError("bool cannot be na in Pine v6", code=PL_VALUE_BOOL)
    if type(value) is bool:
        return value
    if is_number(value):
        if ctx.pine_version <= 5:
            return value != 0
        raise PineRuntimeError(
            "implicit numeric-to-bool is forbidden in Pine v6",
            code=PL_VALUE_BOOL,
        )
    raise PineRuntimeError(
        "value cannot be implicitly converted to Pine bool",
        code=PL_VALUE_BOOL,
        details={"actual_type": type(value).__name__},
    )


def pine_bool_cast(value: object, ctx: RuntimeLanguageContext) -> bool | _NA:
    """Explicit Pine ``bool()`` cast, version-exact for bool-na semantics."""
    if value is None:
        raise PineRuntimeError("transport null is not Pine na", code=PL_VALUE_TYPE)
    if value is na:
        return na if ctx.pine_version <= 5 else False
    if type(value) is bool:
        return value
    if is_number(value):
        return value != 0
    raise PineRuntimeError(
        "bool() accepts only numeric, bool, or na values",
        code=PL_VALUE_TYPE,
        details={"actual_type": type(value).__name__},
    )


def pine_int(value: object) -> int | _NA:
    """Explicit Pine ``int()`` cast. Float conversion truncates toward zero."""
    if value is None:
        raise PineRuntimeError("transport null is not Pine na", code=PL_VALUE_TYPE)
    if value is na:
        return na
    if type(value) is int:
        return value
    if type(value) is float:
        number = require_number(value, name="value")
        return int(number)
    raise PineRuntimeError(
        "int() accepts only int, float, or na values",
        code=PL_VALUE_TYPE,
        details={"actual_type": type(value).__name__},
    )


def pine_div_int_truncate(left: int, right: int) -> int:
    if right == 0:
        raise PineRuntimeError("division by zero", code=PL_VALUE_DIVISION)
    quotient = abs(left) // abs(right)
    return -quotient if (left < 0) != (right < 0) else quotient


def pine_div_const_int(
    left: int, right: int, ctx: RuntimeLanguageContext
) -> int | float:
    if ctx.pine_version <= 5:
        return pine_div_int_truncate(left, right)
    if right == 0:
        raise PineRuntimeError("division by zero", code=PL_VALUE_DIVISION)
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


def pine_mod(left: object, right: object) -> object:
    """Pine modulo uses a floor quotient, shared by script and input evaluators.

    Keep integer operands in the integer domain; using float division loses
    low bits above 2**53. Python % implements the documented floor rule for
    both integer and finite floating-point operands.
    """
    if left is na or right is na:
        return na
    left_number = require_number(left, name="left")
    right_number = require_number(right, name="right")
    if right_number == 0:
        raise PineRuntimeError("modulo by zero", code=PL_VALUE_DIVISION)
    return left_number % right_number


def normalize_na(value: object) -> object:
    """Return Pine values unchanged; transport ``None`` is never a Pine ``na`` marker."""

    return value


def _reject_transport_null(*values: object) -> None:
    if any(value is None for value in values):
        raise PineRuntimeError("transport null is not Pine na", code=PL_VALUE_TYPE)


def pine_binary(
    operator: str, left: object, right: object, ctx: RuntimeLanguageContext
) -> object:
    """Evaluate one declared Pine binary operator without name-based dispatch."""

    left = normalize_na(left)
    right = normalize_na(right)
    _reject_transport_null(left, right)
    from pinelib.reference.heap import PineEnumValue

    if isinstance(left, PineEnumValue) or isinstance(right, PineEnumValue):
        if ctx.pine_version < 5:
            raise PineRuntimeError("enum values require Pine v5/v6", code=PL_VALUE_TYPE)
        if operator not in {"==", "!="} or (
            left is not na
            and right is not na
            and (
                not isinstance(left, PineEnumValue)
                or not isinstance(right, PineEnumValue)
                or left.enum_id != right.enum_id
            )
        ):
            raise PineRuntimeError(
                "enum operands require matching nominal types and equality operators",
                code=PL_VALUE_TYPE,
            )
        if left is na or right is na:
            return na if ctx.pine_version < 6 else False
    if ctx.pine_version == 6 and operator in {"==", "!=", "<", "<=", ">", ">="}:
        if left is na or right is na:
            return False
        if (
            is_number(left)
            and is_number(right)
            and (type(left) is float or type(right) is float)
        ):
            # Mixed numeric comparisons first enter the float domain. Pine v6
            # specifies nine fractional digits; its midpoint tie policy is not
            # established here. Use Python's binary-float round policy locally.
            left = round(cast(float, pine_float(left)), 9)
            right = round(cast(float, pine_float(right)), 9)
    if operator in {"==", "!="}:
        if left is na or right is na:
            equal = False
        elif (type(left) is bool) != (type(right) is bool):
            # Python treats bool as an int subclass (False == 0), Pine does not.
            equal = False
        else:
            equal = left == right
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
            return pine_mod(left_number, right_number)
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
    _reject_transport_null(operand)
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


class _NzOmission(str, _Enum):
    OMITTED = "__pinelib_nz_omitted__"


NZ_OMITTED = _NzOmission.OMITTED


def pine_nz(
    source: object,
    replacement: object,
    *,
    result_type: str,
    ctx: RuntimeLanguageContext,
) -> object:
    """Typed nz: omission is distinct from explicit Pine NA and transport null."""
    allowed = {"int", "float", "color"} | ({"bool"} if ctx.pine_version <= 5 else set())
    if result_type not in allowed:
        raise PineRuntimeError(
            "nz requires a supported scalar overload", code=PL_VALUE_TYPE
        )

    def check(value: object) -> None:
        if is_na(value):
            return
        if result_type == "float":
            require_number(value, name="nz argument")
            return
        valid = (
            type(value) is int
            if result_type == "int"
            else (
                type(value) is bool
                if result_type == "bool"
                else isinstance(value, str)
                and re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value)
                is not None
            )
        )
        if not valid:
            raise PineRuntimeError(
                "nz value does not match its admitted overload", code=PL_VALUE_TYPE
            )

    check(source)
    if replacement is NZ_OMITTED:
        replacement = {"int": 0, "float": 0.0, "bool": False, "color": "#00000000"}[
            result_type
        ]
    check(replacement)
    value = replacement if is_na(source) else source
    return float(value) if result_type == "float" and not is_na(value) else value
