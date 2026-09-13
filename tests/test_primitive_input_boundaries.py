"""Public primitive and admitted input boundaries with explicit independent inputs."""

import operator

import pytest

from pinelib import CallbackFrame
from pinelib.abi import input as inputs_abi
from pinelib.abi import primitives
from pinelib.core import is_na
from pinelib.core.values import pine_binary, pine_unary
from pinelib.errors import PineRuntimeError
from pinelib.input import InputRegistry, InputSpec
from pinelib.input.admission import admit_input_descriptors
from pinelib.runtime import BarValues
from tests.stage3_helpers import inputs, language, session


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize(
    "name,fn",
    [
        ("+", operator.add),
        ("-", operator.sub),
        ("*", operator.mul),
        ("<", operator.lt),
        ("<=", operator.le),
        (">", operator.gt),
        (">=", operator.ge),
    ],
)
def test_numeric_operator_abi_matches_integer_arithmetic(version, name, fn):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    assert primitives.operator_binary_v1(tx, name, -7, 3) == fn(-7, 3)
    assert primitives.operator_unary_v1(tx, "-", 7) == -7
    assert primitives.operator_unary_v1(tx, "+", 7) == 7
    tx.commit()


@pytest.mark.parametrize("version", range(1, 7))
def test_string_division_remainder_and_na_operator_boundaries(version):
    ctx = language(version)
    assert pine_binary("+", "ab", "cd", ctx) == "abcd"
    assert pine_binary("/", -7, 2, ctx) == (-3 if version < 6 else -3.5)
    assert pine_binary("/", -7.0, 2, ctx) == -3.5
    assert pine_binary("%", -7, 3, ctx) == -1
    assert pine_binary("%", -7.5, 3, ctx) == -1.5
    assert pine_binary("%", 7, -3, ctx) == 1
    for op in ["%", "/"]:
        with pytest.raises(PineRuntimeError, match="zero"):
            pine_binary(op, 1, 0, ctx)
    for op in ["-", "+"]:
        assert is_na(pine_unary(op, None, ctx))
    assert pine_unary("not", False, ctx) is True
    if version < 6:
        assert is_na(pine_unary("not", None, ctx))
    else:
        with pytest.raises(PineRuntimeError):
            pine_unary("not", None, ctx)
    for fn, args in [(pine_unary, ("unknown", 1)), (pine_binary, ("unknown", 1, 2))]:
        with pytest.raises(PineRuntimeError):
            fn(*args, ctx)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("bool", False),
        ("int", 3),
        ("float", 1.5),
        ("string", "b"),
        ("time", 1700000000000),
        ("price", 2.5),
        ("symbol", "BINANCE:BTCUSDT"),
        ("timeframe", "15"),
        ("session", "0900-1700:23456"),
        ("color", "#ffffff"),
        ("source", "hl2"),
    ],
)
def test_input_abi_reads_typed_registry_not_default(name, expected):
    assert getattr(inputs_abi, name + "_v1")(inputs(), name) == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("open", 2),
        ("high", 10),
        ("low", 2),
        ("close", 6),
        ("volume", 9),
        ("hl2", 6),
        ("hlc3", 6),
        ("ohlc4", 5),
        ("hlcc4", 6),
    ],
)
def test_source_input_is_evaluated_against_current_bar(name, expected):
    registry = InputRegistry([InputSpec("s", "source", name, name)])
    runtime = session()
    tx = runtime.begin(
        CallbackFrame("HISTORICAL_EVAL", 0), values=BarValues(2, 10, 2, 6, 9, 0, 1)
    )
    assert inputs_abi.generic_v1(tx, registry, "s") == expected
    assert inputs_abi.generic_v1(tx, runtime.inputs, "int") == 3
    tx.abort()


@pytest.mark.parametrize(
    "field,value",
    [
        ("unknown", 0),
        ("alias", ""),
        ("alias", 1),
        ("title", 1),
        ("group", None),
        ("inline", False),
        ("tooltip", []),
        ("confirm", 1),
        ("options", {}),
    ],
)
def test_malformed_input_metadata_never_enters_registry(field, value):
    row = {"input_id": "i", "kind": "int", "default": 1, field: value}
    with pytest.raises(PineRuntimeError):
        admit_input_descriptors({"i": row}, None)


@pytest.mark.parametrize(
    "descriptors,overrides",
    [
        ([], None),
        ({}, []),
        ({1: {}}, None),
        ({"i": None}, None),
        ({"i": {"input_id": "other"}}, None),
        ({"i": {"input_id": "i", "kind": "int"}}, None),
        ({"i": {"input_id": "i", "kind": "int", "default": 1}}, {1: 2}),
        ({"i": {"input_id": "i", "kind": "source", "default": "external"}}, None),
    ],
)
def test_invalid_descriptor_shapes_fail_closed(descriptors, overrides):
    with pytest.raises(PineRuntimeError):
        admit_input_descriptors(descriptors, overrides)


def test_alias_resolution_is_unique_and_cannot_duplicate_direct_override():
    row = {"input_id": "i", "kind": "int", "default": 1, "alias": "n"}
    admitted = admit_input_descriptors({"i": row}, {"n": 3})
    assert InputRegistry(admitted).get("i") == 3
    for overrides in [{"i": 2, "n": 3}, {"unknown": 2}]:
        with pytest.raises(PineRuntimeError):
            admit_input_descriptors({"i": row}, overrides)
    with pytest.raises(PineRuntimeError):
        admit_input_descriptors({"i": row, "j": dict(row, input_id="j")}, {"n": 2})


@pytest.mark.parametrize("version", [5, 6])
def test_na_predicate_and_boolean_short_circuit_are_explicit(version):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    assert primitives.na_v1(tx, None) is True
    assert primitives.na_v1(tx, 1) is False
    if version == 5:
        assert primitives.na_v1(tx, False) is False
    else:
        with pytest.raises(PineRuntimeError):
            primitives.na_v1(tx, False)
    calls = []

    def right():
        calls.append(1)
        return True

    assert primitives.logical_lazy_v1(tx, "and", False, right) is False
    assert primitives.logical_lazy_v1(tx, "or", True, right) is True
    assert calls == []
    assert primitives.logical_lazy_v1(tx, "and", True, right) is True
    assert calls == [1]
    assert primitives.logical_eager_v1(tx, "and", True, False) is False
    assert primitives.logical_eager_v1(tx, "or", False, True) is True
    with pytest.raises(PineRuntimeError):
        primitives.logical_eager_v1(tx, "xor", True, True)
    with pytest.raises(PineRuntimeError):
        primitives.logical_lazy_v1(tx, "xor", True, right)
    tx.abort()
