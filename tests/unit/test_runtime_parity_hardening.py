from __future__ import annotations

import pytest

from pinelib import Bar, PineRuntime, RuntimeConfig, StrategyContext, SymbolInfo, TimeframeInfo, na
from pinelib.errors import (
    PL_MARGIN_LIQUIDATION_DIAGNOSTIC,
    PL_UNSUPPORTED_NESTED_SECURITY,
    PineRequestError,
    PineUnsupportedFeatureError,
)
from pinelib.request.security import security, security_lower_tf


def rt(
    strategy: StrategyContext | None = None, *, config: RuntimeConfig | None = None
) -> PineRuntime:
    runtime = PineRuntime(
        SymbolInfo("TEST:AAA", mintick=0.25),
        TimeframeInfo.from_string("60"),
        config=config or RuntimeConfig(),
    )
    if strategy is not None:
        strategy.attach_runtime(runtime)
    return runtime


def bar(i: int, o: float, h: float, low: float, c: float) -> Bar:
    t = 1_704_067_200_000 + i * 3_600_000
    return Bar(time=t, time_close=t + 3_599_999, open=o, high=h, low=low, close=c)


def process(runtime: PineRuntime, strategy: StrategyContext, b: Bar) -> None:
    runtime.begin_bar(b)
    strategy.process_orders_for_bar(runtime=runtime, bar=b)
    runtime.end_bar()


def enter_long(strategy: StrategyContext, runtime: PineRuntime, qty: float = 1.0) -> None:
    runtime.begin_bar(bar(0, 100, 101, 99, 100))
    strategy.entry("L", "long", qty=qty)
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, strategy, bar(1, 100, 101, 99, 100))


def test_trailing_stop_activates_and_ratchets_for_long_position() -> None:
    strategy = StrategyContext()
    runtime = rt(strategy)
    enter_long(strategy, runtime)

    runtime.begin_bar(bar(2, 100, 101, 99, 100))
    strategy.exit("trail", "L", trail_points=2, trail_offset=1)
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, strategy, bar(3, 100, 101, 99, 100))
    process(runtime, strategy, bar(4, 100, 105, 99, 104))

    assert strategy.position_size == 0
    assert strategy.fills[-1].order_id == "trail"
    assert strategy.fills[-1].price == 104


def test_backtest_fill_limits_assumption_is_diagnosed_and_does_not_change_fills() -> None:
    strategy = StrategyContext(backtest_fill_limits_assumption=2)
    runtime = rt(strategy)
    assert runtime.config.diagnostics[-1]["code"] == "PL_UNSUPPORTED_STRATEGY_SETTING"
    runtime.begin_bar(bar(0, 100, 101, 99, 100))
    strategy.order("L", "long", qty=1, limit=99)
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()

    process(runtime, strategy, bar(1, 100, 101, 98.75, 100))
    assert strategy.position_size == 1
    assert strategy.fills[-1].price == 99


def test_oca_reduce_reduces_sibling_order_quantity() -> None:
    strategy = StrategyContext()
    runtime = rt(strategy)
    runtime.begin_bar(bar(0, 10, 12, 8, 10))
    strategy.order("a", "long", qty=1, limit=9, oca_name="g", oca_type="reduce")
    strategy.order("b", "long", qty=2, limit=7, oca_name="g", oca_type="reduce")
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, strategy, bar(1, 10, 12, 8, 10))

    assert strategy.position_size == 1
    assert [(o.id, o.qty) for o in strategy.pending_orders] == [("b", 1)]


def test_margin_breach_is_explicit_diagnostic_not_silent_liquidation() -> None:
    strategy = StrategyContext(initial_capital=100, margin_long=1, default_qty_value=1000)
    runtime = rt(strategy)
    enter_long(strategy, runtime, qty=1000)

    assert strategy.position_size == 1000
    assert any(d["code"] == PL_MARGIN_LIQUIDATION_DIAGNOSTIC for d in runtime.config.diagnostics)


def test_request_security_lower_tf_missing_provider_fails_closed_without_synthetic_data() -> None:
    runtime = rt()
    runtime.begin_bar(bar(0, 10, 11, 9, 10))
    with pytest.raises(PineRequestError):
        security_lower_tf(
            "TEST:AAA", "1", lambda child: child.close[0], runtime=runtime, state_id="ltf"
        )
    assert (
        list(
            security_lower_tf(
                "TEST:AAA",
                "1",
                lambda child: child.close[0],
                runtime=runtime,
                state_id="ltf",
                ignore_invalid_symbol=True,
            )
        )
        == []
    )


def test_request_security_missing_provider_fails_closed_without_null_provider() -> None:
    runtime = rt()
    runtime.begin_bar(bar(0, 10, 11, 9, 10))

    with pytest.raises(PineRequestError, match="requires runtime.data_provider"):
        security("TEST:AAA", "60", [1.0], runtime=runtime, state_id="htf")

    assert security(
        "TEST:AAA",
        "60",
        [1.0],
        runtime=runtime,
        state_id="htf-ignore",
        ignore_invalid_symbol=True,
    ) is na


def test_nested_request_security_rejects_with_diagnostic() -> None:
    runtime = rt()
    runtime.request_depth = 1
    runtime.chart_bars = [bar(0, 10, 11, 9, 10)]
    with pytest.raises(PineUnsupportedFeatureError) as exc:
        security("TEST:AAA", "60", [1], runtime=runtime, state_id="nested")
    assert exc.value.code == PL_UNSUPPORTED_NESTED_SECURITY
    assert runtime.config.diagnostics[-1]["code"] == PL_UNSUPPORTED_NESTED_SECURITY


def test_strategy_declaration_wires_visual_object_limits() -> None:
    strategy = StrategyContext(max_labels_count=1)
    runtime = rt(strategy)
    runtime.visual.label_new(text="one")
    with pytest.raises(Exception, match="Maximum label object count exceeded"):
        runtime.visual.label_new(text="two")
