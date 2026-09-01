from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

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
    if name.startswith(("array.new", "map.new", "matrix.new")):
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
            ),
            None,
        )
        if source_name is not None:
            rows.append(
                {
                    "abi_parameter": abi_name,
                    "binding": "SOURCE_PARAMETER",
                    "source": source_name,
                }
            )
        elif is_method and abi_name == "handle":
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
                "version_availability": list(official_row["supported_versions"]),
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
        "official_surface": {
            "schema_id": official["schema_id"],
            "content_hash": official["content_hash"],
            "denominator": official["denominator"],
            "counts": official["counts"],
            "source_index_content_hash": official["source_index_content_hash"],
            "source_pack_hashes": official["source_pack_hashes"],
        },
        "compiler_operations": compiler_operations,
        "rows": rows,
        "classification": counts,
        "tradingview_compile_oracle": {"status": "NOT_RUN", "evidence_id": None},
    }
    return {**body, "content_hash": sha(body)}
