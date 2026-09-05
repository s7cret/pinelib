"""Compiler ABI for request expressions in independent historical contexts.

The compiler supplies generated methods, not source strings. RequestEngine owns
alignment, limits, caching and transactional/checkpoint state. This ABI does not
claim support for live revisions, nested request closures or currency conversion.
"""

from __future__ import annotations

from pinelib.core.values import is_na, na
from pinelib.errors import PL_REQUEST_DATA, PL_REQUEST_PROVIDER, PineRuntimeError
from pinelib.request import (
    GapsMode,
    LookaheadMode,
    RequestKind,
    ResultKind,
    ResultShape,
)
from pinelib.request.snapshots import SnapshotRequestProvider
from pinelib.runtime.metadata import BarValues, TimeframeContext
from pinelib.runtime.session import CallbackFrame, RuntimeSession, RuntimeTransaction
from pinelib.state.checkpoint import sha


class CompiledRequestExpression:
    def __init__(
        self,
        parent: RuntimeTransaction,
        script_type: type,
        method: str,
        expression_id: str,
        shape: ResultShape,
        dynamic: bool = False,
    ) -> None:
        self.parent, self.script_type, self.method = parent, script_type, method
        self.shape, self.dynamic = shape, dynamic
        self.expression_id = expression_id
        self.__pinelib_expression_identity__ = sha(
            {"expression": expression_id, "inputs": parent.session.inputs.identity()}
        )
        self.source = None
        self._context = None
        self._runtime = None
        self._script = None

    def __call__(self, bar, context):
        if context is not self._context:
            if self.source is None:
                raise PineRuntimeError(
                    "request expression source is unbound", code=PL_REQUEST_DATA
                )
            self._context = context
            self._runtime = RuntimeSession(
                self.parent.session.language,
                self.parent.session.policies,
                inputs=self.parent.session.inputs,
                instrument=self.source.instrument,
                timeframe=TimeframeContext.parse(self.source.timeframe),
            )
            self._runtime.commit_full_identity = False
            saved = context.state("compiled-runtime", None)
            if saved is not None:
                self._runtime.restore(saved)
            self._script = self.script_type(None)
        runtime = self._runtime
        # Canonical request bars use exclusive closes; Pine runtime uses inclusive ms.
        values = BarValues(
            **{
                key: bar.number(key)
                for key in ("open", "high", "low", "close", "volume")
            },
            time=bar.open_time_ms,
            time_close=bar.close_time_ms - 1,
        )
        index = runtime.sequence + 1
        tx = runtime.begin(
            CallbackFrame(
                "HISTORICAL_EVAL",
                index,
                bar_index=index,
                last_bar_index=context.last_bar_index,
                is_last_bar=context.is_last_bar,
            ),
            values=values,
        )
        self._script.runtime = tx
        try:
            value = getattr(self._script, self.method)()
            tx.commit()
        except BaseException:
            if not tx.closed:
                tx.abort()
            raise
        if context.is_last_bar:
            # Once per source snapshot, not once per bar (avoids quadratic copies).
            context.set_state("compiled-runtime", runtime.checkpoint().to_dict())
        return value


def _run(
    transaction,
    symbol,
    timeframe,
    expression,
    call_site_id,
    *,
    lower=False,
    gaps=None,
    lookahead=None,
    ignore_invalid_symbol=False,
    currency=None,
    ignore_invalid_timeframe=False,
    calc_bars_count=None,
):
    transaction._check()
    if transaction.frame.realtime:
        raise PineRuntimeError(
            "compiled immutable snapshots require historical execution; live revisions are not admitted",
            code=PL_REQUEST_DATA,
        )
    if (
        not isinstance(expression, CompiledRequestExpression)
        or expression.parent is not transaction
    ):
        raise PineRuntimeError(
            "request expression is not bound to this transaction", code=PL_REQUEST_DATA
        )
    if (
        type(ignore_invalid_symbol) is not bool
        or type(ignore_invalid_timeframe) is not bool
    ):
        raise PineRuntimeError(
            "request ignore flags must be bool", code=PL_REQUEST_DATA
        )
    if type(symbol) is not str or type(timeframe) is not str:
        raise PineRuntimeError(
            "request symbol/timeframe must be strings", code=PL_REQUEST_DATA
        )
    provider = transaction.requests.provider
    if not isinstance(provider, SnapshotRequestProvider):
        raise PineRuntimeError(
            "compiled requests require an admitted snapshot provider",
            code=PL_REQUEST_PROVIDER,
        )
    session = transaction.session
    if session.instrument is None or session.timeframe is None:
        raise PineRuntimeError(
            "chart metadata is required for requests", code=PL_REQUEST_DATA
        )
    symbol = symbol or session.instrument.tickerid
    timeframe = timeframe or session.timeframe.period
    requested = TimeframeContext.parse(timeframe)
    if lower:
        if requested.seconds is None or session.timeframe.seconds is None:
            raise PineRuntimeError(
                "lower timeframe requests need fixed-duration intervals",
                code=PL_REQUEST_DATA,
            )
        if requested.seconds > session.timeframe.seconds:
            if ignore_invalid_timeframe:
                return na
            raise PineRuntimeError(
                "requested lower timeframe exceeds chart timeframe",
                code=PL_REQUEST_DATA,
            )
    source = provider.source(symbol, timeframe)
    expression.source = source
    version = session.language.pine_version
    if version <= 2 and type(gaps) is bool:
        gaps = GapsMode.ON if gaps else GapsMode.OFF
    try:
        gaps_mode = (
            GapsMode.OFF
            if gaps is None
            else GapsMode(str(gaps).removeprefix("barmerge."))
        )
        lookahead_mode = (
            (LookaheadMode.ON if version <= 2 else LookaheadMode.OFF)
            if lookahead is None
            else LookaheadMode(str(lookahead).removeprefix("barmerge."))
        )
    except ValueError as exc:
        raise PineRuntimeError(
            "unknown gaps/lookahead mode", code=PL_REQUEST_DATA
        ) from exc
    query = provider.query(
        source,
        kind=RequestKind.SECURITY_LOWER_TF if lower else RequestKind.SECURITY,
        expression_id=expression.expression_id,
        call_site_id=call_site_id,
        currency=currency,
        gaps=gaps_mode,
        lookahead=lookahead_mode,
        calc_bars_count=calc_bars_count,
        pine_version=version,
        dynamic=expression.dynamic,
    )
    method = (
        transaction.requests.security_lower_tf
        if lower
        else transaction.requests.security
    )
    return method(
        query,
        expression,
        expression.shape,
        chart_open_ms=transaction.value_time,
        chart_close_ms=transaction.value_time_close + 1,
        ignore_invalid_symbol=ignore_invalid_symbol,
    )


def security_v1(
    transaction: RuntimeTransaction,
    symbol: str,
    timeframe: str,
    expression: CompiledRequestExpression,
    call_site_id: str,
    gaps: object = None,
    lookahead: object = None,
    ignore_invalid_symbol: bool = False,
    currency: str | None = None,
    calc_bars_count: int | None = None,
) -> object:
    value = _run(
        transaction,
        symbol,
        timeframe,
        expression,
        call_site_id,
        gaps=gaps,
        lookahead=lookahead,
        ignore_invalid_symbol=ignore_invalid_symbol,
        currency=currency,
        calc_bars_count=calc_bars_count,
    )

    def normalize(item, shape):
        if shape.kind == ResultKind.TUPLE:
            items = (na,) * len(shape.items) if is_na(item) else item
            return tuple(
                normalize(child, child_shape)
                for child, child_shape in zip(items, shape.items, strict=True)
            )
        return (
            False
            if is_na(item)
            and shape.type_name == "bool"
            and transaction.session.language.pine_version >= 6
            else item
        )

    return normalize(value, expression.shape)


def security_lower_tf_v1(
    transaction: RuntimeTransaction,
    symbol: str,
    timeframe: str,
    expression: CompiledRequestExpression,
    call_site_id: str,
    ignore_invalid_symbol: bool = False,
    currency: str | None = None,
    ignore_invalid_timeframe: bool = False,
    calc_bars_count: int | None = None,
) -> object:
    values = _run(
        transaction,
        symbol,
        timeframe,
        expression,
        call_site_id,
        lower=True,
        ignore_invalid_symbol=ignore_invalid_symbol,
        currency=currency,
        ignore_invalid_timeframe=ignore_invalid_timeframe,
        calc_bars_count=calc_bars_count,
    )
    shapes = (
        expression.shape.items
        if expression.shape.kind == ResultKind.TUPLE
        else (expression.shape,)
    )
    if is_na(values):
        return (
            tuple(na for _ in shapes)
            if expression.shape.kind == ResultKind.TUPLE
            else na
        )
    # Allocation identity includes callback and occurrence. Later requests must
    # not mutate historical arrays or alias repeated same-callback invocations.
    occurrence = transaction._request_allocations
    transaction._request_allocations += 1
    handles = []
    for index, shape in enumerate(shapes):
        payload = [
            row[index] if expression.shape.kind == ResultKind.TUPLE else row
            for row in values
        ]
        handles.append(
            transaction.references.create(
                f"{call_site_id}:lower:{transaction.frame.sequence}:{occurrence}:{index}",
                "array",
                f"array<{shape.type_name}>",
                payload,
            )
        )
    return tuple(handles) if expression.shape.kind == ResultKind.TUPLE else handles[0]


def gaps_off_v1() -> str:
    return "barmerge.gaps_off"


def gaps_on_v1() -> str:
    return "barmerge.gaps_on"


def lookahead_off_v1() -> str:
    return "barmerge.lookahead_off"


def lookahead_on_v1() -> str:
    return "barmerge.lookahead_on"
