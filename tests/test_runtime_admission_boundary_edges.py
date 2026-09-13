"""Runtime ABI rejection, lexical cleanup, and scratch-state admission regressions."""

from dataclasses import replace

import pytest

from pinelib import CallbackFrame
from pinelib.abi import math as math_abi
from pinelib.abi import metadata, primitives
from pinelib.core import is_na, na
from pinelib.errors import PineRuntimeError
from pinelib.reference.heap import RuntimeReferenceHeap
from pinelib.runtime.delegated import DelegatedCapabilityDispatcher, DelegatedInvocation
from tests.stage3_helpers import language, session, span


@pytest.mark.parametrize(
    "name,value,expected",
    [
        ("acos", 1, 0),
        ("asin", 0, 0),
        ("atan", 0, 0),
        ("cos", 0, 1),
        ("exp", 0, 1),
        ("log10", 100, 2),
        ("sin", 0, 0),
        ("tan", 0, 0),
        ("todegrees", 0, 0),
        ("toradians", 0, 0),
        ("sign", -2, -1),
    ],
)
def test_math_abi_has_exact_special_values_and_na_propagation(name, value, expected):
    fn = getattr(math_abi, name + "_v1")
    assert fn(value) == expected
    assert is_na(fn(na))
    assert math_abi.sum_v1(2, 3) == 5
    assert is_na(math_abi.sum_v1(na, 3))


@pytest.mark.parametrize(
    "name,expected",
    [
        ("syminfo_prefix", "BINANCE"),
        ("syminfo_currency", "USDT"),
        ("syminfo_basecurrency", "BTC"),
        ("syminfo_timezone", "UTC"),
        ("syminfo_type", "crypto"),
        ("syminfo_mintick", 0.01),
        ("syminfo_pointvalue", 1),
        ("syminfo_mincontract", 0.001),
        ("timeframe_multiplier", 15),
        ("timeframe_isdaily", False),
        ("timeframe_isweekly", False),
        ("timeframe_ismonthly", False),
    ],
)
def test_session_metadata_abi_projects_fixed_identity(name, expected):
    assert getattr(metadata, name + "_v1")(session()) == expected


def test_session_barstate_abi_projects_frame_flags():
    rt = session()
    frame = CallbackFrame(
        "HISTORICAL_EVAL", 0, is_last_bar=True, is_last_confirmed_history=True
    )
    assert metadata.barstate_islast_v1(rt, frame) is True
    assert metadata.barstate_ishistory_v1(rt, frame) is True
    assert metadata.barstate_isrealtime_v1(rt, frame) is False
    assert metadata.barstate_islastconfirmedhistory_v1(rt, frame) is True


def test_language_call_scope_validation_and_exception_cleanup():
    rt = session()
    tx = rt.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    for value in [None, "", 1]:
        with pytest.raises(PineRuntimeError):
            tx.scoped_id_v1(value)
    for callsite, fn, args in [
        ("c", None, {}),
        ("c", lambda: 1, []),
        ("", lambda: 1, {}),
    ]:
        with pytest.raises(PineRuntimeError):
            primitives.invoke_function_v1(tx, callsite, fn, args)

    def bad():
        raise ValueError("nested failure")

    with pytest.raises(ValueError):
        tx.invoke_function_v1("c", bad, {})
    assert tx.scoped_id_v1("x") == "x"
    tx._function_path = ("nested",) * 64
    with pytest.raises(PineRuntimeError, match="depth"):
        tx.invoke_function_v1("c", lambda: 1, {})
    tx._function_path = ()
    assert primitives.invoke_function_v1(tx, "c", lambda x: x + 1, {"x": 2}) == 3
    assert primitives.once_v1(tx, "once", lambda: True) is True
    assert primitives.once_v1(tx, "once", lambda: True) is False
    assert is_na(tx.history_value_v1("expr", 7, 1, "int"))
    for base, offset in [("missing", 1), (7, 1)]:
        with pytest.raises(PineRuntimeError):
            primitives.series_history_v1(tx, base, offset)
    tx.set_series("x", 1, "int")
    with pytest.raises(PineRuntimeError, match="offset"):
        primitives.series_history_v1(tx, "x", True)
    tx.abort()


def test_dynamic_range_rechecks_na_and_exact_type():
    rt = session()
    tx = rt.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    assert list(primitives.range_v1(tx, na, lambda: 2, 1)) == []
    stops = iter([2, na])
    assert list(tx.range_v1(0, lambda: next(stops), 1)) == [0]
    stops = iter([2, True])
    gen = tx.range_v1(0, lambda: next(stops), 1)
    assert next(gen) == 0
    with pytest.raises(PineRuntimeError, match="boundary"):
        next(gen)
    tx.abort()


@pytest.mark.parametrize(
    "method",
    ["declare_reference_v1", "write_reference_v1", "declare_enum_v1", "write_enum_v1"],
)
def test_typed_binding_modes_are_exact(method):
    rt = session()
    tx = rt.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError, match="mode"):
        getattr(tx, method)("s", "invalid", lambda: na, "array<int>")
    tx.abort()


def test_missing_runtime_context_cannot_be_invented():
    rt = session()
    rt.timeframe = None
    tx = rt.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    for name in ["value_open", "value_last_bar_index", "value_timeframe_period"]:
        with pytest.raises(PineRuntimeError):
            getattr(tx, name)
    with pytest.raises(PineRuntimeError):
        tx._check_reference_binding(na, "int")
    tx.abort()


@pytest.mark.parametrize("method", ["iter_map_v1", "iter_matrix_v1"])
def test_modern_collection_iterators_reject_legacy_versions(method):
    rt = session(4)
    tx = rt.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    with pytest.raises(PineRuntimeError):
        if method == "iter_map_v1":
            tx.iter_map_v1(None)
        else:
            next(tx.iter_matrix_v1(None, "source"))
    tx.abort()


@pytest.mark.parametrize(
    "field,value",
    [
        ("sequence", True),
        ("sequence", -2),
        ("slots", {}),
        ("series", []),
        ("references", []),
        ("alerts", []),
        ("visuals", []),
        ("requests", []),
        ("series", {"x": 1}),
        ("extra", 1),
    ],
)
def test_unsealed_scratch_state_decoding_rejects_shape_without_mutating_live_state(
    field, value
):
    rt = session()
    baseline = rt._state_json()
    corrupted = dict(baseline, **{field: value})
    with pytest.raises(PineRuntimeError):
        rt._decode_runtime_state(corrupted)
    assert rt._state_json() == baseline


@pytest.mark.parametrize(
    "field,value",
    [("owner", ""), ("source_span", None), ("sequence", True), ("ordinal", -1)],
)
def test_delegated_invocation_rejects_malformed_identity(field, value):
    inv = DelegatedInvocation(
        "owner",
        "schema",
        "cap",
        "symbol",
        "overload",
        {},
        "site",
        span(),
        0,
        "HISTORICAL_EVAL",
        False,
        True,
        None,
        0,
        0,
        0,
    )
    assert inv.to_dict()["invocation_id"] == inv.invocation_id
    with pytest.raises(PineRuntimeError):
        replace(inv, **{field: value})


def test_delegated_registration_and_value_boundary_are_fail_closed():
    for handlers in [{("a", "b"): lambda: 1}, {("a", "b", "c"): 1}]:
        with pytest.raises(PineRuntimeError):
            DelegatedCapabilityDispatcher(handlers)
    for values in [{("a", "b"): 1}, {("a", "b", "c"): float("inf")}]:
        with pytest.raises(PineRuntimeError):
            DelegatedCapabilityDispatcher({}, values=values)
    with pytest.raises(PineRuntimeError):
        DelegatedCapabilityDispatcher({}).resolve_value("", "s", "c")


def test_heap_kind_payload_and_iterator_lifetime_are_enforced():
    heap = RuntimeReferenceHeap(language())
    array = heap.create("array", "array", "int", (1, 2))
    matrix = heap.create(
        "matrix", "matrix", "int", {"rows": 1, "columns": 1, "values": [3]}
    )
    mapping = heap.create("map", "map", "string,int", [["x", 1]])
    for operation in [
        lambda: heap.matrix_dimensions(array),
        lambda: heap.create_array_slice(mapping, 0, 1, "slice"),
        lambda: heap.validate_intrabar_binding(1),
    ]:
        with pytest.raises(PineRuntimeError):
            operation()
    assert heap.validate_intrabar_binding(na) is None
    for handle, operation in [
        (matrix, lambda: heap.matrix_dimensions(matrix)),
        (mapping, lambda: heap.map_iteration(mapping).__enter__()),
    ]:
        item = heap._get(handle)
        old = item.working
        item.working = 1
        with pytest.raises(PineRuntimeError):
            operation()
        item.working = old
    with pytest.raises(PineRuntimeError), heap.map_iteration(array):
        pass
    with heap.map_iteration(mapping) as iterator, pytest.raises(PineRuntimeError):
        heap.mutate_payload(mapping, [1])
    with pytest.raises(StopIteration):
        next(iterator)
    # A live iterator also defends against a corrupted lexical guard.
    with heap.map_iteration(mapping) as live:
        heap._map_iterations[mapping.object_id] = 0
        with pytest.raises(PineRuntimeError, match="lifetime"):
            next(live)
        heap._map_iterations[mapping.object_id] = 1
    legacy = RuntimeReferenceHeap(language(4))
    old = legacy.create("a", "array", "int", [1])
    with pytest.raises(PineRuntimeError):
        legacy.retain_intrabar(old)
