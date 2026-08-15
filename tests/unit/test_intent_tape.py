from pinelib.core.bar import Bar
from pinelib.errors import PineStrategyError
from pinelib.strategy.context import StrategyContext
from openpine_contracts.errors import MoneyError


def test_entry_records_intent_not_fill() -> None:
    ctx = StrategyContext()
    ctx.entry("long", "long", qty=1)
    assert len(ctx.intent_tape) == 1
    event = ctx.intent_tape.events[0]
    assert event.schema_id == "openpine.intent.v2"
    assert event.kind == "entry"
    assert event.order_id == "long"
    assert event.qty == "1"
    assert not hasattr(event, "fill_price")
    assert not hasattr(event, "extra")


def test_cancel_and_cancel_all_are_recorded() -> None:
    ctx = StrategyContext()
    ctx.entry("long", "long", qty="1.50")
    ctx.cancel("long")
    ctx.cancel_all()
    kinds = [event.kind for event in ctx.intent_tape.events]
    assert kinds == ["entry", "cancel", "cancel_all"]
    assert ctx.intent_tape.events[0].qty == "1.5"


def test_float_is_rejected_and_tape_is_immutable() -> None:
    ctx = StrategyContext()
    try:
        ctx.entry("long", "long", qty=1.25)
    except MoneyError:
        pass
    else:
        raise AssertionError("expected MoneyError")
    ctx.entry("long", "long", qty="1")
    try:
        ctx.intent_tape.events.append(ctx.intent_tape.events[0])  # type: ignore[attr-defined]
    except AttributeError:
        return
    raise AssertionError("tape must be immutable")


def test_process_orders_stays_fail_closed() -> None:
    ctx = StrategyContext()
    ctx.entry("long", "long", qty=1)
    try:
        ctx.process_orders_for_bar(runtime=None, bar=Bar(time=0, open=1, high=1, low=1, close=1))  # type: ignore[arg-type]
    except (PineStrategyError, TypeError):
        return
    raise AssertionError("expected fail-closed")
