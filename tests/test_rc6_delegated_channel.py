from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from pinelib import (
    CallbackFrame,
    DelegatedCapabilityDispatcher,
    DelegatedInvocation,
    RuntimeLanguageContext,
    RuntimeSession,
    is_na,
    na,
)
from pinelib.errors import (
    PL_DELEGATED_HANDLER_FAILURE,
    PL_DELEGATED_HANDLER_UNAVAILABLE,
    PL_DELEGATED_INVOCATION,
    PL_DELEGATED_TARGET,
    PL_RUNTIME_TRANSACTION_CLOSED,
    PineRuntimeError,
)
from pinelib.events import SourceSpan


OWNER = "backtest-engine"
SCHEMA_ID = "openpine.backtest.engine.v1"
CAPABILITY_ID = "strategy.entry"
SYMBOL_ID = "pine:function:strategy.entry"
OVERLOAD_ID = "pine:function:strategy.entry#canonical"
SOURCE_HASH = "sha256:" + "a" * 64


def language() -> RuntimeLanguageContext:
    return RuntimeLanguageContext(
        6,
        "2026-08-29",
        "pine-v6",
        "sha256:" + "1" * 64,
        "compiler_annotation",
    )


def span(line: int = 3) -> SourceSpan:
    return SourceSpan(SOURCE_HASH, "main.pine", line, 1, line, 42)


def dispatch_entry(tx, *, entry_id: str, line: int = 3):
    return tx.dispatch_delegated(
        owner=OWNER,
        schema_id=SCHEMA_ID,
        capability_id=CAPABILITY_ID,
        symbol_id=SYMBOL_ID,
        overload_id=OVERLOAD_ID,
        arguments={
            "positional": [],
            "named": {"id": entry_id, "direction": "strategy.long"},
        },
        call_site_id=f"main.pine:{line}:1",
        source_span=span(line),
    )


def invocation(arguments: object | None = None) -> DelegatedInvocation:
    return DelegatedInvocation(
        owner=OWNER,
        schema_id=SCHEMA_ID,
        capability_id=CAPABILITY_ID,
        symbol_id=SYMBOL_ID,
        overload_id=OVERLOAD_ID,
        arguments=(
            {"positional": [], "named": {}}
            if arguments is None
            else arguments
        ),
        call_site_id="main.pine:3:1",
        source_span=span(),
        sequence=0,
        phase="HISTORICAL_EVAL",
        realtime=False,
        final_tick=True,
        projection_hash=None,
        bar_index=0,
        tick_index=0,
        ordinal=0,
    )


def test_commit_publishes_delegated_outputs_once_in_invocation_order() -> None:
    seen: list[DelegatedInvocation] = []

    def handle(invocation: DelegatedInvocation) -> object:
        seen.append(invocation)
        return {
            "intent_id": invocation.arguments["named"]["id"],  # type: ignore[index]
            "invocation_id": invocation.invocation_id,
        }

    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): handle}
    )
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    frame = CallbackFrame(
        "HISTORICAL_EVAL",
        7,
        projection_hash="sha256:" + "b" * 64,
        bar_index=11,
        tick_index=2,
    )
    tx = runtime.begin(frame)

    first_receipt = dispatch_entry(tx, entry_id="L", line=3)
    second_receipt = dispatch_entry(tx, entry_id="S", line=4)
    assert seen == []

    result = tx.commit()

    assert [invocation.ordinal for invocation in seen] == [0, 1]
    assert [
        cast(Mapping[str, object], output.value)["intent_id"]
        for output in result.delegated_outputs
    ] == [
        "L",
        "S",
    ]
    assert [first_receipt, second_receipt] == [
        output.invocation.invocation_id for output in result.delegated_outputs
    ]
    assert [output.invocation for output in result.delegated_outputs] == seen
    assert all(output.invocation.sequence == 7 for output in result.delegated_outputs)
    assert all(output.invocation.bar_index == 11 for output in result.delegated_outputs)
    assert (
        len({output.invocation.invocation_id for output in result.delegated_outputs})
        == 2
    )

    with pytest.raises(PineRuntimeError) as error:
        tx.commit()
    assert error.value.code == PL_RUNTIME_TRANSACTION_CLOSED
    assert len(result.delegated_outputs) == 2


def test_dispatcher_detaches_and_recursively_freezes_handler_output() -> None:
    mutable_output = {"nested": {"items": [1]}}
    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): lambda _: mutable_output}
    )

    output = dispatcher.dispatch_capability(invocation())
    mutable_output["nested"]["items"].append(2)  # type: ignore[index,union-attr]

    assert output["nested"]["items"] == (1,)  # type: ignore[index]
    with pytest.raises(TypeError):
        output["nested"]["new"] = "mutated"  # type: ignore[index]
    with pytest.raises(AttributeError):
        output["nested"]["items"].append(3)  # type: ignore[index,union-attr]


def test_dispatcher_rejects_unsupported_handler_output_with_stable_code() -> None:
    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): lambda _: object()}
    )

    with pytest.raises(PineRuntimeError) as error:
        dispatcher.dispatch_capability(invocation())

    assert error.value.code == PL_DELEGATED_HANDLER_FAILURE


def test_abort_discards_transaction_local_delegated_outputs_without_running_handler() -> None:
    seen: list[str] = []

    def handle(invocation: DelegatedInvocation) -> str:
        seen.append(invocation.invocation_id)
        return invocation.invocation_id

    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): handle}
    )
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    dispatch_entry(tx, entry_id="L")
    assert seen == []

    result = tx.abort()

    assert result.aborted is True
    assert result.delegated_outputs == ()
    assert seen == []
    assert runtime.sequence == -1
    assert runtime.transcript.entries == []


def test_abort_does_not_consume_domain_sequence_or_change_committed_hash() -> None:
    runtime = RuntimeSession(language())
    before = runtime.state_hash

    runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0)).abort()

    assert runtime.sequence == -1
    assert runtime.state_hash == before
    assert runtime.transcript.entries == []

    committed = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0)).commit()
    assert runtime.sequence == 0
    assert committed.state_hash == runtime.state_hash


def test_delegated_handler_observes_a_closed_transaction() -> None:
    observed_codes: list[str | None] = []
    tx = None

    def handle(_: DelegatedInvocation) -> object:
        assert tx is not None
        with pytest.raises(PineRuntimeError) as error:
            tx.set_series("reentrant", 1)
        observed_codes.append(error.value.code)
        return "prepared"

    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): handle}
    )
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    dispatch_entry(tx, entry_id="L")

    result = tx.commit()

    assert observed_codes == [PL_RUNTIME_TRANSACTION_CLOSED]
    assert [output.value for output in result.delegated_outputs] == ["prepared"]
    assert "reentrant" not in runtime.series


def test_commit_handler_failure_aborts_and_releases_runtime_transaction() -> None:
    def fail(_: DelegatedInvocation) -> object:
        raise ValueError("host rejected invocation")

    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): fail}
    )
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    dispatch_entry(tx, entry_id="L")

    with pytest.raises(PineRuntimeError) as error:
        tx.commit()

    assert error.value.code == PL_DELEGATED_HANDLER_FAILURE
    assert runtime.sequence == -1
    assert runtime.transcript.entries == []
    next_tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    next_tx.abort()


def test_delegated_invocation_preserves_detached_exact_source_payload_and_identity() -> (
    None
):
    seen: list[DelegatedInvocation] = []
    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): lambda invocation: seen.append(invocation)}
    )
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=5))
    arguments = {"positional": ["L"], "named": {"qty": 2.0, "limit": na}}

    tx.dispatch_delegated(
        owner=OWNER,
        schema_id=SCHEMA_ID,
        capability_id=CAPABILITY_ID,
        symbol_id=SYMBOL_ID,
        overload_id=OVERLOAD_ID,
        arguments=arguments,
        call_site_id="main.pine:3:1",
        source_span=span(),
    )
    arguments["named"]["qty"] = 99.0  # type: ignore[index]
    tx.commit()

    invocation = seen[0]
    assert invocation.owner == OWNER
    assert invocation.schema_id == SCHEMA_ID
    assert invocation.capability_id == CAPABILITY_ID
    assert invocation.symbol_id == SYMBOL_ID
    assert invocation.overload_id == OVERLOAD_ID
    assert invocation.arguments["positional"] == ("L",)  # type: ignore[index]
    assert invocation.arguments["named"]["qty"] == 2.0  # type: ignore[index]
    assert is_na(invocation.arguments["named"]["limit"])  # type: ignore[index]
    assert invocation.call_site_id == "main.pine:3:1"
    assert invocation.source_span == span()
    assert invocation.source_identity == {
        "call_site_id": "main.pine:3:1",
        "source_span": span().identity(),
    }
    assert invocation.invocation_id.startswith("sha256:")


def test_delegated_invocation_arguments_are_recursively_immutable() -> None:
    seen: list[DelegatedInvocation] = []
    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): lambda invocation: seen.append(invocation)}
    )
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))

    dispatch_entry(tx, entry_id="L")
    tx.commit()

    invocation = seen[0]
    invocation_id = invocation.invocation_id
    with pytest.raises(TypeError):
        invocation.arguments["named"]["id"] = "MUTATED"  # type: ignore[index]
    with pytest.raises(AttributeError):
        invocation.arguments["positional"].append("MUTATED")  # type: ignore[union-attr,index]
    assert invocation.invocation_id == invocation_id


def test_missing_dispatcher_fails_closed_with_stable_code() -> None:
    runtime = RuntimeSession(language())
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))

    with pytest.raises(PineRuntimeError) as error:
        dispatch_entry(tx, entry_id="L")

    assert error.value.code == PL_DELEGATED_HANDLER_UNAVAILABLE
    tx.abort()


@pytest.mark.parametrize(
    ("owner", "schema_id", "capability_id"),
    [
        ("other-owner", SCHEMA_ID, CAPABILITY_ID),
        (OWNER, "other.schema.v1", CAPABILITY_ID),
        (OWNER, SCHEMA_ID, "strategy.unknown"),
    ],
)
def test_unknown_delegated_target_fails_closed_with_stable_code(
    owner: str, schema_id: str, capability_id: str
) -> None:
    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): lambda invocation: None}
    )
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))

    with pytest.raises(PineRuntimeError) as error:
        tx.dispatch_delegated(
            owner=owner,
            schema_id=schema_id,
            capability_id=capability_id,
            symbol_id=SYMBOL_ID,
            overload_id=OVERLOAD_ID,
            arguments={"positional": [], "named": {}},
            call_site_id="main.pine:3:1",
            source_span=span(),
        )

    assert error.value.code == PL_DELEGATED_TARGET
    tx.abort()


def test_invalid_delegated_arguments_fail_closed_with_stable_code() -> None:
    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): lambda invocation: None}
    )
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))

    with pytest.raises(PineRuntimeError) as error:
        tx.dispatch_delegated(
            owner=OWNER,
            schema_id=SCHEMA_ID,
            capability_id=CAPABILITY_ID,
            symbol_id=SYMBOL_ID,
            overload_id=OVERLOAD_ID,
            arguments={"unsupported": object()},
            call_site_id="main.pine:3:1",
            source_span=span(),
        )

    assert error.value.code == PL_DELEGATED_INVOCATION
    tx.abort()


def test_delegated_value_registry_is_pure_detached_and_fail_closed() -> None:
    mutable = {"direction": ["long"]}
    target = (OWNER, SCHEMA_ID, "strategy.long")
    dispatcher = DelegatedCapabilityDispatcher({}, values={target: mutable})
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))

    value = tx.resolve_delegated_value(
        owner=OWNER,
        schema_id=SCHEMA_ID,
        capability_id="strategy.long",
    )
    mutable["direction"].append("mutated")

    assert value["direction"] == ("long",)  # type: ignore[index]
    with pytest.raises(AttributeError):
        value["direction"].append("x")  # type: ignore[index,union-attr]
    with pytest.raises(PineRuntimeError) as error:
        tx.resolve_delegated_value(
            owner=OWNER,
            schema_id=SCHEMA_ID,
            capability_id="strategy.unknown",
        )
    assert error.value.code == PL_DELEGATED_TARGET
    assert tx.abort().delegated_outputs == ()


def test_delegated_dispatch_outside_active_transaction_fails_closed() -> None:
    dispatcher = DelegatedCapabilityDispatcher(
        {(OWNER, SCHEMA_ID, CAPABILITY_ID): lambda invocation: None}
    )
    runtime = RuntimeSession(language(), delegated_dispatcher=dispatcher)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    tx.commit()

    with pytest.raises(PineRuntimeError) as error:
        dispatch_entry(tx, entry_id="L")

    assert error.value.code == PL_RUNTIME_TRANSACTION_CLOSED
