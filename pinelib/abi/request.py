from __future__ import annotations

from pinelib.reference import ReferenceHandle
from pinelib.reference.array import array_new, array_push
from pinelib.request import RequestExpression, RequestQuery, ResultShape
from pinelib.runtime.session import RuntimeTransaction


def security_v1(
    transaction: RuntimeTransaction,
    query: RequestQuery,
    expression: RequestExpression,
    result_shape: ResultShape,
    chart_open_ms: int,
    chart_close_ms: int,
    ignore_invalid_symbol: bool = False,
) -> object:
    return transaction.requests.security(
        query,
        expression,
        result_shape,
        chart_open_ms=chart_open_ms,
        chart_close_ms=chart_close_ms,
        ignore_invalid_symbol=ignore_invalid_symbol,
    )


def security_lower_tf_v1(
    transaction: RuntimeTransaction,
    query: RequestQuery,
    expression: RequestExpression,
    result_shape: ResultShape,
    chart_open_ms: int,
    chart_close_ms: int,
    array_object_id: str,
    ignore_invalid_symbol: bool = False,
) -> ReferenceHandle:
    values = transaction.requests.security_lower_tf(
        query,
        expression,
        result_shape,
        chart_open_ms=chart_open_ms,
        chart_close_ms=chart_close_ms,
        ignore_invalid_symbol=ignore_invalid_symbol,
    )
    handle = array_new(
        transaction.references,
        array_object_id,
        f"array<{result_shape.type_name}>",
    )
    for value in values:
        array_push(transaction.references, handle, value)
    return handle
