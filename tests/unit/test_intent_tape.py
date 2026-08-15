from __future__ import annotations

from pathlib import Path

import pytest
from openpine_contracts import IntentKind, validate_payload

from pinelib.strategy.context import StrategyContext
from pinelib.strategy.intent_tape import IntentTape


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


def test_intent_tape_records_all_command_kinds_without_floats() -> None:
    ctx = StrategyContext(intent_run_id="run-1", intent_strategy_id="strat-1")
    ctx.entry("L", "long", qty=1.25, limit=10.50)
    ctx.order("O", "short", qty=2, stop=9.0, oca_name="g", oca_type="cancel")
    ctx.exit("X", from_entry="L", qty=1, profit=3, loss=1)
    ctx.close("L", qty=1)
    ctx.cancel("O")
    ctx.cancel_all()
    ctx.risk_max_position_size(4, "fixed")

    kinds = [event["kind"] for event in ctx.intent_tape.events]
    assert kinds == [
        IntentKind.ENTRY,
        IntentKind.ORDER,
        IntentKind.EXIT,
        IntentKind.CLOSE,
        IntentKind.CANCEL,
        IntentKind.CANCEL_ALL,
        IntentKind.RISK,
    ]
    for event in ctx.intent_tape.events:
        validate_payload("openpine.intent.v2", event)
        assert not any(isinstance(value, float) for value in event.values())
    assert ctx.intent_tape.events[0]["qty"] == "1.25"
    assert ctx.intent_tape.events[0]["limit"] == "10.5"
    assert ctx.intent_tape.events[1]["oca_name"] == "g"


def test_intent_tape_is_immutable_and_hashed() -> None:
    tape = IntentTape(run_id="r", strategy_id="s")
    tape.record(IntentKind.CANCEL_ALL, command_id="all")
    events = tape.events
    with pytest.raises((TypeError, AttributeError)):
        events.append({})  # type: ignore[attr-defined]
    digest = tape.content_hash()
    assert digest.startswith("sha256:")
    assert tape.content_hash() == digest


def test_duplicate_command_keeps_stable_idempotency_key() -> None:
    ctx = StrategyContext(intent_run_id="run-1", intent_strategy_id="strat-1")
    ctx.entry("L", "long", qty=1)
    ctx.entry("L", "long", qty=1)
    keys = [event["idempotency_key"] for event in ctx.intent_tape.events]
    assert keys[0] == keys[1]
    assert len(ctx.intent_tape.events) == 2


def test_intent_tape_records_runtime_span_and_remaining_commands() -> None:
    ctx = StrategyContext(intent_run_id="run-2", intent_strategy_id="strat-2")

    class _Runtime:
        bar_index = 3
        current_bar = type("B", (), {"time": 1_000})()

    ctx._runtime = _Runtime()  # type: ignore[assignment]
    ctx.entry("L", "long", qty=1, source_map="node-1")
    ctx.close_all()
    ctx.risk_allow_entry_in("long")
    ctx.risk_max_drawdown(10, "percent")
    ctx.risk_max_intraday_loss(5, "percent")
    ctx.risk_max_cons_loss_days(2)
    ctx.risk_max_intraday_filled_orders(8)
    event = ctx.intent_tape.events[0]
    assert event["bar_index"] == 3
    assert event["bar_open_time_utc_ms"] == 1_000
    assert event["source_span"] == {"node": "node-1"}
    assert [item["kind"] for item in ctx.intent_tape.events][-1] == IntentKind.RISK


def test_contracts_pin_is_exact_git_sha() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "openpine-contracts @ git+https://github.com/s7cret/openpine-contracts.git@" in text
    assert "51e32ebaaf02eecb81443e8ca7e89b2543cb25a3" in text


def test_intent_tape_decimal_helpers() -> None:
    from decimal import Decimal

    from pinelib.strategy.intent_tape import _dec

    assert _dec(2) == "2"
    assert _dec(Decimal("1.250")) == "1.25"
    assert _dec(1.5) == "1.5"
    assert _dec("3.00") == "3"
    with pytest.raises(TypeError):
        _dec(True)
