from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pinelib import Bar, PineRuntime, SymbolInfo, TimeframeInfo
from pinelib.core.types import TickUpdate
from pinelib.errors import PineRuntimeError


def _runtime() -> PineRuntime:
    return PineRuntime(SymbolInfo("NASDAQ:AAPL"), TimeframeInfo.from_string("1"))


def test_runtime_checkpoint_restores_realtime_tick_bar_and_series_current() -> None:
    rt = _runtime()
    rt.begin_bar(Bar(time=0, open=10, high=10, low=10, close=10, volume=1, time_close=60))
    rt.end_bar()
    rt.begin_realtime_bar(
        Bar(time=60, open=11, high=11, low=11, close=11, volume=1, time_close=120)
    )
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


def test_runtime_restore_rejects_incomplete_or_unknown_series_snapshot() -> None:
    rt = _runtime()
    snapshot = rt.export_state()
    incomplete = dict(snapshot)
    incomplete["series"] = {}
    with pytest.raises(PineRuntimeError, match="series mismatch"):
        rt.restore_state(incomplete)

    unknown = rt.export_state()
    unknown["series"]["invented"] = {"current": 1, "history": []}
    with pytest.raises(PineRuntimeError, match="series mismatch"):
        rt.restore_state(unknown)


def test_runtime_restore_validates_before_mutating_live_state() -> None:
    rt = _runtime()
    rt.begin_bar(Bar(time=0, open=10, high=10, low=10, close=10, volume=1, time_close=60))
    before = rt.export_state()
    malformed = rt.export_state()
    malformed["bar_index"] = object()

    with pytest.raises(PineRuntimeError, match="bar_index"):
        rt.restore_state(malformed)

    after = rt.export_state()
    for field_name in (
        "bar_index",
        "current_bar",
        "chart_bars",
        "series",
        "indicator_state",
        "barstate",
        "request_depth",
        "request_security_cache",
        "request_lower_tf_cache",
        "request_data_end_ms",
        "lower_tf_metadata_log",
        "request_namespace",
        "varip_state",
    ):
        assert after[field_name] == before[field_name]


def test_runtime_restore_rejects_all_invalid_snapshot_field_shapes() -> None:
    class UndetachableDict(dict[str, object]):
        def __deepcopy__(self, _memo: dict[int, object]) -> object:
            raise RuntimeError("cannot detach")

    def field(name: str, value: object) -> Callable[[dict[str, Any]], None]:
        return lambda snapshot: snapshot.__setitem__(name, value)

    def malformed_series(snapshot: dict[str, Any]) -> None:
        snapshot["series"]["open"] = []

    def malformed_history(snapshot: dict[str, Any]) -> None:
        snapshot["series"]["open"]["history"] = ()

    cases = [
        (field("series", []), "series must be a dict"),
        (malformed_series, "must contain current/history"),
        (malformed_history, "history must be a list"),
        (field("current_bar", object()), "current_bar"),
        (field("chart_bars", [object()]), "chart_bars"),
        (field("indicator_state", []), "indicator_state"),
        (field("varip_state", []), "varip_state"),
        (field("barstate", object()), "barstate"),
        (field("request_depth", -1), "request_depth"),
        (field("request_data_end_ms", True), "request_data_end_ms"),
        (field("lower_tf_metadata_log", object()), "lower_tf_metadata_log"),
        (field("plot_recorder", object()), "plot_recorder"),
        (field("visual", object()), "visual"),
        (field("request_namespace", 1), "request_namespace"),
        (field("indicator_state", UndetachableDict()), "cannot be detached"),
    ]

    for mutate, message in cases:
        runtime = _runtime()
        snapshot = runtime.export_state()
        mutate(snapshot)
        with pytest.raises(PineRuntimeError, match=message):
            runtime.restore_state(snapshot)
