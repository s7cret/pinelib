from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from pinelib.abi.models import CatalogRow, TargetStatus
from pinelib.errors import PL_ABI_MANIFEST, PineRuntimeError
from pinelib.state.checkpoint import sha
from pinelib.version import PACKAGE_VERSION

_SUPPORTED = {
    TargetStatus.SUPPORTED_PURE,
    TargetStatus.SUPPORTED_STATEFUL,
    TargetStatus.SUPPORTED_CONTEXT,
}
_DYNAMIC_LENGTH_SYMBOLS = {
    "ta.sma",
    "ta.wma",
    "ta.range",
    "ta.highest",
    "ta.lowest",
    "ta.highestbars",
    "ta.lowestbars",
    "ta.variance",
    "ta.stdev",
    "ta.dev",
    "ta.median",
    "ta.mode",
}
_VISUAL_GLOBALS = {
    "barcolor",
    "bgcolor",
    "fill",
    "hline",
    "plot",
    "plotbar",
    "plotcandle",
    "plotchar",
    "plotshape",
}
_VISUAL_NAMESPACES = {"box", "label", "line", "linefill", "polyline", "table"}
_COMPILER_OPERATIONS = (
    (
        "operator.div.legacy",
        "eager",
        "pure",
        "pinelib.abi.primitives.operator_binary_v1",
    ),
    (
        "operator.div.fractional",
        "eager",
        "pure",
        "pinelib.abi.primitives.operator_binary_v1",
    ),
    ("control.once", "lazy", "control", "pinelib.abi.primitives.once_v1"),
    (
        "control.for_range.dynamic_end",
        "lazy",
        "control",
        "pinelib.abi.primitives.range_v1",
    ),
    (
        "control.for_range.fixed_end",
        "lazy",
        "control",
        "pinelib.abi.primitives.range_v1",
    ),
    (
        "function.invoke.pure",
        "eager",
        "pure",
        "pinelib.abi.primitives.invoke_function_v1",
    ),
    (
        "function.invoke.stateful",
        "eager",
        "state",
        "pinelib.abi.primitives.invoke_function_v1",
    ),
    (
        "operator.logical.eager",
        "eager",
        "pure",
        "pinelib.abi.primitives.logical_eager_v1",
    ),
    ("operator.logical.lazy", "lazy", "pure", "pinelib.abi.primitives.logical_lazy_v1"),
    (
        "operator.binary",
        "eager",
        "pure",
        "pinelib.abi.primitives.operator_binary_v1",
    ),
    (
        "operator.unary",
        "eager",
        "pure",
        "pinelib.abi.primitives.operator_unary_v1",
    ),
    (
        "series.history",
        "eager",
        "pure",
        "pinelib.abi.primitives.series_history_v1",
    ),
)
_INTERNAL_ABI_BINDINGS = {
    "registry": "RUNTIME_INPUT_REGISTRY",
    "input_id": "ADMITTED_INPUT_SPEC_ID",
    "tx": "RUNTIME_TRANSACTION",
    "transaction": "RUNTIME_TRANSACTION",
    "state_id": "SOURCE_LOCATION_STATE_ID",
    "call_site_id": "SOURCE_LOCATION_STATE_ID",
    "source_span": "SOURCE_SPAN",
    "object_id": "SOURCE_LOCATION_OBJECT_ID",
    "new_object_id": "SOURCE_LOCATION_OBJECT_ID",
    "type_descriptor": "SEMANTIC_TYPE_DESCRIPTOR",
    "result_shape": "SEMANTIC_RESULT_SHAPE",
    "chart_open_ms": "RUNTIME_CHART_OPEN_MS",
    "chart_close_ms": "RUNTIME_CHART_CLOSE_MS",
}
_SOURCE_TO_ABI_ALIASES = {
    "id": "handle",
    "index_from": "start",
    "index_to": "end",
    "initial_value": "initial",
    "from": "from_handle",
}
# Audited per-function spellings. These aliases must never become a global
# argument-name fallback: e.g. `x` means a source in RSI, a number in exp.
_AUDITED_ARGUMENT_ALIASES = {
    "math.abs": {"number": "value"},
    "math.ceil": {"number": "value"},
    "math.floor": {"number": "value"},
    "math.exp": {"number": "value"},
    "math.round": {"number": "value"},
    "math.sqrt": {"number": "value"},
    "ta.macd": {"fastlen": "fast_length", "slowlen": "slow_length", "siglen": "signal_length"},
    "exp": {"x": "value"},
    "abs": {"x": "value"},
    "ceil": {"x": "value"},
    "floor": {"x": "value"},
    "round": {"x": "value"},
    "sqrt": {"x": "value"},
    "rsi": {"x": "source", "y": "length"},
    "macd": {"fastlen": "fast_length", "slowlen": "slow_length", "siglen": "signal_length"},
}
_HISTORICAL_BUILTINS = {"math.abs", "math.ceil", "math.floor", "math.exp", "math.round", "math.sqrt", "math.pow", "ta.macd", "ta.rsi", "ta.sma", "ta.wma"}
_AUDITED_BUILTINS = _HISTORICAL_BUILTINS | {"math.round_to_mintick"}


def _audited_signature(official: dict[str, Any]) -> dict[str, Any]:
    """Correct the projection without rewriting the frozen source inventory.

    TradingView v6 reference and v5 migration guide define these names,
    qualifiers and arity-dependent returns. See docs/STAGE2_BUILTIN_BINDINGS.md.
    """
    name = official["name"]
    if name in {"ta.variance", "ta.stdev"}:
        return {**official, "supported_versions": [5, 6], "parameters": [
            {"name": "source", "type": "float", "qualifier_max": "series", "required": True},
            {"name": "length", "type": "int", "qualifier_max": "series", "required": True},
            {"name": "biased", "type": "bool", "qualifier_max": "series", "required": False, "default": True},
        ]}
    if name == "float" and official["category"] == "functions":
        # The v4 type-system manual dates explicit casts to v4. Scope this
        # correction to the callable row: a type/input constant or a numeric
        # kernel's existence does not authorize the source-level cast in v1-v3.
        # https://www.tradingview.com/pine-script-docs/v4/language/type-system/#type-casting
        return {**official, "supported_versions": [4, 5, 6], "parameters": [
            {"name": "x", "type": "float", "qualifier_max": "series", "required": True}
        ]}
    if name not in _AUDITED_BUILTINS:
        return official
    def parameter(name: str, type_name: str, *, qualifier: str = "series", required: bool = True) -> dict[str, object]:
        return {"name": name, "type": type_name, "qualifier_max": qualifier, "required": required}

    if name in {"math.abs", "math.ceil", "math.floor", "math.exp", "math.round", "math.sqrt", "math.round_to_mintick"}:
        parameters = [parameter("number", "float")]
        if name == "math.round":
            parameters.append(parameter("precision", "int", required=False))
    elif name == "ta.macd":
        parameters = [parameter("source", "float")] + [
            parameter(item, "int", qualifier="simple") for item in ("fastlen", "slowlen", "siglen")
        ]
    elif name == "ta.rsi":
        parameters = [parameter("source", "float"), parameter("length", "int", qualifier="simple")]
    else:
        return official
    returns = {"math.round": "int|float", "math.abs": "int|float", "math.ceil": "int", "math.floor": "int"}
    return {**official, "parameters": parameters, "returns": returns.get(name, official["returns"])}


def _historical_call_bindings(
    rows: list[dict[str, object]], by_symbol: Mapping[str, tuple[CatalogRow, ...]]
) -> list[dict[str, object]]:
    """Separate, version-bounded producer identities; not official-v6 rows."""
    result: list[dict[str, object]] = []
    for row in rows:
        modern = str(row["name"])
        if modern not in _HISTORICAL_BUILTINS:
            continue
        old_name = modern.split(".", 1)[1]
        legacy = next((entry for entry in by_symbol.get("pine:function:" + old_name, ())
                       if entry.status in _SUPPORTED), None)
        if legacy is None or legacy.abi_callable != row["abi_callable"]:
            raise PineRuntimeError("audited historical target disagrees with catalog", code=PL_ABI_MANIFEST)
        historical = dict(row)
        historical["name"] = old_name
        historical["call_form"] = "global_function"
        historical["producer_call_forms"] = ["FUNCTION"]
        historical["version_availability"] = list(legacy.pine_versions)
        historical["source_symbol_ids"] = [str(row["symbol_id"]), legacy.symbol_id]
        historical["producer_overload_ids"] = [
            str(row["symbol_id"]) + ("#overload:0" if old_name == "rsi" else "#canonical")
        ]
        if old_name == "abs":
            historical["producer_overload_ids"] = [str(row["symbol_id"]) + suffix
                                                   for suffix in ("#canonical", "#overload:0")]
        renames = {"number": "x"} if old_name in {"abs", "ceil", "floor", "exp", "round", "sqrt"} else (
            {"source": "x", "length": "y"} if old_name == "rsi" else {}
        )
        parameters = [{**item, "name": renames.get(str(item["name"]), item["name"])}
                      for item in cast(list[dict[str, object]], row["parameters"])]
        historical["parameters"] = parameters
        historical["parameter_bindings"] = _parameter_bindings(
            {"name": old_name, "category": "functions", "parameters": parameters},
            cast(list[dict[str, object]], historical["abi_parameters"]),
        )
        if old_name == "rsi":
            historical["dynamic_length_policy"] = {"y": "SIMPLE_STABLE"}
        if old_name == "round":
            # Precision was added in v4. Its producer overload has a separate
            # identity and must not widen the one-argument v1-v3 signature.
            precise = {**historical, "version_availability": [4],
                       "producer_overload_ids": [str(row["symbol_id"]) + "#overload:0"],
                       "parameters": [{**item, "required": True} for item in parameters],
                       "return": {**cast(dict[str, object], row["return"]), "pine_type": "float"}}
            historical["parameters"] = parameters[:1]
            historical["parameter_bindings"] = _parameter_bindings(
                {"name": old_name, "category": "functions", "parameters": parameters[:1]},
                cast(list[dict[str, object]], historical["abi_parameters"]),
            )
            historical["producer_overload_ids"] = [str(row["symbol_id"]) + "#canonical"]
            historical["return"] = {**cast(dict[str, object], row["return"]), "pine_type": "int"}
            result.extend([historical, precise])
        else:
            result.append(historical)
    return result


def _load_official_surface() -> dict[str, Any]:
    path = Path(__file__).with_name("official_pine_v6_surface.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PineRuntimeError(
            "official surface must be an object", code=PL_ABI_MANIFEST
        )
    body = {key: value for key, value in data.items() if key != "content_hash"}
    if data.get("content_hash") != sha(body):
        raise PineRuntimeError("official surface hash mismatch", code=PL_ABI_MANIFEST)
    rows = data.get("rows")
    if not isinstance(rows, list) or data.get("denominator") != len(rows):
        raise PineRuntimeError(
            "official surface row count mismatch", code=PL_ABI_MANIFEST
        )
    return data


def _candidate_ids(official: Mapping[str, Any]) -> tuple[str, ...]:
    symbol_id = str(official["symbol_id"])
    name = str(official["name"])
    candidates = [symbol_id]
    if symbol_id.startswith("pine:method:"):
        candidates.append("pine:function:" + name)
    if name == "array.new<type>" or name.startswith("array.new_"):
        candidates.append("pine:function:array.new")
    if name == "matrix.new<type>" or name.startswith("matrix.new_"):
        candidates.append("pine:function:matrix.new")
    if name == "map.new<type,type>":
        candidates.append("pine:function:map.new")
    return tuple(dict.fromkeys(candidates))


def _direct_target(
    official: Mapping[str, Any], by_symbol: Mapping[str, tuple[CatalogRow, ...]]
) -> CatalogRow | None:
    for symbol_id in _candidate_ids(official):
        for target in by_symbol.get(symbol_id, ()):
            if target.status in _SUPPORTED and set(target.pine_versions).intersection(
                official.get("supported_versions", [])
            ):
                return target
    return None


def _delegation(name: str) -> dict[str, str] | None:
    namespace = name.split(".", 1)[0]
    if name.startswith("request."):
        return {
            "owner": "marketdata-provider",
            "schema_id": "openpine.marketdata.provider.v1",
            "capability_id": name,
        }
    if name.startswith("strategy."):
        return {
            "owner": "backtest-engine",
            "schema_id": "openpine.backtest.engine.v1",
            "capability_id": name,
        }
    if name in _VISUAL_GLOBALS or namespace in _VISUAL_NAMESPACES:
        return {
            "owner": "visual-recorder",
            "schema_id": "openpine.visual.recorder.v1",
            "capability_id": name,
        }
    return None


def _dynamic_length_policy(
    name: str, parameters: list[dict[str, Any]]
) -> dict[str, str]:
    length = next((item for item in parameters if item.get("name") == "length"), None)
    if length is None:
        return {}
    if name in _DYNAMIC_LENGTH_SYMBOLS:
        return {"length": "SERIES_ALLOWED"}
    return {
        "length": (
            "SIMPLE_STABLE"
            if length.get("qualifier_max") in {"const", "input", "simple"}
            else "SERIES_UNSUPPORTED_FAIL_CLOSED"
        )
    }


def _return_identity(name: str, target: CatalogRow | None) -> str:
    if name == "array.slice":
        return "PARENT_LINKED_SHALLOW_VIEW"
    if name.startswith(("array.new", "map.new", "matrix.new")) or name in {"map.keys", "map.values"}:
        return "NEW_REFERENCE"
    if target is not None and target.tuple_arity:
        return "FIXED_TUPLE"
    if target is not None and target.return_type in {
        "array<T>",
        "map<K,V>",
        "matrix<T>",
        "udt",
    }:
        return "REFERENCE"
    if target is not None and target.return_type == "visual_handle":
        return "VISUAL_REFERENCE"
    return "VALUE"


def _na_policy(name: str) -> dict[str, str]:
    result = {
        "acceptance": "PARAMETER_SPECIFIC_RUNTIME_VALIDATION",
        "propagation": "PINE_FUNCTION_SPECIFIC",
    }
    if name.startswith("array.new"):
        result["omitted_initial_value"] = "CANONICAL_PINE_NA"
    return result


def _source_aliases(
    official: Mapping[str, Any], target: CatalogRow | None
) -> list[str]:
    aliases = [str(official["symbol_id"])]
    if official["name"] in {"array.new<type>", "matrix.new<type>", "map.new<type,type>"}:
        # Exact producer spelling of the declared generic template. Concrete type
        # arguments stay in checked semantic result facts, not a wildcard binding.
        aliases.append(str(official["symbol_id"]).replace("<", "u003c").replace(",", "u002c").replace(">", "u003e"))
    if official["name"] == "request.security":
        aliases.append("pine:function:security")
    if target is not None:
        aliases.append(target.symbol_id)
        aliases.append(str(official["symbol_id"]) + "#canonical")
    return list(dict.fromkeys(aliases))


def _parameter_bindings(
    official: Mapping[str, Any], abi_parameters: list[dict[str, object]]
) -> list[dict[str, object]]:
    source_parameters = [
        item for item in official.get("parameters", []) if isinstance(item, dict)
    ]
    source_names = {str(item["name"]) for item in source_parameters if item.get("name")}
    is_method = str(official.get("category")) == "methods"
    rows: list[dict[str, object]] = []
    for parameter in abi_parameters:
        abi_name = str(parameter["name"])
        if abi_name == "timeframe" and official["name"] == "request.security":
            rows.append(
                {
                    "abi_parameter": abi_name,
                    "binding": "INJECTED",
                    "source": "REQUEST_TIMEFRAME_ARGUMENT",
                }
            )
            continue
        if abi_name == "expression" and official["name"] in {
            "request.security",
            "request.security_lower_tf",
        }:
            rows.append(
                {
                    "abi_parameter": abi_name,
                    "binding": "INJECTED",
                    "source": "COMPILED_REQUEST_EXPRESSION",
                }
            )
            continue
        if abi_name in _INTERNAL_ABI_BINDINGS:
            rows.append(
                {
                    "abi_parameter": abi_name,
                    "binding": "INJECTED",
                    "source": _INTERNAL_ABI_BINDINGS[abi_name],
                }
            )
            continue
        source_name = next(
            (
                name
                for name in source_names
                if name == abi_name or _SOURCE_TO_ABI_ALIASES.get(name) == abi_name
                or _AUDITED_ARGUMENT_ALIASES.get(str(official["name"]), {}).get(name) == abi_name
            ),
            None,
        )
        if source_name is not None:
            rows.append(
                {
                    "abi_parameter": abi_name,
                    "binding": (
                        "SOURCE_VARIADIC"
                        if parameter.get("kind") == "VAR_POSITIONAL"
                        and official["name"] in {"math.min", "math.max"}
                        and official.get("category") == "functions"
                        and source_name == "values"
                        and any(
                            item.get("name") == source_name
                            and item.get("variadic") is True
                            for item in source_parameters
                        )
                        else "SOURCE_PARAMETER"
                    ),
                    "source": source_name,
                }
            )
        elif is_method and (
            abi_name == "handle"
            or (official["name"] == "array.concat" and abi_name == "id1")
        ):
            rows.append(
                {
                    "abi_parameter": abi_name,
                    "binding": "METHOD_RECEIVER",
                    "source": "receiver",
                }
            )
        elif abi_name == "query" and str(official["name"]).startswith("request."):
            rows.append(
                {
                    "abi_parameter": abi_name,
                    "binding": "INJECTED",
                    "source": "REQUEST_QUERY_FROM_SOURCE_PARAMETERS",
                }
            )
        elif parameter.get("has_default"):
            rows.append(
                {
                    "abi_parameter": abi_name,
                    "binding": "ABI_DEFAULT",
                    "source": None,
                }
            )
        else:
            rows.append(
                {
                    "abi_parameter": abi_name,
                    "binding": "UNBOUND_FAIL_CLOSED",
                    "source": None,
                }
            )
    return rows


def build_manifest_v2(
    catalog: Iterable[CatalogRow],
    *,
    resolve: Callable[[str], Callable[..., object]],
    inspect_parameters: Callable[[Callable[..., object]], list[dict[str, object]]],
) -> dict[str, object]:
    official = _load_official_surface()
    compiler_operations: list[dict[str, object]] = []
    for name, evaluation, effect, operation_abi_callable in _COMPILER_OPERATIONS:
        operation_abi_parameters = inspect_parameters(resolve(operation_abi_callable))
        operation_parameter_bindings: list[dict[str, object]] = []
        operation_index = 0
        for parameter in operation_abi_parameters:
            abi_name = str(parameter["name"])
            if abi_name == "tx":
                operation_parameter_bindings.append(
                    {
                        "abi_parameter": abi_name,
                        "binding": "INJECTED",
                        "source": "RUNTIME_TRANSACTION",
                    }
                )
            else:
                operation_parameter_bindings.append(
                    {
                        "abi_parameter": abi_name,
                        "binding": "OPERATION_ARGUMENT",
                        "source_index": operation_index,
                    }
                )
                operation_index += 1
        compiler_operations.append(
            {
                "name": name,
                "evaluation": evaluation,
                "effect": effect,
                "abi_callable": operation_abi_callable,
                "abi_parameters": operation_abi_parameters,
                "parameter_bindings": operation_parameter_bindings,
            }
        )
    catalog_rows = tuple(catalog)
    by_symbol: dict[str, list[CatalogRow]] = {}
    for entry in catalog_rows:
        by_symbol.setdefault(entry.symbol_id, []).append(entry)
    frozen_index = {key: tuple(value) for key, value in by_symbol.items()}

    rows: list[dict[str, object]] = []
    for official_row in official["rows"]:
        if not isinstance(official_row, dict):
            raise PineRuntimeError(
                "official surface row is invalid", code=PL_ABI_MANIFEST
            )
        name = str(official_row["name"])
        official_row = _audited_signature(official_row)
        # Verified reference contract absent in the frozen snapshot; do not infer
        # arbitrary source signatures from coincidental Python ABI names.
        if name in {"array.get", "array.set"} and not official_row.get("parameters"):
            signature = [
                {
                    "name": "id",
                    "type": "array",
                    "qualifier_max": "series",
                    "required": True,
                },
                {
                    "name": "index",
                    "type": "int",
                    "qualifier_max": "series",
                    "required": True,
                },
            ]
            if name == "array.set":
                signature.append(
                    {
                        "name": "value",
                        "type": "any",
                        "qualifier_max": "series",
                        "required": True,
                    }
                )
            official_row = {
                **official_row,
                "parameters": signature[1:]
                if official_row["category"] == "methods"
                else signature,
            }
        if (
            name == "na"
            and official_row["category"] == "functions"
            and not official_row.get("parameters")
        ):
            official_row = {
                **official_row,
                "parameters": [
                    {
                        "name": "x",
                        "type": "any",
                        "required": True,
                        "qualifier_max": "series",
                    }
                ],
            }
        if name in {"math.min", "math.max"} and official_row["category"] == "functions":
            original_parameters = official_row.get("parameters", [])
            if len(original_parameters) == 1 and original_parameters[0].get("name") == "values":
                official_row = {
                    **official_row,
                    "parameters": [{**original_parameters[0], "variadic": True}],
                }
        parameters = [
            dict(item)
            for item in official_row.get("parameters", [])
            if isinstance(item, dict)
        ]
        target = _direct_target(official_row, frozen_index)
        dynamic_policy = _dynamic_length_policy(name, parameters)
        if "SERIES_UNSUPPORTED_FAIL_CLOSED" in dynamic_policy.values():
            target = None
        delegation = None if target is not None else _delegation(name)
        disposition = (
            "TARGET_DIRECT"
            if target is not None
            else (
                "TARGET_DELEGATED"
                if delegation is not None
                else "UNSUPPORTED_FAIL_CLOSED"
            )
        )
        abi_parameters: list[dict[str, object]] = []
        abi_callable: str | None = None
        overload_id: str | None = None
        parameter_bindings: list[dict[str, object]] = []
        state_model = "NONE"
        capabilities: list[str] = []
        diagnostic: str | None = None
        if target is not None:
            if target.abi_callable is None:
                raise PineRuntimeError(
                    "direct target has no ABI callable", code=PL_ABI_MANIFEST
                )
            abi_callable = target.abi_callable
            callable_value = resolve(abi_callable)
            abi_parameters = inspect_parameters(callable_value)
            overload_id = str(official_row["symbol_id"]) + "#v1"
            parameter_bindings = _parameter_bindings(official_row, abi_parameters)
            state_model = target.state_model
            capabilities = list(target.capabilities)
        elif delegation is not None:
            overload_id = str(official_row["symbol_id"]) + "#canonical"
            state_model = "EXTERNAL_CAPABILITY"
        else:
            diagnostic = f"PL2001 {name} has no admitted PineLib or delegated target"

        rows.append(
            {
                "category": official_row["category"],
                "name": name,
                "symbol_id": official_row["symbol_id"],
                "source_symbol_ids": _source_aliases(official_row, target),
                "overload_id": overload_id,
                "producer_overload_ids": (
                    [str(official_row["symbol_id"]) + "#canonical"]
                    if target is not None or delegation is not None
                    else []
                ),
                "disposition": disposition,
                "call_form": (
                    "method"
                    if official_row["category"] == "methods"
                    else (
                        "context_field"
                        if official_row["category"] == "variables"
                        else "namespace_function"
                    )
                ),
                "version_availability": (
                    sorted(
                        set(official_row["supported_versions"])
                        | {
                            version
                            for legacy in frozen_index.get("pine:function:security", ())
                            for version in legacy.pine_versions
                        }
                    )
                    if name == "request.security"
                    else list(official_row["supported_versions"])
                ),
                "parameters": parameters,
                "abi_callable": abi_callable,
                "abi_parameters": abi_parameters,
                "parameter_bindings": parameter_bindings,
                "return": {
                    "pine_type": official_row["returns"],
                    "runtime_type": target.return_type if target is not None else None,
                    "tuple_arity": target.tuple_arity if target is not None else 0,
                    "identity": _return_identity(name, target),
                },
                "evaluation_mode": (
                    target.evaluation_mode if target is not None else "EAGER_ARGUMENTS"
                ),
                "state_model": state_model,
                "state_identity_inputs": [
                    str(item["name"])
                    for item in abi_parameters
                    if item.get("name")
                    in {"state_id", "call_site_id", "object_id", "new_object_id"}
                ],
                "capabilities": capabilities,
                "na_policy": _na_policy(name),
                "dynamic_length_policy": dynamic_policy,
                "delegation": delegation,
                "diagnostic": diagnostic,
            }
        )
        if name in _AUDITED_BUILTINS:
            rows[-1]["producer_call_forms"] = ["NAMESPACE_FUNCTION"]
        if name == "float" and official_row["category"] == "functions":
            rows[-1]["producer_call_forms"] = ["FUNCTION"]
            rows[-1]["call_form"] = "global_function"
        if name == "math.round":
            cast(dict[str, object], rows[-1]["return"])["by_source_arity"] = {"1": "int", "2": "float"}
            rows[-1]["producer_overload_ids"] = [str(official_row["symbol_id"]) + suffix
                                                for suffix in ("#canonical", "#overload:0")]
        if name == "math.abs":
            cast(dict[str, object], rows[-1]["return"])["by_source_type"] = {"int": "int", "float": "float"}
            rows[-1]["producer_overload_ids"] = [str(official_row["symbol_id"]) + suffix
                                                for suffix in ("#canonical", "#overload:0")]
        if name == "ta.macd":
            rows[-1]["dynamic_length_policy"] = {
                item: "SIMPLE_STABLE" for item in ("fastlen", "slowlen", "siglen")
            }

    counts = {
        "official_total": len(rows),
        "classified_official": len(rows),
        "target_direct": sum(row["disposition"] == "TARGET_DIRECT" for row in rows),
        "target_delegated": sum(
            row["disposition"] == "TARGET_DELEGATED" for row in rows
        ),
        "unsupported_fail_closed": sum(
            row["disposition"] == "UNSUPPORTED_FAIL_CLOSED" for row in rows
        ),
        "unknown": 0,
    }
    body: dict[str, object] = {
        "schema_id": "pinelib.target_manifest.v2",
        "schema_version": "2.0.0",
        "package_version": PACKAGE_VERSION,
        "producer": "pinelib-rc6-cross-stack-local-candidate",
        "historical_call_bindings": _historical_call_bindings(rows, frozen_index),
        "official_surface": {
            "schema_id": official["schema_id"],
            "content_hash": official["content_hash"],
            "denominator": official["denominator"],
            "counts": official["counts"],
            "source_index_content_hash": official["source_index_content_hash"],
            "source_pack_hashes": official["source_pack_hashes"],
        },
        "compiled_reference_storage": {
            "revision": 1,
            "identity": "callback-and-occurrence",
            "binding_modes": ["default", "var"],
            "reference_history_min_version": {"array": 5},
        },
        "compiled_nominal_types": {
            "revision": 1,
            "identity": "source-declaration",
            "udt_binding_modes": ["default", "var", "varip"],
            "udt_fields": "declared-schema-field-rollback",
            "enum_storage": "nominal-portable-values",
            "min_pine_version": 5,
        },
        "compiled_nominal_registry": {
            "revision": 1,
            "schema_id": "pinelib.nominal_registry.v1",
            "identity": "source-declaration",
            "admission": "module-literal-before-execution",
            "min_pine_version": 5,
        },
        "compiled_varip_reference_storage": {
            "revision": 1,
            "policy": "per-object-transactional-persistence",
            "kinds": ["array", "matrix", "map"],
            "element_types": ["int", "float", "bool", "color", "string"],
            "min_pine_version": 5,
        },
        "compiled_varip_nominal_arrays": {
            "revision": 1,
            "registry_schema_id": "pinelib.nominal_registry.v1",
            "element_type": "udt",
            "field_profile": "fundamentals-and-ordinary-fundamental-array-matrix",
            "persistence": "array-elements-and-declared-varip-fields",
            "min_pine_version": 5,
        },
        "compiled_collection_iteration": {
            "revision": 1, "map": "insertion-order-stable-keys-live-values",
            "matrix": "live-size-row-arrays", "min_pine_version": 5,
        },
        "compiled_loop_values": {
            "revision": 1,
            "budget": "shared-callback",
            "for_in": "live-array",
            "empty_tuple": "typed-elements",
        },
        "compiler_operations": compiler_operations,
        "rows": rows,
        "classification": counts,
        "tradingview_compile_oracle": {"status": "NOT_RUN", "evidence_id": None},
    }
    return {**body, "content_hash": sha(body)}
