"""Closed admission for modern bar-preserving extrema state.

The old valid-sample buffer discarded NA positions and cannot be upgraded by
renaming its schema. Unrelated TA owners remain outside this bounded contract.
"""
from __future__ import annotations

import math

from pinelib.core.values import is_na
from pinelib.errors import PL_RESOURCE_LIMIT, PL_TA_STATE, PineRuntimeError
from pinelib.state.checkpoint import from_portable

EXTREMA = frozenset({"ta.highest", "ta.lowest"})
_RESERVED_SCHEMA_PREFIXES = tuple(name + ".state." for name in sorted(EXTREMA))


def validate_extrema_payload(owner: str, value: object, max_observations: int) -> list:
    if type(value) is not dict or set(value) != {"kernel", "bars"} or value["kernel"] != owner:
        raise PineRuntimeError("extrema state payload schema/kernel mismatch", code=PL_TA_STATE)
    bars = value["bars"]
    if type(bars) is not list:
        raise PineRuntimeError("extrema bar history must be a list", code=PL_TA_STATE)
    if len(bars) > max_observations:
        raise PineRuntimeError("extrema retained history limit exceeded", code=PL_RESOURCE_LIMIT)
    if any(not is_na(item) and (type(item) is not float or not math.isfinite(item)) for item in bars):
        raise PineRuntimeError("extrema history requires finite floats or canonical Pine NA", code=PL_TA_STATE)
    return bars


def validate_extrema_slots(rows: list, *, pine_version: int, max_observations: int) -> None:
    """Validate decoded slot metadata at every scratch checkpoint boundary."""
    for row in rows:
        owner, schema = row["owner"], row["schema_version"]
        if owner not in EXTREMA and not schema.startswith(_RESERVED_SCHEMA_PREFIXES):
            continue
        if pine_version < 5:
            if owner not in EXTREMA or schema != owner + ".state.v1":
                raise PineRuntimeError("extrema state revision differs from Pine version", code=PL_TA_STATE)
            continue
        if owner in EXTREMA and schema == owner + ".state.v1":
            raise PineRuntimeError("legacy extrema state lost NA positions; replay the original input from the beginning", code=PL_TA_STATE)
        if owner not in EXTREMA or schema != owner + ".state.v2" or row["varip"]:
            raise PineRuntimeError("extrema slot owner/schema/persistence mismatch", code=PL_TA_STATE)
        committed = validate_extrema_payload(owner, from_portable(row["committed"]), max_observations)
        validate_extrema_payload(owner, from_portable(row["working"]), max_observations)
        if not row["committed_exists"] and committed:
            raise PineRuntimeError("uncommitted extrema slot has nonempty initial history", code=PL_TA_STATE)
