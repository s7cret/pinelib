from __future__ import annotations

from pinelib.abi.models import CatalogRow, TargetStatus

ALL_VERSIONS = (1, 2, 3, 4, 5, 6)
PRE_NAMESPACE = (1, 2, 3, 4)
NAMESPACE = (5, 6)


def _row(
    symbol: str,
    callable_path: str | None,
    *,
    versions: tuple[int, ...],
    status: TargetStatus,
    return_type: str = "object",
    call_form: str = "namespace_function",
    state_model: str = "PURE",
    capabilities: tuple[str, ...] = (),
    diagnostic: str | None = None,
    tuple_arity: int = 0,
    overload: str = "v1",
) -> CatalogRow:
    prefix = "pine:variable:" if call_form == "context_field" else "pine:function:"
    symbol_id = prefix + symbol
    return CatalogRow(
        symbol_id,
        symbol_id + "#" + overload,
        call_form,
        versions,
        status,
        callable_path,
        return_type,
        "EAGER_ARGUMENTS",
        state_model,
        capabilities,
        diagnostic,
        tuple_arity,
    )


ROWS: list[CatalogRow] = []

# Pure math namespace and historical global aliases.
_math = {
    "abs": "object",
    "acos": "object",
    "asin": "object",
    "atan": "object",
    "avg": "object",
    "ceil": "object",
    "cos": "object",
    "exp": "object",
    "floor": "object",
    "log": "object",
    "log10": "object",
    "max": "object",
    "min": "object",
    "pow": "object",
    "round": "object",
    "round_to_mintick": "object",
    "sign": "object",
    "sin": "object",
    "sqrt": "object",
    "sum": "object",
    "tan": "object",
    "todegrees": "object",
    "toradians": "object",
}
for name, return_type in _math.items():
    path = f"pinelib.abi.math.{name}_v1"
    ROWS.append(
        _row(
            f"math.{name}",
            path,
            versions=NAMESPACE,
            status=TargetStatus.SUPPORTED_PURE,
            return_type=return_type,
            capabilities=("value.numeric",),
        )
    )
    if name not in {"round_to_mintick", "avg"}:
        ROWS.append(
            _row(
                name,
                path,
                versions=PRE_NAMESPACE,
                status=TargetStatus.SUPPORTED_PURE,
                return_type=return_type,
                call_form="global_function",
                capabilities=("value.numeric",),
            )
        )
ROWS.append(
    _row(
        "math.random",
        None,
        versions=NAMESPACE,
        status=TargetStatus.UNSUPPORTED_FAIL_CLOSED,
        diagnostic="PL2001 deterministic random stream contract is not admitted in Stage 3",
    )
)

# Strings.
_string = {
    "contains": "bool",
    "startswith": "bool",
    "endswith": "bool",
    "length": "int",
    "lower": "string",
    "upper": "string",
    "trim": "string",
    "pos": "int",
    "substring": "string",
    "replace": "string",
    "replace_all": "string",
    "split": "array<string>",
    "tonumber": "float",
    "tostring": "string",
    "format": "string",
    "format_time": "string",
}
for name, return_type in _string.items():
    path = f"pinelib.abi.string.{name}_v1"
    state_model = "REFERENCE_HEAP" if name == "split" else "PURE"
    status = (
        TargetStatus.SUPPORTED_STATEFUL
        if name == "split"
        else TargetStatus.SUPPORTED_PURE
    )
    ROWS.append(
        _row(
            f"str.{name}",
            path,
            versions=NAMESPACE,
            status=status,
            return_type=return_type,
            state_model=state_model,
            capabilities=("string",)
            + (("reference.array",) if name == "split" else ()),
        )
    )
for old_name in ("tostring", "tonumber"):
    ROWS.append(
        _row(
            old_name,
            f"pinelib.abi.string.{old_name}_v1",
            versions=PRE_NAMESPACE,
            status=TargetStatus.SUPPORTED_PURE,
            return_type=_string[old_name],
            call_form="global_function",
            capabilities=("string",),
        )
    )

# Immutable inputs.
ROWS.append(
    _row(
        "input",
        "pinelib.abi.input.generic_v1",
        versions=ALL_VERSIONS,
        status=TargetStatus.SUPPORTED_CONTEXT,
        return_type="any",
        state_model="ADMITTED_INPUT",
        capabilities=("input.registry",),
    )
)
for name, return_type in {
    "bool": "bool",
    "int": "int",
    "float": "float",
    "string": "string",
    "time": "int",
    "price": "float",
    "symbol": "string",
    "timeframe": "string",
    "session": "string",
    "color": "color",
    "source": "source",
}.items():
    ROWS.append(
        _row(
            f"input.{name}",
            (
                "pinelib.abi.input.source_value_v1"
                if name == "source"
                else f"pinelib.abi.input.{name}_v1"
            ),
            versions=NAMESPACE,
            status=TargetStatus.SUPPORTED_CONTEXT,
            return_type=return_type,
            state_model="ADMITTED_INPUT",
            capabilities=("input.registry",),
        )
    )

# Canonical Request Engine. Historical ``security`` and v5+ request namespace
# share one exact implementation; no name-based dispatcher exists.
ROWS.append(
    _row(
        "security",
        "pinelib.abi.request.security_v1",
        versions=PRE_NAMESPACE,
        status=TargetStatus.SUPPORTED_STATEFUL,
        return_type="typed_request_result",
        call_form="global_function",
        state_model="REQUEST_DATASET_REGISTRY",
        capabilities=("request.security", "marketdata.v2"),
    )
)
ROWS.append(
    _row(
        "request.security",
        "pinelib.abi.request.security_v1",
        versions=NAMESPACE,
        status=TargetStatus.SUPPORTED_STATEFUL,
        return_type="typed_request_result",
        state_model="REQUEST_DATASET_REGISTRY",
        capabilities=("request.security", "marketdata.v2"),
    )
)
ROWS.append(
    _row(
        "request.security_lower_tf",
        "pinelib.abi.request.security_lower_tf_v1",
        versions=NAMESPACE,
        status=TargetStatus.SUPPORTED_STATEFUL,
        return_type="array<typed_request_result>",
        state_model="REQUEST_DATASET_REGISTRY",
        capabilities=("request.security_lower_tf", "marketdata.v2", "reference.array"),
    )
)
for name in (
    "financial",
    "economic",
    "earnings",
    "dividends",
    "splits",
    "currency_rate",
    "seed",
    "footprint",
):
    ROWS.append(
        _row(
            f"request.{name}",
            None,
            versions=NAMESPACE,
            status=TargetStatus.UNSUPPORTED_FAIL_CLOSED,
            diagnostic=f"PL2001 request.{name} has no admitted provider capability in Stage 4",
            state_model="REQUEST_DATASET_REGISTRY",
            capabilities=(f"request.{name}",),
        )
    )

# Calendar and sessions.
for name in (
    "timestamp",
    "year",
    "month",
    "dayofmonth",
    "dayofweek",
    "hour",
    "minute",
    "second",
):
    ROWS.append(
        _row(
            name,
            f"pinelib.abi.time.{name}_v1",
            versions=ALL_VERSIONS,
            status=TargetStatus.SUPPORTED_CONTEXT,
            return_type="int",
            call_form="global_function",
            state_model="TIME_CONTEXT",
            capabilities=("time.iana",),
        )
    )
ROWS.append(
    _row(
        "time.in_session",
        "pinelib.abi.time.in_session_v1",
        versions=ALL_VERSIONS,
        status=TargetStatus.SUPPORTED_CONTEXT,
        return_type="bool",
        state_model="SESSION_POLICY",
        capabilities=("time.iana", "time.session"),
    )
)

# syminfo/timeframe/barstate context fields.
_context_fields = {
    "open": "float",
    "high": "float",
    "low": "float",
    "close": "float",
    "volume": "float",
    "time": "int",
    "time_close": "int",
    "bar_index": "int",
    "last_bar_index": "int",
    "syminfo.ticker": "string",
    "syminfo.tickerid": "string",
    "syminfo.prefix": "string",
    "syminfo.currency": "string",
    "syminfo.basecurrency": "string",
    "syminfo.timezone": "string",
    "syminfo.type": "string",
    "syminfo.mintick": "float",
    "syminfo.pointvalue": "float",
    "syminfo.mincontract": "float",
    "timeframe.period": "string",
    "timeframe.multiplier": "int",
    "timeframe.in_seconds": "int",
    "timeframe.isintraday": "bool",
    "timeframe.isdaily": "bool",
    "timeframe.isweekly": "bool",
    "timeframe.ismonthly": "bool",
    "barstate.isfirst": "bool",
    "barstate.islast": "bool",
    "barstate.ishistory": "bool",
    "barstate.isrealtime": "bool",
    "barstate.isnew": "bool",
    "barstate.isconfirmed": "bool",
    "barstate.islastconfirmedhistory": "bool",
}
for symbol, return_type in _context_fields.items():
    callable_name = symbol.replace(".", "_") + "_v1"
    ROWS.append(
        _row(
            symbol,
            f"pinelib.abi.runtime_values.{callable_name}",
            versions=ALL_VERSIONS,
            status=TargetStatus.SUPPORTED_CONTEXT,
            return_type=return_type,
            call_form="context_field",
            state_model="RUNTIME_CONTEXT",
            capabilities=(symbol.split(".")[0] + ".context",),
        )
    )

# TA exact kernels and pre-v5 aliases.
_ta = {
    "sma": ("object", 0),
    "ema": ("object", 0),
    "rma": ("object", 0),
    "wma": ("object", 0),
    "vwma": ("object", 0),
    "swma": ("object", 0),
    "alma": ("object", 0),
    "hma": ("object", 0),
    "rsi": ("object", 0),
    "macd": ("tuple<float,float,float>", 3),
    "mom": ("object", 0),
    "roc": ("object", 0),
    "cmo": ("object", 0),
    "tsi": ("object", 0),
    "stoch": ("object", 0),
    "tr": ("object", 0),
    "atr": ("object", 0),
    "bb": ("tuple<float,float,float>", 3),
    "bbw": ("object", 0),
    "kc": ("tuple<float,float,float>", 3),
    "kcw": ("object", 0),
    "range": ("object", 0),
    "wpr": ("object", 0),
    "dmi": ("tuple<float,float,float>", 3),
    "supertrend": ("tuple<float,int>", 2),
    "sar": ("object", 0),
    "pivothigh": ("object", 0),
    "pivotlow": ("object", 0),
    "rising": ("bool", 0),
    "falling": ("bool", 0),
    "highest": ("object", 0),
    "lowest": ("object", 0),
    "highestbars": ("object", 0),
    "lowestbars": ("object", 0),
    "variance": ("object", 0),
    "stdev": ("object", 0),
    "dev": ("object", 0),
    "correlation": ("object", 0),
    "percentile_linear_interpolation": ("object", 0),
    "percentile_nearest_rank": ("object", 0),
    "percentrank": ("object", 0),
    "linreg": ("object", 0),
    "median": ("object", 0),
    "mode": ("object", 0),
    "valuewhen": ("object", 0),
    "barssince": ("object", 0),
    "cci": ("object", 0),
    "mfi": ("object", 0),
    "obv": ("object", 0),
    "vwap": ("object", 0),
    "cum": ("object", 0),
}
for name, (return_type, tuple_arity) in _ta.items():
    path = f"pinelib.abi.ta.{name}_v1"
    ROWS.append(
        _row(
            f"ta.{name}",
            path,
            versions=NAMESPACE,
            status=TargetStatus.SUPPORTED_STATEFUL,
            return_type=return_type,
            state_model="TA_KERNEL_SLOT",
            capabilities=("state.ta", "series.history"),
            tuple_arity=tuple_arity,
        )
    )
    ROWS.append(
        _row(
            name,
            path,
            versions=PRE_NAMESPACE,
            status=TargetStatus.SUPPORTED_STATEFUL,
            return_type=return_type,
            call_form="global_function",
            state_model="TA_KERNEL_SLOT",
            capabilities=("state.ta", "series.history"),
            tuple_arity=tuple_arity,
        )
    )

# References.
_array = {
    "new": "array<T>",
    "size": "int",
    "get": "T",
    "set": "void",
    "push": "void",
    "pop": "T",
    "shift": "T",
    "unshift": "void",
    "insert": "void",
    "remove": "T",
    "clear": "void",
    "copy": "array<T>",
    "slice": "array<T>",
    "sort": "void",
    "indexof": "int",
    "lastindexof": "int",
    "binary_search": "int",
    "binary_search_leftmost": "int",
    "binary_search_rightmost": "int",
    "first": "T",
    "last": "T",
    "includes": "bool",
    "reverse": "void",
    "fill": "void",
    "concat": "void",
    "values": "tuple<T>",
}
for name, return_type in _array.items():
    ROWS.append(
        _row(
            f"array.{name}",
            f"pinelib.abi.reference.array_{name}_v1",
            versions=(4, 5, 6),
            status=TargetStatus.SUPPORTED_STATEFUL,
            return_type=return_type,
            state_model="REFERENCE_HEAP",
            capabilities=("reference.array",),
        )
    )
_map = {
    "new": "map<K,V>",
    "put": "V",
    "get": "V",
    "contains": "bool",
    "remove": "V",
    "keys": "tuple<K>",
    "values": "tuple<V>",
    "size": "int",
    "clear": "void",
    "copy": "map<K,V>",
    "put_all": "void",
}
for name, return_type in _map.items():
    ROWS.append(
        _row(
            f"map.{name}",
            f"pinelib.abi.reference.map_{name}_v1",
            versions=(5, 6),
            status=TargetStatus.SUPPORTED_STATEFUL,
            return_type=return_type,
            state_model="REFERENCE_HEAP",
            capabilities=("reference.map",),
        )
    )
_matrix = {
    "new": "matrix<T>",
    "rows": "int",
    "columns": "int",
    "get": "T",
    "set": "void",
    "copy": "matrix<T>",
}
for name, return_type in _matrix.items():
    ROWS.append(
        _row(
            f"matrix.{name}",
            f"pinelib.abi.reference.matrix_{name}_v1",
            versions=(5, 6),
            status=TargetStatus.SUPPORTED_STATEFUL,
            return_type=return_type,
            state_model="REFERENCE_HEAP",
            capabilities=("reference.matrix",),
        )
    )
for name, return_type in {
    "new": "udt",
    "get": "object",
    "set": "void",
    "copy": "udt",
}.items():
    ROWS.append(
        _row(
            f"udt.{name}",
            f"pinelib.abi.reference.udt_{name}_v1",
            versions=(5, 6),
            status=TargetStatus.SUPPORTED_STATEFUL,
            return_type=return_type,
            state_model="REFERENCE_HEAP",
            capabilities=("reference.udt",),
        )
    )
ROWS.append(
    _row(
        "enum.value",
        "pinelib.abi.reference.enum_value_v1",
        versions=(5, 6),
        status=TargetStatus.SUPPORTED_PURE,
        return_type="enum",
        state_model="PURE",
        capabilities=("reference.enum",),
    )
)

# Visuals and alerts are deterministic event producers, not renderers/notifiers.
_visuals = (
    "plot",
    "plotshape",
    "plotchar",
    "bgcolor",
    "barcolor",
    "hline",
    "fill",
    "line_new",
    "line_set_xy1",
    "line_set_xy2",
    "line_delete",
    "label_new",
    "label_set_text",
    "label_delete",
)
for name in _visuals:
    symbol = name.replace("_", ".") if name.startswith(("line_", "label_")) else name
    return_type = (
        "visual_handle" if name in {"line_new", "label_new"} else "visual_event"
    )
    ROWS.append(
        _row(
            symbol,
            f"pinelib.abi.visual.{name}_v1",
            versions=ALL_VERSIONS,
            status=TargetStatus.SUPPORTED_STATEFUL,
            return_type=return_type,
            call_form="global_function",
            state_model="VISUAL_TAPE",
            capabilities=("visual.events", "reference.visual"),
        )
    )
for name in ("alert", "alertcondition"):
    ROWS.append(
        _row(
            name,
            f"pinelib.abi.alert.{name}_v1",
            versions=(4, 5, 6),
            status=TargetStatus.SUPPORTED_STATEFUL,
            return_type="alert_event",
            call_form="global_function",
            state_model="ALERT_TAPE",
            capabilities=("alert.events",),
        )
    )

CATALOG: tuple[CatalogRow, ...] = tuple(ROWS)
