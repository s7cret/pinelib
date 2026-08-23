"""Strict Intent v2.2 field and source-provenance validation."""

from __future__ import annotations

import re
from collections.abc import Mapping

_CONTENT_HASH_RE = re.compile(r"^sha256:(?!0{64}$)[0-9a-f]{64}$")
_SOURCE_SPAN_FIELDS = (
    "start_offset",
    "end_offset",
    "start_line",
    "start_col",
    "end_line",
    "end_col",
)
_UNKNOWN_SOURCE_SPAN: dict[str, object | None] = {
    "known": False,
    "source_hash": None,
    "start_offset": None,
    "end_offset": None,
    "start_line": None,
    "start_col": None,
    "end_line": None,
    "end_col": None,
}
_ALLOWED_BUSINESS_FIELDS: dict[str, frozenset[str]] = {
    "entry": frozenset(
        {"order_id", "direction", "qty", "stop", "limit", "oca_name", "oca_type", "comment"}
    ),
    "order": frozenset(
        {"order_id", "direction", "qty", "stop", "limit", "oca_name", "oca_type", "comment"}
    ),
    "exit": frozenset(
        {
            "order_id",
            "qty",
            "qty_percent",
            "stop",
            "limit",
            "profit",
            "loss",
            "trail_price",
            "trail_points",
            "trail_offset",
            "from_entry",
            "oca_name",
            "comment",
        }
    ),
    "close": frozenset({"qty", "qty_percent", "from_entry", "comment", "immediately"}),
    "close_all": frozenset({"comment", "immediately"}),
    "cancel": frozenset({"order_id"}),
    "cancel_all": frozenset(),
    "risk": frozenset({"risk_rule", "risk_value", "risk_unit", "risk_scope"}),
}


def direction(value: object) -> str:
    normalized = str(value).strip().upper()
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    return normalized


def reject_unrelated_business_fields(kind: str, values: Mapping[str, object]) -> None:
    allowed = _ALLOWED_BUSINESS_FIELDS.get(kind)
    if allowed is None:
        raise ValueError(f"unsupported intent kind: {kind!r}")
    unrelated = sorted(
        name for name, value in values.items() if value is not None and name not in allowed
    )
    if unrelated:
        raise ValueError(f"{kind} intent received unrelated fields: {', '.join(unrelated)}")


def unknown_source_provenance() -> dict[str, object | None]:
    """Return the explicit Contracts RC4 unknown-source shape."""

    return dict(_UNKNOWN_SOURCE_SPAN)


def source_span(
    value: Mapping[str, object] | object | None,
    *,
    strict_production: bool = False,
    expected_source_hash: str | None = None,
) -> dict[str, object]:
    if value is None:
        if strict_production:
            raise ValueError("strict direct intent recording requires an explicit source_span")
        return unknown_source_provenance()
    if not isinstance(value, Mapping):
        raise TypeError("source_span must be a mapping")

    known = value.get("known")
    if known is False:
        expected_unknown = unknown_source_provenance()
        if dict(value) != expected_unknown:
            raise ValueError("unknown source_span must use known=false and null provenance fields")
        return expected_unknown

    if known is not True:
        # Legacy offset-only values do not establish provenance. Validate their
        # supplied offsets so malformed input is not silently hidden, then mark
        # the source unknown rather than inventing a hash or line-one span.
        for field in _SOURCE_SPAN_FIELDS:
            if field in value:
                raw = value[field]
                if isinstance(raw, bool) or not isinstance(raw, int):
                    raise TypeError(f"source_span.{field} must be an integer")
        if strict_production:
            raise ValueError("strict source_span must explicitly declare known=true or known=false")
        return unknown_source_provenance()

    if set(value) != {"known", "source_hash", *_SOURCE_SPAN_FIELDS}:
        raise ValueError("known source_span must contain the complete RC4 provenance shape")
    source_hash = value.get("source_hash")
    if not isinstance(source_hash, str) or _CONTENT_HASH_RE.fullmatch(source_hash) is None:
        raise ValueError("source_span.source_hash must be a nonzero sha256 content hash")
    if expected_source_hash is not None and source_hash != expected_source_hash:
        raise ValueError("source_span.source_hash must match execution_context.source_hash")

    span: dict[str, object] = {"known": True, "source_hash": source_hash}
    for field in _SOURCE_SPAN_FIELDS:
        raw = value[field]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise TypeError(f"source_span.{field} must be an integer")
        span[field] = raw
    return span
