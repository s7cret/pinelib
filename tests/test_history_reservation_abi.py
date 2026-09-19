from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimePolicies, RuntimeSession, na
from pinelib.abi import primitives
from pinelib.abi.builder import check_manifest
from pinelib.abi.manifest import load_target_manifest
from pinelib.errors import PineRuntimeError
from pinelib.runtime.metadata import BarValues
from pinelib.runtime.policies import ResourcePolicy
from pinelib.runtime.session import RuntimeTransaction
from pinelib.state.checkpoint import sha


def language(version: int = 1) -> RuntimeLanguageContext:
    return RuntimeLanguageContext(
        version,
        "history-reservation-test",
        f"pine-v{version}",
        "sha256:" + "1" * 64,
        "compiler_annotation",
    )


def transaction(session: RuntimeSession, sequence: int) -> RuntimeTransaction:
    return session.begin(CallbackFrame("HISTORICAL_EVAL", sequence, bar_index=sequence))


def test_reservation_exposes_first_bar_na_and_defers_initializer_once() -> None:
    session = RuntimeSession(language())
    tx = transaction(session, 0)

    assert primitives.reserve_history_v1(tx, "f", "float", "each_bar") is None
    storage = session.series["f"]
    assert storage.dtype == "float"
    assert storage.history_policy == "each_bar"
    assert storage.initialized is False
    assert storage.working is None
    assert storage.evaluated is False
    assert list(storage.committed) == []
    assert tx.op_series_history("f", 1) is na

    calls = 0

    def initializer() -> float:
        nonlocal calls
        calls += 1
        return 2.0

    assert tx.declare_scalar_v1("f", "default", initializer, "float") == 2.0
    assert calls == 1
    assert storage.evaluated is True
    tx.commit()
    assert list(storage.committed) == [2.0]


def test_repeated_reservation_preserves_history_for_native_dependency_order() -> None:
    session = RuntimeSession(language())
    first = session.begin(
        CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0),
        values=BarValues(1.0, 1.0, 1.0, 1.0, 1.0, 0, 0),
    )
    primitives.reserve_history_v1(first, "f", "float", "each_bar")
    d = first.op_series_history("f", 1)
    assert d is na
    first_time = first.value_time
    first_close = first.value_close
    assert type(first_time) is int
    assert type(first_close) is float
    assert first_time == 0
    e = 1.0
    first.declare_scalar_v1("f", "default", lambda: e + first_close, "float")
    first.commit()

    second = session.begin(
        CallbackFrame("HISTORICAL_EVAL", 1, bar_index=1),
        values=BarValues(1.0, 1.0, 1.0, 1.0, 1.0, 1, 1),
    )
    primitives.reserve_history_v1(second, "f", "float", "each_bar")
    primitives.reserve_history_v1(second, "f", "float", "each_bar")
    d = second.op_series_history("f", 1)
    assert type(d) is float
    assert d == 2.0
    second_time = second.value_time
    second_close = second.value_close
    assert type(second_time) is int
    assert type(second_close) is float
    assert second_time != 0
    e = d + 1.0
    second.declare_scalar_v1("f", "default", lambda: e + second_close, "float")
    second.commit()

    assert list(session.series["f"].committed) == [2.0, 4.0]


def test_reservation_abort_retry_checkpoint_and_restore_are_transactional() -> None:
    session = RuntimeSession(language())
    first = transaction(session, 0)
    primitives.reserve_history_v1(first, "f", "int", "each_bar")
    first.abort()
    assert "f" not in session.series

    retry = transaction(session, 1)
    primitives.reserve_history_v1(retry, "f", "int", "each_bar")
    retry.commit()
    assert session.series["f"].initialized is False
    assert list(session.series["f"].committed) == []

    checkpoint = session.checkpoint().to_dict()
    restored = RuntimeSession(language())
    restored.restore(checkpoint)
    resumed = transaction(restored, 2)
    primitives.reserve_history_v1(resumed, "f", "int", "each_bar")
    assert resumed.op_series_history("f", 1) is na
    resumed.declare_scalar_v1("f", "default", lambda: 7, "int")
    resumed.commit()
    assert list(restored.series["f"].committed) == [7]


@pytest.mark.parametrize(
    ("version", "series_id", "dtype", "history_policy"),
    [
        (3, "f", "float", "each_bar"),
        (1, "", "float", "each_bar"),
        (1, 1, "float", "each_bar"),
        (1, "f", "array<float>", "each_bar"),
        (1, "f", "float", "on_evaluation"),
    ],
)
def test_reservation_rejects_unsupported_version_descriptor_and_identity(
    version: int, series_id: object, dtype: str, history_policy: str
) -> None:
    session = RuntimeSession(language(version))
    tx = transaction(session, 0)
    with pytest.raises(PineRuntimeError):
        primitives.reserve_history_v1(tx, series_id, dtype, history_policy)
    tx.abort()


def test_reservation_rejects_descriptor_change_corrupt_storage_and_closed_transaction() -> None:
    session = RuntimeSession(language())
    tx = transaction(session, 0)
    primitives.reserve_history_v1(tx, "f", "int", "each_bar")
    with pytest.raises(PineRuntimeError):
        primitives.reserve_history_v1(tx, "f", "float", "each_bar")
    tx.commit()
    with pytest.raises(PineRuntimeError):
        primitives.reserve_history_v1(tx, "f", "int", "each_bar")

    forged = RuntimeTransaction(session, CallbackFrame("HISTORICAL_EVAL", 1))
    with pytest.raises(PineRuntimeError):
        primitives.reserve_history_v1(forged, "f", "int", "each_bar")

    live = transaction(session, 1)
    session.series["forged"] = object()  # type: ignore[assignment]
    with pytest.raises(PineRuntimeError):
        primitives.reserve_history_v1(live, "forged", "int", "each_bar")
    session.series.pop("forged")
    live.abort()


def test_reservation_rejects_a_non_string_policy_that_compares_equal() -> None:
    class EqualPolicy:
        def __eq__(self, other: object) -> bool:
            return other == "each_bar"

        def __hash__(self) -> int:
            return hash("each_bar")

    session = RuntimeSession(language())
    tx = transaction(session, 0)
    with pytest.raises(PineRuntimeError):
        primitives.reserve_history_v1(tx, "f", "float", EqualPolicy())
    assert "f" not in session.series
    tx.abort()


def test_reservation_enforces_series_resource_limit_without_leaking_series() -> None:
    policies = RuntimePolicies(resource=ResourcePolicy(max_series=1))
    session = RuntimeSession(language(), policies)
    tx = transaction(session, 0)
    primitives.reserve_history_v1(tx, "first", "bool", "each_bar")
    with pytest.raises(PineRuntimeError):
        primitives.reserve_history_v1(tx, "second", "bool", "each_bar")
    assert set(session.series) == {"first"}
    tx.abort()
    assert session.series == {}


def test_history_reservation_operation_manifest_callable_and_hash_are_exact() -> None:
    cache_clear = getattr(load_target_manifest, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()
    manifest = load_target_manifest()
    assert manifest["compiled_history_reservation"] == {
        "revision": 1,
        "operation": "state.reserve_history.v1",
        "capability": "compiler.history_reservation.v1",
        "supported_pine_versions": [1, 2],
        "scalar_types": ["bool", "color", "float", "int", "string"],
        "history_policies": ["each_bar"],
        "reservation": "typed-storage-without-evaluation",
        "rollback": "transactional",
    }
    rows = [
        row
        for row in manifest["compiler_operations"]
        if row["name"] == "state.reserve_history.v1"
    ]
    assert rows == [
        {
            "name": "state.reserve_history.v1",
            "evaluation": "eager",
            "effect": "state",
            "abi_callable": "pinelib.abi.primitives.reserve_history_v1",
            "abi_parameters": [
                {
                    "name": "tx",
                    "position": 0,
                    "kind": "POSITIONAL_OR_KEYWORD",
                    "has_default": False,
                    "annotation": "RuntimeTransaction",
                },
                {
                    "name": "series_id",
                    "position": 1,
                    "kind": "POSITIONAL_OR_KEYWORD",
                    "has_default": False,
                    "annotation": "str",
                },
                {
                    "name": "dtype",
                    "position": 2,
                    "kind": "POSITIONAL_OR_KEYWORD",
                    "has_default": False,
                    "annotation": "str",
                },
                {
                    "name": "history_policy",
                    "position": 3,
                    "kind": "POSITIONAL_OR_KEYWORD",
                    "has_default": False,
                    "annotation": "str",
                },
            ],
            "parameter_bindings": [
                {
                    "abi_parameter": "tx",
                    "binding": "INJECTED",
                    "source": "RUNTIME_TRANSACTION",
                },
                {
                    "abi_parameter": "series_id",
                    "binding": "OPERATION_ARGUMENT",
                    "source_index": 0,
                },
                {
                    "abi_parameter": "dtype",
                    "binding": "OPERATION_ARGUMENT",
                    "source_index": 1,
                },
                {
                    "abi_parameter": "history_policy",
                    "binding": "OPERATION_ARGUMENT",
                    "source_index": 2,
                },
            ],
            "capabilities": ["compiler.history_reservation.v1"],
        }
    ]
    assert primitives.reserve_history_v1.__module__ == "pinelib.abi.primitives"
    body = deepcopy(manifest)
    content_hash = body.pop("content_hash")
    assert content_hash == sha(body)
    check_manifest(Path(__file__).parents[1] / "pinelib/abi/target_manifest.json")
