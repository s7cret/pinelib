from __future__ import annotations

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na, na
from pinelib.abi.primitives import bool_v1, int_v1, logical_lazy_v1, na_v1
from pinelib.core.values import pine_binary, pine_bool, pine_bool_cast, pine_int, pine_unary
from pinelib.errors import PineRuntimeError


def ctx(version: int) -> RuntimeLanguageContext:
    return RuntimeLanguageContext(
        version,
        "2026-09-16",
        f"pine-v{version}",
        "sha256:" + str(version) * 64,
        "compiler_annotation",
    )


def session(version: int = 6) -> RuntimeSession:
    return RuntimeSession(ctx(version))


@pytest.mark.parametrize("version", range(1, 6))
def test_legacy_implicit_numeric_bool_is_version_exact(version: int) -> None:
    language = ctx(version)
    assert pine_bool(0, language) is False
    assert pine_bool(0.0, language) is False
    assert pine_bool(1, language) is True
    assert pine_bool(-0.25, language) is True
    assert is_na(pine_bool(na, language))


def test_v6_implicit_bool_rejects_numeric_na_transport_and_python_truthiness() -> None:
    language = ctx(6)
    assert pine_bool(True, language) is True
    assert pine_bool(False, language) is False
    for value in (0, 1, 0.5, -1.0, na, None, "x", [], object()):
        with pytest.raises(PineRuntimeError):
            pine_bool(value, language)


@pytest.mark.parametrize("version", range(1, 6))
def test_explicit_bool_cast_preserves_legacy_na(version: int) -> None:
    language = ctx(version)
    assert pine_bool_cast(0, language) is False
    assert pine_bool_cast(1, language) is True
    assert is_na(pine_bool_cast(na, language))


def test_v6_explicit_bool_cast_is_two_state() -> None:
    language = ctx(6)
    assert pine_bool_cast(0, language) is False
    assert pine_bool_cast(0.0, language) is False
    assert pine_bool_cast(-2, language) is True
    assert pine_bool_cast(na, language) is False
    for value in (None, "", "x", [], object()):
        with pytest.raises(PineRuntimeError):
            pine_bool_cast(value, language)


def test_int_cast_truncates_toward_zero_and_never_accepts_python_bool_or_null() -> None:
    assert pine_int(3) == 3
    assert pine_int(3.9) == 3
    assert pine_int(-3.9) == -3
    assert is_na(pine_int(na))
    for value in (True, False, None, "3"):
        with pytest.raises(PineRuntimeError):
            pine_int(value)


@pytest.mark.parametrize("version", range(1, 7))
def test_condition_boundary_distinguishes_pine_na_from_transport_null(version: int) -> None:
    s = session(version)
    tx = s.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    if version <= 5:
        assert tx.condition_v1(na) is False
        assert tx.condition_v1(0) is False
        assert tx.condition_v1(2) is True
    else:
        for value in (na, 0, 2):
            with pytest.raises(PineRuntimeError):
                tx.condition_v1(value)
    with pytest.raises(PineRuntimeError):
        tx.condition_v1(None)
    with pytest.raises(PineRuntimeError):
        tx.condition_v1("x")
    tx.abort()



@pytest.mark.parametrize("version", range(1, 7))
def test_false_zero_na_and_missing_remain_distinct(version: int) -> None:
    language = ctx(version)
    assert pine_binary("==", False, 0, language) is False
    assert pine_binary("!=", False, 0, language) is True
    assert na is not False

    s = session(version)
    tx = s.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    tx.set_series("number", 1.0, "float")
    # Storage-level missing history is transport absence; the Pine operator
    # materializes it as the language-level na marker.
    assert s.series["number"].read(1) is None
    assert tx.op_series_history("number", 1) is na
    tx.abort()

def test_transport_none_is_not_pine_na_in_operators_or_na_predicate() -> None:
    s = session(6)
    tx = s.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError):
        pine_binary("==", None, na, s.language)
    with pytest.raises(PineRuntimeError):
        pine_unary("-", None, s.language)
    with pytest.raises(PineRuntimeError):
        na_v1(tx, None)
    assert na_v1(tx, na) is True
    tx.abort()


def test_compiled_bool_and_int_primitives_use_runtime_contract() -> None:
    s5 = session(5)
    tx5 = s5.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    assert is_na(bool_v1(tx5, na))
    assert bool_v1(tx5, 3) is True
    tx5.abort()

    s6 = session(6)
    tx6 = s6.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    assert bool_v1(tx6, na) is False
    assert bool_v1(tx6, 0) is False
    assert bool_v1(tx6, 3) is True
    assert int_v1(4.9) == 4
    tx6.abort()


def _seed_series(s: RuntimeSession, name: str = "x", dtype: str = "float") -> None:
    tx = s.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    tx.set_series(name, True if dtype == "bool" else 1.0, dtype)
    tx.commit()


def test_history_reservation_is_transactional_and_checkpointed() -> None:
    s = session(6)
    _seed_series(s)
    assert s.series["x"].reserved_history == 0

    tx = s.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    tx.set_series("x", 2.0, "float")
    assert tx.op_series_history("x", 12) is na
    assert s.series["x"].working_reserved_history == 12
    tx.abort()
    assert s.series["x"].reserved_history == 0
    assert s.series["x"].working_reserved_history == 0

    tx = s.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    tx.set_series("x", 2.0, "float")
    assert tx.op_series_history("x", 12) is na
    tx.commit()
    assert s.series["x"].reserved_history == 12

    restored = session(6)
    restored.restore(s.checkpoint().to_dict())
    assert restored.series["x"].reserved_history == 12
    assert restored.series["x"].working_reserved_history == 12


def test_lazy_conditional_history_does_not_reserve_unexecuted_branch() -> None:
    s = session(6)
    _seed_series(s)
    tx = s.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    tx.set_series("x", 2.0, "float")
    assert logical_lazy_v1(tx, "and", False, lambda: tx.op_series_history("x", 500)) is False
    assert s.series["x"].working_reserved_history == 0
    tx.abort()


def test_history_limits_and_dynamic_offsets_fail_closed() -> None:
    s = session(6)
    _seed_series(s, "x")
    tx = s.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    tx.set_series("x", 2.0, "float")
    assert tx.op_series_history("x", 5000) is na
    with pytest.raises(PineRuntimeError):
        tx.op_series_history("x", 5001)
    for invalid in (True, 1.0, -1, "1"):
        with pytest.raises(PineRuntimeError):
            tx.op_series_history("x", invalid)
    tx.abort()


def test_builtin_price_series_keeps_10000_bar_limit() -> None:
    s = session(6)
    _seed_series(s, "close")
    tx = s.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    tx.set_series("close", 2.0, "float")
    assert tx.op_series_history("close", 10_000) is na
    with pytest.raises(PineRuntimeError):
        tx.op_series_history("close", 10_001)
    tx.abort()
