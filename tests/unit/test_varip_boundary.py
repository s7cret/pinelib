from __future__ import annotations

from pinelib import Bar, PineRuntime, SymbolInfo, TimeframeInfo
from pinelib.core.types import TickUpdate


def _runtime() -> PineRuntime:
    return PineRuntime(SymbolInfo("NASDAQ:AAPL"), TimeframeInfo.from_string("1"))


def test_runtime_rollback_snapshot_can_preserve_varip_between_ticks() -> None:
    rt = _runtime()
    rt.begin_realtime_bar(Bar(time=0, open=10, high=10, low=10, close=10, volume=0, time_close=60))
    varip = rt.get_varip_state("counter", lambda: {"count": 0})
    assert isinstance(varip, dict)
    varip["count"] = 1
    checkpoint = rt.export_state(include_varip=False)

    rt.update_realtime_tick(TickUpdate(price=12, volume=1, time=30))
    rt.get_varip_state("counter", dict)["count"] = 2

    rt.restore_state(checkpoint)

    assert rt.close.current == 10
    assert rt.get_varip_state("counter", dict)["count"] == 2


def test_runtime_full_snapshot_restores_varip_for_resume_style_export() -> None:
    rt = _runtime()
    rt.get_varip_state("counter", lambda: {"count": 1})
    checkpoint = rt.export_state()

    rt.get_varip_state("counter", dict)["count"] = 99
    rt.restore_state(checkpoint)

    assert rt.get_varip_state("counter", dict)["count"] == 1


def test_runtime_reset_varip_state_clears_storage() -> None:
    rt = _runtime()
    rt.get_varip_state("x", lambda: [1])

    rt.reset_varip_state()

    assert rt.varip_state == {}
