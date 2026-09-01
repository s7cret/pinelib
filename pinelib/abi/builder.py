from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import cast

from pinelib.abi.catalog import CATALOG
from pinelib.abi.models import TargetStatus
from pinelib.errors import PL_ABI_MANIFEST, PineRuntimeError
from pinelib.state.checkpoint import canonical_json, to_portable

_GENERIC_NAMES = {"invoke", "execute_operation", "dispatch", "execute_namespace"}


def _resolve(path: str) -> Callable[..., object]:
    module_name, attribute = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    try:
        value = getattr(module, attribute)
    except AttributeError as error:
        raise PineRuntimeError(
            f"Target ABI callable does not exist: {path}", code=PL_ABI_MANIFEST
        ) from error
    if not callable(value):
        raise PineRuntimeError(
            f"Target ABI object is not callable: {path}", code=PL_ABI_MANIFEST
        )
    return cast(Callable[..., object], value)


def _parameters(callable_value: Callable[..., object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for position, parameter in enumerate(
        inspect.signature(callable_value).parameters.values()
    ):
        row: dict[str, object] = {
            "name": parameter.name,
            "position": position,
            "kind": parameter.kind.name,
            "has_default": parameter.default is not inspect.Parameter.empty,
        }
        if parameter.default is not inspect.Parameter.empty:
            row["default"] = to_portable(parameter.default)
        annotation = parameter.annotation
        row["annotation"] = (
            "object" if annotation is inspect.Parameter.empty else str(annotation)
        )
        rows.append(row)
    return rows


def _validate_catalog_entries() -> None:
    identities: set[tuple[str, str]] = set()
    for entry in CATALOG:
        identity = (entry.symbol_id, entry.overload_id)
        if identity in identities:
            raise PineRuntimeError(
                f"duplicate target ABI identity: {identity}", code=PL_ABI_MANIFEST
            )
        identities.add(identity)
        if entry.status in {
            TargetStatus.SUPPORTED_PURE,
            TargetStatus.SUPPORTED_STATEFUL,
            TargetStatus.SUPPORTED_CONTEXT,
        }:
            if entry.abi_callable is None:
                raise PineRuntimeError(
                    f"supported ABI row has no callable: {identity}",
                    code=PL_ABI_MANIFEST,
                )
            callable_value = _resolve(entry.abi_callable)
            if callable_value.__name__ in _GENERIC_NAMES:
                raise PineRuntimeError(
                    "generic dispatch is forbidden in generated ABI",
                    code=PL_ABI_MANIFEST,
                )
            continue
        if entry.abi_callable is not None or entry.diagnostic is None:
            raise PineRuntimeError(
                f"unsupported ABI row is not fail-closed: {identity}",
                code=PL_ABI_MANIFEST,
            )


def build_manifest() -> dict[str, object]:
    from pinelib.abi.manifest_v2_builder import build_manifest_v2

    _validate_catalog_entries()
    return build_manifest_v2(
        CATALOG,
        resolve=_resolve,
        inspect_parameters=_parameters,
    )


def write_manifest(path: Path) -> dict[str, object]:
    manifest = build_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(manifest) + b"\n")
    return manifest


def check_manifest(path: Path) -> None:
    expected = canonical_json(build_manifest()) + b"\n"
    try:
        actual = path.read_bytes()
    except FileNotFoundError as error:
        raise PineRuntimeError(
            "materialized target manifest is missing", code=PL_ABI_MANIFEST
        ) from error
    if actual != expected:
        raise PineRuntimeError(
            "materialized target manifest drift", code=PL_ABI_MANIFEST
        )
