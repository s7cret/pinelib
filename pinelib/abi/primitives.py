from __future__ import annotations

from pinelib.runtime.session import RuntimeTransaction


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
    from pinelib.core.values import is_na
    from pinelib.errors import PL_VALUE_TYPE, PineRuntimeError
    tx._check()
    if tx.session.language.pine_version >= 6 and type(x) is bool:
        raise PineRuntimeError("na does not accept bool in Pine v6", code=PL_VALUE_TYPE)
    return is_na(x)
