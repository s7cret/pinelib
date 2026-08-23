from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from openpine_contracts import IntentKind, validate_payload, verify_content_hash

from pinelib.strategy.context import StrategyContext
from pinelib.strategy.intent_tape import (
    FrozenDict,
    IntentTape,
    _dec,
    _deep_freeze,
    _deep_thaw,
    _nonempty,
    _source_span,
)
from tests.rc4_fixtures import COMMIT, execution_context, known_source_span

SPAN = known_source_span()


def _tape(**kwargs: Any) -> IntentTape:
    defaults: dict[str, Any] = {
        "run_id": "run-1",
        "strategy_id": "strat-1",
        "series_id": "series-1",
        "instrument_id": "NASDAQ:AAPL",
        "timeframe": "60",
        "producer_commit": COMMIT,
        "strict_production": False,
    }
    defaults.update(kwargs)
    return IntentTape(**defaults)


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_contains_float(key) or _contains_float(item) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_float(item) for item in value)
    return False


def test_strict_public_api_does_not_export_fill_or_trade() -> None:
    import pinelib
    import pinelib.strategy as strategy

    assert "Fill" not in pinelib.__all__
    assert "Trade" not in pinelib.__all__
    assert "Fill" not in strategy.__all__
    assert "Trade" not in strategy.__all__
    with pytest.raises(ImportError):
        from pinelib.strategy import Fill  # noqa: F401


def test_compat_v4_keeps_fill_trade() -> None:
    from pinelib.compat.v4 import Fill, Trade, _OpenLot

    fill = Fill("L", "long", 1.0, 10.0, 0.0, 0, 1, "entry")
    trade = Trade("L", "long", 1, 0, 10.0, None, None, None, 1.0, 0.0, 0.0, 0.0, None)
    lot = _OpenLot("L", "long", 1.0, 10.0, 1, 0)
    assert fill.order_id == "L"
    assert trade.entry_id == "L"
    assert lot.entry_id == "L"


def test_intent_tape_emits_complete_v22_envelope_and_supported_business_fields() -> None:
    tape = _tape()
    tape.begin_callback(
        bar_index=7,
        bar_open_time_utc_ms=1_700_000_000_000,
        phase="BAR_COMMIT",
        recalc_iteration=2,
    )
    events = [
        tape.record(
            IntentKind.ENTRY,
            command_id="L",
            order_id="L",
            direction="long",
            qty=1.25,
            limit=10.5,
            oca_name="entries",
            oca_type="cancel",
            source_span=SPAN,
        ),
        tape.record(
            IntentKind.ORDER,
            command_id="O",
            order_id="O",
            direction="short",
            qty=2,
            stop=9.0,
            oca_name="orders",
            oca_type="reduce",
            source_span=SPAN,
        ),
        tape.record(
            IntentKind.EXIT,
            command_id="X",
            order_id="X",
            from_entry="L",
            qty=1,
            qty_percent=50,
            limit=12,
            stop=9,
            source_span=SPAN,
        ),
        tape.record(
            IntentKind.CLOSE,
            command_id="close:L",
            from_entry="L",
            qty=1,
            qty_percent=25,
            immediately=True,
            source_span=SPAN,
        ),
        tape.record(IntentKind.CLOSE_ALL, command_id="close_all", immediately=True),
        tape.record(IntentKind.CANCEL, command_id="O", order_id="O"),
        tape.record(IntentKind.CANCEL_ALL, command_id="*"),
        tape.record(
            IntentKind.RISK,
            command_id="max_position_size",
            risk_rule="max_position_size",
            risk_value=4,
            risk_unit="fixed",
            risk_scope="strategy",
        ),
    ]

    assert [event["kind"] for event in events] == list(IntentKind)
    assert [event["sequence"] for event in events] == list(range(len(events)))
    for event in events:
        validate_payload("openpine.intent.v2", event)
        assert event["schema_version"] == "2.2.0"
        assert event["producer_version"] == "5.0.0-rc.4"
        assert event["producer_commit"] == COMMIT
        assert event["series_id"] == "series-1"
        assert event["instrument_id"] == "NASDAQ:AAPL"
        assert event["timeframe"] == "60"
        assert event["bar_index"] == 7
        assert event["bar_open_time_utc_ms"] == 1_700_000_000_000
        assert event["phase"] == "BAR_COMMIT"
        assert event["recalc_iteration"] == 2
        assert event["semantic_profile"] == "strict_5x"
        assert event["event_id"]
        assert event["command_id"]
        assert event["idempotency_key"]
        assert verify_content_hash(event)
        assert not _contains_float(event)

    assert events[0]["direction"] == "LONG"
    assert events[0]["qty"] == "1.25"
    assert events[0]["limit"] == "10.5"
    assert events[0]["oca_name"] == "entries"
    assert events[1]["direction"] == "SHORT"
    assert events[2]["from_entry"] == "L"
    assert events[2]["qty_percent"] == "50"
    assert events[3]["immediately"] is True
    assert events[4]["kind"] == "close_all"
    assert events[5]["order_id"] == "O"
    assert events[7]["risk_rule"] == "max_position_size"
    assert events[7]["risk_value"] == "4"


def test_events_are_deeply_immutable_and_public_values_are_defensive() -> None:
    span = dict(SPAN)
    tape = _tape()
    event = tape.record(IntentKind.CANCEL_ALL, command_id="*", source_span=span)
    span["start_line"] = 99

    with pytest.raises(TypeError):
        event["command_id"] = "tampered"  # type: ignore[index]
    with pytest.raises(TypeError):
        event["source_span"]["start_line"] = 99  # type: ignore[index]

    # Even a caller deliberately bypassing the FrozenDict override only mutates
    # its detached public copy, never the tape's internal event.
    dict.__setitem__(event, "command_id", "tampered")
    assert tape.events[0]["command_id"] == "*"
    assert tape.events[0]["source_span"]["start_line"] == 2


def test_same_command_same_bar_and_recalc_uses_invocation_ordinal() -> None:
    tape = _tape()
    callback = {
        "bar_index": 3,
        "bar_open_time_utc_ms": 1_000,
        "phase": "BAR_COMMIT",
        "recalc_iteration": 1,
    }
    tape.begin_callback(**callback)
    first = tape.record(
        IntentKind.ENTRY,
        command_id="L",
        order_id="L",
        direction="long",
        qty=1,
    )
    second = tape.record(
        IntentKind.ENTRY,
        command_id="L",
        order_id="L",
        direction="long",
        qty=1,
    )

    assert len(tape.events) == 2
    assert first["event_id"] != second["event_id"]
    assert first["idempotency_key"] != second["idempotency_key"]

    # Re-delivering the same callback resets invocation ordinals, so event
    # identity and sequence are stable instead of appending duplicates.
    tape.begin_callback(**callback)
    replay_first = tape.record(
        IntentKind.ENTRY,
        command_id="L",
        order_id="L",
        direction="long",
        qty=1,
    )
    replay_second = tape.record(
        IntentKind.ENTRY,
        command_id="L",
        order_id="L",
        direction="long",
        qty=1,
    )
    assert len(tape.events) == 2
    assert replay_first == first
    assert replay_second == second
    assert [event["sequence"] for event in tape.events] == [0, 1]


def test_repeated_delivery_with_conflicting_content_is_rejected() -> None:
    tape = _tape()
    tape.begin_callback(bar_index=0, bar_open_time_utc_ms=1, phase="INTRABAR")
    tape.record(
        IntentKind.ORDER,
        command_id="O",
        order_id="O",
        direction="long",
        qty=1,
    )
    tape.begin_callback(bar_index=0, bar_open_time_utc_ms=1, phase="INTRABAR")
    with pytest.raises(ValueError, match="conflicting repeated delivery"):
        tape.record(
            IntentKind.ORDER,
            command_id="O",
            order_id="O",
            direction="long",
            qty=2,
        )


def test_bar_commit_freezes_all_events_for_bar() -> None:
    tape = _tape()
    tape.begin_callback(bar_index=5, bar_open_time_utc_ms=500, phase="BAR_COMMIT")
    tape.record(IntentKind.CANCEL_ALL, command_id="*")
    tape.commit_bar(bar_index=5, bar_open_time_utc_ms=500)

    tape.begin_callback(bar_index=5, bar_open_time_utc_ms=500, phase="BAR_COMMIT")
    with pytest.raises(RuntimeError, match="already committed"):
        tape.record(IntentKind.CANCEL_ALL, command_id="*")


def test_strict_production_requires_supplied_exact_git_commit() -> None:
    context = execution_context()
    with pytest.raises(ValueError, match="producer_commit"):
        _tape(
            producer_commit="unknown",
            strict_production=True,
            execution_context=context,
        )
    with pytest.raises(ValueError, match="producer_commit"):
        _tape(
            producer_commit="deadbeef",
            strict_production=True,
            execution_context=context,
        )


def test_context_records_direct_fields_and_explicit_close_all() -> None:
    ctx = StrategyContext(
        intent_run_id="run-2",
        intent_strategy_id="strat-2",
        intent_series_id="series-2",
        intent_instrument_id="BINANCE:BTCUSDT",
        intent_timeframe="1",
        intent_producer_commit=COMMIT,
        intent_strict_production=True,
        intent_execution_context=execution_context(
            run_id="run-2",
            strategy_id="strat-2",
            series_id="series-2",
            instrument_id="BINANCE:BTCUSDT",
            exchange="BINANCE",
            market="spot",
            symbol="BTCUSDT",
            timeframe="1",
        ),
    )
    ctx.entry(
        "L",
        "long",
        qty=1,
        oca_name="entry-group",
        oca_type="cancel",
        source_map=SPAN,
    )
    ctx.close_all(immediately=True)
    ctx.cancel("L")
    ctx.risk_max_position_size(4, "fixed")

    entry, close_all, cancel, risk = ctx.intent_tape.events
    assert entry["order_id"] == "L"
    assert entry["direction"] == "LONG"
    assert entry["oca_name"] == "entry-group"
    assert close_all["kind"] == IntentKind.CLOSE_ALL
    assert close_all["immediately"] is True
    assert cancel["order_id"] == "L"
    assert risk["risk_rule"] == "max_position_size"
    assert risk["risk_value"] == "4"
    assert risk["risk_unit"] == "fixed"
    assert risk["risk_scope"] == "strategy"


def test_contract_schema_exposes_complete_exit_and_risk_fields() -> None:
    from openpine_contracts import get_schema

    properties = get_schema("openpine.intent.v2")["properties"]
    assert {
        "profit",
        "loss",
        "trail_price",
        "trail_points",
        "trail_offset",
        "risk_unit",
        "risk_scope",
    } <= set(properties)


def test_intent_tape_decimal_policy_is_explicit_deterministic_and_not_migration_helper() -> None:
    assert _dec(2) == "2"
    assert _dec(Decimal("1.250")) == "1.25"
    assert _dec(0.1) == "0.1"
    assert _dec(-0.0) == "0"
    assert _dec("3.00") == "3"
    with pytest.raises(TypeError):
        _dec(True)
    with pytest.raises(ValueError):
        _dec(float("inf"))

    tree = ast.parse(Path("pinelib/strategy/intent_tape.py").read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "openpine_contracts"
        for alias in node.names
    }
    assert "unsafe_decimal_from_float" not in imported_names


def test_tape_content_hash_is_stable() -> None:
    tape = _tape()
    tape.record(IntentKind.CANCEL_ALL, command_id="*")
    digest = tape.content_hash()
    assert digest.startswith("sha256:")
    assert tape.content_hash() == digest


def test_immutable_helpers_and_strict_scalar_validation() -> None:
    frozen = FrozenDict({"value": 1})
    assert frozen.copy() == frozen
    with pytest.raises(TypeError, match="immutable"):
        frozen["value"] = 2
    with pytest.raises(TypeError, match="keys"):
        _deep_freeze({1: "bad"})

    nested = _deep_freeze([1, {"items": [2]}])
    assert isinstance(nested, tuple)
    assert _deep_thaw(nested) == [1, {"items": [2]}]
    with pytest.raises(ValueError, match="nonempty"):
        _nonempty("", field="test")
    with pytest.raises(TypeError, match="source_span.start_offset"):
        _source_span({**SPAN, "start_offset": True})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bar_index", -1),
        ("bar_open_time_utc_ms", True),
        ("recalc_iteration", "bad"),
    ],
)
def test_callback_and_event_positions_are_strict(field: str, value: object) -> None:
    tape = _tape()
    callback = {
        "bar_index": 0,
        "bar_open_time_utc_ms": 0,
        "phase": "BAR_BEGIN",
        "recalc_iteration": 0,
    }
    callback[field] = value
    with pytest.raises(ValueError):
        tape.begin_callback(**callback)  # type: ignore[arg-type]

    event = {field: value}
    with pytest.raises(ValueError):
        tape.record(IntentKind.CANCEL_ALL, command_id="*", **event)


@pytest.mark.parametrize("value", [True, "bad", -1])
def test_invocation_ordinal_must_be_nonnegative_integer(value: object) -> None:
    with pytest.raises(ValueError, match="invocation_ordinal"):
        _tape().record(
            IntentKind.CANCEL_ALL,
            command_id="*",
            invocation_ordinal=value,  # type: ignore[arg-type]
        )


def test_explicit_invocation_ordinal_is_stable_for_redelivery() -> None:
    tape = _tape()
    first = tape.record(IntentKind.CANCEL_ALL, command_id="*", invocation_ordinal=7)
    second = tape.record(IntentKind.CANCEL_ALL, command_id="*", invocation_ordinal=7)

    assert first == second
    assert len(tape.events) == 1
    assert first["sequence"] == 0


def test_identity_freeze_and_kind_specific_required_fields() -> None:
    tape = _tape()
    tape.record(IntentKind.CANCEL_ALL, command_id="*")
    with pytest.raises(RuntimeError, match="cannot change"):
        tape.set_series_identity(
            series_id="other",
            instrument_id=tape.instrument_id,
            timeframe=tape.timeframe,
        )

    cases = [
        (IntentKind.ENTRY, {}),
        (IntentKind.EXIT, {"order_id": "X"}),
        (IntentKind.CLOSE, {}),
        (IntentKind.CANCEL, {}),
        (
            IntentKind.RISK,
            {"risk_rule": "max_position_size", "risk_value": 1},
        ),
        ("unknown", {}),
    ]
    for kind, fields in cases:
        with pytest.raises(ValueError):
            _tape().record(kind, command_id="required", **fields)
