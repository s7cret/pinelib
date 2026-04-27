import pytest

from pinelib import (
    Bar,
    PineArray,
    PineMap,
    PineMatrix,
    PineRuntime,
    PineStrategyError,
    PineUnsupportedFeatureError,
    RuntimeConfig,
    StrategyContext,
    SymbolInfo,
    TimeframeInfo,
    VisualRecorder,
    reference_history,
)
from pinelib.errors import (
    PL_MISSING_INTRABAR_DATA,
    PL_REFERENCE_HISTORY_UNSUPPORTED,
    PL_WARNING_BAR_MAGNIFIER_FALLBACK,
    PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK,
)


def bar(i: int, o: float, h: float, l: float, c: float) -> Bar:
    t = 1704067200000 + i * 3_600_000
    return Bar(time=t, time_close=t + 3_599_999, open=o, high=h, low=l, close=c)


class Intrabars:
    def __init__(self, values: list[Bar]) -> None:
        self.values = values

    def get_intrabar_bars(self, symbol: str, chart_bar: Bar, lower_timeframe: str | None = None, *, max_bars: int | None = None) -> list[Bar]:
        del symbol, chart_bar, lower_timeframe, max_bars
        return self.values


def rt(strategy: StrategyContext | None = None, provider: object | None = None, *, strict: bool = False) -> PineRuntime:
    runtime = PineRuntime(
        SymbolInfo("TEST:AAA", mintick=0.01),
        TimeframeInfo.from_string("60"),
        config=RuntimeConfig(strict_tv_parity=strict),
        intrabar_provider=provider,  # type: ignore[arg-type]
    )
    if strategy:
        strategy.attach_runtime(runtime)
    return runtime


def process(runtime: PineRuntime, strategy: StrategyContext, b: Bar) -> None:
    runtime.begin_bar(b)
    strategy.process_orders_for_bar(runtime=runtime, bar=b)
    runtime.end_bar()


def seed_long(strategy: StrategyContext, runtime: PineRuntime) -> None:
    runtime.begin_bar(bar(0, 10, 11, 9, 10))
    strategy.entry("L", "long", qty=1)
    strategy.process_orders_for_bar(runtime=runtime, bar=runtime.current_bar)  # type: ignore[arg-type]
    runtime.end_bar()
    process(runtime, strategy, bar(1, 10, 11, 9, 10))


def test_intrabar_tp_sl_ordering_can_differ_from_ohlc_path() -> None:
    chart = bar(2, 10, 15, 5, 12)  # synthetic path hits stop before target because open is closer to high
    intrabars = [
        Bar(time=chart.time, time_close=chart.time + 999, open=10, high=10, low=6, close=6),
        Bar(time=chart.time + 1000, time_close=chart.time + 1999, open=6, high=15, low=6, close=12),
    ]
    s = StrategyContext(use_bar_magnifier=True)
    runtime = rt(s, Intrabars(intrabars))
    seed_long(s, runtime)
    s.exit("br", "L", qty=1, limit=14, stop=7)
    runtime.begin_bar(chart)
    s.process_orders_for_bar(runtime=runtime, bar=chart)
    runtime.end_bar()
    assert [f.order_id for f in s.fills][-1] == "br:stop"
    assert s.fills[-1].fill_source == "intrabar"
    assert s.closed_trade_log[-1].fill_source == "intrabar"


def test_missing_intrabar_data_warns_and_falls_back_unless_strict() -> None:
    s = StrategyContext(use_bar_magnifier=True)
    runtime = rt(s, Intrabars([]))
    seed_long(s, runtime)
    process(runtime, s, bar(2, 10, 12, 8, 11))
    assert any(d["code"] == PL_WARNING_BAR_MAGNIFIER_FALLBACK for d in runtime.config.diagnostics)

    strict_strategy = StrategyContext(use_bar_magnifier=True)
    strict_runtime = rt(strict_strategy, Intrabars([]), strict=True)
    strict_runtime.begin_bar(bar(0, 10, 11, 9, 10))
    with pytest.raises(PineStrategyError) as exc:
        strict_strategy.process_orders_for_bar(runtime=strict_runtime, bar=strict_runtime.current_bar)  # type: ignore[arg-type]
    assert exc.value.code == PL_MISSING_INTRABAR_DATA


def test_calc_on_every_tick_emits_fallback_diagnostic() -> None:
    s = StrategyContext(calc_on_every_tick=True)
    runtime = rt(s)
    assert any(d["code"] == PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK for d in runtime.config.diagnostics)


def test_visual_id_lifecycle_and_limits() -> None:
    recorder = VisualRecorder(max_labels_count=1)
    label = recorder.label_new(x=1, y=2, text="a")
    assert label == label
    recorder.set(label, text="b")
    assert recorder.objects[label]["text"] == "b"
    with pytest.raises(Exception):
        recorder.label_new(text="too many")
    recorder.delete(label)
    second = recorder.label_new(text="ok")
    assert second.value != label.value
    assert [event.action for event in recorder.events] == ["new", "set", "delete", "new"]


def test_array_map_matrix_identity_and_copy() -> None:
    arr = PineArray([1])
    same = arr
    clone = arr.copy()
    same.set(0, 2)
    assert arr.get(0) == 2
    assert clone.get(0) == 1

    m = PineMap({"a": arr})
    m_clone = m.copy()
    m.get("a").push(3)  # type: ignore[union-attr]
    assert len(m_clone.get("a")) == 2  # shallow copy preserves reference values

    matrix = PineMatrix[int](2, 2, 0)
    matrix.set(0, 1, 9)
    matrix_clone = matrix.copy()
    matrix.set(0, 1, 3)
    assert matrix_clone.get(0, 1) == 9


def test_reference_history_unsupported_diagnostic() -> None:
    config = RuntimeConfig()
    with pytest.raises(PineUnsupportedFeatureError) as exc:
        reference_history(PineArray([1]), 1, config)
    assert exc.value.code == PL_REFERENCE_HISTORY_UNSUPPORTED
    assert config.diagnostics[-1]["code"] == PL_REFERENCE_HISTORY_UNSUPPORTED
