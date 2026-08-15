"""Canonical SemanticProfile resolution. No silent getattr fallbacks."""

from __future__ import annotations

from typing import Any

from openpine_contracts import SemanticProfile

from pinelib.errors import (
    PL_SEMANTIC_PROFILE_REQUIRED,
    PL_UNKNOWN_SEMANTIC_PROFILE,
    PineRuntimeError,
)

_LEGACY_SOURCES = frozenset(
    {
        "openpine.frontend.v1",
        "compat.v4",
        "migration.4x",
    }
)


class SemanticProfileError(PineRuntimeError):
    pass


def resolve_semantic_profile(
    value: object,
    *,
    source: str = "runtime",
) -> SemanticProfile:
    if value is None:
        if source in _LEGACY_SOURCES:
            return SemanticProfile.LEGACY_4X
        raise SemanticProfileError(
            f"{PL_SEMANTIC_PROFILE_REQUIRED}: semantic profile missing for {source}",
            code=PL_SEMANTIC_PROFILE_REQUIRED,
        )
    if isinstance(value, SemanticProfile):
        return value
    text = str(value).strip()
    try:
        return SemanticProfile(text)
    except ValueError as exc:
        raise SemanticProfileError(
            f"{PL_UNKNOWN_SEMANTIC_PROFILE}: {text!r}",
            code=PL_UNKNOWN_SEMANTIC_PROFILE,
        ) from exc


def security_lookup_index(runtime: Any) -> int:
    profile = resolve_semantic_profile(
        getattr(getattr(runtime, "config", None), "semantic_profile", None),
        source="runtime",
    )
    bar_index = int(runtime.bar_index)
    if profile is SemanticProfile.LEGACY_4X and runtime.current_bar is not None:
        return bar_index + 1
    return bar_index
