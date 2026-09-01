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
