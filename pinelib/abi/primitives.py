from __future__ import annotations

from pinelib.runtime.session import RuntimeTransaction
from pinelib.core.values import NZ_OMITTED


def float_v1(x: object) -> object:
    from pinelib.core.values import pine_float

    return pine_float(x)


def bool_v1(tx: RuntimeTransaction, value: object) -> object:
    from pinelib.core.values import pine_bool_cast

    tx._check()
    return pine_bool_cast(value, tx.session.language)


def int_v1(value: object) -> object:
    from pinelib.core.values import pine_int

    return pine_int(value)


def operator_binary_v1(
    tx: RuntimeTransaction, operator: str, left: object, right: object
) -> object:
    return tx.op_operator_binary(operator, left, right)


def operator_div_legacy_v1(
    tx: RuntimeTransaction, operator: str, left: object, right: object
) -> object:
    return _div_opcode(tx, operator, left, right, truncate=True)


def operator_div_fractional_v1(
    tx: RuntimeTransaction, operator: str, left: object, right: object
) -> object:
    return _div_opcode(tx, operator, left, right, truncate=False)


def _div_opcode(
    tx: RuntimeTransaction,
    operator: str,
    left: object,
    right: object,
    *,
    truncate: bool,
) -> object:
    from pinelib.core.values import na, normalize_na, pine_div, pine_div_int_truncate
    from pinelib.errors import PineRuntimeError

    tx._check()
    if operator != "/":
        raise PineRuntimeError("invalid division operator")
    left = normalize_na(left)
    right = normalize_na(right)
    if left is na or right is na:
        return na
    if truncate and type(left) is int and type(right) is int:
        return pine_div_int_truncate(left, right)
    return pine_div(left, right, tx.session.language)


def operator_unary_v1(tx: RuntimeTransaction, operator: str, operand: object) -> object:
    return tx.op_operator_unary(operator, operand)


def series_history_v1(tx: RuntimeTransaction, base: object, offset: object) -> object:
    return tx.op_series_history(base, offset)


def na_v1(tx: RuntimeTransaction, x: object) -> bool:
    """Version-aware missing-value predicate, including flat broker values."""
    from pinelib.core.values import is_na
    from pinelib.errors import PL_VALUE_TYPE, PineRuntimeError

    tx._check()
    if tx.session.language.pine_version >= 6 and type(x) is bool:
        raise PineRuntimeError("na does not accept bool in Pine v6", code=PL_VALUE_TYPE)
    if x is None:
        raise PineRuntimeError("transport null is not Pine na", code=PL_VALUE_TYPE)
    return is_na(x)


def once_v1(tx: RuntimeTransaction, state_id: str, condition):
    return tx.once_v1(state_id, condition)


def range_v1(tx: RuntimeTransaction, start, end, step):
    return tx.range_v1(start, end, step)


def range_fixed_end_v1(tx: RuntimeTransaction, start, end, step):
    return tx.range_policy_v1(start, end, step, dynamic=False)


def range_dynamic_end_v1(tx: RuntimeTransaction, start, end, step):
    return tx.range_policy_v1(start, end, step, dynamic=True)


def invoke_function_v1(tx: RuntimeTransaction, callsite: str, function, arguments):
    return tx.invoke_function_v1(callsite, function, arguments)


def logical_eager_v1(tx: RuntimeTransaction, operator: str, left, right):
    # Inputs have both been evaluated before this call, including legacy na.
    a, b = tx.condition_v1(left), tx.condition_v1(right)
    if operator == "and":
        return a and b
    if operator == "or":
        return a or b
    from pinelib.errors import PineRuntimeError

    raise PineRuntimeError("invalid logical operator")


def logical_lazy_v1(tx: RuntimeTransaction, operator: str, left, right):
    a = tx.condition_v1(left)
    if operator == "and":
        return a and tx.condition_v1(right())
    if operator == "or":
        return a or tx.condition_v1(right())
    from pinelib.errors import PineRuntimeError

    raise PineRuntimeError("invalid logical operator")


def nz_v1(
    tx: RuntimeTransaction,
    source: object,
    expression_type: str,
    replacement: object = NZ_OMITTED,
) -> object:
    from pinelib.core.values import pine_nz

    tx._check()
    return pine_nz(
        source, replacement, result_type=expression_type, ctx=tx.session.language
    )
