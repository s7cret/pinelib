"""Literal comparison evidence; midpoint cases assert local policy, not Pine parity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, na
from pinelib.abi.primitives import operator_binary_v1
from pinelib.core.values import pine_binary
from pinelib.errors import PL_VALUE_DOMAIN, PL_VALUE_TYPE, PineRuntimeError


FIXTURE_PATH = Path(__file__).parent / "fixtures/float_comparison_manual_expected.json"
FIXTURE_SHA = "19ecb5d3fbdc4229b01110b7cbecd0419e6eb9f9d11530b2b19308350d80f8a1"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
OPERATORS = ("==", "!=", "<", "<=", ">", ">=")


def language(version):
    return RuntimeLanguageContext(
        version, "comparison-evidence-v1", f"pine-v{version}",
        "sha256:" + "a" * 64, "compiler_annotation",
    )


def session(version, compact=False):
    runtime = RuntimeSession(language(version))
    runtime.commit_full_identity = not compact
    return runtime


def begin(runtime, sequence, bar, *, realtime=False, final=True):
    return runtime.begin(CallbackFrame(
        "REALTIME_TICK" if realtime else "HISTORICAL_EVAL", sequence,
        bar_index=bar, realtime=realtime, final_tick=final,
    ))


def checkpoint(runtime):
    return json.loads(json.dumps(runtime.checkpoint().to_dict()))


def test_independently_authored_fixture_is_immutable_and_bounded():
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == FIXTURE_SHA
    assert len(FIXTURE["cases"]) == 26
    assert FIXTURE["semantic_sut_executed_before_authoring"] is False
    assert FIXTURE["tradingview_export"] is False
    assert FIXTURE["full_stage2_accepted"] is False
    assert FIXTURE["midpoint_pine_parity"].startswith("UNVERIFIED")


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["case_id"])
def test_literal_comparison_table(version, operator, case):
    expected = case["expected_v6" if version == 6 else "expected_v1_to_v5"]
    assert pine_binary(operator, case["left"], case["right"], language(version)) is expected[operator]


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("operands", [(na, 1.0), (1.0, na), (na, na)])
def test_canonical_na_value_comparisons(version, operator, operands):
    # Native values, not forbidden bare-na literal source syntax.
    expected = FIXTURE["na_v6_expected" if version == 6 else "na_v1_to_v5_native_compatibility"]
    assert pine_binary(operator, *operands, language(version)) is expected[operator]


@pytest.mark.parametrize("version", range(1, 7))
def test_non_numeric_equality_and_pure_integer_domain_are_preserved(version):
    for case in FIXTURE["bool_cases"]:
        assert pine_binary("==", case["left"], case["right"], language(version)) is case["eq"]
        assert pine_binary("!=", case["left"], case["right"], language(version)) is case["ne"]
    assert pine_binary("==", "same", "same", language(version)) is True
    assert pine_binary("!=", "same", "other", language(version)) is True
    assert pine_binary(">", 10**400 + 1, 10**400, language(version)) is True
    assert pine_binary("==", 10**400 + 1, 10**400, language(version)) is False
    for operator in ("<", "<=", ">", ">="):
        with pytest.raises(PineRuntimeError) as error:
            pine_binary(operator, False, True, language(version))
        assert error.value.code == PL_VALUE_TYPE


@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("invalid_left", [False, True])
def test_v6_nonfinite_native_numeric_operands_reject_atomically(operator, invalid, invalid_left):
    runtime = session(6)
    tx = begin(runtime, 0, 0)
    tx.set_series("valid", 7.0)
    tx.commit()
    saved = checkpoint(runtime)
    tx = begin(runtime, 1, 1)
    operands = (invalid, 1.0) if invalid_left else (1.0, invalid)
    # Check the shared value owner independently of the transaction's portable
    # reference-value admission, which also rejects nonfinite inputs.
    with pytest.raises(PineRuntimeError) as error:
        pine_binary(operator, *operands, language(6))
    assert error.value.code == PL_VALUE_TYPE
    with pytest.raises(PineRuntimeError) as error:
        operator_binary_v1(tx, operator, *operands)
    assert error.value.code == PL_VALUE_TYPE
    tx.abort()
    assert checkpoint(runtime) == saved


@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("huge_left", [False, True])
def test_v6_mixed_float_conversion_reports_owner_domain_error(operator, huge_left):
    operands = (10**400, 1.0) if huge_left else (1.0, 10**400)
    with pytest.raises(PineRuntimeError) as error:
        pine_binary(operator, *operands, language(6))
    assert error.value.code == PL_VALUE_DOMAIN


@pytest.mark.parametrize("left,right", [
    (0.0009765625, 0.000976562),
    (0.0029296875, 0.002929688),
    (-0.0009765625, -0.000976562),
    (-0.0029296875, -0.002929688),
])
def test_local_binary_midpoint_policy_is_explicitly_not_a_pine_oracle(left, right):
    # Exact binary midpoints: 1/1024 and 3/1024. The runtime chooses ties-even;
    # TradingView's ninth-digit tie rule has not been independently established.
    expected = {"==": True, "!=": False, "<": False, "<=": True, ">": False, ">=": True}
    for operator in OPERATORS:
        assert pine_binary(operator, left, right, language(6)) is expected[operator]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True], ids=["full", "compact"])
@pytest.mark.parametrize("case_id", ["positive_inside", "negative_inside", "mixed_large_cast"])
def test_real_transaction_abi_trial_abort_retry_and_checkpoint(version, compact, case_id):
    cases = {case["case_id"]: case for case in FIXTURE["cases"]}
    # The table labels are the observation inputs, never generated storage IDs.
    case = cases[case_id]
    expected = case["expected_v6" if version == 6 else "expected_v1_to_v5"]
    runtime = session(version, compact)

    def evaluate(tx, left, right, values):
        tx.set_series("left", left, dtype="int" if type(left) is int else "float")
        tx.set_series("right", right, dtype="int" if type(right) is int else "float")
        for index, operator in enumerate(OPERATORS):
            actual = operator_binary_v1(tx, operator, tx.read_series("left"), tx.read_series("right"))
            assert actual is values[operator]
            tx.set_series(f"comparison-{index}", actual, dtype="bool")

    tx = begin(runtime, 0, 0)
    evaluate(tx, case["left"], case["right"], expected)
    tx.commit()
    baseline = checkpoint(runtime)
    tx = begin(runtime, 1, 1, realtime=True, final=False)
    evaluate(tx, case["left"], case["right"], expected)
    tx.commit()
    # A second tick changes the operands/results, then abort restores bar 0.
    tx = begin(runtime, 2, 1, realtime=True, final=False)
    equal = {"==": True, "!=": False, "<": False, "<=": True, ">": False, ">=": True}
    left_equal = 1 if type(case["left"]) is int else 1.0
    right_equal = 1 if type(case["right"]) is int else 1.0
    evaluate(tx, left_equal, right_equal, equal)
    tx.abort()
    saved = checkpoint(runtime)
    clone = session(version, compact)
    clone.restore(saved)
    assert checkpoint(clone) == saved
    assert clone.sequence == runtime.sequence == 1
    assert baseline["state"]["series"] == saved["state"]["series"]
    for current in (runtime, clone):
        tx = begin(current, 2, 1, realtime=True)
        evaluate(tx, case["left"], case["right"], expected)
        tx.commit()
        tx = begin(current, 3, 2)
        for index, operator in enumerate(OPERATORS):
            assert tx.read_series(f"comparison-{index}", 1) is expected[operator]
        evaluate(tx, case["left"], case["right"], expected)
        tx.commit()
    assert checkpoint(runtime) == checkpoint(clone)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True], ids=["full", "compact"])
def test_na_operand_series_survives_checkpoint_with_versioned_comparison(version, compact):
    expected = FIXTURE["na_v6_expected" if version == 6 else "na_v1_to_v5_native_compatibility"]
    runtime = session(version, compact)
    tx = begin(runtime, 0, 0)
    tx.set_series("missing", na, dtype="float")
    tx.commit()
    clone = session(version, compact)
    clone.restore(checkpoint(runtime))
    for current in (runtime, clone):
        tx = begin(current, 1, 1, realtime=True)
        for operator in OPERATORS:
            assert operator_binary_v1(tx, operator, tx.read_series("missing", 1), 1.0) is expected[operator]
        tx.commit()
    assert checkpoint(runtime) == checkpoint(clone)
