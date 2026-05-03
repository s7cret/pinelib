from __future__ import annotations

from pinelib import Bar, PineRuntime, SymbolInfo, TimeframeInfo
from pinelib.core.types import TickUpdate


def _runtime() -> PineRuntime:
    return PineRuntime(SymbolInfo("NASDAQ:AAPL"), TimeframeInfo.from_string("1"))


def test_runtime_checkpoint_restores_realtime_tick_bar_and_series_current() -> None:
    rt = _runtime()
    rt.begin_bar(Bar(time=0, open=10, high=10, low=10, close=10, volume=1, time_close=60))
    rt.end_bar()
    rt.begin_realtime_bar(Bar(time=60, open=11, high=11, low=11, close=11, volume=1, time_close=120))
    checkpoint = rt.export_state()

    rt.update_realtime_tick(TickUpdate(price=15, volume=5, time=90))
    assert rt.close.current == 15
    assert rt.high.current == 15
    assert rt.volume.current == 6
    assert rt.barstate.isnew is False
    assert rt.barstate.isrealtime is True

    rt.restore_state(checkpoint)

    assert rt.bar_index == 0
    assert rt.current_bar is not None
    assert rt.current_bar.close == 11
    assert rt.close.current == 11
    assert rt.high.current == 11
    assert rt.volume.current == 1
    assert rt.barstate.isnew is True
    assert rt.barstate.isrealtime is True


def test_runtime_checkpoint_is_detached_from_later_visual_and_series_mutations() -> None:
    rt = _runtime()
    custom = rt.series("custom", "float")
    rt.begin_realtime_bar(Bar(time=0, open=10, high=10, low=10, close=10, volume=0, time_close=60))
    custom.set_current(1.0)
    obj = rt.visual.label_new(text="before")
    checkpoint = rt.export_state()

    custom.set_current(2.0)
    rt.visual.set(obj, text="after")
    rt.update_realtime_tick(TickUpdate(price=12, volume=1, time=30))

    rt.restore_state(checkpoint)

    assert custom.current == 1.0
    assert rt.visual.objects[obj]["text"] == "before"
    assert rt.close.current == 10


def test_runtime_commit_after_restore_preserves_only_restored_realtime_state() -> None:
    rt = _runtime()
    rt.begin_realtime_bar(Bar(time=0, open=10, high=10, low=10, close=10, volume=0, time_close=60))
    checkpoint = rt.export_state()
    rt.update_realtime_tick(TickUpdate(price=20, volume=1, time=30))
    rt.restore_state(checkpoint)
    rt.update_realtime_tick(TickUpdate(price=11, volume=1, time=50, is_final=True))
    rt.end_bar()

    assert rt.bar_index == 0
    assert rt.close[1] == 11
    assert rt.high[1] == 11
    assert rt.low[1] == 10
