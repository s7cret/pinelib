from __future__ import annotations

import pytest

from pinelib import CallbackFrame, RuntimePolicies, RuntimeSession, is_na, na
from pinelib.abi import math as math_abi
from pinelib.abi.builder import build_manifest
from pinelib.errors import PineRuntimeError
from tests.stage3_helpers import language, session


# Reference: https://www.tradingview.com/pine-script-reference/v6/#fun_math.round
# Hand-selected exact decimal ties and adjacent values, not outputs from the kernel.
@pytest.mark.parametrize(
    ("number", "expected"),
    [(2.5, 3), (1.5, 2), (0.5, 1), (-0.5, 0), (-1.5, -1), (-2.5, -2), (-1.5001, -2), (-1.4999, -1)],
)
def test_round_integer_ties_up(number, expected):
    actual = math_abi.round_v1(number)
    assert type(actual) is int
    assert actual == expected


@pytest.mark.parametrize(
    ("number", "precision", "expected"),
    [
        (1.25, 1, 1.3),
        (-1.25, 1, -1.2),
        (-1.251, 1, -1.3),
        (-1.249, 1, -1.2),
        (2.5, 0, 3.0),
        (-2.5, 0, -2.0),
        (125.0, -1, 130.0),
        (-125.0, -1, -120.0),
        (0.0, 0, 0.0),
    ],
)
def test_round_explicit_precision_always_returns_float(number, precision, expected):
    actual = math_abi.round_v1(number, precision)
    assert type(actual) is float
    assert actual == expected


@pytest.mark.parametrize(
    ("number", "tick", "expected"),
    [
        (1.225, 0.05, 1.25),
        (-1.225, 0.05, -1.2),
        (-1.226, 0.05, -1.25),
        (-1.224, 0.05, -1.2),
        (-0.005, 0.01, 0.0),
        (0.125, 0.25, 0.25),
        (-0.125, 0.25, 0.0),
    ],
)
def test_mintick_uses_the_same_ties_up_rule(number, tick, expected):
    assert math_abi.round_to_mintick_v1(number, tick) == expected


@pytest.mark.parametrize("version", [5, 6])
def test_mintick_compiled_target_reads_injected_instrument(version):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    assert math_abi.round_to_mintick_context_v1(tx, -1.225) == -1.22
    tx.commit()
    with pytest.raises(PineRuntimeError):
        math_abi.round_to_mintick_context_v1(tx, 1.0)
    missing_context = RuntimeSession(language(version), RuntimePolicies())
    tx = missing_context.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError):
        math_abi.round_to_mintick_context_v1(tx, 1.0)
    tx.abort()


@pytest.mark.parametrize("bad", [True, "1", [], float("inf"), float("nan")])
def test_round_rejects_non_pine_numbers(bad):
    with pytest.raises(PineRuntimeError):
        math_abi.round_v1(bad)


@pytest.mark.parametrize("bad", [True, "1", 1.5, [], float("inf")])
def test_round_rejects_non_integer_precision(bad):
    with pytest.raises(PineRuntimeError):
        math_abi.round_v1(1.25, bad)


def test_round_na_and_large_finite_numbers():
    assert is_na(math_abi.round_v1(na))
    assert is_na(math_abi.round_v1(na, 2))
    assert is_na(math_abi.round_v1(1.25, na))
    assert math_abi.round_v1(1e30) == 10**30
    assert math_abi.round_v1(1.25, 10**9) == 1.25
    assert math_abi.round_v1(1.25, -(10**9)) == 0.0


def _row(manifest, name, *, historical=False):
    group = "historical_call_bindings" if historical else "rows"
    return next(row for row in manifest[group] if row["name"] == name)


@pytest.mark.parametrize(
    "name",
    [
        "math.exp",
        "math.round",
        "math.sqrt",
        "math.pow",
        "math.round_to_mintick",
        "ta.macd",
        "ta.rsi",
        "ta.sma",
        "ta.wma",
    ],
)
def test_audited_modern_targets_are_fully_bound(name):
    row = _row(build_manifest(), name)
    assert row["disposition"] == "TARGET_DIRECT"
    assert row["producer_call_forms"] == ["NAMESPACE_FUNCTION"]
    assert row["version_availability"] == [5, 6]
    assert all(binding["binding"] != "UNBOUND_FAIL_CLOSED" for binding in row["parameter_bindings"])


def test_audited_source_parameter_names_and_qualifiers():
    manifest = build_manifest()
    assert _row(manifest, "math.exp")["parameters"] == [
        {"name": "number", "type": "float", "qualifier_max": "series", "required": True}
    ]
    assert [item["name"] for item in _row(manifest, "math.round")["parameters"]] == [
        "number",
        "precision",
    ]
    macd = _row(manifest, "ta.macd")
    assert [item["name"] for item in macd["parameters"]] == [
        "source",
        "fastlen",
        "slowlen",
        "siglen",
    ]
    assert all(item["qualifier_max"] == "simple" for item in macd["parameters"][1:])
    assert _row(manifest, "ta.rsi")["dynamic_length_policy"] == {"length": "SIMPLE_STABLE"}


@pytest.mark.parametrize(
    ("name", "canonical", "parameters"),
    [
        ("exp", "math.exp", ["x"]),
        ("round", "math.round", ["x"]),
        ("macd", "ta.macd", ["source", "fastlen", "slowlen", "siglen"]),
        ("rsi", "ta.rsi", ["x", "y"]),
        ("sqrt", "math.sqrt", ["x"]),
        ("pow", "math.pow", ["base", "exponent"]),
        ("sma", "ta.sma", ["source", "length"]),
        ("wma", "ta.wma", ["source", "length"]),
    ],
)
def test_historical_bindings_preserve_exact_version_and_identity(name, canonical, parameters):
    manifest = build_manifest()
    row = _row(manifest, name, historical=True)
    assert row["symbol_id"] == "pine:function:" + canonical
    assert row["producer_call_forms"] == ["FUNCTION"]
    assert row["version_availability"] == [1, 2, 3, 4]
    assert [item["name"] for item in row["parameters"]] == parameters
    assert all(binding["binding"] != "UNBOUND_FAIL_CLOSED" for binding in row["parameter_bindings"])
    assert (
        manifest["classification"]["official_total"]
        == manifest["official_surface"]["denominator"]
        == len(manifest["rows"])
    )


def test_historical_rsi_does_not_admit_ratio_overload():
    row = _row(build_manifest(), "rsi", historical=True)
    assert row["producer_overload_ids"] == ["pine:function:ta.rsi#overload:0"]


def test_precision_overload_is_limited_to_its_exact_versions():
    manifest = build_manifest()
    modern = _row(manifest, "math.round")
    assert modern["producer_overload_ids"] == [
        "pine:function:math.round#canonical",
        "pine:function:math.round#overload:0",
    ]
    historical = [row for row in manifest["historical_call_bindings"] if row["name"] == "round"]
    assert len(historical) == 2
    integer, precise = historical
    assert integer["producer_overload_ids"] == ["pine:function:math.round#canonical"]
    assert precise["producer_overload_ids"] == ["pine:function:math.round#overload:0"]
    assert precise["version_availability"] == [4]
    assert [item["name"] for item in precise["parameters"]] == ["x", "precision"]
    assert all(item["required"] for item in precise["parameters"])
