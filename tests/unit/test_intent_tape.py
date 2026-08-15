from pinelib.strategy.context import StrategyContext


def test_entry_records_intent_not_fill() -> None:
    ctx = StrategyContext()
    ctx.entry("long", "long", qty=1)
    assert len(ctx.intent_tape) == 1
    event = ctx.intent_tape.events[0]
    assert event.schema_id == "openpine.intent.v2"
    assert event.kind == "entry"
    assert event.order_id == "long"
    assert not hasattr(event, "fill_price")


def test_process_orders_stays_fail_closed() -> None:
    from pinelib.core.bar import Bar
    from pinelib.errors import PineStrategyError

    ctx = StrategyContext()
    ctx.entry("long", "long", qty=1)
    try:
        ctx.process_orders_for_bar(runtime=None, bar=Bar(time=0, open=1, high=1, low=1, close=1))  # type: ignore[arg-type]
    except (PineStrategyError, TypeError):
        return
    raise AssertionError("expected fail-closed")
