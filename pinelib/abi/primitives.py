from __future__ import annotations

from pinelib.runtime.session import RuntimeTransaction


def float_v1(x: object) -> object:
    from pinelib.core.values import pine_float

    return pine_float(x)


def operator_binary_v1(
    tx: RuntimeTransaction, operator: str, left: object, right: object
) -> object:
    return tx.op_operator_binary(operator, left, right)


def operator_unary_v1(tx: RuntimeTransaction, operator: str, operand: object) -> object:
    return tx.op_operator_unary(operator, operand)


def series_history_v1(tx: RuntimeTransaction, base: object, offset: object) -> object:
    return tx.op_series_history(base, offset)


def na_v1(tx: RuntimeTransaction, x: object) -> bool:
    """Version-aware missing-value predicate, including flat broker values."""
    from pinelib.core.values import is_na, normalize_na
    from pinelib.errors import PL_VALUE_TYPE, PineRuntimeError

    tx._check()
    if tx.session.language.pine_version >= 6 and type(x) is bool:
        raise PineRuntimeError("na does not accept bool in Pine v6", code=PL_VALUE_TYPE)
    return is_na(normalize_na(x))


def once_v1(tx: RuntimeTransaction, state_id: str, condition):
    return tx.once_v1(state_id, condition)


def range_v1(tx: RuntimeTransaction, start, end, step):
    return tx.range_v1(start, end, step)


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
