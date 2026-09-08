"""Closed admission for versioned extrema and EMA/MACD state.

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


_EMA_OWNERS = frozenset({"ta.ema", "ta.macd"})
_EMA_SCHEMA_PREFIXES = tuple(name + ".state." for name in sorted(_EMA_OWNERS))
_EMA_PROFILE = "ema_first_source_v1"


def _ema_payload(owner: str, value: object, *, initial: bool = False) -> dict:
    """Admit only the finite, constant-size first-source state representation."""
    if type(value) is not dict or value.get("kernel") != owner or value.get("profile") != _EMA_PROFILE:
        raise PineRuntimeError("EMA/MACD state kernel/profile mismatch", code=PL_TA_STATE)
    base = {"kernel", "profile"}
    if initial:
        if set(value) != base:
            raise PineRuntimeError("uncommitted EMA/MACD state has noninitial committed payload", code=PL_TA_STATE)
        return value
    parameters = value.get("parameters")
    names = {"length"} if owner == "ta.ema" else {"fast_length", "slow_length", "signal_length"}
    if (type(parameters) is not dict or set(parameters) != names
            or any(type(n) is not int or n <= 0 for n in parameters.values())):
        raise PineRuntimeError("EMA/MACD state parameter shape is invalid", code=PL_TA_STATE)
    if owner == "ta.ema":
        if set(value) not in (base | {"parameters"}, base | {"parameters", "value"}):
            raise PineRuntimeError("EMA state payload has invalid fields", code=PL_TA_STATE)
        values = [value["value"]] if "value" in value else []
    else:
        if set(value) != base | {"parameters", "fast", "slow", "signal"}:
            raise PineRuntimeError("MACD state payload has invalid fields", code=PL_TA_STATE)
        parts = [value[key] for key in ("fast", "slow", "signal")]
        if any(type(part) is not dict or set(part) not in (set(), {"value"}) for part in parts):
            raise PineRuntimeError("MACD EMA substate shape is invalid", code=PL_TA_STATE)
        if len({bool(part) for part in parts}) != 1:
            raise PineRuntimeError("MACD EMA substates must seed together", code=PL_TA_STATE)
        values = [part["value"] for part in parts if part]
    if any(type(number) is not float or not math.isfinite(number) for number in values):
        raise PineRuntimeError("EMA/MACD state values must be finite exact floats", code=PL_TA_STATE)
    return value


def validate_ema_slots(rows: list, *, pine_version: int) -> None:
    """Validate all scratch boundaries before live root/child state replacement."""
    for row in rows:
        owner, schema = row["owner"], row["schema_version"]
        if owner not in _EMA_OWNERS and not schema.startswith(_EMA_SCHEMA_PREFIXES):
            continue
        if pine_version < 5:
            if owner not in _EMA_OWNERS or schema != owner + ".state.v1":
                raise PineRuntimeError("EMA/MACD state revision differs from Pine version", code=PL_TA_STATE)
            continue
        if owner in _EMA_OWNERS and schema == owner + ".state.v1":
            raise PineRuntimeError(
                "legacy EMA/MACD seed differs; replay the original input from the beginning", code=PL_TA_STATE)
        if owner not in _EMA_OWNERS or schema != owner + ".state.v2" or row["varip"]:
            raise PineRuntimeError("EMA/MACD slot owner/schema/persistence mismatch", code=PL_TA_STATE)
        committed = _ema_payload(owner, from_portable(row["committed"]), initial=not row["committed_exists"])
        working = _ema_payload(owner, from_portable(row["working"]))
        if row["committed_exists"]:
            if committed["parameters"] != working["parameters"]:
                raise PineRuntimeError("EMA/MACD parameters changed across state portions", code=PL_TA_STATE)
            old_seeded = "value" in committed if owner == "ta.ema" else bool(committed["fast"])
            new_seeded = "value" in working if owner == "ta.ema" else bool(working["fast"])
            if old_seeded and not new_seeded:
                raise PineRuntimeError("EMA/MACD state lost its seed", code=PL_TA_STATE)


_TSI_PROFILE = "tsi_ratio_legacy_seed_v1"
_TSI_STAGES = frozenset({"change_long", "absolute_long", "change_short", "absolute_short"})


def _tsi_payload(value: object, max_observations: int, *, initial: bool = False) -> dict:
    """Closed local stage shapes include actual partial progress after fsum errors."""
    base = {"kernel", "profile"}
    if type(value) is not dict or value.get("kernel") != "ta.tsi" or value.get("profile") != _TSI_PROFILE:
        raise PineRuntimeError("TSI state kernel/profile mismatch", code=PL_TA_STATE)
    if initial:
        if set(value) != base:
            raise PineRuntimeError("uncommitted TSI state has noninitial committed payload", code=PL_TA_STATE)
        return value
    parameters = value.get("parameters")
    if (type(parameters) is not dict or set(parameters) != {"short_length", "long_length"}
            or any(type(n) is not int or n <= 0 for n in parameters.values())):
        raise PineRuntimeError("TSI state parameter shape is invalid", code=PL_TA_STATE)
    if max(parameters.values()) > max_observations:
        raise PineRuntimeError("TSI warmup length exceeds resource limit", code=PL_RESOURCE_LIMIT)
    required = base | {"parameters"}
    stages_present = bool(set(value) & _TSI_STAGES)
    if stages_present:
        required |= _TSI_STAGES | {"previous"}
    elif "previous" in value:
        required.add("previous")
    if set(value) != required:
        raise PineRuntimeError("TSI state payload has invalid fields", code=PL_TA_STATE)
    if "previous" in value and (type(value["previous"]) is not float or not math.isfinite(value["previous"])):
        raise PineRuntimeError("TSI previous source must be a finite exact float", code=PL_TA_STATE)
    if not stages_present:
        return value
    for name in _TSI_STAGES:
        stage = value[name]
        if type(stage) is not dict or set(stage) not in (set(), {"warmup"}, {"warmup", "value"}):
            raise PineRuntimeError("TSI local stage shape is invalid", code=PL_TA_STATE)
        if not stage:
            continue
        warmup = stage["warmup"]
        length = parameters["long_length" if name.endswith("long") else "short_length"]
        if type(warmup) is not list or not 1 <= len(warmup) <= length:
            raise PineRuntimeError("TSI warmup count is invalid", code=PL_TA_STATE)
        values = list(warmup)
        if "value" in stage:
            if len(warmup) != length:
                raise PineRuntimeError("TSI seed lacks a full warmup", code=PL_TA_STATE)
            values.append(stage["value"])
        if any(type(n) is not float or not math.isfinite(n) for n in values):
            raise PineRuntimeError("TSI stage values must be finite exact floats", code=PL_TA_STATE)
        if name.startswith("absolute") and any(n < 0 for n in values):
            raise PineRuntimeError("TSI absolute stage contains a negative value", code=PL_TA_STATE)
    return value


def validate_tsi_slots(rows: list, *, pine_version: int, max_observations: int) -> None:
    """Admit numerical representation, not an invented paired-stage trajectory."""
    for row in rows:
        owner, schema = row["owner"], row["schema_version"]
        if owner != "ta.tsi" and not schema.startswith("ta.tsi.state."):
            continue
        if pine_version < 5:
            if owner != "ta.tsi" or schema != "ta.tsi.state.v1":
                raise PineRuntimeError("TSI state revision differs from Pine version", code=PL_TA_STATE)
            continue
        if owner == "ta.tsi" and schema == "ta.tsi.state.v1":
            raise PineRuntimeError("legacy TSI percentage state; replay the original input from the beginning", code=PL_TA_STATE)
        if owner != "ta.tsi" or schema != "ta.tsi.state.v2" or row["varip"]:
            raise PineRuntimeError("TSI slot owner/schema/persistence mismatch", code=PL_TA_STATE)
        committed = _tsi_payload(from_portable(row["committed"]), max_observations, initial=not row["committed_exists"])
        working = _tsi_payload(from_portable(row["working"]), max_observations)
        if row["committed_exists"]:
            if committed["parameters"] != working["parameters"]:
                raise PineRuntimeError("TSI parameters changed across state portions", code=PL_TA_STATE)
            for name in _TSI_STAGES:
                if "value" in committed.get(name, {}) and "value" not in working.get(name, {}):
                    raise PineRuntimeError("TSI state lost a committed seed", code=PL_TA_STATE)
