from __future__ import annotations

from pinelib import Bar, PineRuntime, SymbolInfo, TimeframeInfo, ta


def _runtime() -> PineRuntime:
    return PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
        timeframe=TimeframeInfo.from_string("60"),
    )


def _bar(index: int, close: float) -> Bar:
    return Bar(
        time=1_700_000_000_000 + index * 3_600_000,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1_000.0,
    )


def test_runtime_crossover_updates_only_when_call_is_evaluated() -> None:
    runtime = _runtime()
    fast = runtime.series("fast", "float")
    slow = runtime.series("slow", "float")

    runtime.begin_bar(_bar(0, 10))
    fast.set_current(9)
    slow.set_current(10)
    assert ta.crossover(fast, slow, runtime=runtime, state_id="x") is False
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 11))
    fast.set_current(11)
    slow.set_current(10)
    # Simulate a Pine short-circuit gate: the call is not evaluated on this bar,
    # so the call-site state must still remember bar 0.
    runtime.end_bar()

    runtime.begin_bar(_bar(2, 12))
    fast.set_current(12)
    slow.set_current(10)
    assert ta.crossover(fast, slow, runtime=runtime, state_id="x") is True
    runtime.end_bar()


def test_runtime_crossunder_updates_only_when_call_is_evaluated() -> None:
    runtime = _runtime()
    fast = runtime.series("fast", "float")
    slow = runtime.series("slow", "float")

    runtime.begin_bar(_bar(0, 10))
    fast.set_current(11)
    slow.set_current(10)
    assert ta.crossunder(fast, slow, runtime=runtime, state_id="x") is False
    runtime.end_bar()

    runtime.begin_bar(_bar(1, 9))
    fast.set_current(9)
    slow.set_current(10)
    runtime.end_bar()

    runtime.begin_bar(_bar(2, 8))
    fast.set_current(8)
    slow.set_current(10)
    assert ta.crossunder(fast, slow, runtime=runtime, state_id="x") is True
    runtime.end_bar()
